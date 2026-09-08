/* Shared, dependency-free state rules. DOM access belongs in content.js. */
(function (root) {
  "use strict";
  const CLIQ_HOSTS = new Set(["cliq.zoho.com", "cliq.zoho.eu", "cliq.zoho.in",
    "cliq.zoho.com.au", "cliq.zoho.jp", "cliq.zoho.ca", "cliq.zoho.com.cn", "cliq.zoho.sa"]);
  function providerFor(url) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "https:") return null;
      if (parsed.hostname === "meet.google.com") return "google_meet";
      return CLIQ_HOSTS.has(parsed.hostname) ? "zoho_cliq" : null;
    } catch { return null; }
  }
  function clean(value, limit = 240) {
    return String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, limit);
  }
  function timerSeconds(value) {
    const match = clean(value).match(/^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$/);
    if (!match || +match[2] > 59 || +match[3] > 59) return null;
    return +(match[1] || 0) * 3600 + +match[2] * 60 + +match[3];
  }
  function controlLabel({aria, tooltip, title, avTooltip, text}) {
    return [aria, tooltip, title, avTooltip, String(text || "").length < 90 ? text : ""].map(value => clean(value)).find(Boolean) || "";
  }
  function classify(snapshot) {
    if (snapshot.provider === "google_meet") {
      // Preview microphone/camera access is not participation. A joined meeting
      // has its leave control; a preview has Join now / Ask to join instead.
      if (snapshot.meetingPath && snapshot.hangup && !snapshot.preview && !snapshot.ended) return "connected";
      return null;
    }
    if (snapshot.provider !== "zoho_cliq" || !snapshot.callPanel || snapshot.ended) return null;
    // A connected SFU or remote track alone is not proof the other person answered.
    if (snapshot.incoming) return "ringing";
    if (snapshot.dialing) return "dialing";
    if (snapshot.hangup && (snapshot.elapsed >= 1 || snapshot.explicitConnected)) return "connected";
    return null;
  }
  class CallTracker {
    constructor({uuid = () => crypto.randomUUID(), confirmMs = 700, endGraceMs = 2500} = {}) {
      this.uuid = uuid; this.confirmMs = confirmMs; this.endGraceMs = endGraceMs;
      this.call = null; this.candidateSince = null; this.absentSince = null;
      this.nativeCallKey = null;
    }
    observe(snapshot, now = Date.now()) {
      if (this.call && this.nativeCallKey && snapshot.nativeCallKey && this.nativeCallKey !== snapshot.nativeCallKey) {
        const ended = {...this.call, state: "ended"};
        this.call = null; this.candidateSince = null; this.absentSince = null; this.nativeCallKey = null;
        return ended;
      }
      let state = classify(snapshot);
      if (state === "connected" && this.call?.state !== "connected") {
        this.candidateSince ??= now;
        if (now - this.candidateSince < this.confirmMs) state = null;
      } else if (state !== "connected") this.candidateSince = null;
      if (!state) {
        if (!this.call) return null;
        // Accepting an invitation can hide its answer/ringing controls before
        // the connection finishes. A still-visible, identical call wrapper with
        // an end-call control and a zero timer is a pending handshake, not an
        // absent call. Retain invitation metadata without granting attendance.
        const pendingHandshake = (this.call.state === "ringing" || this.call.state === "dialing")
          && snapshot.callPanel && snapshot.hangup && snapshot.elapsed === 0 && !snapshot.ended
          && this.nativeCallKey && snapshot.nativeCallKey === this.nativeCallKey;
        if (pendingHandshake) { this.absentSince = null; return null; }
        this.absentSince ??= now;
        if (!snapshot.ended && now - this.absentSince < this.endGraceMs) return null;
        const ended = {...this.call, state: "ended"};
        this.call = null; this.absentSince = null; this.nativeCallKey = null;
        return ended;
      }
      this.absentSince = null;
      // A transient reconnect banner cannot turn an attended call back into an
      // invitation. Explicit end or loss of call UI closes the call first.
      if (this.call?.state === "connected" && state !== "connected") return null;
      const direction = state === "ringing" ? "incoming" : state === "dialing" ? "outgoing" : this.call?.direction || "unknown";
      const next = {
        call_id: this.call?.call_id || this.uuid(), provider: snapshot.provider,
        state, direction, contact: {name: clean(snapshot.contact) || this.call?.contact.name || ""},
        title: clean(snapshot.title) || this.call?.title || "",
        // Never include query parameters, fragments, tokens, or chat text.
        url: new URL(snapshot.url).origin + new URL(snapshot.url).pathname,
      };
      const changed = !this.call || JSON.stringify(next) !== JSON.stringify(this.call);
      this.call = next;
      this.nativeCallKey = snapshot.nativeCallKey || this.nativeCallKey;
      return changed ? {...next} : null;
    }
  }
  const api = {providerFor, clean, timerSeconds, controlLabel, classify, CallTracker};
  root.VoiceLoopDetector = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
