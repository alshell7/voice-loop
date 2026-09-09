# Verification record

Local host: Windows 11 x64, Python 3.13.14, SoundCard 0.4.6, NumPy 2.5.3,
PySide6 Essentials 6.11.2, keyring 25.7.0. The current development build is 0.5.1;
earlier released checks are labeled below. Live assistant-call verification
remains separate from automated and packaging results.

## 0.5.1 name scheduling and busy fallback

- Full Python suite: **546 passed in 79.68 seconds**. Extension suite:
  **127 Node tests passed**. Native source UI and MCP startup checks pass.
- Tests cover unique/ambiguous names, unchanged ID-based requests, relative
  delays and DST, strict saved-name resolution, and actionable MCP errors.
- Busy fallback tests cover exact owned prompt detection, alternate body markup,
  negated statuses, confirmed cancellation, updated-extension capability,
  policy revocation, exact objective/recipient delivery, duplicate results, and
  uncertain sends without retries. Busy messages do not require summary opt-in.
- No real call or message was sent for these changes. Busy detection currently
  recognizes explicit English Cliq audio-call confirmation prompts; arbitrary
  post-dial error dialogs, localized variants, and unanswered calls are not
  treated as evidence that a recipient is busy.

## AI Assistant and Automation implementation checks

- The 0.5.0 full Python run passed **489 tests in 69.26 seconds**.
  Realtime-focused checks also passed after the opening-response correction.
  Ruff lint and formatting checks, and actionlint workflow checks, pass. The
  browser extension suite passes **99 Node tests**, including multiline draft
  verification and message receipt checks using controlled fixtures.
- Configuration and UI coverage includes exact supported chat
  URLs, regional hosts, forged IDs, malformed policy files failing closed,
  time zones, weekday boundaries, overnight shifts, daylight saving changes,
  objective validation, aware schedules, per-chat flags, profile selection,
  missing prerequisites, cancellation controls, and escaped transcript rendering.
- Coordinator coverage includes prepare/ready/connected
  audio gates, duplicate callbacks and immediate requests, wrong chat/profile
  events, policy revocation during preparation, existing manual audio, missing
  credentials, missed/cancelled schedules, incoming calls that connect or end
  while preparing, late events after cancellation, restart uncertainty, browser
  disconnection, and overlapping calls.
- Summary coordinator checks confirm the original chat/profile, call-end
  gating, no duplicate sends, opt-out before delivery, and failure when call end
  remains unconfirmed. Test doubles replace browser commands, audio devices,
  credentials, and OpenAI responses; no real recipient is called by these tests.
- Twenty focused history tests cover SQLite pagination beyond 200 jobs, stable
  ordering, summary-only filtering, searches of older records, Unicode casefold,
  literal SQL/wildcard characters, bounded page sizes, and invalid inputs.
- Company/contact regressions cover migration, new ID/link resolution,
  outgoing-only defaults, policy checks before persistence, wrong-company
  rejection, future availability, and passing the selected language to Realtime.
  UI checks cover contact editing after a workspace change, exact selection,
  readable search popups, pagination, and opening the latest job in Recordings.
- Source Qt render checks inspected Call, Settings, Contacts, History, and
  Automation using synthetic contacts. The quick-call page remains compact
  independently of the longer settings tab. Editable dropdowns reuse the
  explicitly styled completion popup. Floating controls distinguish preparation,
  dialing/ringing, and active audio, reset the timer on stop, and restore the
  ordinary mute help afterward. Playback cannot start or resume during an AI call.
- Source audio and browser integration checks pass using generated audio,
  authenticated loopback events, and real spawned audio workers. They do not
  open a real microphone or call a real contact.
- Native and frozen **Windows 0.5.0** checks pass for MCP startup/runtime and
  discovery of all five tools, the desktop `check-ui` diagnostic, and
  `check-capture`. The local Codex MCP registration uses the source Python
  command `-m voiceloop.assistant_mcp`, with no OpenAI API key in MCP configuration.
