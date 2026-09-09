import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {JSDOM} from "jsdom";
const detector = await readFile(new URL("../detector.js", import.meta.url), "utf8");
const commands = await readFile(new URL("../commands.js", import.meta.url), "utf8");
const CHAT = "12345", CHAT_URL = `https://cliq.zoho.com/company/987/chats/${CHAT}`;
function fixture(html, url = CHAT_URL) {
  const dom = new JSDOM(html, {url, runScripts: "outside-only", pretendToBeVisual: true});
  const w = dom.window;
  w.Element.prototype.getClientRects = function () {
    if (!this.isConnected) return [];
    for (let node = this; node; node = node.parentElement) if (node.hidden || w.getComputedStyle(node).display === "none") return [];
    return [{width: 100, height: 20}];
  };
  w.eval(detector); w.eval(commands);
  let call = null, snapshot = {callPanel: false, hangup: false}, active = true;
  return {w, d: w.document, close: () => w.close(), setActive: value => { active = value; }, setCall: value => { call = value; }, setSnapshot: value => { snapshot = value; },
    execute: patch => w.VoiceLoopCommands.execute({version: 1, command_id: "cmd-1", profile_id: "profile-1", action: "call", provider: "zoho_cliq", call_id: "", chat_id: CHAT, chat_url: CHAT_URL, text: "", expires_at: new Date(Date.now() + 2000).toISOString(), ...patch}, {getCall: () => call, snapshot: () => snapshot, tick() {}, isActive: () => active})};
}
test("extension invalidation after opening call menu prevents dialing", async t => {
  const b = fixture(`<button id="onetoonecall_call_12345">Call</button><button id="audio" hidden>Audio Call</button>`); t.after(b.close);
  let dialed = 0;
  b.d.querySelector("#onetoonecall_call_12345").onclick = () => { b.setActive(false); b.d.querySelector("#audio").hidden = false; };
  b.d.querySelector("#audio").onclick = () => dialed++;
  const result = await b.execute({}); assert.equal(result.status, "failed"); assert.equal(dialed, 0); assert.match(result.detail, /connection ended/);
});
test("outgoing command clicks only the exact visible chat audio controls", async t => {
  const b = fixture(`<button id="onetoonecall_call_12345" hidden>Call</button><button id="onetoonecall_call_12345">Call</button><button id="audio" hidden>Audio Call</button>`); t.after(b.close);
  let count = 0;
  b.d.querySelectorAll("#onetoonecall_call_12345")[1].onclick = () => { b.d.querySelector("#audio").hidden = false; };
  b.d.querySelector("#audio").onclick = () => { count++; b.setSnapshot({callPanel: true, dialing: true}); b.setCall({call_id: "new-call", direction: "outgoing"}); };
  const result = await b.execute({});
  assert.equal(result.status, "succeeded"); assert.equal(result.call_id, "new-call"); assert.equal(count, 1);
});
test("outgoing command refuses another chat, expired command or existing call", async t => {
  const b = fixture(`<button id="onetoonecall_call_12345">Call</button>`); t.after(b.close);
  let count = 0; b.d.querySelector("button").onclick = () => count++;
  assert.equal((await b.execute({chat_url: "https://cliq.zoho.com/company/987/chats/99999"})).status, "failed");
  assert.equal((await b.execute({expires_at: new Date(Date.now() - 100).toISOString()})).status, "failed");
  b.setSnapshot({callPanel: true}); assert.equal((await b.execute({})).status, "failed"); assert.equal(count, 0);
});
test("observed Cliq bare DIV menu chooses exact chat audio option, never video or another chat", async t => {
  const b = fixture(`<button id="onetoonecall_call_12345">Call</button><div class="zcl-menu-wrap no-pointer cht-hdr-dropdown" type="menuOption" hidden><div id="audio_call_12345" chid="12345" class="zcl-menu-item ellips" purpose="options"><em></em><span>Audio Call</span></div><div id="audio_call_99999" chid="99999" purpose="options"><span>Audio Call</span></div><div id="video_call_12345" chid="12345" purpose="options"><span>Video Call</span></div></div>`); t.after(b.close);
  const clicked = [];
  b.d.querySelector("button").onclick = () => { b.d.querySelector("[type='menuOption']").hidden = false; };
  for (const option of b.d.querySelectorAll("[purpose='options']")) option.onclick = () => { clicked.push(option.id); b.setSnapshot({callPanel: true, dialing: true}); b.setCall({call_id: "new-call", direction: "outgoing"}); };
  const result = await b.execute({}); assert.equal(result.status, "succeeded"); assert.deepEqual(clicked, ["audio_call_12345"]);
});
function presenceFixture(presence = "Away", {preexisting = false, title = "Start Audio Call?", duplicateStart = false} = {}) {
  const b = fixture(`<button id="onetoonecall_call_12345">Call</button><button id="audio" hidden>Audio Call</button><div id="callConfirmation" type="popup" class="modalwindow zcl-alert-dialog-2 call-confirmation-dialog" ${preexisting ? "" : "hidden"}><div><div id="winhead" class="mheader drag"><div class="mheader_ttl">${title}</div><div class="mheader_p">The user's status is <b>${presence}</b>. Do you still want to proceed with the call?</div></div><div class="mcontent"><div class="mcontent_btn_con textR"><button button="1">Cancel</button><button button="2">Start</button>${duplicateStart ? "<button>Start</button>" : ""}</div></div></div></div>`);
  b.clicks = {menu: 0, audio: 0, start: 0};
  b.d.querySelector("#onetoonecall_call_12345").onclick = () => { b.clicks.menu++; b.d.querySelector("#audio").hidden = false; };
  b.d.querySelector("#audio").onclick = () => { b.clicks.audio++; b.d.querySelector("#callConfirmation").hidden = false; b.afterAudio?.(); };
  b.d.querySelector("[button='2']").onclick = () => {
    b.clicks.start++;
    b.setSnapshot({callPanel: true, dialing: true});
    b.setCall({call_id: "confirmed-call", direction: "outgoing"});
  };
  return b;
}
for (const presence of ["Away", "Busy", "Offline", "Do Not Disturb"]) {
  test(`observed Cliq ${presence} audio confirmation automatically clicks Start once`, async t => {
    const b = presenceFixture(presence); t.after(b.close);
    const result = await b.execute({});
    assert.equal(result.status, "succeeded"); assert.equal(result.call_id, "confirmed-call");
    assert.deepEqual(b.clicks, {menu: 1, audio: 1, start: 1});
  });
}
test("an existing call confirmation is never inherited or clicked by a new command", async t => {
  const b = presenceFixture("Away", {preexisting: true}); t.after(b.close);
  const result = await b.execute({}); assert.equal(result.status, "failed");
  assert.deepEqual(b.clicks, {menu: 0, audio: 0, start: 0}); assert.match(result.detail, /earlier call confirmation/);
});
for (const cause of ["expiry", "context", "target"]) {
  test(`pending presence confirmation is not accepted after ${cause} changes`, async t => {
    const b = presenceFixture(); t.after(b.close);
    const before = Date.now();
    b.afterAudio = () => {
      if (cause === "expiry") b.w.Date.now = () => before + 5000;
      else if (cause === "context") b.setActive(false);
      else b.w.history.replaceState({}, "", "/company/987/chats/99999");
    };
    const result = await b.execute({expires_at: new Date(before + 1000).toISOString()});
    assert.equal(result.status, "ambiguous"); assert.equal(b.clicks.start, 0);
  });
}
for (const options of [{title: "Start Video Call?"}, {duplicateStart: true}]) {
  test(`ambiguous or non-audio presence prompt is never accepted: ${JSON.stringify(options)}`, async t => {
    const b = presenceFixture("Away", options); t.after(b.close);
    const result = await b.execute({expires_at: new Date(Date.now() + 250).toISOString()});
    assert.equal(result.status, "ambiguous"); assert.equal(b.clicks.start, 0);
  });
}
test("incoming answer requires authoritative matching caller chat and exact call ID", async t => {
  const b = fixture(`<div mediacallwrapper><button id="answer">Accept call</button></div>`); t.after(b.close);
  const incoming = {call_id: "incoming-1", provider: "zoho_cliq", direction: "incoming", state: "ringing", chat_id: CHAT, chat_url: CHAT_URL};
  let clicks = 0; b.d.querySelector("#answer").onclick = () => { clicks++; b.setCall({...incoming, state: "connected"}); };
  b.setCall({...incoming, chat_id: ""});
  assert.equal((await b.execute({action: "answer", call_id: "incoming-1"})).status, "failed");
  b.setCall(incoming);
  assert.equal((await b.execute({action: "answer", call_id: "different-call"})).status, "failed");
  assert.equal((await b.execute({action: "answer", call_id: "incoming-1"})).status, "succeeded"); assert.equal(clicks, 1);
});
test("hangup acts only on the correlated call", async t => {
  const b = fixture(`<div mediacallwrapper><span mediacallbuttons purpose="endCall" av-tooltip-title="End call"></span></div>`); t.after(b.close);
  b.setCall({call_id: "call-1", provider: "zoho_cliq", state: "connected"});
  let clicks = 0; b.d.querySelector("[mediacallbuttons]").onclick = () => { clicks++; b.setCall(null); };
  assert.equal((await b.execute({action: "hangup", call_id: "other"})).status, "failed");
  assert.equal((await b.execute({action: "hangup", call_id: "call-1"})).status, "succeeded"); assert.equal(clicks, 1);
});
test("desktop-learned incoming participant mapping requires the exact live caller ID", async t => {
  const b = fixture(`<div mediacallwrapper><button>Answer call</button></div>`); t.after(b.close);
  const incoming = {call_id: "incoming-1", provider: "zoho_cliq", state: "ringing", direction: "incoming", participant_id: "111222333", url: CHAT_URL, chat_id: "", chat_url: ""};
  b.setCall(incoming); let clicks = 0;
  b.d.querySelector("button").onclick = () => { clicks++; b.setCall({...incoming, state: "connected"}); };
  assert.equal((await b.execute({action: "answer", call_id: "incoming-1", participant_id: "999999999"})).status, "failed");
  assert.equal((await b.execute({action: "answer", call_id: "incoming-1", participant_id: "111222333"})).status, "succeeded"); assert.equal(clicks, 1);
});
const composer = `<section class="currentchat" purpose="chatview" id="12345"><div composer-main-container><div composer-component-editor contenteditable="true" class="ProseMirror"></div><button aria-label="Send message">Send</button></div></section>`;
test("summary preserves existing drafts without clicking send", async t => {
  const b = fixture(composer); t.after(b.close);
  b.d.querySelector("[contenteditable]").textContent = "My draft";
  let clicks = 0; b.d.querySelector("button").onclick = () => clicks++;
  const result = await b.execute({action: "send_summary", text: "AI summary"});
  assert.equal(result.status, "failed"); assert.match(result.detail, /unsent draft/); assert.equal(clicks, 0);
  assert.equal(b.d.querySelector("[contenteditable]").textContent, "My draft");
});
test("summary uses plain text and verifies a new own-message bubble in exact chat", async t => {
  const b = fixture(composer); t.after(b.close);
  const text = "Voice Loop summary: <script>not HTML</script> & next steps.";
  let clicks = 0;
  b.d.querySelector("button").onclick = () => {
    clicks++; const editor = b.d.querySelector("[contenteditable]");
    assert.equal(editor.querySelector("script"), null);
    const bubble = b.d.createElement("div"); bubble.setAttribute("msg-cont", ""); bubble.setAttribute("chid", CHAT); bubble.setAttribute("mymsg", "true"); bubble.setAttribute("msguid", "new-1");
    const pre = b.d.createElement("pre"); pre.id = "posted-message-container"; pre.setAttribute("postedchatid", CHAT); pre.textContent = editor.textContent; bubble.append(pre); b.d.querySelector("section").append(bubble); editor.textContent = "";
  };
  assert.equal((await b.execute({action: "send_summary", text})).status, "succeeded"); assert.equal(clicks, 1);
});
test("clearing the editor without a new matching message remains ambiguous", async t => {
  const b = fixture(composer); t.after(b.close);
  b.d.querySelector("button").onclick = () => { b.d.querySelector("[contenteditable]").textContent = ""; };
  assert.equal((await b.execute({action: "send_summary", text: "Test summary", expires_at: new Date(Date.now() + 300).toISOString()})).status, "ambiguous");
});

