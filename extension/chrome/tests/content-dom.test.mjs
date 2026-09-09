import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {JSDOM} from "jsdom";

const detectorSource = await readFile(new URL("../detector.js", import.meta.url), "utf8");
const contentSource = await readFile(new URL("../content.js", import.meta.url), "utf8");

async function browserFixture(name, overrideUrl) {
  const html = await readFile(new URL(`dom-fixtures/${name}.html`, import.meta.url), "utf8");
  const url = name.startsWith("meet") ? "https://meet.google.com/abc-defg-hij?authuser=7#private" : "https://cliq.zoho.com/?token=private#chat";
  const dom = new JSDOM(html, {url: overrideUrl || url, runScripts: "outside-only", pretendToBeVisual: true});
  const {window} = dom;
  // jsdom parses HTML and evaluates actual CSS selectors, but has no layout
  // engine. Supply only its missing layout/innerText APIs. Visibility is derived
  // from the real parsed DOM and computed styles, including hidden ancestors;
  // no querySelector/querySelectorAll results or detector snapshots are mocked.
  function hasLayout(element) {
    if (!element.isConnected) return false;
    for (let current = element; current; current = current.parentElement) {
      const style = window.getComputedStyle(current);
      if (current.hidden || style.display === "none" || style.visibility === "hidden") return false;
    }
    return true;
  }
  window.Element.prototype.getClientRects = function () { return hasLayout(this) ? [{width: 100, height: 20}] : []; };
  Object.defineProperty(window.HTMLElement.prototype, "innerText", {get() {
    if (!hasLayout(this)) return "";
    return [...this.childNodes].map(node => node.nodeType === 3 ? node.textContent : node.innerText || "").join("");
  }});
  let now = Date.now();
  window.Date.now = () => now;
  const intervals = new Map();
  const timeouts = new Map();
  let timerId = 0;
  window.setInterval = callback => { const id = ++timerId; intervals.set(id, callback); return id; };
  window.clearInterval = id => intervals.delete(id);
  window.setTimeout = (callback, delay = 0) => { const id = ++timerId; timeouts.set(id, {callback, due: now + delay}); return id; };
  window.clearTimeout = id => timeouts.delete(id);
  const events = [];
  const messages = [];
  const listeners = new Set();
  window.chrome = {runtime: {
    id: "a".repeat(32),
    async sendMessage(message) { messages.push(message); if (message.type === "call-event") events.push(JSON.parse(JSON.stringify(message.event))); return {ok: true}; },
    onMessage: {addListener(callback) { listeners.add(callback); }, removeListener(callback) { listeners.delete(callback); }},
  }};
  window.eval(detectorSource);
  window.eval(contentSource);
  async function advance(ms = 1000) {
    now += ms;
    for (const callback of [...intervals.values()]) callback();
    for (const [id, timer] of [...timeouts.entries()]) if (timer.due <= now) { timeouts.delete(id); timer.callback(); }
    await Promise.resolve();
    await Promise.resolve();
  }
  return {window, document: window.document, events, messages, intervals, timeouts, listeners, advance, close: () => window.close()};
}