- Diagnostics and UI/browser smoke tools use temporary assistant databases and
  leave assistant control off when exercising tray integration. An isolation
  regression preserves an existing simulated active-call database and control
  token unchanged. The isolated source diagnostic reports no audio, network, or
  startup changes, and no assistant control listener started.
  Every test that constructs the desktop App also supplies temporary assistant
  storage and contacts, so a test cannot recover real in-progress jobs.
  Test teardown deletes retained windows, and application styling initializes
  once. The combined 75-test UI/browser/capture sequence passes without the
  earlier repeated-styling stall.
- Additional coverage includes normal-quit hangup grace and transcript
  persistence, the per-chat summary path for completed ordinary browser call
  recordings after transcription, cancellation and scoped confirmation of
  Cliq's Away/Busy audio-call prompt, and cleanup of invalidated extension
  contexts after reload.

### Live Windows Cliq call

A later authorized outbound test with the **0.5.0 development build on Windows
and Chrome** connected and exchanged audio in both directions. Cliq selected
**VoiceLoop Mic** through VB-CABLE and **VoiceLoop Speaker** through Hi-Fi Cable.
The extension confirmed the scoped Away prompt, dialed, and preserved the call
when Cliq replaced its provisional invitation ID with the connected native ID.
The local diagnostic recorded this handoff instead of treating it as call end.

The call produced eight transcript turns: three from the participant and five
from the assistant. Audio diagnostics reported the following mono-frame counts
at 24 kHz; no private utterances or recipient details are included here:

| Diagnostic | Frames |
| --- | ---: |
| Captured meeting input | 501,600 |
| Input marked voiced by the diagnostic | 72,960 |
| Uploaded meeting input | 420,960 |
| Generated assistant audio | 825,600 |
| Assistant audio acknowledged as played | 401,280 |

Generated and played counts differ; generated audio alone is not evidence that
the recipient heard it. The participant requested a stop and ended the call at
approximately 32 seconds. Voice Loop observed browser call end and recorded a
`cancelled` worker result. **Assistant-initiated browser hangup, including the
configured time-limit path, was not verified by this call.** Local
`transcript.json` and `transcript.html` exports were created.

### Live summary and separate Realtime completion check

Automation generated a summary and inserted a valid multiline draft into the
correct chat. The extension's newline comparison reported an ambiguous result.
The user then **manually pressed Send**, and the chat displayed a sent message.
**Automatic Send remains unverified in a live call.** No automated resend was
attempted. The multiline-draft correction is covered separately by browser
fixture tests; it does not turn this manual-send observation into an automatic
delivery result.

A separate, explicitly authorized paid OpenAI Realtime check used generated
test data and a fake audio sink, with **no audio hardware or browser call**. It
completed in 10.88 seconds and generated 150,000 PCM frames at 24 kHz, or 6.25
seconds of audio. It conveyed the supplied test objective, identified itself as
AI, and included a thank-you and goodbye. The model invoked
`finish_call`, the worker returned `completed`, and output drain was verified.
This check followed a correction that preserves the full objective and session
instructions in the opening response. It verifies Realtime completion behavior,
not Cliq's hangup control or message delivery.

Real incoming-call answering, assistant-initiated Cliq hangup, and automatic
summary sending still need their own authorized live verification. A successful
API check, fixture, or queued command is not a substitute. Keep keys, private
transcripts, and recipient identifiers out of public verification reports.

Local diagnostic copies under `artifacts/` were anonymized without changing
functional AppData settings or original recordings. A scan of current tracked
files and artifact text found no remaining known private recipient/company/chat
identifiers; diagnostic JSON remained valid after redaction. This does not make
future captures safe to share automatically: inspect new logs and screenshots
before including them in a report. The retained smoke-test WAVs contain generated
speech rather than a recipient's recorded call.

The following assistant suites run without calling OpenAI or a real contact:

