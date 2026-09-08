export const BRIDGE = "http://127.0.0.1:49321";
export const EVENT_TTL = 30_000;
const STATES = new Set(["ringing", "dialing", "connected", "ended"]);
const DIRECTIONS = new Set(["incoming", "outgoing", "unknown"]);
const HOSTS = new Set(["cliq.zoho.com", "cliq.zoho.eu", "cliq.zoho.in", "cliq.zoho.com.au", "cliq.zoho.jp", "cliq.zoho.ca", "cliq.zoho.com.cn", "cliq.zoho.sa"]);
const clean = (value, max) => typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max) : "";
export function providerForUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:") return null;
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
  return {version: 1, event_id: event.event_id, call_id: event.call_id, provider,
    state: event.state, direction: event.direction,
    contact: {name: clean(event.contact?.name, 240)}, title: clean(event.title, 240),
    url: url.origin + url.pathname, timestamp: new Date(timestamp).toISOString()};
}
export function queueLatest(outbox, event, now = Date.now()) {
  // One latest state per call prevents replay of a completed offline call.
  const pending = outbox.filter(item => item.event.call_id !== event.call_id && now - item.queuedAt < EVENT_TTL);
  return [...pending, {event, queuedAt: now}].slice(-30);
}
export function pendingFresh(outbox, now = Date.now()) {
  return outbox.filter(item => now - item.queuedAt < EVENT_TTL && now - Date.parse(item.event.timestamp) < EVENT_TTL);
}