test("extension reload synchronous heartbeat failure stops timers and observation", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  b.window.VoiceLoopCommands = {};
  let attempts = 0;
  b.window.chrome.runtime.sendMessage = () => { attempts++; throw new Error("Extension context invalidated."); };
  await b.advance(2000);
  assert.equal(attempts, 1); assert.equal(b.intervals.size, 0); assert.equal(b.listeners.size, 0);
  b.document.querySelector("[statuscontent]").textContent = "Ringing...";
  await b.advance(20000); await b.advance(20000);
  assert.equal(attempts, 1); assert.equal(b.timeouts.size, 0);
});
test("extension reload rejected call heartbeat stops without orphan sends", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  let attempts = 0;
  b.window.chrome.runtime.sendMessage = async () => { attempts++; throw new Error("Extension context invalidated."); };
  await b.advance(10000); await b.advance(10000);
  assert.equal(attempts, 1); assert.equal(b.intervals.size, 0); assert.equal(b.listeners.size, 0);
});
test("removed extension runtime ID shuts down before touching messaging API", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  let attempts = 0;
  b.window.chrome.runtime.sendMessage = () => { attempts++; throw new Error("Must not send"); };
  Object.defineProperty(b.window.chrome.runtime, "id", {get() { throw new Error("Extension context invalidated."); }});
  await b.advance(); assert.equal(attempts, 0); assert.equal(b.intervals.size, 0);
});
test("runtime invalidation between message-listener ID checks cannot escape the listener", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  const callback = [...b.listeners][0];
  let reads = 0;
  Object.defineProperty(b.window.chrome.runtime, "id", {get() {
    if (++reads > 2) throw new Error("Extension context invalidated.");
    return "a".repeat(32);
  }});
  assert.doesNotThrow(() => callback({type: "snapshot-request"}, {id: "a".repeat(32)}, () => {}));
  await b.advance(10000);
  assert.equal(b.intervals.size, 0); assert.equal(b.listeners.size, 0);
});
test("snapshot response to an invalidated worker does not escape the content listener", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  const callback = [...b.listeners][0];
  assert.doesNotThrow(() => callback({type: "assistant-snapshot"}, {id: "a".repeat(32)}, () => { throw new Error("Extension context invalidated."); }));
});
test("transient worker rejection keeps detection alive and later heartbeat succeeds", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  const original = b.window.chrome.runtime.sendMessage;
  b.window.chrome.runtime.sendMessage = async () => { throw new Error("Could not establish connection. Receiving end does not exist."); };
  await b.advance(10000); assert.equal(b.intervals.size, 1);
  b.window.chrome.runtime.sendMessage = original;
  await b.advance(10000); assert.equal(b.events.length, 2); assert.equal(b.events.at(-1).state, "dialing");
});
test("page hide emits ended once and tears down observation", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  b.window.dispatchEvent(new b.window.Event("pagehide"));
  await Promise.resolve();
  assert.equal(b.events.at(-1).state, "ended"); assert.equal(b.intervals.size, 0); assert.equal(b.listeners.size, 0);
  assert.match(b.events.at(-1).event_id, /^pagehide-/);
  const count = b.events.length;
  b.window.dispatchEvent(new b.window.Event("pagehide")); await b.advance(10000); assert.equal(b.events.length, count);
});
test("heartbeat refresh receives an explicit reply and UI terminal IDs identify their source", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  let response;
  [...b.listeners][0]({type: "snapshot-request"}, {id: "a".repeat(32)}, value => { response = value; });
  assert.equal(response.ok, true);
  b.document.querySelector("[statuscontent]").textContent = "No answer";
  await b.advance();
  assert.match(b.events.at(-1).event_id, /^ui-ended-/);
});

test("incoming identity comes from the call wrapper, never the chat open behind it", async t => {
  const b = await browserFixture("cliq-incoming", "https://cliq.zoho.com/company/987/chats/99999"); t.after(b.close);
  assert.equal(b.events[0].chat_id, undefined);
  b.document.querySelector("[mediacallwrapper]").setAttribute("chatid", "12345");
  b.document.querySelector("[mediacallwrapper]").setAttribute("callerid", "111222333");
  b.document.querySelector("[mediacallwrapper]").setAttribute("calleeid", "444555666");
  await b.advance();
  assert.equal(b.events.at(-1).chat_id, "12345");
  assert.equal(b.events.at(-1).chat_url, "https://cliq.zoho.com/company/987/chats/12345");
  assert.equal(b.events.at(-1).participant_id, "111222333");
});

test("call container temporarily missing its wrapper remains safe during a Cliq rerender", async t => {
  const b = await browserFixture("cliq-incoming", "https://cliq.zoho.com/company/987/chats/99999"); t.after(b.close);
  const wrapper = b.document.querySelector("[mediacallwrapper]");
  wrapper.removeAttribute("mediacallwrapper");
  await b.advance(10000);
  assert.equal(b.events.at(-1).state, "ringing");
  assert.equal(b.events.at(-1).chat_id, undefined);
  wrapper.remove();
  await b.advance(); await b.advance(2600);
  assert.equal(b.events.at(-1).state, "ended");
  assert.equal(b.intervals.size, 1);
});

test("outgoing call participant identity uses callee ID from its call wrapper", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  b.document.querySelector("[mediacallwrapper]").setAttribute("callerid", "111222333");
  b.document.querySelector("[mediacallwrapper]").setAttribute("calleeid", "444555666");
  await b.advance();
  assert.equal(b.events.at(-1).participant_id, "444555666");
});

