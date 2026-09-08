/* Isolated world: read only visible call UI; never inspect message history. */
(() => {
  "use strict";
  const D = globalThis.VoiceLoopDetector;
  const provider = D.providerFor(location.href);
  if (!provider || globalThis.__voiceLoopContent) return;
  globalThis.__voiceLoopContent = true;
  const tracker = new D.CallTracker();
  let lastSent = 0;
  let disabled = false;
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
    const panel = panels.find(el => el !== document.body && el !== document.documentElement && el.textContent.length < 8000);
    if (!panel) return {provider, url: location.href, callPanel: false};
    const text = all(panel, "[statuscontent], [data-call-status], [class*='call-status' i]").map(el => D.clean(el.innerText)).join(" ");
    const panelControls = all(panel, "button, [role='button'], [title], [aria-label], [data-tooltip], [mediacallbuttons]");
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
    const wrapper = panel.matches("[mediacallwrapper]") ? panel : panel.querySelector("[mediacallwrapper]");
    return {provider, url: location.href, nativeCallKey: wrapper?.getAttribute("callid") || "", callPanel: true, incoming, dialing,
      hangup: !!hangupButton, elapsed, explicitConnected,
      contact, title: contact ? `Call with ${contact}` : "Zoho Cliq call",
      ended: /\b(?:call ended|call declined|call rejected|no answer|call missed|call cancelled|call canceled)\b/i.test(text)};
  }
  async function send(call) {
    if (!call || disabled) return;
    lastSent = Date.now();
    try {
      await chrome.runtime.sendMessage({type: "call-event", event: {...call,
        version: 1, event_id: crypto.randomUUID(), timestamp: new Date().toISOString()}});
    } catch (error) {
      // Chrome invalidates old scripts on extension reload. Stop cleanly; a page
      // reload attaches the new version without duplicate observation timers.
      if (/context invalidated/i.test(String(error))) { disabled = true; clearInterval(poll); observer.disconnect(); }
    }
  }
  function tick() {
    if (disabled || !document.documentElement) return;
    const changed = tracker.observe(snapshot());
    if (changed) void send(changed);
    else if (tracker.call && Date.now() - lastSent >= 10000) void send({...tracker.call});
  }
  let queued = false;
  const observer = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    setTimeout(() => { queued = false; tick(); }, 250);
  });
  observer.observe(document, {childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "aria-label", "title", "data-call-state"]});
  const poll = setInterval(tick, 1000);
  chrome.runtime.onMessage.addListener(message => {
    if (message.type === "snapshot-request") { lastSent = 0; tick(); }
  });
  window.addEventListener("pagehide", () => { if (tracker.call) void send({...tracker.call, state: "ended"}); });
  tick();
})();
