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
  const transport = {offline: false, unauthorized: false};
  globalThis.fetch = async (url, init) => {
    requests.push({url, ...init});
    if (transport.offline) throw new TypeError("Failed to fetch");
    return {ok: !transport.unauthorized, status: transport.unauthorized ? 401 : 200,
      async json() { return {ok: true, version: 1, application: "VoiceLoop"}; }};
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
  assert.equal(h.requests.length, 1);
  assert.equal(JSON.parse(h.requests[0].body).state, "ended");
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
