# Verification record

Local host: Windows 11 x64, Python 3.13.14, SoundCard 0.4.6, NumPy 2.5.3,
PySide6 Essentials 6.11.2, keyring 25.7.0. Updated for Voice Loop 0.3.2.

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
- **PyInstaller:** Windows native bundle built locally. Linux/macOS build jobs
  are configured, but have not run on this local Windows host.
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
