/* Isolated world: observe visible call UI and execute narrow worker commands. */
(() => {
  "use strict";
  const D = globalThis.VoiceLoopDetector;
  if (!D) return;
  const provider = D.providerFor(location.href);
  if (!provider || globalThis.__voiceLoopContent) return;
  globalThis.__voiceLoopContent = true;
  const tracker = new D.CallTracker();
  let lastSent = 0;
  let disabled = false;
  let lastPulse = 0;
  let poll = null;
  let observer = null;
  let mutationTimer = null;
  function shutdown() {
    if (disabled) return;
    disabled = true;
    if (poll !== null) clearInterval(poll);
    if (mutationTimer !== null) clearTimeout(mutationTimer);
    observer?.disconnect();
    window.removeEventListener("pagehide", pagehide);
    try { chrome.runtime.onMessage.removeListener?.(onMessage); } catch { /* Context already invalidated. */ }
  }
  function runtimeId() {
    try {
      const id = chrome.runtime.id;
      return typeof id === "string" ? id : "";
    } catch { return ""; }
  }
  const runtimeAvailable = () => !!runtimeId();
  async function sendRuntime(message) {
    if (disabled) return;
    if (!runtimeAvailable()) { shutdown(); return; }
    try {
      // An invalidated Chrome context can throw before returning a Promise.
      // Keep both synchronous throws and asynchronous rejection inside try.
      return await chrome.runtime.sendMessage(message);
    } catch (error) {
      if (!runtimeAvailable() || /context invalidated|extension (?:has been |was )?(?:reloaded|removed|disabled)/i.test(String(error))) shutdown();
      // A temporarily sleeping worker may reject a message; the next pulse
      // retries only connectivity, never a browser command's side effects.
    }
  }
  function visible(element) {
    if (!element || element.hidden || element.getAttribute("aria-hidden") === "true") return false;
    const style = getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
  }
  const all = (scope, selector) => [...scope.querySelectorAll(selector)].filter(visible);
  const firstText = (scope, selector) => all(scope, selector).map(el => D.clean(el.textContent)).find(Boolean) || "";
  const label = el => D.controlLabel({
    aria: el.getAttribute("aria-label"), tooltip: el.getAttribute("data-tooltip"),
    title: el.getAttribute("title"), avTooltip: el.getAttribute("av-tooltip-title"),
    text: el.textContent,
  });
  function snapshot() {
    const controls = all(document, "button, [role='button'], [title], [aria-label], [data-tooltip], [mediacallbuttons]");
    const hangupButton = controls.find(el => el.getAttribute("purpose") === "endCall" || /(?:leave (?:the )?call|end (?:the )?call|hang ?up|disconnect call)/i.test(label(el)));
    if (provider === "google_meet") {
      const preview = controls.some(el => /^(?:join now|ask to join|join meeting)$/i.test(label(el)));
      return {provider, url: location.href, nativeCallKey: location.pathname, meetingPath: /^\/[a-z]{3}-[a-z]{4}-[a-z]{3}\/?$/i.test(location.pathname),
        hangup: !!hangupButton, preview,
        title: firstText(document, "[data-meeting-title]") || D.clean(document.title.replace(/\s*[-–|]\s*Google Meet$/i, "").replace(/^Meet\s*[-–]\s*/i, "")),
        contact: "", ended: controls.some(el => /^rejoin$/i.test(label(el)))};
    }
    // Limit textual reads to call-specific containers. Generic chat panels and
    // the document body are deliberately never used as text fallbacks.
    const panels = all(document, "[mediacallwrapper], #mediacall_container, [data-call-state], [data-testid*='call-window'], [data-testid*='call-popup'], [id*='callwindow' i], [id*='call_window' i], [id*='callcontainer' i], [id*='callpopup' i], [class*='call-window' i], [class*='callwindow' i], [class*='call-popup' i], [class*='callcontainer' i], [class*='call-container' i], [class*='incoming-call' i], [class*='incomingcall' i]");
    const closePanel = hangupButton?.closest("[role='dialog'], [class*='call' i], [id*='call' i]");
    if (!panels.length && visible(closePanel) && closePanel !== document.body) panels.push(closePanel);
    const usable = el => el !== document.body && el !== document.documentElement && el.textContent.length < 8000;
    // Native visible wrappers outrank generic ancestors/status panels. Cliq can
    // retain an older hidden wrapper ahead of the current one during rerenders;
    // document.querySelector on the container would read that stale call ID.
    const nativePanels = all(document, "[mediacallwrapper]").filter(usable);
    const nativePanel = nativePanels.find(el => tracker.nativeCallKey && el.getAttribute("callid") === tracker.nativeCallKey)
      || (nativePanels.length === 1 ? nativePanels[0] : null);
    const panel = nativePanel || (nativePanels.length ? null : panels.find(usable));
    if (!panel) return {provider, url: location.href, callPanel: false};
    const text = all(panel, "[statuscontent], [data-call-status], [class*='call-status' i]").map(el => D.clean(el.innerText)).join(" ");
    const panelControls = all(panel, "button, [role='button'], [title], [aria-label], [data-tooltip], [mediacallbuttons]");
    const panelHangup = panelControls.some(el => el.getAttribute("purpose") === "endCall" || /(?:end (?:the )?call|hang ?up|disconnect call)/i.test(label(el)));
    const incoming = all(panel, ".AV-call-incoming").length > 0 || /incoming (?:audio |video |voice )?call|is calling you/i.test(text)
      || panelControls.some(el => /^(?:accept|answer)(?: (?:audio |video )?call)?$/i.test(label(el)));
    const dialing = (all(panel, ".AV-call-outgoing").length > 0 || /\b(?:calling|ringing|dialing|waiting for (?:a |the )?(?:response|answer))\b/i.test(text)) && !incoming;
    const timerNodes = all(panel, "[class*='timer' i], [class*='duration' i], [id*='timer' i], [data-call-duration], time");
    let elapsed = Math.max(-1, ...timerNodes.map(el => D.timerSeconds(el.textContent) ?? -1));
    // Some Cliq builds render a bare span, so accept a time only inside this call
    // panel, never timestamps in the conversation behind it.
    if (elapsed < 0) elapsed = Math.max(-1, ...all(panel, "span").filter(el => !el.children.length).map(el => D.timerSeconds(el.textContent) ?? -1));
    const contact = firstText(panel, "[other-username], [data-caller-name], [data-contact-name]")
      || firstText(panel, "[class*='callername' i], [class*='caller-name' i], [class*='callee' i], [class*='call-user' i], [class*='username' i]:not([current-username]), [class*='user-name' i]:not([current-username]), [class*='contact-name' i], [class*='participant-name' i]");
    const explicitConnected = /^(?:connected|ongoing|in-progress)$/.test(panel.getAttribute("data-call-state") || "")
      || /\bcall connected\b/i.test(text);
    const wrapper = panel.matches("[mediacallwrapper]") ? panel : all(panel, "[mediacallwrapper]")[0];
    // Caller identity comes from the call wrapper, never whichever chat happens
    // to be open behind an incoming invitation. Unknown identity stays blank.
    const chatId = wrapper?.getAttribute("chatid") || wrapper?.getAttribute("data-chat-id") || "";
    const company = location.pathname.match(/^\/company\/([0-9]+)(?:\/|$)/)?.[1];
    const chat = /^[0-9]{1,64}$/.test(chatId) && company ? {chat_id: chatId, chat_url: `${location.origin}/company/${company}/chats/${chatId}`} : {};
    const direction = incoming ? "incoming" : dialing ? "outgoing" : tracker.call?.direction;
    const participantId = wrapper?.getAttribute(direction === "incoming" ? "callerid" : direction === "outgoing" ? "calleeid" : "data-no-participant") || "";
    if (/^[0-9]{1,64}$/.test(participantId)) chat.participant_id = participantId;
    return {provider, url: location.href, nativeCallKey: wrapper?.getAttribute("callid") || "", callPanel: true, incoming, dialing,
      hangup: panelHangup, elapsed, explicitConnected,
      contact, title: contact ? `Call with ${contact}` : "Zoho Cliq call", ...chat,
      ended: /\b(?:call ended|call declined|call rejected|no answer|call missed|call cancelled|call canceled)\b/i.test(text)};
  }
  async function send(call, endReason = "") {
    if (!call || disabled) return;
    lastSent = Date.now();
    await sendRuntime({type: "call-event", event: {...call,
      version: 1, event_id: (endReason ? endReason + "-" : "") + crypto.randomUUID(), timestamp: new Date().toISOString()}});
  }
  function tick() {
    if (disabled || !document.documentElement) return;
    if (!runtimeAvailable()) { shutdown(); return; }
    const changed = tracker.observe(snapshot());
    if (changed) void send(changed, tracker.lastEndReason || tracker.lastUpdateReason);
    else if (tracker.call && Date.now() - lastSent >= 10000) void send({...tracker.call});
    if (globalThis.VoiceLoopCommands && Date.now() - lastPulse >= 2000) {
      lastPulse = Date.now();
      void sendRuntime({type: "assistant-pulse"});
    }
  }
  let queued = false;
  observer = new MutationObserver(() => {
    if (disabled || queued) return;
    queued = true;
    mutationTimer = setTimeout(() => { mutationTimer = null; queued = false; tick(); }, 250);
  });
  observer.observe(document, {childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "aria-label", "title", "data-call-state"]});
  poll = setInterval(tick, 1000);
  function onMessage(message, sender, respond) {
    const ownId = runtimeId();
    if (disabled || !ownId) { shutdown(); return false; }
    if (!message || typeof message !== "object") return false;
    if (sender?.id !== ownId) return false;
    const reply = value => { try { respond(value); } catch { /* The worker or tab closed. */ } };
    if (message?.type === "snapshot-request") { lastSent = 0; tick(); reply({ok: true}); return false; }
    if (message.type === "assistant-snapshot") {
      const current = snapshot();
      reply({ready: !!globalThis.VoiceLoopCommands && document.readyState !== "loading", active: !!tracker.call || !!current.callPanel || !!current.hangup});
      return false;
    }
    if (message.type === "assistant-command" && globalThis.VoiceLoopCommands) {
      void Promise.resolve().then(() => globalThis.VoiceLoopCommands.execute(message.command, {
        getCall: () => tracker.call, snapshot, tick, isActive: () => !disabled && runtimeAvailable(),
      })).then(reply, () => reply({status: "ambiguous", detail: "The page disconnected during the action. It will not be repeated."}));
      return true;
    }
    return false;
  }
  try { chrome.runtime.onMessage.addListener(onMessage); } catch { shutdown(); return; }
  function pagehide() {
    if (tracker.call) void send({...tracker.call, state: "ended"}, "pagehide");
    shutdown();
  }
  window.addEventListener("pagehide", pagehide);
  tick();
})();
