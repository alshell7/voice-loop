import test from "node:test";
import assert from "node:assert/strict";

function listener() {
  const callbacks = [];
  return {addListener(fn) { callbacks.push(fn); }, callbacks};
}
function area(initial = {}) {
  let data = structuredClone(initial);
  const access = [];
  return {
    access,
    async setAccessLevel(value) { access.push(value.accessLevel); },
    async get(defaults) { return {...structuredClone(defaults), ...structuredClone(data)}; },
    async set(value) { data = {...data, ...structuredClone(value)}; },
    async remove(key) { delete data[key]; },
    async clear() { data = {}; },
    inspect() { return structuredClone(data); },
  };
}
async function harness(sharedStorage) {
  const requests = [];
  const id = "a".repeat(32);
  const storage = sharedStorage || {local: area({pairingToken: "test-" + "a".repeat(32)}), session: area()};
  const chrome = {
    storage,
    alarms: {onAlarm: listener(), async create() {}},
    action: {async setBadgeBackgroundColor() {}, async setBadgeText() {}, async setTitle() {}},
    tabs: {onRemoved: listener(), onUpdated: listener(), async query() { return []; }, async get(id) { return {id}; }, async sendMessage() {}},
    runtime: {id, getURL: path => `chrome-extension://${id}/${path}`, onMessage: listener(), onStartup: listener()},
  };
  globalThis.chrome = chrome;
  const transport = {offline: false, unauthorized: false, commands: []};
  globalThis.fetch = async (url, init) => {
    requests.push({url, ...init});
    if (transport.offline) throw new TypeError("Failed to fetch");
    return {ok: !transport.unauthorized, status: transport.unauthorized ? 401 : 200,
      async json() { return {ok: true, version: 1, application: "VoiceLoop", ...(url.endsWith("/commands/poll") ? {commands: transport.commands.splice(0, 1)} : {})}; }};
  };
  await import(`../background.js?test=${crypto.randomUUID()}`);
  async function message(body, sender = {id, tab: {id: 7}, frameId: 0, url: "https://cliq.zoho.com/"}) {
    return new Promise(resolve => {
      if (!chrome.runtime.onMessage.callbacks[0](body, sender, resolve)) resolve(undefined);
    });
  }
  const popup = body => message(body, {id, url: chrome.runtime.getURL("popup.html")});
  const event = (state = "connected", patch = {}) => ({type: "call-event", event: {
    version: 1, event_id: crypto.randomUUID(), call_id: "test-call", provider: "zoho_cliq",
    state, direction: "outgoing", contact: {name: "Test Contact"}, title: "Test call", url: "https://cliq.zoho.com/",
    timestamp: new Date().toISOString(), ...patch,
  }});
  return {chrome, storage, requests, transport, message, popup, event};
}