```sh
python -m pytest tests/test_assistant_config.py tests/test_assistant_ui.py tests/test_assistant.py
python -m pytest tests/test_assistant_audio.py tests/test_realtime.py
python -m pytest tests/test_assistant_control.py tests/test_assistant_mcp.py
python -m pytest tests/test_assistant_store.py
node --test extension/chrome/tests/*.test.mjs
```

Real incoming-call identity mapping, macOS/Linux assistant audio, and
account-specific browser control still need their own device/browser
verification. See
[AI Assistant setup and limits](AI_ASSISTANT.md). Earlier recording checks below
do not establish an end-to-end AI conversation.

## Capture protection checks (0.4.1)

- **183 Python tests** pass (the full 182-test suite plus the added pre-show
  regression); the eight capture tests cover toggling, persisted settings,
  window ownership, new windows, recreated handles, unavailable platforms, and
  native failure/recovery. Ruff and workflow syntax checks pass.
- Source and frozen Windows apps passed `check-capture --pixels`. Native affinity
  reads confirmed exclusion on the main window, floating controls, app dialog,
  contact suggestions, and mode dropdown. Hide/show and compact resizing kept
  protection. Disabling restored normal affinity.
- Actual desktop screenshot pixels showed the synthetic background for **100%**
  of each sampled region with protection on, versus **0%** with protection off
  and after disabling it. Both the main and translucent floating window passed.
- A separate native Windows Graphics Capture check showed both synthetic app
  windows before enabling protection and the windows behind them after enabling
  it. The protected Voice Loop content was absent.
- Checks used temporary synthetic UI, no audio, no network and no personal
  settings changes. They do not establish that every screenshot/recording tool
  honors exclusion. macOS modern ScreenCaptureKit capture is explicitly not
  blocked; frozen native legacy-flag checks run in release CI. Linux is unsupported.

Reproduce with the commands in [CAPTURE_PROTECTION.md](CAPTURE_PROTECTION.md).

## Browser companion checks (0.4.0)

- **175 Python tests** and **39 Node tests** pass locally. Ruff lint/format,
  workflow syntax checks, the Windows installer build, and the frozen native Qt
  smoke check also pass for 0.4.0.
- Authenticated HTTP bridge tests cover local-only binding, pairing persistence,
  Host/Origin validation, malformed/stale events, request/queue bounds, concurrent
  clients, shutdown, and requests racing with disable/re-enable.
- Lifecycle and Qt tests cover unanswered incoming/outgoing calls, explicit
  consent, automatic recording, ended/timeout handling, manual-session ownership,
  manual-stop suppression, delayed event queues, successive calls, device-switch
  races, and automatic recording during a nested manual-consent event loop.
- **39 Node tests** include worker restart/offline delivery, safe URL metadata,
  tab close, pairing, and actual `content.js` execution against sanitized HTML.
  Outgoing Cliq ringing and joined Meet fixtures derive from observed live DOM;
  incoming/answered fixtures are representative and are labeled accordingly.
  Slow connection setup preserves invitation identity and incoming direction
  while a visible zero timer still prevents recording.
- `scripts/smoke_browser.py` passes real authenticated HTTP events through the
  Qt app and real spawned audio workers using generated 220/660 Hz tones. It
  verifies no ringing capture, accepted prompts, automatic recording, call-end
  saving, stereo channel frequencies, manifest metadata, and worker cleanup.
  It opens no microphones, changes no personal settings, and uploads nothing.
- Native Windows screenshots confirm browser preferences, masked pairing,
  connected status in normal/compact floating controls, and the recording popup.
- The extension was loaded into the user's Chrome and its real pairing popup
  successfully connected to the desktop loopback listener. Its unpaired/paired
  appearance was inspected.
