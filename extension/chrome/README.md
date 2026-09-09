# Voice Loop Chrome companion

By **alshell7**. MIT licensed as part of [Voice Loop](https://github.com/alshell7/voice-loop).

This Manifest V3 extension sends Zoho Cliq call state and Google Meet meeting
state to the Voice Loop desktop app on this computer. The desktop's optional
**AI Assistant** can also request an outgoing Cliq audio call, answer a permitted
incoming call, end its own call, and send an optional summary into the configured
chat. Actions use the visible browser interface. The extension does not capture
audio; the desktop owns audio routing, Realtime access, policies, and recording.

## Install and pair

1. Install and open the matching Voice Loop release. In **Preferences → Browser calls**,
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

When testing source changes, refresh both in that order: **Reload the extension**,
then **reload the call page**. Chrome can retain registered content-script code
when only the page is refreshed. An **Extension context invalidated** entry from
an old page may remain in Chrome's Errors list after the update; check whether
a fresh error appears after both reloads before diagnosing its highlighted line.

The AI Assistant update adds narrow host access for Cliq and Meet so it can find
the exact configured tab or open its configured chat link in this Chrome profile.
Chrome may ask you to approve that access after updating. Pair each profile
separately and choose the intended profile in the desktop app; commands never
fan out across profiles. The extension panel shows its stable profile identifier.

## Behavior

- Cliq incoming ringing and outgoing dialing update Voice Loop's floating status.
  Neither starts recording. A visible call timer advancing past zero, or an
  explicit connected call state, together with a visible end-call control,
  establishes attendance. Ringing/dialing status takes precedence over timers.
- An attended call keeps the direction established by its invitation. The visible
  other participant's name is sent as contact metadata. When attached during an
  existing call, direction may be unknown; no identity is guessed.
  Cliq's provisional-to-server call ID change during continuous outgoing setup
  preserves the logical call only when the same numeric participant ID is still
  present. Recipient changes, attendance, explicit endings, and observed gaps
  require a new call identity. Diagnostic event-ID prefixes distinguish that
  handoff from UI endings and browser-tab lifecycle events.
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
- AI call commands are disabled unless enabled by desktop policy. An outbound
  call requires an exact numeric chat ID and matching Cliq chat URL. Existing
  calls are protected, and multiple tabs for the same target are treated as
  ambiguous. The extension never automatically retries dialing after an
  uncertain result or worker restart.
  When that outbound action opens Cliq's **Start Audio Call?** presence prompt,
  its **Start** button is confirmed automatically for Away, Busy, Offline, or
  other presence states. A prompt left over from an earlier action is not
  accepted; changing chats, an expired command, or a disconnected extension
  prevents further confirmation.
- Incoming AI answering requires a specific live call ID and authoritative
  caller identity. The call wrapper may provide the chat ID directly; otherwise
  the desktop can use the participant ID learned from an earlier, explicitly
  targeted outbound call. A contact's display name or the chat behind an
  incoming invitation is never sufficient to authorize answering.
- Automation inserts summaries as plain text only into the exact target chat.
  An existing draft prevents insertion. A newly-created own-message bubble must
  match the summary before the extension reports success. An uncertain send is
  reported for review and is never automatically repeated.

English call controls are the initial supported detection language. Cliq's
attribute-based selectors cover its observed current web interface, while
fallbacks use English labels. Site redesigns can require detector updates. Cliq
native desktop calls, Teams, Zoom, arbitrary websites, and browser private mode
are not covered by this release. Cliq data centers supported: `.com`, `.eu`, `.in`,
`.com.au`, `.jp`, `.ca`, `.com.cn`, and `.sa`.

## Local protocol and privacy

The extension's own HTTP requests go only to `http://127.0.0.1:49321`; browser
actions use Cliq's existing web interface. No Cliq API or Deluge integration is
used. The desktop app must be
running with browser detection enabled. Authentication uses a random bearer
pairing token copied from the desktop app. The token is stored in Chrome local
extension storage, restricted to trusted extension contexts; it is not sent into
the meeting page or synchronized to a Google account. Chrome profile files are
not an encrypted credential vault. Disconnect removes the token.

- `GET /v1/health`: authenticated identity and connectivity check.
- `POST /v1/events`: JSON with `version`, `event_id`, `call_id`, `provider`,
  `state`, `direction`, `contact.name`, `title`, `url`, and UTC `timestamp`;
  optional `profile_id`, `chat_id`, `chat_url`, `participant_id`, and `command_id`
  establish call identity and command correlation.
- `POST /v1/commands/poll`: register this profile's capabilities and lease one
  expiring, profile-bound command. Active pages poll every two seconds; Chrome's
  thirty-second alarm provides a fallback when no supported page is active.
- `POST /v1/commands/result`: acknowledge a command outcome. A small durable
  journal records claimed IDs and outcomes before side effects, preventing
  duplicate calls and messages after a worker restart. Summary bodies and API
  keys are not stored in that journal.
- URLs omit query parameters and fragments. Call metadata is transient in Chrome
  session storage. No audio, API key, or chat history is sent to the desktop.
  An enabled summary command carries only the text to be sent to that chat.
- The service worker validates sender origin, top-level frame, event schema,
  length, and freshness before forwarding. Its short retry queue keeps only the
  newest state per call and discards events after 30 seconds. It never replays an
  ended offline call as a new attended call.
- All page observation runs in an isolated content script. The extension does
  not hook WebRTC, request media access, or inject into the page's JavaScript
  world. Pairing tokens remain outside the page. Refresh messages address only
  this extension's content scripts; no broad browsing-history permission
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
rules, `commands.js` executes narrow call/message actions, `protocol.mjs` validates
events and commands, and `background.js` owns the loopback connection and durable
command journal. Fixture names and IDs are synthetic. Tests cover
ringing versus attendance, missed calls, preview versus joined meetings, stable
metadata, successive calls, re-render grace, safe URLs, malformed messages, queue
expiry, service-worker restart, tab close, pairing, disconnect, profile isolation,
single execution, draft preservation and exact summary verification. `content-dom`
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