function ownMessage(b, lines) {
  const bubble = b.d.createElement("div");
  bubble.setAttribute("msg-cont", ""); bubble.setAttribute("chid", CHAT); bubble.setAttribute("mymsg", "true"); bubble.setAttribute("msguid", "sent-123");
  const pre = b.d.createElement("pre"); pre.id = "posted-message-container"; pre.setAttribute("postedchatid", CHAT);
  for (const [index, line] of lines.entries()) {
    if (index) pre.append(b.d.createElement("br"));
    pre.append(b.d.createTextNode(line));
  }
  const status = b.d.createElement("div"); status.setAttribute("purpose", "sendingstatus");
  const sent = b.d.createElement("div"); sent.setAttribute("purpose", "msgstatus"); sent.className = "zcf-tickmsg-sent-tick"; sent.title = "Sent"; sent.textContent = "Sent";
  status.append(sent); pre.append(status); bubble.append(pre); b.d.querySelector("section").append(bubble);
  return bubble;
}

test("multiline ProseMirror paragraphs match the summary and its BR-rendered own receipt", async t => {
  const b = fixture(composer); t.after(b.close);
  const editor = b.d.querySelector("[contenteditable]");
  editor.innerHTML = '<p data-text="Message Sample Contact" class="ui-rte-placeholder"><br class="ProseMirror-trailingBreak"></p>';
  const lines = ["Voice Loop · Call summary", "The assistant called Sample Contact. Next step: review <draft> & reply."];
  // A ProseMirror transaction represents newlines as paragraphs, not text nodes.
  editor.addEventListener("input", () => {
    const paragraphs = editor.textContent.split("\n").map(line => { const p = b.d.createElement("p"); p.textContent = line; return p; });
    editor.replaceChildren(...paragraphs);
  });
  let clicks = 0;
  b.d.querySelector("button").onclick = () => {
    clicks++; assert.equal(editor.children.length, 2); assert.equal(editor.querySelector("draft"), null);
    ownMessage(b, lines); editor.replaceChildren();
  };
  const result = await b.execute({action: "send_summary", text: lines.join("\n")});
  assert.equal(result.status, "succeeded"); assert.equal(clicks, 1);
});