test("Cliq connecting rerender with hidden old wrapper and no timer preserves the outgoing call", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  const callId = b.events[0].call_id;
  const connecting = await readFile(new URL("dom-fixtures/cliq-connecting.html", import.meta.url), "utf8");
  const parsed = new b.window.DOMParser().parseFromString(connecting, "text/html");
  b.document.querySelector("#mediacall_container").replaceWith(b.document.importNode(parsed.querySelector("#mediacall_container"), true));
  for (const delay of [1000, 4000, 4000]) await b.advance(delay);
  assert.equal(b.events.some(event => event.state === "ended" || event.state === "connected"), false);
  const current = [...b.document.querySelectorAll("[mediacallwrapper]")].find(wrapper => wrapper.getAttribute("callid") === "synthetic-call-one");
  const timer = b.document.createElement("span"); timer.id = "mediacallsessiontimer";
  timer.innerHTML = "<span>00</span> : <span>00</span> : <span>02</span>";
  current.querySelector(".AV-call-main").append(timer);
  await b.advance(); await b.advance();
  assert.equal(b.events.at(-1).state, "connected");
  assert.equal(b.events.at(-1).call_id, callId); assert.equal(b.events.at(-1).direction, "outgoing");
  assert.equal(b.events.at(-1).contact.name, "Test Contact");
  current.remove(); await b.advance(); await b.advance(2600);
  assert.equal(b.events.at(-1).state, "ended");
});
test("observed Cliq provisional ID handoff then split-span timer retains command-correlatable call ID", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  const wrapper = b.document.querySelector("[mediacallwrapper]");
  wrapper.setAttribute("calleeid", "111222333"); await b.advance();
  const callId = b.events.at(-1).call_id;
  wrapper.setAttribute("callid", "synthetic-final-server-call"); await b.advance(1200);
  assert.equal(b.events.at(-1).state, "dialing"); assert.equal(b.events.at(-1).call_id, callId);
  assert.match(b.events.at(-1).event_id, /^native-handoff-/);
  wrapper.className = "AV-call-wrapper AV-call-audio-only";
  wrapper.querySelector(".AV-call-outgoing").style.display = "none";
  wrapper.querySelector("#mediacallsessionsubtimer").innerHTML = '<span hours style="display:none">00</span><span separator style="display:none">:</span><span minutes>00</span><span separator>:</span><span seconds>05</span>';
  await b.advance(); await b.advance();
  assert.equal(b.events.at(-1).state, "connected"); assert.equal(b.events.at(-1).call_id, callId);
  assert.equal(b.events.some(event => event.state === "ended"), false);
});

test("an exact visible Connected status activates a retained outgoing layout without a timer", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  const callId = b.events.at(-1).call_id;
  b.document.querySelector("[statuscontent]").textContent = "Connected";
  await b.advance(1000); await b.advance(1000);
  assert.deepEqual(b.events.map(event => event.state), ["dialing", "connected"]);
  assert.equal(b.events.at(-1).call_id, callId);
  assert.equal(b.events.at(-1).direction, "outgoing");
});

test("a visible running call timer overrides only a stale outgoing layout marker", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  b.document.querySelector("[statuscontent]").textContent = "";
  b.document.querySelector("#mediacallsessionsubtimer").textContent = "00:03";
  await b.advance(1000); await b.advance(1000);
  assert.deepEqual(b.events.map(event => event.state), ["dialing", "connected"]);
});

for (const text of ["Ringing...", "Calling...", "Waiting for the answer", "SFU connected", "Not connected", "Call connected to the server"]) {
  test(`unattended status never establishes a connection: ${text}`, async t => {
    const b = await browserFixture("cliq-outgoing"); t.after(b.close);
    b.document.querySelector("[statuscontent]").textContent = text;
    if (/Ringing|Calling|Waiting/.test(text)) b.document.querySelector("#mediacallsessionsubtimer").textContent = "00:03";
    await b.advance(1000); await b.advance(1000);
    assert.equal(b.events.some(event => event.state === "connected"), false);
  });
}

test("a visible native call wrapper takes priority over unrelated generic call status panels", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  const panel = b.document.createElement("div"); panel.setAttribute("data-call-state", "idle");
  panel.innerHTML = "<span statuscontent>Call ended</span>";
  b.document.body.prepend(panel);
  await b.advance(); await b.advance(4000);
  assert.equal(b.events.some(event => event.state === "ended"), false);
});

test("real content.js maps observed Cliq outgoing HTML to dialing/contact without hidden timer attendance", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  await b.advance(1000); await b.advance(1000);
  assert.deepEqual(b.events.map(event => event.state), ["dialing"]);
  assert.equal(b.events[0].contact.name, "Test Contact");
  assert.equal(b.events[0].direction, "outgoing");
  assert.equal(b.events[0].title, "Call with Test Contact");
  assert.equal(b.events[0].url, "https://cliq.zoho.com/");
  b.document.querySelector("[statuscontent]").textContent = "No answer";
  await b.advance();
  assert.deepEqual(b.events.map(event => event.state), ["dialing", "ended"]);
});

test("real content.js gates an outgoing answer on visible timer, preserves metadata, then ends on call removal", async t => {
  const b = await browserFixture("cliq-outgoing"); t.after(b.close);
  const firstId = b.events[0].call_id;
  b.document.querySelector("[initialcontainer]").style.display = "none";
  b.document.querySelector(".AV-call-main").style.display = "block";
  b.document.querySelector(".AV-call-main [other-username]").textContent = "Test Contact";
  b.document.querySelector("#mediacallsessiontimer").textContent = "00:00";
  await b.advance();
  assert.equal(b.events.some(event => event.state === "connected"), false);
  b.document.querySelector("#mediacallsessiontimer").textContent = "00:01";
  await b.advance(); await b.advance();
  assert.deepEqual(b.events.map(event => event.state), ["dialing", "connected"]);
  assert.equal(b.events[1].call_id, firstId);
  assert.equal(b.events[1].direction, "outgoing");
  assert.equal(b.events[1].contact.name, "Test Contact");
  b.document.querySelector("#mediacall_container").remove();
  await b.advance(); await b.advance(2600);
  assert.equal(b.events.at(-1).state, "ended");
  assert.equal(b.events.at(-1).call_id, firstId);
});

