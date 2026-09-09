export const BRIDGE = "http://127.0.0.1:49321";
export const EVENT_TTL = 30_000;
const STATES = new Set(["ringing", "dialing", "connected", "ended"]);
const DIRECTIONS = new Set(["incoming", "outgoing", "unknown"]);
const HOSTS = new Set(["cliq.zoho.com", "cliq.zoho.eu", "cliq.zoho.in", "cliq.zoho.com.au", "cliq.zoho.jp", "cliq.zoho.ca", "cliq.zoho.com.cn", "cliq.zoho.sa"]);
const clean = (value, max) => typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max) : "";
export function providerForUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
    if (url.hostname === "meet.google.com") return "google_meet";
    return HOSTS.has(url.hostname) ? "zoho_cliq" : null;
  } catch { return null; }
}
export function normalizeEvent(event, senderUrl, now = Date.now()) {
  const provider = providerForUrl(senderUrl);
  if (!event || event.version !== 1 || !provider || event.provider !== provider || !STATES.has(event.state) || !DIRECTIONS.has(event.direction)) return null;
  if (![event.event_id, event.call_id].every(value => typeof value === "string" && /^[a-zA-Z0-9_-]{1,100}$/.test(value))) return null;
  const timestamp = Date.parse(event.timestamp);
  if (!Number.isFinite(timestamp) || Math.abs(now - timestamp) > EVENT_TTL) return null;
  const url = new URL(senderUrl);
  const target = chatTarget(event.chat_url, event.chat_id);
  const metadata = target && target.origin === url.origin ? {chat_id: target.chat_id, chat_url: target.chat_url} : {};
  if (provider === "zoho_cliq" && typeof event.participant_id === "string" && /^[0-9]{1,64}$/.test(event.participant_id)) metadata.participant_id = event.participant_id;
  return {version: 1, event_id: event.event_id, call_id: event.call_id, provider,
    state: event.state, direction: event.direction,
    contact: {name: clean(event.contact?.name, 240)}, title: clean(event.title, 240),
    url: url.origin + url.pathname, timestamp: new Date(timestamp).toISOString(), ...metadata};
}
export function chatTarget(value, chatId) {
  try {
    const url = new URL(value);
    const path = url.pathname.match(/^\/company\/([0-9]+)\/chats\/([0-9]{1,64})\/?$/);
    if (providerForUrl(value) !== "zoho_cliq" || !path || url.search || url.hash || typeof chatId !== "string" || path[2] !== chatId) return null;
    return {origin: url.origin, chat_id: chatId, chat_url: url.origin + url.pathname.replace(/\/$/, "")};
  } catch { return null; }
}
export function normalizeCommand(command, profileId, now = Date.now()) {
  if (!command || command.version !== 1 || command.profile_id !== profileId || !/^[A-Za-z0-9_-]{1,128}$/.test(command.command_id || "")) return null;
  if (!["call", "answer", "hangup", "send_summary"].includes(command.action)) return null;
  const expires = Date.parse(command.expires_at);
  if (!Number.isFinite(expires) || expires <= now || expires > now + 121000) return null;
  if (typeof command.call_id !== "string" || (command.call_id && !/^[A-Za-z0-9_-]{1,128}$/.test(command.call_id))) return null;
  if (["answer", "hangup"].includes(command.action) && !command.call_id) return null;
  const participantId = command.participant_id || "";
  if (typeof participantId !== "string" || participantId && !/^[0-9]{1,64}$/.test(participantId)) return null;
  const target = chatTarget(command.chat_url, command.chat_id);
  if (command.provider === "zoho_cliq" ? !target : command.provider !== "google_meet" || command.action !== "hangup" || command.chat_id || command.chat_url) return null;
  if (typeof command.text !== "string" || command.text.length > 4000 || /[\u0000-\u0008\u000b-\u001f\u007f]/.test(command.text)) return null;
  if (command.action === "send_summary" && !command.text.trim()) return null;
  return {version: 1, command_id: command.command_id, profile_id: profileId, action: command.action,
    provider: command.provider, call_id: command.call_id, chat_id: target?.chat_id || "", chat_url: target?.chat_url || "",
    participant_id: participantId, text: command.text, expires_at: new Date(expires).toISOString()};
}
export function queueLatest(outbox, event, now = Date.now()) {
  // One latest state per call prevents replay of a completed offline call.
  const pending = outbox.filter(item => item.event.call_id !== event.call_id && now - item.queuedAt < EVENT_TTL);
  return [...pending, {event, queuedAt: now}].slice(-30);
}
export function pendingFresh(outbox, now = Date.now()) {
  return outbox.filter(item => now - item.queuedAt < EVENT_TTL && now - Date.parse(item.event.timestamp) < EVENT_TTL);
}