test("Chromium innerText is used when a rendered editor has BR paragraph boundaries", async t => {
  const b = fixture(composer); t.after(b.close);
  const editor = b.d.querySelector("[contenteditable]"), lines = ["Call summary", "Follow up tomorrow."];
  editor.addEventListener("input", () => {
    editor.replaceChildren(b.d.createTextNode(lines[0]), b.d.createElement("br"), b.d.createTextNode(lines[1]));
  });
  Object.defineProperty(editor, "innerText", {get() { return this.childNodes.length ? lines.join("\n") : ""; }});
  b.d.querySelector("button").onclick = () => { ownMessage(b, lines); editor.replaceChildren(); };
  assert.equal((await b.execute({action: "send_summary", text: lines.join("\n")})).status, "succeeded");
});

test("summary waits for a new own receipt arriving after the editor cleared", async t => {
  const b = fixture(composer); t.after(b.close);
  const lines = ["Voice Loop · Call summary", "Next step: review tomorrow."];
  let clicks = 0;
  b.d.querySelector("button").onclick = () => {
    clicks++; b.d.querySelector("[contenteditable]").replaceChildren();
    b.w.setTimeout(() => ownMessage(b, lines), 150);
  };
  assert.equal((await b.execute({action: "send_summary", text: lines.join("\n")})).status, "succeeded"); assert.equal(clicks, 1);
});

for (const changed of ["Next step: review tomorrow!", "Next step: cancel tomorrow."]) {
  test(`summary content changes remain rejected: ${changed}`, async t => {
    const b = fixture(composer); t.after(b.close);
    const editor = b.d.querySelector("[contenteditable]");
    editor.addEventListener("input", () => { editor.textContent = changed; });
    let clicks = 0; b.d.querySelector("button").onclick = () => clicks++;
    const result = await b.execute({action: "send_summary", text: "Next step: review tomorrow."});
    assert.equal(result.status, "ambiguous"); assert.equal(clicks, 0);
  });
}
