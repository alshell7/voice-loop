# Voice Loop Chrome companion

By **alshell7**. MIT licensed as part of [Voice Loop](https://github.com/alshell7/voice-loop).

This Manifest V3 extension sends Zoho Cliq call state and Google Meet meeting
state to the Voice Loop desktop app on this computer. It does not record browser
audio, join calls, answer calls, or read chat messages. Recording uses the desktop
app's selected audio devices and its recording preference.

## Install and pair

1. Install and open Voice Loop 0.4.0 or newer. In **Preferences → Browser calls**,
   enable browser call detection and copy the pairing code.
2. Download the Chrome extension ZIP from the matching GitHub release and extract
   it, or use this `extension/chrome` source folder directly.
3. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**,
   and select the directory containing `manifest.json`.
4. Open **Voice Loop** from Chrome's Extensions menu. Paste the pairing code and
   choose **Connect to Voice Loop**. The panel confirms the desktop connection.
5. Reload any already-open Cliq or Meet tabs once. New tabs work immediately.
   Pin the extension if you want easy access to its connection status.

Chrome manages unpacked extension installation; the desktop installer does not
silently add browser extensions. Keep the extracted directory in a permanent
location. When updating, replace its files, click **Reload** on the extension's
Chrome management card, and reload Cliq and Meet tabs.

## Behavior

- Cliq incoming ringing and outgoing dialing update Voice Loop's floating status.
  Neither starts recording. A visible call timer advancing past zero, or an
  explicit connected call state, together with a visible end-call control,
  establishes attendance. Ringing/dialing status takes precedence over timers.
- An attended call keeps the direction established by its invitation. The visible
  other participant's name is sent as contact metadata. When attached during an
  existing call, direction may be unknown; no identity is guessed.
- Meet starts detection after the joined-meeting **Leave call** control appears.
  Camera/microphone preview and waiting-to-join screens do not trigger it. The
  meeting title comes from a meeting-title element or the tab title; an unnamed
  meeting uses its meeting code. No attendee list is collected.
- Call end, navigation away, and tab close send an ended event. Short UI rerenders
  are tolerated. Active calls send ten-second heartbeats. Browser suspension or
  closure is also handled by the desktop app's heartbeat timeout.
- Voice Loop decides whether to ask or record automatically. Review its recording
  preference before enabling automatic recording. Use the desktop controls to
  route audio only or stop an active session.

English call controls are the initial supported detection language. Cliq's
attribute-based selectors cover its observed current web interface, while
fallbacks use English labels. Site redesigns can require detector updates. Cliq
native desktop calls, Teams, Zoom, arbitrary websites, and browser private mode
are not covered by this release. Cliq data centers supported: `.com`, `.eu`, `.in`,
`.com.au`, `.jp`, `.ca`, `.com.cn`, and `.sa`.

## Local protocol and privacy

The only network destination is `http://127.0.0.1:49321`. The desktop app must be
running with browser detection enabled. Authentication uses a random bearer
pairing token copied from the desktop app. The token is stored in Chrome local
extension storage, restricted to trusted extension contexts; it is not sent into
the meeting page or synchronized to a Google account. Chrome profile files are
not an encrypted credential vault. Disconnect removes the token.

- `GET /v1/health`: authenticated identity and connectivity check.
- `POST /v1/events`: JSON with `version`, `event_id`, `call_id`, `provider`,
  `state`, `direction`, `contact.name`, `title`, `url`, and UTC `timestamp`.
- URLs omit query parameters and fragments. Call metadata is transient in Chrome
  session storage. No transcript, audio, email address, or chat body is sent.
- The service worker validates sender origin, top-level frame, event schema,
  length, and freshness before forwarding. Its short retry queue keeps only the
  newest state per call and discards events after 30 seconds. It never replays an
  ended offline call as a new attended call.
- All page observation runs in an isolated content script. The extension does
  not hook WebRTC, request media access, or inject into the page's JavaScript
  world. Pairing tokens remain outside the page. Refresh messages address only
  this extension's content scripts; no tab title or browsing-history permission
  is requested.

## Develop and test

The shipped extension has no build step, JavaScript framework, or runtime
dependency. Tests use jsdom as a development-only HTML/DOM implementation. With
Node 24.15 or newer (within Node 24), run from the repository root:

```sh
npm ci --ignore-scripts --prefix extension/chrome
node --test extension/chrome/tests/*.test.mjs
```

`detector.js` owns pure state rules, `content.js` maps visible DOM controls to those
rules, `protocol.mjs` validates events and bounds retries, and `background.js`
owns the loopback connection. Fixture names and IDs are synthetic. Tests cover
ringing versus attendance, missed calls, preview versus joined meetings, stable
metadata, successive calls, re-render grace, safe URLs, malformed messages, queue
expiry, service-worker restart, tab close, pairing and disconnect. `content-dom`
tests execute the shipped `content.js` against parsed, sanitized HTML fixtures;
CSS selectors are real, while only jsdom's missing geometry and `innerText` APIs
are supplied. Observed outgoing Cliq/Meet structure is distinguished from
representative incoming/answered fixtures. These tests do not establish live
attendance or rendered browser visibility. The repository's browser-integration
guide records live-test evidence and limitations.

For manual acceptance, check outgoing unanswered, outgoing answered, incoming
declined, incoming answered, Meet preview, Meet joined, end/close, desktop offline
and reconnect, and extension reload. Verify the desktop floating status and actual
recording boundary, not only the extension badge. Browser throttling can delay
heartbeats, and future site markup changes should fail closed instead of inferring
attendance from camera or microphone activity.
