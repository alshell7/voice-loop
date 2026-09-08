import test from "node:test";
import assert from "node:assert/strict";
import {normalizeEvent, queueLatest, pendingFresh, providerForUrl} from "../protocol.mjs";
const now = Date.parse("2026-09-08T12:00:00Z");
const event = {version: 1, event_id: "event-1", call_id: "call-1", provider: "zoho_cliq", state: "dialing", direction: "outgoing", contact: {name: "Test Contact"}, title: "Test call", url: "https://untrusted.example", timestamp: new Date(now).toISOString()};
test("worker derives provider and safe URL from browser-authenticated sender", () => {
  const result = normalizeEvent(event, "https://cliq.zoho.com/path?token=secret#chat", now);
  assert.equal(result.url, "https://cliq.zoho.com/path");
  assert.equal(normalizeEvent({...event, provider: "google_meet"}, "https://cliq.zoho.com/", now), null);
  assert.equal(normalizeEvent(event, "https://evil.example/", now), null);
  assert.equal(providerForUrl("https://cliq.zoho.com.evil.example/"), null);
});
test("malformed states, IDs, stale and future timestamps are rejected", () => {
  for (const patch of [{version: 2}, {state: "record"}, {direction: "self"}, {event_id: "bad id"}, {call_id: []}, {timestamp: "no"}, {timestamp: new Date(now - 31000).toISOString()}, {timestamp: new Date(now + 31000).toISOString()}]) {
    assert.equal(normalizeEvent({...event, ...patch}, "https://cliq.zoho.com/", now), null);
  }
});
test("metadata is bounded and unknown fields never cross bridge", () => {
  const result = normalizeEvent({...event, contact: {name: "A".repeat(500), password: "secret"}, audio: "blob", title: "Hi\nthere"}, "https://cliq.zoho.com/", now);
  assert.equal(result.contact.name.length, 240);
  assert.equal(result.contact.password, undefined);
  assert.equal(result.audio, undefined);
  assert.equal(result.title, "Hi there");
});
test("latest state replaces queued connected state after an offline call ends", () => {
  let queue = queueLatest([], {...event, state: "connected"}, now);
  queue = queueLatest(queue, {...event, event_id: "ended-event", state: "ended"}, now + 1000);
  assert.equal(queue.length, 1);
  assert.equal(queue[0].event.state, "ended");
  assert.equal(pendingFresh(queue, now + 31000).length, 0);
});
test("queue isolates concurrent calls and bounds memory", () => {
  let queue = [];
  for (let i = 0; i < 40; i++) queue = queueLatest(queue, {...event, call_id: `call-${i}`}, now);
  assert.equal(queue.length, 30);
  assert.equal(queue[0].event.call_id, "call-10");
});