- **Live Google Meet checks passed** on 2026-09-08: the preview did not prompt or
  record, joining opened the recording prompt, accepting started recording, and
  leaving saved and closed the session. A second join with automatic recording
  enabled started without a prompt and stopped on leaving. Both stereo files
  match their manifest frame counts (1,238,343 and 614,445 frames) and contain
  the meeting code, URL, unique call ID, and correct recording trigger. The off
  timer reset to zero. Automatic recording was restored to off afterward.
  These were solo meetings; they verify detection and recording boundaries,
  not remote-participant audio quality. No transcription or upload was performed.
- **Live outgoing Cliq check passed** on 2026-09-08: ringing displayed the other
  contact in the floating controls without starting capture. After the recipient
  answered, a visible elapsed timer and the recording popup established the
  connected transition. Accepting produced a stereo recording with the correct
  contact, outgoing direction, and prompt trigger. Ending the call automatically
  saved it; the WAV and manifest both contain 733,702 frames. Incoming live
  acceptance remains pending; incoming fixtures are representative.

The earlier verification below records prior release checks. Consult GitHub
Actions for the native/macOS result of the current commit.

## Automated checks

- **98 passing tests:** stereo channel separation, timeline gaps/wraparound,
  late/overflow frame handling, PCM clipping/nonfinite values, segmented WAV order,
  header readability before close, atomic settings, interrupted recording metadata,
  route validation, Linux setup/idempotence/rollback, transcription timing/channel
  labels, upload consent, manifest path containment, automatic two-cable routing,
  incomplete setup, Windows manufacturer suffixes, swapped recording channels,
  invalid-channel zero-file behavior, and verified downloads. v0.3 coverage adds
  mute on both the recording and virtual mic feed, typed preferences, saved
  contacts, library search/filter/pagination, tag persistence, secure audio paths,
  cloud multipart parameters and redacted errors, escaped JSON-to-HTML rendering,
  resume without reuploading completed chunks, per-user startup files, floating
  recording mode, tray mode synchronization, active device switching, single
  instance, and playback pause/seeking/WAV part boundaries.
- **v0.3.1 regressions:** timer reset on Turn off and after completion, 30-second
  speaker-energy threshold, fragmented analysis windows, prompt acceptance,
  decline/snooze, route-only exclusion, and automatic dismissal when audio resumes.
  Trimming tests cover microphone activity after the speaker goes quiet, swapped
  channels, ending padding, partial final activity, multi-file trim boundaries,
  entirely quiet recordings, and injected replacement failure preserving audio.
- **v0.3.2 regressions:** tray icons change through off, active, muted, then off
  while mute remains selected. Native dark-palette smoke checks tool/contact
  completion with keyboard selection, ordinary mode dropdowns, and tray icons at
  16/32 pixels on light/dark backgrounds. Contact autosave no longer resets the
  completion model while choosing a suggestion. Four screenshots were inspected
  at Windows 175% DPI, using synthetic contact names and no opened audio.
  The source and packaged v0.3.2 desktop diagnostics also passed completion-popup
  rendering and all three tray-icon state changes. The updated application was
  reopened with audio off after verification.
- **Synthetic process integration:** real engine and writer with spawned tone
  sources. Frequency analysis verifies separate 220 Hz / 660 Hz channels. Covers
  duration, routing-only zero-file behavior, startup failure, cancelled startup,
  restart, and no leaked processes. No hardware is opened by this check.
  The real worker integration also records generated tones followed by silence,
  accepts a trim stop, verifies retained microphone audio and WAV/manifest frame
  agreement, and confirms ordinary Stop does not trim. The 30-second prompt is
  tested with synthesized timeline frames without waiting in real time.
- **Native Qt tests and smoke:** real window and widgets, consent acceptance/cancellation,
  mode switching, disabled route controls while active, missing-device behavior,
  empty library, Simple/Advanced fields, paired channels, tooltips, and
  desktop/compact rendering at Windows 175% DPI. v0.3 screenshots cover floating
  off, recording/muted, collapsed controls, the library at 1060×900 and 820×640,
  Preferences, and the native transcript reader. An explicit native size check
  caught a Windows stale minimum-height issue that offscreen Qt did not show;
  deferred resizing now produces a compact panel. Keyboard playback seeking is
  tested separately from programmatic timer updates.
