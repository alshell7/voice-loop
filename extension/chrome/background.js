import {BRIDGE, normalizeEvent, providerForUrl, queueLatest, pendingFresh, normalizeCommand, chatTarget} from "./protocol.mjs";

const RETRY_ALARM = "voiceloop-retry";
let chain = Promise.resolve();
const serialized = fn => {
  const next = chain.then(fn, fn);
  chain = next.catch(() => {});
  return next;
};
const ready = Promise.all([
  chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"}),
  chrome.storage.session.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"}),
  chrome.alarms.create(RETRY_ALARM, {periodInMinutes: 0.5}),
]);
async function config() {
  await ready;
  const value = await chrome.storage.local.get({pairingToken: "", profileId: "", profileLabel: "Chrome profile", commandJournal: {}});
  if (!value.profileId) { value.profileId = crypto.randomUUID(); await chrome.storage.local.set({profileId: value.profileId}); }
  return value;
}
async function state() { return chrome.storage.session.get({outbox: [], calls: {}, bindings: {}, endedCalls: [], connection: {ok: false, message: "Connect to Voice Loop to begin."}}); }
async function badge(ok, current) {
  await chrome.action.setBadgeBackgroundColor({color: ok ? "#006FEE" : "#626977"});
  await chrome.action.setBadgeText({text: current?.state === "connected" ? "ON" : current && current.state !== "ended" ? "…" : ok ? "" : "!"});
  await chrome.action.setTitle({title: current && current.state !== "ended" ? `Voice Loop · ${current.state} · ${current.contact.name || current.title}` : ok ? "Voice Loop · connected to desktop" : "Voice Loop · desktop unavailable"});
}
async function request(path, token, event) {
  const response = await fetch(`${BRIDGE}${path}`, {
    method: event ? "POST" : "GET", cache: "no-store", redirect: "error",
    headers: {Authorization: `Bearer ${token}`, ...(event ? {"Content-Type": "application/json"} : {})},
    ...(event ? {body: JSON.stringify(event)} : {}), signal: AbortSignal.timeout(2500),
  });
  if (response.status === 401 || response.status === 403) throw new Error("Pairing code was rejected. Copy a new code from Voice Loop Preferences.");
  if (!response.ok) throw new Error(response.status === 503 ? "Voice Loop is busy. Call updates will retry automatically." : `Voice Loop returned HTTP ${response.status}.`);
  const result = await response.json();
  if (!result.ok || (!event && result.application !== "VoiceLoop")) throw new Error("The local service did not identify itself as Voice Loop.");
  return result;
}
function failure(error) {
  return /Pairing code|Voice Loop returned|Voice Loop is busy|local service/.test(error.message) ? error.message : "Open Voice Loop and enable browser call detection in Preferences, then try again.";
}
async function flush() {
  const {pairingToken} = await config();
  let {outbox, calls} = await state();
  outbox = pendingFresh(outbox);
  if (!pairingToken) { await chrome.storage.session.set({outbox: []}); return; }
  for (const item of [...outbox]) {
    try {
      await request("/v1/events", pairingToken, item.event);
      outbox = outbox.filter(entry => entry.event.event_id !== item.event.event_id);
      const {connection: previous} = await state();
      const connection = {...previous, lastEvent: item.event};
      await chrome.storage.session.set({connection, outbox});
      await badge(connection.ok, item.event);
    } catch (error) {
      await chrome.storage.session.set({outbox, connection: {ok: false, message: failure(error), checkedAt: Date.now()}});
      await badge(false, Object.values(calls).at(-1));
      break;
    }
  }
  await chrome.storage.session.set({outbox});
}
async function accept(event, sender) {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !Number.isInteger(sender.tab?.id)) return {ok: false};
  const clean = normalizeEvent(event, sender.url);
  if (!clean) return {ok: false};
  const {pairingToken, profileId} = await config();
  if (!pairingToken) return {ok: false, reason: "unpaired"};
  const {outbox, calls, bindings, endedCalls} = await state();
  const callKey = `${sender.tab.id}:${clean.call_id}`;
  if (clean.state !== "ended" && endedCalls.includes(callKey)) return {ok: true, ignored: true};
  const current = calls[sender.tab.id];
  if (clean.state !== "ended" && current && Date.parse(clean.timestamp) < Date.parse(current.timestamp)) return {ok: true, ignored: true};
  clean.profile_id = profileId;
  const binding = bindings[sender.tab.id];
  if (binding && clean.provider === "zoho_cliq" && clean.direction === "outgoing"
      && (binding.call_id === clean.call_id || (!binding.call_id && clean.state !== "ended"
        && Number.isFinite(binding.created) && Date.parse(clean.timestamp) >= binding.created && Date.now() < binding.expires))) {
    // Bind one newly-created call only. A later unrelated call in this tab must
    // never inherit the assistant's contact or command authorization.
    clean.chat_id = binding.chat_id; clean.chat_url = binding.chat_url; clean.command_id = binding.command_id;
    binding.call_id = clean.call_id;
    if (clean.state === "ended") delete bindings[sender.tab.id];
  }
  if (clean.state === "ended") {
    if (current?.call_id === clean.call_id) delete calls[sender.tab.id];
    if (!endedCalls.includes(callKey)) endedCalls.push(callKey);
  } else {
    if (current && current.call_id !== clean.call_id) endedCalls.push(`${sender.tab.id}:${current.call_id}`);
    calls[sender.tab.id] = {...clean, tabId: sender.tab.id, seenAt: Date.now()};
  }
  await chrome.storage.session.set({outbox: queueLatest(outbox, clean), calls, bindings, endedCalls: endedCalls.slice(-256)});
  await flush();
  return {ok: true};
}
async function endTab(tabId, reason = "tab-closed") {
  const {calls, outbox, bindings, endedCalls} = await state();
  if (!calls[tabId]) return;
  const {tabId: _tabId, seenAt: _seenAt, ...call} = calls[tabId];
  const ended = {...call, state: "ended", event_id: `${reason}-${crypto.randomUUID()}`, timestamp: new Date().toISOString()};
  delete calls[tabId];
  delete bindings[tabId];
  endedCalls.push(`${tabId}:${call.call_id}`);
  await chrome.storage.session.set({calls, bindings, endedCalls: endedCalls.slice(-256), outbox: queueLatest(outbox, ended)});
  await flush();
}
async function check(token) {
  try {
    await request("/v1/health", token);
    const {profileId, profileLabel} = await config();
    // Registration never leases commands: pairing/checking cannot place a call.
    try {
      await request("/v1/commands/register", token, {version: 1, profile_id: profileId, label: profileLabel, capabilities: ["call-control-v1", "busy-fallback-v1", "zoho_cliq", "google_meet"]});
    } catch (error) {
      if (/HTTP 404/.test(error.message)) throw new Error("Voice Loop returned an unsupported profile protocol. Update and restart the desktop app to match this extension.");
      throw error;
    }
    const connection = {ok: true, message: "Connected to Voice Loop", checkedAt: Date.now()};
    const {calls} = await state();
    await chrome.storage.session.set({connection}); await badge(true, Object.values(calls).sort((a, b) => b.seenAt - a.seenAt)[0]);
    return connection;
  } catch (error) {
    const connection = {ok: false, message: failure(error), checkedAt: Date.now()};
    await chrome.storage.session.set({connection}); await badge(false);
    return connection;
  }
}
async function refreshTabs() {
  const tabs = await chrome.tabs.query({});
  // Tab IDs need no sensitive-tab permission. sendMessage only reaches this
  // extension's own scripts, which exist solely on our manifest's call hosts.
  // Do not read tab URLs/titles or request browsing-history access to refresh.
  for (const tab of tabs) {
    try { await chrome.tabs.sendMessage(tab.id, {type: "snapshot-request"}); } catch { /* Reload existing pages after extension installation. */ }
  }
}
const CALL_HOSTS = ["https://cliq.zoho.com/*", "https://cliq.zoho.eu/*", "https://cliq.zoho.in/*", "https://cliq.zoho.com.au/*", "https://cliq.zoho.jp/*", "https://cliq.zoho.ca/*", "https://cliq.zoho.com.cn/*", "https://cliq.zoho.sa/*", "https://meet.google.com/*"];
let lastPoll = 0;
async function commandTab(command) {
  const {calls} = await state();
  if (["answer", "hangup"].includes(command.action)) {
    const matches = Object.values(calls).filter(call => call.call_id === command.call_id && call.profile_id === command.profile_id
      && call.provider === command.provider && (!command.chat_id || call.chat_id === command.chat_id && call.chat_url === command.chat_url
        || command.action === "answer" && command.participant_id && call.participant_id === command.participant_id && new URL(call.url).origin === new URL(command.chat_url).origin));
    if (matches.length !== 1) throw new Error("The exact call is no longer available in this profile.");
    return {id: matches[0].tabId};
  }
  const tabs = await chrome.tabs.query({url: CALL_HOSTS});
  if (command.action === "call") {
    if (Object.values(calls).some(call => call.state !== "ended")) throw new Error("A call is already active in this profile.");
    for (const tab of tabs) {
      try { const snapshot = await chrome.tabs.sendMessage(tab.id, {type: "assistant-snapshot"}); if (snapshot?.active) throw new Error("A call is already active in this profile."); }
      catch (error) { if (error.message === "A call is already active in this profile.") throw error; }
    }
  }
  const exact = tabs.filter(tab => chatTarget(tab.url, command.chat_id)?.chat_url === command.chat_url);
  if (exact.length > 1) throw new Error("This chat is open in multiple tabs. Keep one tab open before trying again.");
  return exact[0] || chrome.tabs.create({url: command.chat_url, active: false});
}
async function runCommand(command) {
  const tab = await commandTab(command);
  // Reserve correlation before clicking. Events can arrive as soon as the page
  // initiates a call, even before command execution returns to the worker.
  if (command.action === "call") {
    const {bindings} = await state();
    bindings[tab.id] = {command_id: command.command_id, chat_id: command.chat_id, chat_url: command.chat_url, call_id: "", created: Date.now(), expires: Date.parse(command.expires_at)};
    await chrome.storage.session.set({bindings});
  }
  let ready = false;
  const readyDeadline = Math.min(Date.parse(command.expires_at), Date.now() + 10000);
  while (Date.now() < readyDeadline) {
    try { ready = !!(await chrome.tabs.sendMessage(tab.id, {type: "assistant-snapshot"}))?.ready; } catch { /* New tab may still be loading. */ }
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 250));
    if (Date.now() >= Date.parse(command.expires_at)) break;
  }
  if (!ready) throw new Error("Reload the Cliq page to attach the updated Voice Loop extension.");
  try {
    const result = await chrome.tabs.sendMessage(tab.id, {type: "assistant-command", command});
    if (!result || !["succeeded", "failed", "ambiguous"].includes(result.status)) return {status: "ambiguous", detail: "The browser did not confirm the command outcome."};
    const code = result.code === undefined ? "" : result.code;
    if (code !== "" && (code !== "recipient_busy" || command.action !== "call" || !command.busy_fallback || result.status !== "failed" || result.call_id || command.call_id)) return {status: "ambiguous", detail: "The browser returned an invalid command outcome code."};
    if (command.action === "call" && /^[A-Za-z0-9_-]{1,100}$/.test(result.call_id || "")) {
      const {bindings} = await state();
      if (bindings[tab.id]?.command_id === command.command_id) {
        bindings[tab.id].call_id = result.call_id;
        await chrome.storage.session.set({bindings});
      }
    }
    return {status: result.status, detail: String(result.detail || "").slice(0, 512), call_id: result.call_id || "", ...(code ? {code} : {})};
  } catch { return {status: "ambiguous", detail: "The page disconnected during the command. It will not be repeated."}; }
}
async function pollCommands(force = false) {
  if (!force && Date.now() - lastPoll < 1500) return;
  lastPoll = Date.now();
  const {pairingToken, profileId, profileLabel, commandJournal} = await config();
  if (!pairingToken) return;
  // Refresh presence before retrying results, which may fail independently.
  if (!(await check(pairingToken)).ok) return;
  try {
    // Persistent claiming happens before any DOM side effect. A worker/browser
    // crash with an unfinished claim is ambiguous, never permission to redial.
    for (const [id, entry] of Object.entries(commandJournal)) {
      if (entry.acknowledged) continue;
      entry.result ||= {status: "ambiguous", detail: "The browser restarted during this action. It was not repeated."};
      try { await request("/v1/commands/result", pairingToken, {version: 1, profile_id: profileId, command_id: id, ...entry.result}); }
      catch (error) { if (!/HTTP 400/.test(error.message)) throw error; /* Desktop restarted and forgot the command; never replay it. */ }
      entry.acknowledged = true;
    }
    for (const [id, entry] of Object.entries(commandJournal)) if (entry.acknowledged && Date.now() - entry.created > 86400000) delete commandJournal[id];
    await chrome.storage.local.set({commandJournal});
    const response = await request("/v1/commands/poll", pairingToken, {version: 1, profile_id: profileId, label: profileLabel, capabilities: ["call-control-v1", "busy-fallback-v1", "zoho_cliq", "google_meet"]});
    for (const raw of (Array.isArray(response.commands) ? response.commands.slice(0, 1) : [])) {
      const command = normalizeCommand(raw, profileId);
      if (!command) continue;
      const existing = commandJournal[command.command_id];
      if (existing) {
        await request("/v1/commands/result", pairingToken, {version: 1, profile_id: profileId, command_id: command.command_id, ...existing.result});
        continue;
      }
      if (Object.keys(commandJournal).length >= 512) return;
      commandJournal[command.command_id] = {created: Date.now(), result: null, acknowledged: false};
      await chrome.storage.local.set({commandJournal});
      let result;
      try { result = await runCommand(command); } catch (error) { result = {status: "failed", detail: String(error.message).slice(0, 512)}; }
      if (command.action === "call" && result.status === "failed") {
        const {bindings} = await state();
        for (const [tabId, binding] of Object.entries(bindings)) if (binding.command_id === command.command_id) delete bindings[tabId];
        await chrome.storage.session.set({bindings});
      }
      commandJournal[command.command_id].result = result;
      await chrome.storage.local.set({commandJournal});
      await request("/v1/commands/result", pairingToken, {version: 1, profile_id: profileId, command_id: command.command_id, ...result});
      commandJournal[command.command_id].acknowledged = true;
      await chrome.storage.local.set({commandJournal});
    }
  } catch { /* An unacknowledged result is retried; a DOM action never is. */ }
}
async function popupMessage(message) {
  const {pairingToken} = await config();
  if (message.type === "pair") {
    const token = typeof message.token === "string" ? message.token.trim() : "";
    if (!/^[A-Za-z0-9_-]{24,200}$/.test(token)) return {ok: false, message: "Paste the full pairing code from Voice Loop Preferences."};
    const result = await check(token);
    if (result.ok) {
      await chrome.storage.local.set({pairingToken: token});
      // A pairing change must not replay previously queued call events.
      await chrome.storage.session.set({outbox: []});
      void refreshTabs();
    }
    return result;
  }
  if (message.type === "unpair") {
    const {calls} = await state();
    for (const tabId of Object.keys(calls)) await endTab(tabId, "unpaired");
    await chrome.storage.local.remove("pairingToken");
    await chrome.storage.session.clear();
    await badge(false);
    return {ok: true};
  }
  if (message.type === "status") {
    if (pairingToken && message.check) await check(pairingToken);
    const {connection, calls} = await state();
    const {profileId, profileLabel} = await config();
    return {paired: !!pairingToken, profileId, profileLabel, connection, call: Object.values(calls).sort((a, b) => b.seenAt - a.seenAt)[0] || null};
  }
  return {ok: false};
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  const popup = sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL("popup.html");
  const pulse = message?.type === "assistant-pulse" && sender.id === chrome.runtime.id && sender.frameId === 0 && Number.isInteger(sender.tab?.id) && !!providerForUrl(sender.url);
  if (message?.type !== "call-event" && !popup && !pulse) return false;
  serialized(() => pulse ? pollCommands().then(() => ({ok: true})) : message.type === "call-event" ? accept(message.event, sender) : popupMessage(message))
    .then(respond, () => respond({ok: false, message: "Voice Loop could not save the browser connection. Try again."}));
  return true;
});
chrome.tabs.onRemoved.addListener(tabId => { void serialized(() => endTab(tabId)); });
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.url && !providerForUrl(change.url)) void serialized(() => endTab(tabId, "navigation"));
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name !== RETRY_ALARM) return;
  void serialized(async () => {
    const {calls} = await state();
    for (const [tabId, call] of Object.entries(calls)) {
      try {
        await chrome.tabs.get(+tabId);
      } catch (error) {
        if (/No tab with id|Invalid tab ID/i.test(String(error.message))) await endTab(tabId, "tab-missing");
        continue;
      }
      if (Date.now() - call.seenAt > 15_000) {
        try { await chrome.tabs.sendMessage(+tabId, {type: "snapshot-request"}); }
        catch { /* A suspended/reloaded content channel is not evidence the call ended. */ }
      }
    }
    await flush();
    await pollCommands(true);
  });
});
chrome.runtime.onStartup.addListener(() => { void serialized(async () => { await flush(); await pollCommands(true); }); });