test("worker restricts credentials and sends validated events only to loopback", async () => {
  const h = await harness();
  assert.deepEqual(await h.message(h.event()), {ok: true});
  assert.deepEqual(h.storage.local.access, ["TRUSTED_CONTEXTS"]);
  assert.deepEqual(h.storage.session.access, ["TRUSTED_CONTEXTS"]);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, "http://127.0.0.1:49321/v1/events");
  assert.match(h.requests[0].headers.Authorization, /^Bearer test-/);
  assert.equal(h.requests[0].redirect, "error");
  assert.equal(h.storage.session.inspect().outbox.length, 0);
  assert.equal(h.storage.session.inspect().calls[7].contact.name, "Test Contact");
});
test("page and iframe senders cannot pair, unpair, or forge provider events", async () => {
  const h = await harness();
  assert.equal(await h.message({type: "unpair"}), undefined);
  assert.deepEqual(await h.message(h.event(), {id: h.chrome.runtime.id, frameId: 1, tab: {id: 7}, url: "https://cliq.zoho.com/"}), {ok: false});
  assert.deepEqual(await h.message(h.event(), {id: h.chrome.runtime.id, frameId: 0, tab: {id: 7}, url: "https://evil.example/"}), {ok: false});
  assert.deepEqual(await h.message(h.event(), {id: "another-extension", frameId: 0, tab: {id: 7}, url: "https://cliq.zoho.com/"}), {ok: false});
  assert.equal(h.requests.length, 0);
});
test("unpaired extension never queues or forwards calls", async () => {
  const h = await harness({local: area(), session: area()});
  assert.deepEqual(await h.message(h.event()), {ok: false, reason: "unpaired"});
  assert.equal(h.requests.length, 0);
  assert.equal(h.storage.session.inspect().outbox, undefined);
});
test("offline call ended state survives worker restart without replaying connected", async () => {
  let h = await harness(); h.transport.offline = true;
  await h.message(h.event("connected"));
  await h.message(h.event("ended"));
  assert.equal(h.storage.session.inspect().outbox.length, 1);
  assert.equal(h.storage.session.inspect().outbox[0].event.state, "ended");
  h = await harness(h.storage);
  h.chrome.runtime.onStartup.callbacks[0]();
  await h.popup({type: "status"}); // Serialized behind the startup flush.
  assert.equal(h.requests.filter(request => request.url.endsWith("/events")).length, 1);
  assert.equal(JSON.parse(h.requests.find(request => request.url.endsWith("/events")).body).state, "ended");
  assert.equal(h.storage.session.inspect().outbox.length, 0);
});
test("closing an attended tab emits ended using its retained call metadata", async () => {
  const h = await harness(); await h.message(h.event());
  h.chrome.tabs.onRemoved.callbacks[0](7);
  await h.popup({type: "status"});
  const ended = JSON.parse(h.requests.at(-1).body);
  assert.equal(ended.state, "ended");
  assert.equal(ended.call_id, "test-call");
  assert.equal(ended.contact.name, "Test Contact");
  assert.equal(ended.tabId, undefined);
  assert.deepEqual(h.storage.session.inspect().calls, {});
});
test("pairing checks desktop identity before persisting token", async () => {
  const h = await harness({local: area(), session: area()});
  h.transport.unauthorized = true;
  assert.equal((await h.popup({type: "pair", token: "x".repeat(40)})).ok, false);
  assert.equal(h.storage.local.inspect().pairingToken, undefined);
  h.transport.unauthorized = false;
  assert.equal((await h.popup({type: "pair", token: "y".repeat(40)})).ok, true);
  assert.equal(h.storage.local.inspect().pairingToken, "y".repeat(40));
  const status = await h.popup({type: "status"});
  assert.equal(status.paired, true);
  assert.equal(JSON.stringify(status).includes("y".repeat(40)), false);
});
test("disconnect ends tracked calls and removes pairing material", async () => {
  const h = await harness(); await h.message(h.event());
  assert.deepEqual(await h.popup({type: "unpair"}), {ok: true});
  assert.equal(JSON.parse(h.requests.at(-1).body).state, "ended");
  assert.equal(h.storage.local.inspect().pairingToken, undefined);
  assert.deepEqual(h.storage.session.inspect(), {});
});
test("pairing refreshes this extension's scripts without needing sensitive tab URLs", async () => {
  const h = await harness({local: area(), session: area()});
  const refreshed = [];
  h.chrome.tabs.query = async () => [{id: 3, get url() { throw new Error("No URL permission"); }}, {id: 8}];
  h.chrome.tabs.sendMessage = async (id, message) => { refreshed.push({id, type: message.type}); };
  assert.equal((await h.popup({type: "pair", token: "z".repeat(40)})).ok, true);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(refreshed, [{id: 3, type: "snapshot-request"}, {id: 8, type: "snapshot-request"}]);
});

