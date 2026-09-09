import test from "node:test";
import assert from "node:assert/strict";
import {normalizeEvent, queueLatest, pendingFresh, providerForUrl, normalizeCommand, chatTarget} from "../protocol.mjs";
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
test("command protocol permits only current exact-profile actions and targets", () => {
  const command = {version: 1, command_id: "cmd-1", profile_id: "profile-1", action: "call", provider: "zoho_cliq", chat_id: "12345", chat_url: "https://cliq.zoho.com/company/987/chats/12345", call_id: "", text: "", expires_at: new Date(now + 45000).toISOString()};
  assert.equal(normalizeCommand(command, "profile-1", now).chat_id, "12345");
  for (const patch of [{action: "evaluate"}, {action: "answer"}, {profile_id: "profile-2"}, {chat_id: "99999"}, {chat_url: "javascript:alert(1)"}, {chat_url: command.chat_url + "?token=secret"}, {expires_at: new Date(now - 1).toISOString()}, {expires_at: new Date(now + 122000).toISOString()}, {text: "x".repeat(4001)}, {action: "send_summary", text: ""}]) {
    assert.equal(normalizeCommand({...command, ...patch}, "profile-1", now), null);
  }
  assert.equal(normalizeCommand({...command, action: "hangup", provider: "google_meet", call_id: "meet-call", chat_id: "", chat_url: ""}, "profile-1", now).action, "hangup");
  assert.equal(normalizeCommand(command, "profile-1", now).busy_fallback, false);
  assert.equal(normalizeCommand({...command, busy_fallback: true}, "profile-1", now).busy_fallback, true);
  for (const busy_fallback of [null, 1, "true", {}, []]) assert.equal(normalizeCommand({...command, busy_fallback}, "profile-1", now), null);
  assert.equal(normalizeCommand({...command, action: "send_summary", text: "Objective", busy_fallback: true}, "profile-1", now), null);
  assert.equal(normalizeCommand({...command, call_id: "existing-call", busy_fallback: true}, "profile-1", now), null);
  assert.equal(chatTarget("https://user@cliq.zoho.com/company/987/chats/12345", "12345"), null);
});
test("optional event chat identity cannot cross origin or forge worker correlation", () => {
  const result = normalizeEvent({...event, chat_id: "12345", chat_url: "https://cliq.zoho.com/company/987/chats/12345", profile_id: "fake-profile", command_id: "fake-command"}, "https://cliq.zoho.com/", now);
  assert.equal(result.chat_id, "12345"); assert.equal(result.profile_id, undefined); assert.equal(result.command_id, undefined);
  assert.equal(normalizeEvent({...event, chat_id: "12345", chat_url: "https://cliq.zoho.eu/company/987/chats/12345"}, "https://cliq.zoho.com/", now).chat_id, undefined);
});
test("diagnostic terminal event ID prefixes retain protocol v1 compatibility", () => {
  for (const reason of ["native-handoff", "native-replaced", "ui-ended", "ui-absent", "pagehide", "tab-closed", "tab-missing", "navigation", "unpaired"]) {
    const id = `${reason}-11111111-2222-3333-4444-555555555555`;
    assert.equal(normalizeEvent({...event, state: "ended", event_id: id}, "https://cliq.zoho.com/", now).event_id, id);
  }
});
