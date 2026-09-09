/* Narrow DOM actions, executed only by this extension's authenticated worker.
 * No page-script bridge, arbitrary selectors, provider API, or chat-history scan.
 */
(function (root) {
  "use strict";
  const D = root.VoiceLoopDetector;
  function visible(element) {
    if (!element?.isConnected || element.hidden || element.getAttribute("aria-hidden") === "true") return false;
    const style = getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
  }
  const all = (scope, selector) => [...scope.querySelectorAll(selector)].filter(visible);
  const label = element => D.controlLabel({aria: element.getAttribute("aria-label"), tooltip: element.getAttribute("data-tooltip"), title: element.getAttribute("title"), avTooltip: element.getAttribute("av-tooltip-title"), text: element.textContent});
  const controls = scope => all(scope, "button, [role='button'], [role='menuitem'], [title], [aria-label], [data-tooltip], [mediacallbuttons]");
  const one = elements => elements.length === 1 ? elements[0] : null;
  const outcome = (status, detail, call_id = "") => ({status, detail, call_id});
  function checkDeadline(command) {
    if (Date.parse(command.expires_at) <= Date.now()) throw new Error("The browser command expired before the action.");
  }
  function targetMatches(command) {
    try {
      const current = new URL(location.href), target = new URL(command.chat_url);
      return current.origin === target.origin && current.pathname.replace(/\/$/, "") === target.pathname.replace(/\/$/, "")
        && D.providerFor(target.href) === "zoho_cliq" && !target.search && !target.hash
        && new RegExp(`^/company/[0-9]+/chats/${command.chat_id}/?$`).test(target.pathname)
        && /^[0-9]{1,64}$/.test(command.chat_id);
    } catch { return false; }
  }
  async function waitFor(command, inspect, milliseconds = 5000) {
    const end = Math.min(Date.parse(command.expires_at), Date.now() + milliseconds);
    do {
      const value = inspect(); if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 100));
    } while (Date.now() < end);
    return null;
  }
  function callPanel() {
    return one(all(document, "[mediacallwrapper]")) || one(all(document, "#mediacall_container"));
  }
  const presencePrompts = () => all(document, "#callConfirmation");
  function audioPresenceStart() {
    const prompt = one(presencePrompts());
    if (!prompt?.matches("[type='popup'].call-confirmation-dialog")) return null;
    const title = one(all(prompt, ".mheader_ttl"));
    if (!title || !/^start audio call\??$/i.test(D.clean(title.textContent))) return null;
    return one(all(prompt, "button").filter(button => !button.disabled && /^start$/i.test(label(button))));
  }
  function exactCall(command, getCall) {
    const call = getCall();
    if (!call || call.call_id !== command.call_id || call.provider !== command.provider || call.state === "ended") return null;
    if (command.provider === "zoho_cliq" && command.action === "answer") {
      const exactChat = call.chat_id === command.chat_id && call.chat_url === command.chat_url;
      const exactParticipant = /^[0-9]{1,64}$/.test(command.participant_id || "") && call.participant_id === command.participant_id
        && new URL(call.url).origin === new URL(command.chat_url).origin;
      if ((!exactChat && !exactParticipant) || call.direction !== "incoming" || call.state !== "ringing") return null;
    }
    return call;
  }
  function currentChatScope(command) {
    if (!targetMatches(command)) return null;
    // Prefer the chat's own typed container. Fall back only when the exact URL
    // is already selected and a single visible composer exists on the page.
    return one(all(document, `.currentchat[purpose='chatview'][id='${command.chat_id}']`))
      || one(all(document, `[data-chat-id='${command.chat_id}'], [chatid='${command.chat_id}'], #chat_${command.chat_id}`)) || document;
  }
  function composerFor(scope) {
    return one(all(scope, "[composer-component-editor][contenteditable='true'], [contenteditable='true'][role='textbox'], [contenteditable='true'][data-placeholder], [contenteditable='true'].zcedit, [contenteditable='true'].msg-input, textarea[placeholder*='message' i], textarea[aria-label*='message' i]"));
  }
  const receiptDecoration = "[purpose='sendingstatus'], [purpose='msgstatus'], script, style";
  function renderedText(element) {
    if (!element) return "";
    if (element.nodeType === 3) return element.textContent || "";
    if (element.nodeType !== 1 || element.matches(receiptDecoration)) return "";
    if (element.tagName === "BR") return "\n";
    // Chromium's rendered text preserves ProseMirror paragraphs and BRs;
    // textContent concatenates them and can reject a correctly inserted draft.
    // Receipt decorations are UI, so exclude them from the message itself.
    const text = typeof element.innerText === "string" && !element.querySelector(receiptDecoration)
      ? element.innerText : [...element.childNodes].map(renderedText).join("");
    return /^(?:P|DIV|LI|UL|OL|PRE|BLOCKQUOTE|H[1-6])$/.test(element.tagName) ? `\n${text}\n` : text;
  }
  function composerText(element) { return ("value" in element ? element.value : renderedText(element)) || ""; }
  const sameText = (actual, expected) => actual.replace(/\s+/gu, " ").trim() === expected.replace(/\s+/gu, " ").trim();
  function setText(element, text) {
    element.focus();
    if ("value" in element) {
      const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value");
      descriptor?.set ? descriptor.set.call(element, text) : element.value = text;
    } else {
      if (typeof document.execCommand === "function" && document.execCommand("insertText", false, text)) return;
      // Plain text only. InputEvent lets editor state observe the DOM update;
      // HTML from objectives/transcripts is never interpreted as markup.
      element.textContent = text;
      const range = document.createRange(); range.selectNodeContents(element); range.collapse(false);
      const selection = root.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    }
    element.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: text}));
  }
  async function execute(command, {getCall, snapshot, tick, isActive = () => true}) {
    let acted = false;
    const checkExpiry = command => {
      checkDeadline(command);
      if (!isActive()) throw new Error("The extension connection ended before the action.");
    };
    try {
      if (!command || !["call", "answer", "hangup", "send_summary"].includes(command.action) || !Number.isFinite(Date.parse(command.expires_at))) return outcome("failed", "Unsupported command.");
      checkExpiry(command);
      if (command.action === "call") {
        if (!targetMatches(command)) return outcome("failed", "The exact configured chat is not open.");
        if (getCall() || snapshot().callPanel || snapshot().hangup) return outcome("failed", "A call is already active in this tab.");
        if (presencePrompts().length) return outcome("failed", "An earlier call confirmation is still open. Close it before starting another call.");
        const callButton = await waitFor(command, () => one(all(document, `#onetoonecall_call_${command.chat_id}`)));
        if (!callButton) return outcome("failed", "The chat's audio call control was not found.");
        if (!targetMatches(command) || presencePrompts().length) return outcome("failed", "The chat or pending call confirmation changed before dialing.");
        checkExpiry(command); callButton.click();
        const audio = await waitFor(command, () => {
          const scoped = one(all(document, `.zcl-menu-wrap[type='menuOption'] #audio_call_${command.chat_id}[chid='${command.chat_id}'][purpose='options']`));
          return scoped || one(controls(document).filter(element => /^audio call$/i.test(label(element))));
        });
        if (!audio) return outcome("failed", "The audio call menu was not available.");
        if (!targetMatches(command)) return outcome("failed", "The selected chat changed before dialing.");
        if (presencePrompts().length) return outcome("failed", "Another call confirmation appeared before this command could dial.");
        checkExpiry(command); acted = true; audio.click();
        // Cliq confirms Away/Busy/Offline/DND presence through the same audio
        // dialog. Only the prompt appearing after our own Audio Call action can
        // be accepted; its presence label does not change the user's intent.
        let confirmedPresence = false;
        const started = await waitFor(command, () => {
          checkExpiry(command);
          if (!targetMatches(command)) throw new Error("The selected chat changed while waiting for call confirmation.");
          tick();
          if (getCall()?.direction === "outgoing" || snapshot().dialing) return true;
          const start = audioPresenceStart();
          if (start && !confirmedPresence) { checkExpiry(command); confirmedPresence = true; start.click(); }
          return false;
        });
        return started ? outcome("succeeded", "Outbound audio call started.", getCall()?.call_id || "") : outcome("ambiguous", "Cliq did not confirm dialing. The command will not be repeated.");
      }
      if (command.action === "answer" || command.action === "hangup") {
        const call = exactCall(command, getCall);
        if (!call) return outcome("failed", "The requested call is no longer the active call.");
        const scope = command.provider === "zoho_cliq" ? callPanel() : document;
        if (!scope) return outcome("failed", "The call controls are unavailable.");
        const pattern = command.action === "answer" ? /^(?:accept|answer)(?: (?:audio |voice )?call)?$/i : /^(?:leave (?:the )?call|end (?:the )?call|hang ?up|disconnect call)$/i;
        const button = one(controls(scope).filter(el => pattern.test(label(el)) || command.action === "hangup" && el.getAttribute("purpose") === "endCall"));
        if (!button) return outcome("failed", "The exact call control could not be identified.");
        checkExpiry(command); acted = true; button.click();
        const confirmed = await waitFor(command, () => {
          tick(); const current = getCall();
          return command.action === "answer" ? current?.call_id === call.call_id && current.state === "connected" : !current || current.call_id !== call.call_id || current.state === "ended";
        }, 10000);
        return outcome(confirmed ? "succeeded" : "ambiguous", confirmed ? command.action === "answer" ? "Incoming call answered." : "Call ended." : "The call control was clicked but Cliq has not confirmed the transition.", call.call_id);
      }
      if (!targetMatches(command) || typeof command.text !== "string" || !command.text.trim() || command.text.length > 4000) return outcome("failed", "The summary target or text is invalid.");
      const scope = currentChatScope(command), composer = scope && composerFor(scope);
      if (!composer) return outcome("failed", "The chat message composer could not be identified.");
      if (composerText(composer).trim() || composer.querySelector?.("img, [data-attachment], .attachment")) return outcome("failed", "This chat has an unsent draft. The summary was not inserted.");
      const messageSelector = `[msg-cont][chid='${command.chat_id}'][mymsg='true'], [data-message-text], .message-content, .msg-content, .message-text`;
      const before = new Set(all(scope, messageSelector));
      checkExpiry(command); setText(composer, command.text); acted = true;
      await new Promise(resolve => setTimeout(resolve, 80));
      if (!sameText(composerText(composer), command.text) || !targetMatches(command)) return outcome("ambiguous", "The editor did not accept the exact summary; review the draft.");
      const send = one(controls(scope).filter(el => /^(?:send|send message)$/i.test(label(el))));
      checkExpiry(command);
      if (send) send.click();
      else {
        composer.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true}));
        composer.dispatchEvent(new KeyboardEvent("keyup", {key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true}));
      }
      // A cleared editor is not a delivery receipt. Look only for this exact
      // newly-authored text in a message content element, never return history.
      // Cliq may clear the composer before appending the delivered bubble.
      const sent = await waitFor(command, () => {
        checkExpiry(command);
        if (!targetMatches(command) || composerText(composer).trim()) return false;
        return all(scope, messageSelector).some(el => {
          if (before.has(el)) return false;
          const message = el.matches("[msg-cont]") ? el.querySelector(`[postedchatid='${command.chat_id}'][id='posted-message-container']`) : el;
          return message && sameText(renderedText(message), command.text);
        });
      });
      return outcome(sent ? "succeeded" : "ambiguous", sent ? "Summary appeared in the configured chat." : "The send outcome could not be confirmed. The summary will not be sent again automatically.");
    } catch (error) { return outcome(acted ? "ambiguous" : "failed", String(error.message || "Browser action failed.").slice(0, 512)); }
  }
  root.VoiceLoopCommands = {execute, targetMatches};
})(globalThis);
