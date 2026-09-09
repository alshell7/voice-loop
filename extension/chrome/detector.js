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
    const match = clean(value).replace(/\s*:\s*/g, ":").match(/^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$/);
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
      this.lastEndReason = "";
      this.lastUpdateReason = "";
      this.nativeKeyHistory = [];
      this.lastObservation = null;
    }
    observe(snapshot, now = Date.now()) {
      this.lastEndReason = "";
      this.lastUpdateReason = "";
      const previous = this.lastObservation;
      const samePendingRecipient = this.call?.provider === "zoho_cliq" && snapshot.provider === "zoho_cliq"
        && this.call.state === "dialing" && this.call.direction === "outgoing" && !snapshot.incoming
        && /^[0-9]{1,64}$/.test(this.call.participant_id || "") && snapshot.participant_id === this.call.participant_id;
      const continuousCallUI = snapshot.callPanel && snapshot.hangup && !snapshot.ended
        && previous?.callPanel && previous.hangup && !previous.ended;
      const recentNativeIdentity = previous?.nativeCallKey === this.nativeCallKey
        && Number.isFinite(previous?.nativeAt) && now >= previous.nativeAt && now - previous.nativeAt <= 5000;
      // A transient missing attribute is not a missing call. Retain the last
      // native ID only while the exact outgoing participant and continuous call
      // controls remain visible; the original identity timestamp is not renewed.
      const retainedNativeIdentity = !snapshot.nativeCallKey && samePendingRecipient
        && continuousCallUI && recentNativeIdentity && this.absentSince === null;
      this.lastObservation = {at: now, nativeCallKey: snapshot.nativeCallKey || (retainedNativeIdentity ? this.nativeCallKey : ""),
        nativeAt: snapshot.nativeCallKey ? now : retainedNativeIdentity ? previous.nativeAt : null,
        callPanel: snapshot.callPanel, hangup: snapshot.hangup, ended: snapshot.ended};
      let handedOff = false;
      if (this.call && this.nativeCallKey && snapshot.nativeCallKey && this.nativeCallKey !== snapshot.nativeCallKey) {
        // Cliq assigns a provisional call ID, then replaces it with a server
        // ID while the same recipient is still ringing. This is one logical
        // call only when continuous, recent call UI proves that narrow setup
        // handoff. A different recipient, observed gap/end or attended call
        // must still establish a new logical call and new authorization.
        const handoff = samePendingRecipient && continuousCallUI && recentNativeIdentity
          && this.absentSince === null && this.nativeKeyHistory.length < 8
          && !this.nativeKeyHistory.some(entry => entry.key === snapshot.nativeCallKey);
        if (handoff) {
          this.nativeCallKey = snapshot.nativeCallKey;
          this.nativeKeyHistory.push({key: snapshot.nativeCallKey, at: now, reason: "provisional-handoff"});
          this.lastUpdateReason = "native-handoff";
          this.candidateSince = null;
          handedOff = true;
        } else {
          this.lastEndReason = "native-replaced";
          const ended = {...this.call, state: "ended"};
          this.call = null; this.candidateSince = null; this.absentSince = null; this.nativeCallKey = null;
          return ended;
        }
      }
      let state = classify(snapshot);
      // Wait for an actual native identity before granting a pending call's
      // attendance; remembered identity alone cannot activate the assistant.
      if (state === "connected" && this.call && this.call.state !== "connected"
          && this.nativeCallKey && !snapshot.nativeCallKey) state = null;
      if (state === "connected" && this.call?.state !== "connected") {
        this.candidateSince ??= now;
        if (now - this.candidateSince < this.confirmMs) state = null;
      } else if (state !== "connected") this.candidateSince = null;
      if (!state) {
        if (!this.call) return null;
        // Cliq removes invitation text before rendering its connected timer,
        // and can hide the timer during an attended call's rerender. The same
        // native wrapper and its end-call control prove the call still exists,
        // even with a missing timer. Preserve state without granting attendance.
        const sameVisibleCall = snapshot.callPanel && snapshot.hangup && !snapshot.ended
          && this.nativeCallKey && (snapshot.nativeCallKey === this.nativeCallKey || retainedNativeIdentity);
        if (sameVisibleCall) { this.absentSince = null; return handedOff ? {...this.call} : null; }
        this.absentSince ??= now;
        if (!snapshot.ended && now - this.absentSince < this.endGraceMs) return null;
        this.lastEndReason = snapshot.ended ? "ui-ended" : "ui-absent";
        const ended = {...this.call, state: "ended"};
        this.call = null; this.absentSince = null; this.nativeCallKey = null;
        return ended;
      }
      this.absentSince = null;
      // A transient reconnect banner cannot turn an attended call back into an
      // invitation. Explicit end or loss of call UI closes the call first.
      if (this.call?.state === "connected" && state !== "connected") return null;
      const direction = state === "ringing" ? "incoming" : state === "dialing" ? "outgoing" : this.call?.direction || "unknown";
      if (!this.call) this.nativeKeyHistory = [];
      if (snapshot.nativeCallKey && !this.nativeKeyHistory.some(entry => entry.key === snapshot.nativeCallKey)) {
        this.nativeKeyHistory.push({key: snapshot.nativeCallKey, at: now, reason: "observed"});
      }
      const next = {
        call_id: this.call?.call_id || this.uuid(), provider: snapshot.provider,
        state, direction, contact: {name: clean(snapshot.contact) || this.call?.contact.name || ""},
        title: clean(snapshot.title) || this.call?.title || "",
        // Never include query parameters, fragments, tokens, or chat text.
        url: new URL(snapshot.url).origin + new URL(snapshot.url).pathname,
      };
      if (snapshot.chat_id && snapshot.chat_url || this.call?.chat_id) {
        next.chat_id = snapshot.chat_id || this.call.chat_id;
        next.chat_url = snapshot.chat_url || this.call.chat_url;
      }
      if (snapshot.participant_id || this.call?.participant_id) next.participant_id = snapshot.participant_id || this.call.participant_id;
      const changed = !this.call || JSON.stringify(next) !== JSON.stringify(this.call);
      this.call = next;
      this.nativeCallKey = snapshot.nativeCallKey || this.nativeCallKey;
      return changed || handedOff ? {...next} : null;
    }
  }
  const api = {providerFor, clean, timerSeconds, controlLabel, classify, CallTracker};
  root.VoiceLoopDetector = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