function command(profileId, patch = {}) {
  return {version: 1, command_id: "command-1", profile_id: profileId, action: "call", provider: "zoho_cliq", chat_id: "12345", chat_url: "https://cliq.zoho.com/company/987/chats/12345", call_id: "", text: "", expires_at: new Date(Date.now() + 45000).toISOString(), ...patch};
}
test("commands are durably claimed before execution and never dial twice", async () => {
  let h = await harness(); const profile = (await h.popup({type: "status"})).profileId;
  const cmd = command(profile); h.transport.commands.push(cmd);
  const actions = [];
  const attachTabs = current => {
    current.chrome.tabs.query = async () => [{id: 7, url: cmd.chat_url}];
    current.chrome.tabs.sendMessage = async (_id, message) => {
      if (message.type === "assistant-snapshot") return {ready: true, active: false};
      if (message.type === "assistant-command") {
        assert.equal(current.storage.local.inspect().commandJournal[cmd.command_id].result, null);
        actions.push(message.command.action); return {status: "succeeded", detail: "Dialing confirmed.", call_id: "new-call"};
      }
    };
  };
  attachTabs(h);
  await h.message({type: "assistant-pulse"});
  assert.deepEqual(actions, ["call"]);
  assert.equal(h.storage.local.inspect().commandJournal[cmd.command_id].acknowledged, true);
  await h.message(h.event("dialing", {call_id: "new-call"}));
  const event = JSON.parse(h.requests.findLast(request => request.url.endsWith("/events")).body);
  assert.equal(event.chat_id, "12345"); assert.equal(event.command_id, cmd.command_id); assert.equal(event.profile_id, profile);
  h = await harness(h.storage); attachTabs(h); h.transport.commands.push(cmd);
  await h.message({type: "assistant-pulse"});
  assert.deepEqual(actions, ["call"]);
});
test("restart with unfinished claim reports ambiguous without browser side effects", async () => {
  const h = await harness({local: area({pairingToken: "x".repeat(43), profileId: "profile-1", commandJournal: {"unfinished-1": {created: Date.now(), result: null, acknowledged: false}}}), session: area()});
  h.chrome.tabs.query = async () => { throw new Error("Must not inspect or dial tabs"); };
  await h.message({type: "assistant-pulse"});
  const result = JSON.parse(h.requests.find(request => request.url.endsWith("/commands/result")).body);
  assert.equal(result.status, "ambiguous"); assert.equal(result.command_id, "unfinished-1");
});
test("expired and other-profile commands never reach a tab", async () => {
  const h = await harness(); const profile = (await h.popup({type: "status"})).profileId;
  h.chrome.tabs.query = async () => { throw new Error("Must not inspect or dial tabs"); };
  h.transport.commands.push(command("different-profile"));
  await h.message({type: "assistant-pulse"});
  assert.deepEqual(h.storage.local.inspect().commandJournal, {});
  const restarted = await harness(h.storage);
  restarted.transport.commands.push(command(profile, {expires_at: new Date(Date.now() - 1000).toISOString()}));
  await restarted.message({type: "assistant-pulse"});
  assert.deepEqual(restarted.storage.local.inspect().commandJournal, {});
});
test("a stale heartbeat snapshot-channel failure never fabricates call ended", async () => {
  const h = await harness(); await h.message(h.event("dialing"));
  const calls = h.storage.session.inspect().calls; calls[7].seenAt = Date.now() - 20000;
  await h.storage.session.set({calls});
  h.chrome.tabs.get = async id => ({id});
  h.chrome.tabs.sendMessage = async () => { throw new Error("The message port closed before a response was received."); };
  h.chrome.alarms.onAlarm.callbacks[0]({name: "voiceloop-retry"});
  await h.popup({type: "status"});
  assert.equal(h.storage.session.inspect().calls[7]?.state, "dialing");
  assert.equal(h.requests.filter(request => request.url.endsWith("/events")).some(request => JSON.parse(request.body).state === "ended"), false);
});
test("only a positively missing tab produces a synthetic terminal event", async () => {
  const h = await harness(); await h.message(h.event("dialing"));
  h.chrome.tabs.get = async () => { throw new Error("Chrome is temporarily unavailable"); };
  h.chrome.alarms.onAlarm.callbacks[0]({name: "voiceloop-retry"}); await h.popup({type: "status"});
  assert.ok(h.storage.session.inspect().calls[7]);
  h.chrome.tabs.get = async () => { throw new Error("No tab with id: 7."); };
  h.chrome.alarms.onAlarm.callbacks[0]({name: "voiceloop-retry"}); await h.popup({type: "status"});
  const ended = JSON.parse(h.requests.findLast(request => request.url.endsWith("/events")).body);
  assert.equal(ended.state, "ended"); assert.match(ended.event_id, /^tab-missing-/);
});
test("an old terminal or pre-command event cannot claim a new outbound command", async () => {
  const h = await harness(); await h.popup({type: "status"});
  const now = Date.now();
  const binding = {command_id: "new-command", chat_id: "12345", chat_url: "https://cliq.zoho.com/company/987/chats/12345", call_id: "", created: now, expires: now + 45000};
  await h.storage.session.set({bindings: {7: binding}});
  await h.message(h.event("ended", {call_id: "old-call"}));
  assert.equal(JSON.parse(h.requests.at(-1).body).command_id, undefined);
  assert.equal(h.storage.session.inspect().bindings[7].call_id, "");
  await h.message(h.event("dialing", {call_id: "old-call-2", timestamp: new Date(now - 1000).toISOString()}));
  assert.equal(JSON.parse(h.requests.at(-1).body).command_id, undefined);
  assert.equal(h.storage.session.inspect().bindings[7].call_id, "");
  await h.message(h.event("dialing", {call_id: "new-call"}));
  assert.equal(JSON.parse(h.requests.at(-1).body).command_id, "new-command");
});
test("late end or heartbeat from an old call cannot erase or resurrect over a newer tab call", async () => {
  const h = await harness();
  await h.message(h.event("dialing", {call_id: "old-call"}));
  await h.message(h.event("dialing", {call_id: "new-call"}));
  await h.message(h.event("ended", {call_id: "old-call"}));
  assert.equal(h.storage.session.inspect().calls[7]?.call_id, "new-call");
  await h.message(h.event("dialing", {call_id: "old-call"}));
  assert.equal(h.storage.session.inspect().calls[7]?.call_id, "new-call");
});