test("real content.js representative incoming HTML waits for attendance and preserves incoming caller", async t => {
  const b = await browserFixture("cliq-incoming"); t.after(b.close);
  assert.equal(b.events[0].state, "ringing");
  assert.equal(b.events[0].direction, "incoming");
  assert.equal(b.events[0].contact.name, "Test Caller");
  await b.advance(2000);
  assert.equal(b.events.length, 1);
  b.document.querySelector("[initialcontainer]").style.display = "none";
  b.document.querySelector(".AV-call-main").style.display = "block";
  b.document.querySelector(".AV-call-main [other-username]").textContent = "Test Caller";
  b.document.querySelector("#mediacallsessiontimer").textContent = "00:00";
  await b.advance(); await b.advance(5000);
  assert.deepEqual(b.events.map(event => event.state), ["ringing"]);
  b.document.querySelector("#mediacallsessiontimer").textContent = "00:01";
  await b.advance(); await b.advance();
  assert.equal(b.events.at(-1).state, "connected");
  assert.equal(b.events.at(-1).call_id, b.events[0].call_id);
  assert.equal(b.events.at(-1).direction, "incoming");
  assert.equal(b.events.at(-1).contact.name, "Test Caller");
});

test("real content.js ignores declined incoming calls and unrelated chat timestamps", async t => {
  const b = await browserFixture("cliq-incoming"); t.after(b.close);
  b.document.querySelector("[statuscontent]").textContent = "Call declined";
  await b.advance();
  assert.deepEqual(b.events.map(event => event.state), ["ringing", "ended"]);
  b.document.querySelector("#mediacall_container").remove();
  await b.advance(5000);
  assert.equal(b.events.length, 2);
});

test("real content.js representative answered HTML ignores hidden ringing and emits attended metadata", async t => {
  const b = await browserFixture("cliq-answered"); t.after(b.close);
  await b.advance();
  assert.equal(b.events.length, 1);
  assert.equal(b.events[0].state, "connected");
  assert.equal(b.events[0].contact.name, "Test Attendee");
  assert.equal(b.events[0].direction, "unknown");
});

test("real content.js detects a new Cliq source call ID before treating a fresh invitation as attended", async t => {
  const b = await browserFixture("cliq-answered"); t.after(b.close);
  await b.advance();
  const firstId = b.events[0].call_id;
  b.document.querySelector("[mediacallwrapper]").setAttribute("callid", "synthetic-next-call");
  b.document.querySelector(".AV-call-main").style.display = "none";
  b.document.querySelector("[initialcontainer]").style.display = "block";
  b.document.querySelector("[initialcontainer] button").remove();
  await b.advance(); await b.advance();
  assert.deepEqual(b.events.map(event => event.state), ["connected", "ended", "dialing"]);
  assert.notEqual(b.events.at(-1).call_id, firstId);
});

test("real content.js maps observed joined Meet HTML to meeting code, never the details icon text", async t => {
  const b = await browserFixture("meet-joined"); t.after(b.close);
  await b.advance();
  assert.equal(b.events.length, 1);
  assert.equal(b.events[0].state, "connected");
  assert.equal(b.events[0].title, "abc-defg-hij");
  assert.equal(b.events[0].contact.name, "");
  assert.equal(b.events[0].url, "https://meet.google.com/abc-defg-hij");
  b.window.dispatchEvent(new b.window.Event("pagehide"));
  assert.equal(b.events.at(-1).state, "ended");
});

test("real content.js ignores Meet preview/ask-to-join despite microphone and hidden leave controls", async t => {
  const b = await browserFixture("meet-preview"); t.after(b.close);
  await b.advance(); await b.advance();
  assert.equal(b.events.length, 0);
  b.document.querySelector("#join").setAttribute("aria-label", "Ask to join");
  b.document.querySelector("#join").textContent = "Ask to join";
  // Even during a transitional DOM overlap, the visible join control vetoes attendance.
  b.document.querySelector("#joined-controls").style.display = "block";
  await b.advance(); await b.advance();
  assert.equal(b.events.length, 0);
  b.document.querySelector("#join").remove();
  b.document.title = "Project planning – Google Meet";
  await b.advance(); await b.advance();
  assert.equal(b.events.length, 1);
  assert.equal(b.events[0].title, "Project planning");
});
