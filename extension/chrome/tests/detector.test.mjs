import test from "node:test";
import assert from "node:assert/strict";
import "../detector.js";
import {outgoing, incoming, connected, meetPreview, meetJoined} from "./fixtures.mjs";
const {classify, CallTracker, providerFor, timerSeconds, controlLabel} = globalThis.VoiceLoopDetector;
const tracker = () => new CallTracker({uuid: () => "test-call-id"});

test("Cliq ringing is never connected even when the RTC server is connected", () => {
  assert.equal(classify({...outgoing, rtc: {connected: 1, remoteAudio: 1}, elapsed: 30}), "dialing");
  assert.equal(classify({...incoming, elapsed: 30}), "ringing");
});
test("incoming call keeps its identity and caller until attended, then ends", () => {
  const t = tracker();
  const ring = t.observe(incoming, 1000);
  assert.equal(ring.state, "ringing");
  assert.equal(ring.direction, "incoming");
  assert.equal(t.observe(connected, 2000), null);
  const attended = t.observe(connected, 2800);
  assert.equal(attended.call_id, ring.call_id);
  assert.equal(attended.state, "connected");
  assert.equal(attended.contact.name, "Test Contact");
  assert.equal(attended.direction, "incoming");
  assert.equal(t.observe({...connected, ended: true}, 3000).state, "ended");
  assert.equal(t.call, null);
});
test("slow incoming handshake retains identity and direction without establishing attendance", () => {
  const t = tracker();
  const call = {...incoming, nativeCallKey: "native-incoming"};
  const ring = t.observe(call, 0);
  const handshake = {...call, incoming: false, elapsed: 0};
  for (const at of [1000, 4000, 9000, 20000]) {
    assert.equal(t.observe(handshake, at), null);
    assert.equal(t.call.state, "ringing");
    assert.equal(t.call.direction, "incoming");
    assert.equal(t.call.call_id, ring.call_id);
  }
  assert.equal(t.observe({...handshake, elapsed: 1}, 21000), null);
  const attended = t.observe({...handshake, elapsed: 2}, 21800);
  assert.equal(attended.state, "connected");
  assert.equal(attended.call_id, ring.call_id);
  assert.equal(attended.direction, "incoming");
});
test("a pending handshake still ends on explicit termination or actual wrapper absence", () => {
  for (const explicit of [true, false]) {
    const t = tracker();
    const invitation = {...incoming, nativeCallKey: "native-incoming"};
    t.observe(invitation, 0);
    const handshake = {...invitation, incoming: false, elapsed: 0};
    t.observe(handshake, 1000); t.observe(handshake, 5000);
    const endedSnapshot = explicit ? {...handshake, ended: true} : {...handshake, callPanel: false, hangup: false, nativeCallKey: ""};
    let ended = t.observe(endedSnapshot, 6000);
    if (!explicit) {
      assert.equal(ended, null);
      ended = t.observe(endedSnapshot, 8600);
    }
    assert.equal(ended.state, "ended");
    assert.equal(ended.direction, "incoming");
    assert.equal(t.call, null);
  }
});
test("replacement call during an incoming handshake gets a new identity and its own direction", () => {
  let id = 0;
  const t = new CallTracker({uuid: () => `call-${++id}`});
  t.observe({...incoming, nativeCallKey: "native-incoming"}, 0);
  t.observe({...incoming, nativeCallKey: "native-incoming", incoming: false, elapsed: 0}, 1000);
  const replacement = {...outgoing, nativeCallKey: "native-outgoing"};
  assert.equal(t.observe(replacement, 5000).state, "ended");
  const next = t.observe(replacement, 6000);
  assert.equal(next.state, "dialing");
  assert.equal(next.call_id, "call-2");
  assert.equal(next.direction, "outgoing");
});
test("zero timer alone cannot preserve an invitation without the same visible call and hangup", () => {
  for (const patch of [{nativeCallKey: ""}, {hangup: false}, {callPanel: false}]) {
    const t = tracker();
    t.observe({...incoming, nativeCallKey: "native-incoming"}, 0);
    const candidate = {...incoming, incoming: false, elapsed: 0, nativeCallKey: "native-incoming", ...patch};
    assert.equal(t.observe(candidate, 1000), null);
    assert.equal(t.observe(candidate, 3600).state, "ended");
  }
});
test("outgoing call connects only after answer and preserves outgoing direction", () => {
  const t = tracker(); t.observe(outgoing, 1000);
  assert.equal(t.observe(outgoing, 9000), null);
  assert.equal(t.call.state, "dialing");
  t.observe(connected, 10_000);
  const event = t.observe(connected, 10_800);
  assert.equal(event.state, "connected");
  assert.equal(event.direction, "outgoing");
});
test("unanswered and rejected calls never enter connected state", () => {
  for (const initial of [outgoing, incoming]) {
    const t = tracker(); t.observe(initial, 0);
    assert.equal(t.observe({...initial, ended: true}, 1000).state, "ended");
    assert.equal(t.observe({...initial, callPanel: false}, 5000), null);
  }
});
test("microphone preview and empty timers do not count as attendance", () => {
  assert.equal(classify({...outgoing, dialing: false, elapsed: 0, rtc: {remoteAudio: 1}}), null);
  assert.equal(classify({...outgoing, dialing: false, elapsed: -1}), null);
  assert.equal(classify({...connected, hangup: false}), null);
  assert.equal(classify({...connected, callPanel: false}), null);
  assert.equal(classify(meetPreview), null);
});
test("Meet preview, waiting room and rejoin screen are ignored", () => {
  assert.equal(classify({...meetPreview, hangup: true}), null);
  assert.equal(classify({...meetJoined, ended: true}), null);
  assert.equal(classify({...meetJoined, meetingPath: false}), null);
});
test("joined Meet emits a stable call with title and strips URL secrets", () => {
  const t = tracker(); assert.equal(t.observe(meetJoined, 0), null);
  const event = t.observe(meetJoined, 800);
  assert.equal(event.state, "connected");
  assert.equal(event.title, "Weekly planning");
  assert.equal(event.url, "https://meet.google.com/abc-defg-hij");
  assert.equal(t.observe(meetJoined, 10000), null);
});
test("short DOM rerenders do not end or split an attended call", () => {
  const t = tracker(); t.observe(connected, 0); t.observe(connected, 800);
  assert.equal(t.observe({...connected, callPanel: false}, 1000), null);
  assert.equal(t.observe(connected, 2000), null);
  assert.equal(t.call.state, "connected");
  t.observe({...connected, callPanel: false}, 3000);
  assert.equal(t.observe({...connected, callPanel: false}, 5600).state, "ended");
});
test("reconnect invitations cannot downgrade a connected session", () => {
  const t = tracker(); t.observe(connected, 0); t.observe(connected, 800);
  assert.equal(t.observe(outgoing, 1200), null);
  assert.equal(t.call.state, "connected");
});
test("a different native call closes the previous session before a new invitation", () => {
  let id = 0;
  const t = new CallTracker({uuid: () => `call-${++id}`});
  t.observe({...connected, nativeCallKey: "native-call-one"}, 0);
  t.observe({...connected, nativeCallKey: "native-call-one"}, 800);
  assert.equal(t.observe({...outgoing, nativeCallKey: "native-call-two"}, 1000).state, "ended");
  const invitation = t.observe({...outgoing, nativeCallKey: "native-call-two"}, 1200);
  assert.equal(invitation.state, "dialing");
  assert.equal(invitation.call_id, "call-2");
  assert.equal(invitation.nativeCallKey, undefined);
});
test("metadata updates preserve call identity and survive temporarily missing names", () => {
  const t = tracker(); t.observe(outgoing, 0);
  const updated = t.observe({...outgoing, contact: "Updated Contact"}, 1000);
  assert.equal(updated.call_id, "test-call-id");
  assert.equal(t.observe({...outgoing, contact: ""}, 2000), null);
  assert.equal(t.call.contact.name, "Updated Contact");
});
test("allowlist rejects spoofed and unsupported website origins", () => {
  assert.equal(providerFor("https://cliq.zoho.in/"), "zoho_cliq");
  assert.equal(providerFor("https://cliq.zoho.com.evil.example/"), null);
  assert.equal(providerFor("http://cliq.zoho.com/"), null);
  assert.equal(providerFor("https://teams.microsoft.com/"), null);
});
test("timer parser accepts duration and rejects invalid text", () => {
  assert.equal(timerSeconds(" 00:01 "), 1);
  assert.equal(timerSeconds("1:02:03"), 3723);
  assert.equal(timerSeconds("12:60"), null);
  assert.equal(timerSeconds("Calling..."), null);
  assert.equal(timerSeconds(""), null);
});
test("control labels prefer accessible names without duplicate text or icon glyphs", () => {
  assert.equal(controlLabel({aria: "Join now", text: "Join now"}), "Join now");
  assert.equal(controlLabel({aria: "Leave call", text: "call_end"}), "Leave call");
  assert.equal(controlLabel({avTooltip: "End call", text: "phone"}), "End call");
  assert.equal(controlLabel({text: "Answer"}), "Answer");
  assert.equal(controlLabel({text: "A".repeat(90)}), "");
});
