import {BRIDGE, normalizeEvent, providerForUrl, queueLatest, pendingFresh} from "./protocol.mjs";

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
async function config() { await ready; return chrome.storage.local.get({pairingToken: ""}); }
async function state() { return chrome.storage.session.get({outbox: [], calls: {}, connection: {ok: false, message: "Connect to Voice Loop to begin."}}); }
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
      const connection = {ok: true, message: "Connected to Voice Loop", checkedAt: Date.now(), lastEvent: item.event};
      await chrome.storage.session.set({connection, outbox});
      await badge(true, item.event);
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
  const {pairingToken} = await config();
  if (!pairingToken) return {ok: false, reason: "unpaired"};
  const {outbox, calls} = await state();
  if (clean.state === "ended") delete calls[sender.tab.id];
  else calls[sender.tab.id] = {...clean, tabId: sender.tab.id, seenAt: Date.now()};
  await chrome.storage.session.set({outbox: queueLatest(outbox, clean), calls});
  await flush();
  return {ok: true};
}
async function endTab(tabId) {
  const {calls, outbox} = await state();
  if (!calls[tabId]) return;
  const {tabId: _tabId, seenAt: _seenAt, ...call} = calls[tabId];
  const ended = {...call, state: "ended", event_id: crypto.randomUUID(), timestamp: new Date().toISOString()};
  delete calls[tabId];
  await chrome.storage.session.set({calls, outbox: queueLatest(outbox, ended)});
  await flush();
}
async function check(token) {
  try {
    await request("/v1/health", token);
    const connection = {ok: true, message: "Connected to Voice Loop", checkedAt: Date.now()};
    await chrome.storage.session.set({connection}); await badge(true);
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
    for (const tabId of Object.keys(calls)) await endTab(tabId);
    await chrome.storage.local.remove("pairingToken");
    await chrome.storage.session.clear();
    await badge(false);
    return {ok: true};
  }
  if (message.type === "status") {
    if (pairingToken && message.check) await check(pairingToken);
    const {connection, calls} = await state();
    return {paired: !!pairingToken, connection, call: Object.values(calls).sort((a, b) => b.seenAt - a.seenAt)[0] || null};
  }
  return {ok: false};
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  const popup = sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL("popup.html");
  if (message?.type !== "call-event" && !popup) return false;
  serialized(() => message.type === "call-event" ? accept(message.event, sender) : popupMessage(message))
    .then(respond, () => respond({ok: false, message: "Voice Loop could not save the browser connection. Try again."}));
  return true;
});
chrome.tabs.onRemoved.addListener(tabId => { void serialized(() => endTab(tabId)); });
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.url && !providerForUrl(change.url)) void serialized(() => endTab(tabId));
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name !== RETRY_ALARM) return;
  void serialized(async () => {
    const {calls} = await state();
    for (const [tabId, call] of Object.entries(calls)) {
      try {
        await chrome.tabs.get(+tabId);
        if (Date.now() - call.seenAt > 15_000) await chrome.tabs.sendMessage(+tabId, {type: "snapshot-request"});
      } catch { await endTab(tabId); }
    }
    await flush();
  });
});
chrome.runtime.onStartup.addListener(() => { void serialized(flush); });
