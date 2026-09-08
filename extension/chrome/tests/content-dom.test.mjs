import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {JSDOM} from "jsdom";

const detectorSource = await readFile(new URL("../detector.js", import.meta.url), "utf8");
const contentSource = await readFile(new URL("../content.js", import.meta.url), "utf8");

async function browserFixture(name) {
  const html = await readFile(new URL(`dom-fixtures/${name}.html`, import.meta.url), "utf8");
  const url = name.startsWith("meet") ? "https://meet.google.com/abc-defg-hij?authuser=7#private" : "https://cliq.zoho.com/?token=private#chat";
  const dom = new JSDOM(html, {url, runScripts: "outside-only", pretendToBeVisual: true});
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
  window.chrome = {runtime: {
    async sendMessage(message) { assert.equal(message.type, "call-event"); events.push(JSON.parse(JSON.stringify(message.event))); return {ok: true}; },
    onMessage: {addListener() {}},
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
  return {window, document: window.document, events, advance, close: () => window.close()};
}

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