- **Ruff:** source lint and formatting checks.
- **GitHub CI:** all six Windows/macOS/Linux × Python 3.11/3.13 combinations
  passed on the initial public push, including Swift helper compilation and
  synthetic audio integration. Native installer jobs run separately; consult
  [GitHub Actions](https://github.com/alshell7/voice-loop/actions) for current results.
- **PyInstaller:** Windows native bundle built locally. The first hosted macOS
  Apple Silicon app build passed; its installer job exposed an HTTP 406 from
  the driver download server. Downloads now identify Voice Loop in an explicit
  compatible User-Agent and retain checksum/signature checks. Linux has source
  testing but no automated installer release.
- **Packaged native backend:** the standalone Windows executable successfully
  exported the real device list including VoiceLoop Mic and VoiceLoop Speaker.
- **Packaged Qt startup:** `scripts/smoke_packaged.ps1` launched and rendered the
  frozen app on the native Windows Qt platform, then closed it without opening
  audio. This caught and resolved an unrelated ICU DLL being collected from the
  build shell's PATH. Windows bundles now use OS ICU and Qt's matching VC runtime.
- **Windows installer:** NSIS packages the complete original VB-CABLE package
  and verified vendor download flow for Hi-Fi Cable. The previous v0.2 Program
  Files installation check was attempted, but Windows reported that its
  administrator prompt was canceled. App/Start menu installation remains
  unverified; the standalone bundle and audio setup helper are checked separately.
  The v0.3.0 Windows installer and SHA-256 sidecar were built successfully.
  The v0.3.1 update and SHA-256 sidecar were also built; its normal launch opened
  responsive floating controls with audio off.

## OpenAI and v0.3 desktop checks

- **Live OpenAI request passed** on 2026-09-08 using
  `gpt-4o-transcribe-diarize`: 13 segments and two speaker labels from offline
  synthesized speech with two voices. Only generated test speech was uploaded;
  no live meeting or microphone audio was used. Both JSON and standalone HTML
  were produced. This verifies the API integration, not diarization accuracy in
  real meetings. The supplied credential was entered through hidden input and
  was not embedded in code, configuration, reports, or the installer.
- **Windows credential storage** passed a write/read/delete round trip under a
  unique temporary account with a dummy value. The user's test key was not saved.
- **Native desktop diagnostic** renders the main/floating windows, asserts compact
  height and route-only defaults, creates the real system tray menu, exercises
  its mute action, loads the platform credential backend, and starts a real
  spawned transcription job using exact silence. Silence skips all API calls
  while testing JSON/HTML output. It opens no audio, changes no startup settings,
  and makes no network requests. Run it against source and the frozen executable.
  Both source and the v0.3.0 Windows executable passed, reporting the native tray
  available, `WinVaultKeyring` loaded, and the transcription worker complete.
  The v0.3.1 source and frozen executable additionally passed the silence prompt,
  Keep recording, and immediate timer-reset checks. Native prompt rendering was
  inspected at Windows 175% DPI. No API request or microphone input was needed.
- **Normal Windows launch** opened the v0.3.0 floating controls and registered
  the current executable with `--background` in the user's Windows Run key.
  The process remained responsive with no audio worker children. Startup currently
  targets the workspace's `dist/VoiceLoop/VoiceLoop.exe`; launching an installed
  copy updates the login path. An actual logout/login cycle was not exercised.
- Playback tests use actual WAV readers with an injected output device. They
  verify exact sample order across parts, pause, and session-relative seeking.
  Actual physical-speaker playback and manual tray selection in a live meeting
  still require user acceptance testing.

## Hardware check performed

The default Jabra EVOLVE 20 MS microphone and its WASAPI speaker loopback were
opened together for three seconds through the real worker processes in monitor-only
mode. The engine started, received data, stopped, and released workers cleanly.
No audio was saved. The device list also included the Realtek speaker and Stereo Mix.

The Windows audio setup installed official Hi-Fi Cable 1.0.0.7 alongside the
existing VB-CABLE Pack45. Endpoint descriptions were set through the Windows
audio policy service, PnP names through Configuration Manager; no registry ACLs
or signed driver files were changed. Both Hi-Fi endpoints were set to 48 kHz.
Repeated setup resolved existing drivers without reinstalling them.

`scripts/smoke_virtual.py` opened both actual virtual cable paths concurrently:
220 Hz through the mic cable and 660 Hz through the speaker cable. Both returned
nonzero audio (RMS approximately 0.066); measured isolation was 71 dB and 61 dB.
It used generated tones, no physical microphone and no saved audio. This verifies
independent native driver paths, not meeting-app processing or long-session drift.

This establishes native capture compatibility on that setup. It does not establish
recording quality, intelligibility, echo behavior, or operation through a meeting app.
The mono-microphone path requests two shared-mode channels to avoid SoundCard's
documented Windows single-channel capture issue.

## Still requires actual device testing

| Path | Verification needed |
| --- | --- |
| Windows real meeting | Verify mic delivery and stereo meeting playback in Zoom/Teams/Meet; native cables themselves passed tone tests |
| macOS BlackHole | Microphone permissions, 2ch/16ch routing, physical playback, packaging/signing |
| Linux PulseAudio | Native module creation, mic remap, monitor capture, physical playback |
| Linux PipeWire | Same matrix through pipewire-pulse |
| Extended sessions | Multi-hour device clock drift, disk pressure, system sleep, Bluetooth profile changes |
| Local Whisper | Install optional model runtime and evaluate real transcription quality |

Core tests use deterministic inputs and mocked server responses. macOS/Linux
support is implemented through the cross-platform backend, but those hardware
paths are not certified by tests performed on Windows.

## Reproduce

```sh
python -m pytest
python -m ruff check .
python scripts/smoke_audio.py
python scripts/smoke_ui.py
python scripts/smoke_v03_ui.py
python scripts/smoke_dropdown_tray.py
python scripts/smoke_virtual.py  # Windows; requires completed audio setup
python -m voiceloop devices
python -m voiceloop check-ui --output artifacts/desktop-check.json
# Windows, after packaging:
powershell -NoProfile -File scripts/smoke_packaged.ps1
```

For an explicitly requested live microphone/loopback check with no saved recording:

```sh
python scripts/smoke_hardware.py --monitor --seconds 3
```

Screenshot generation uses Qt's own window capture; no Pillow or desktop capture
is needed: `python scripts/smoke_ui.py --screenshots .impeccable/review`.

To repeat the optional paid API check with generated speech on Windows:

```powershell
powershell -NoProfile -File scripts/make_test_speech.ps1
python scripts/smoke_openai.py --speech artifacts/openai-smoke/synthetic-conversation.wav --output artifacts/openai-smoke
```

The API key prompt uses hidden terminal input. Do not put real keys in source,
command-line arguments, fixture files, or committed reports.

The independent v0.2 UI review identified one attribution-link accessibility fix;
the link now has explicit readable blue coloring and keyboard interaction. The
follow-up review passed all six recaptures and the scored fixes. A documenter
refreshed the design record for Qt. The specialized reviewer/documenter roles
were unavailable, so fresh general agents performed those bounded roles.
macOS/Linux rendering and active meeting screenshots are not part of the
Windows visual checks.

The fresh v0.3 reviewer requested keyboard playback seeking. The fix was scored
resolved with all seven recaptures valid; the ship verdict covers that scored
fix. A fresh general documenter updated the retained native design record.
Specialized reviewer/documenter roles were unavailable, so general agents
performed those required roles.
