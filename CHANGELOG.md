# Changelog

## 0.5.0 (prerelease)

- Add AI Assistant with configurable OpenAI Realtime model, voice, instructions,
  objective, and a bounded call duration. Activate audio only after connection;
  use the virtual meeting return without opening the physical microphone.
- Add immediate and scheduled Cliq calls, allowed incoming-call answering, and
  assistance after joining an allowed Google Meet. Enforce exact chat links,
  paired Chrome profiles, platform permissions, busy status, and working hours.
- Learn incoming participant identity from successful outgoing calls to allowed
  chats. Leave unknown or ambiguous callers unanswered.
- Add durable job history, cancellation, local JSON/HTML transcripts, expired
  schedules, and interrupted-call recovery without automatic redialing.
- Search and paginate complete call and summary histories directly from SQLite,
  including older records beyond the recent 200-job status snapshot.
- Add visible contact management, chat-link and numeric-ID entry, a separate Cliq
  company/region setting, and light searchable contact selectors. Open call
  history in Recordings with a transcript and JSON viewer.
- Configure the assistant's language, including following the caller. MCP call
  and schedule tools accept an optional name for new outgoing-only contacts.
- Fix immediate local-control listener restart on macOS/Linux while retaining
  exclusive listener ownership on Windows.
- Initialize Qt styling once, release closed transcript readers, and isolate
  test windows and assistant storage to prevent repeated-run UI stalls.
- Add Automation for concise summaries sent through the Chrome extension's
  browser controls. Require a per-chat opt-in; support assistant conversations
  and completed browser-tagged recordings after separate transcription consent.
- Bundle a stdio MCP executable with status, call, schedule, job, and cancel
  tools. Keep MCP authorization separate from the extension pairing token.
- Confirm the scoped Cliq Away/Busy audio-call prompt for an authorized outgoing
  call, and stop stale extension timers and observers after a context reload.
- Keep browser hangup processing alive for a bounded normal-quit grace period
  and persist the assistant result before shutdown.
- Show preparation, ringing, and active conversation separately in floating
  controls, reset elapsed time on stop, and prevent conflicting local playback.
- Isolate diagnostic and smoke-test assistant storage and leave their local
  MCP listener off so verification cannot recover or interrupt real user jobs.
- Anonymize diagnostic copies and public fixtures, and require configured contact
  selection at runtime in local live-test helpers instead of embedded private IDs.
- Preserve multiline summary text during composer checks and wait for the matching
  new chat message after sending; uncertain delivery is never automatically retried.
- Preserve the complete objective and session instructions in the Realtime
  opening response. Verify completion and output drain with a separate paid
  synthetic-audio check that does not open audio hardware or make a browser call.
- Add configuration, UI, lifecycle, audio, MCP, and browser-command regression
  coverage. Windows native/frozen checks and a live two-way Cliq audio test pass.
  The recipient ended that call and the summary was sent manually;
  assistant-initiated browser hangup and automatic sending remain unverified live.

## 0.4.1

- Add an opt-in Screen privacy setting to exclude the main window, floating
  controls, and app dialogs from supported Windows capture tools.
- Apply the setting immediately and after native window recreation; report
  failures instead of claiming protection. Turning it off restores capture.
- Add Electron-equivalent legacy macOS exclusion with an explicit ScreenCaptureKit
  limitation. Linux shows the setting as unavailable.
- Verify native on/off state and actual Windows desktop capture before release.

## 0.4.0

- Add a Chrome companion for attended Zoho Cliq incoming/outgoing calls and
  joined Google Meet meetings, with local pairing and no browser audio capture.
- Add opt-in connected-call automatic recording, a recording prompt when it is
  off, and live call status in the floating controls.
- Save call direction, contact details, meeting title, and browser source with
  sessions. Finish recordings owned by an ended call; preserve manual sessions.
- Ship the unpacked extension source and a release ZIP with setup documentation.

## 0.3.2

- Fix unreadable meeting-tool and contact dropdowns under dark system palettes.
- Preserve contact suggestions while selecting and automatically saving names.
- Show a green tray dot when active, red when muted during a session, and grey
  when off, with a corresponding status tooltip.
- Prepare the public repository under **alshell7/voice-loop**, add contributor
  and security guidance, and automate Windows/macOS prereleases on `main`.

## 0.3.1

- Reset floating and main session timers immediately when turning off.
- Offer to stop after 30 seconds of low speaker energy during recording.
- On explicit acceptance, trim trailing silence while preserving activity from
  either channel and a short ending buffer; normal Stop keeps all audio.

## 0.3.0

- Add floating on/off, mute, route-only/record controls, compact view and opacity.
- Add tray controls, microphone/speaker switching, and per-user login startup.
- Add manual meeting-tool tags, saved searchable contacts, library filters and
  pagination, playback, and a transcript viewer.
- Add optional OpenAI transcription/diarization with OS credential storage,
  resumable jobs, JSON and offline HTML output, and opt-in automatic transcription.

## 0.2.0

- Add simple/advanced audio setup and independent VoiceLoop Mic/Speaker paths.
- Add Windows VB-CABLE + Hi-Fi Cable setup and macOS BlackHole setup/packaging.
- Add native Qt controls, stereo local recording, and cross-platform source support.

Versions before the first public GitHub release describe local development milestones.
