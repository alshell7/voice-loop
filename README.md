# Voice Loop

**Local audio routing and stereo recording for meeting tools, without a meeting bot.**

Created and maintained by **[alshell7](https://github.com/alshell7)** · [Download installers](https://github.com/alshell7/voice-loop/releases) · [Report an issue](https://github.com/alshell7/voice-loop/issues)

Voice Loop is an open-source Python desktop app for Windows, macOS, and Linux.
Choose your microphone and speaker, then decide whether to save each session.
No Voice Loop account or telemetry. Optional browser detection uses an authenticated
connection on your own computer. Audio stays local unless you
choose OpenAI transcription or explicitly enable automatic transcription.

## Install and use

Packaged apps include Python and the native Qt interface. The Windows installer
installs the app and offers virtual audio setup in the same wizard. macOS builds
produce one `.pkg` containing Voice Loop and both BlackHole drivers. OS driver
approval and a restart may be required. Builds are currently unsigned; public
release signing/notarization is not configured.

1. Install Voice Loop. Leave **Virtual audio devices** selected on Windows.
2. Open **Audio setup** if device setup needs finishing after a restart.
3. In **Session → Simple**, select your physical microphone and speaker. That's it.
4. Open **Floating controls**, choose **Route only** or **Record too**, then **Turn on**.
5. In your meeting app select **VoiceLoop Mic** and **VoiceLoop Speaker**.
6. Keep Voice Loop running through the meeting. **Turn off** closes the session.

### Everyday controls

The floating panel stays above other windows. Choose the recording mode before
turning on; the dropdown remains visible during the session. **Route only** saves
no files. **Record too** saves a new stereo recording. Turn off before changing
mode. The last choice is remembered, and audio always starts off at login.
Both session timers reset as soon as you turn off; saved recordings retain their
own duration in the library.

- **Mute / Unmute** silences the microphone feed and local microphone recording.
  In Direct capture, mute the meeting app too: it uses the physical mic directly.
- Tag the meeting tool and search or add a **contact** before turning on. New
  contact names save on this device. The optional Chrome extension fills these
  details for Zoho Cliq and Google Meet. Tags can be edited later in the session viewer.
- Collapse meeting details for compact controls; minimize to the system tray.
  Drag the header to move the panel. Set opacity (65–100%) in **Preferences**.
- Voice Loop runs at login by default. Disable **Launch at login** in Preferences.
  Closing its window leaves routing running in the tray. Tray **Quit Voice Loop**
  finishes the session and exits; **Force quit** ends a stuck app and may leave
  the current recording marked unfinished.
- The notification-area icon has a **green dot** while active, **red** while
  active with the mic muted, and **grey** when off. Its tooltip also states the
  current mode. An idle app stays grey even if mute is selected for the next session.
- The tray menu switches microphones and speakers. Switching during a live
  session finishes that session and starts another with the same recording mode.
- **Recordings** shows the current folder, searchable tool/contact tags, date and
  status filters, and eight sessions per page. Select a session to play, view its
  transcript, or transcribe. Playback uses your physical speaker and requires
  the live session to be off. Transcript timestamps seek into the recording.

The main Session screen retains **Start session** with its explicit recording
choice dialog. Startup registration is per user (Windows Run entry, macOS
LaunchAgent, or Linux XDG autostart). Launching the app alone does not start audio;
opt-in browser automation can start recording when a connected call is detected.

### Connected-call recording in Chrome

The companion extension is in [`extension/chrome`](extension/chrome). It detects
Zoho Cliq incoming/outgoing calls and Google Meet meetings without joining as a
bot. Ringing and dialing update the floating panel; recording is offered only
after a Cliq call is answered or a Meet meeting is joined.

Enable browser detection in **Preferences**, load the unpacked extension in Chrome,
and pair it using the local pairing token. Keep **Record connected calls
automatically** off to receive a recording popup, or enable it for automatic
recording. Call details are saved with the session. Ending the detected call
finishes recordings started by that call; existing manual sessions remain yours
to control. Teams and other providers are not supported yet.

See [browser setup, permissions, and troubleshooting](docs/BROWSER_EXTENSION.md).
The extension sends call state and meeting/contact metadata locally; it never
captures browser audio or uploads recordings. Browser automation and automatic
OpenAI transcription are separate preferences.

Simple automatically uses the named virtual bridge when both paths are ready.
Without virtual devices, Windows/Linux can use direct capture of your chosen
speaker. The meeting-app instructions update to match the selected routing.

**Advanced** exposes Direct capture / Virtual bridge, meeting audio source,
virtual microphone feed, and **Left channel / Right channel**. Assign Microphone
and Meeting audio to either recording channel; the other channel follows so each
source stays separate. Simple always uses microphone left, meeting right.
Hover or focus the information buttons for explanations.

**Direct capture** records your physical microphone and the selected speaker's
system audio without changing meeting routing. It includes all apps playing on
that speaker. **Virtual bridge** forwards your mic to the meeting and meeting
audio to your chosen speaker through two independent virtual paths.

```text
Physical mic → Voice Loop → VoiceLoop Mic → meeting app
Meeting app  → VoiceLoop Speaker → Voice Loop → physical speaker
                    └── optional local stereo recording ──┘
```

Meeting playback preserves its first two stereo channels. Recordings are dual
mono: microphone and downmixed meeting audio remain separate for later processing.
Headphones help prevent echo; the app does not implement acoustic echo cancellation.

### Windows

Setup uses the original **VB-CABLE Pack45** for the microphone and the free
**VB-Audio Hi-Fi Cable & ASIO Bridge 1.0.0.7** for the speaker. The supplied local
VB-CABLE package can be passed to `scripts/build_windows.py --cable-package PATH`.
Hi-Fi Cable downloads directly from VB-Audio during setup. Downloaded archives
have pinned SHA-256 checksums and vendor executables must pass Authenticode checks.

The user-editable endpoint names are **VoiceLoop Mic** and **VoiceLoop Speaker**.
Windows WASAPI lists commonly append `(VB-Audio Virtual Cable)` or
`(VB-Audio Hi-Fi Cable)`. The app recognizes those native names. Internal feed
endpoints are called VoiceLoop Mic Feed and VoiceLoop Speaker Capture.
Hi-Fi Cable's two sides are configured to the same 48 kHz format.

Setup preserves existing default-device selections, does not alter signed driver
files, and skips installing drivers already registered. Audio setup can repair
names after a restart. Diagnostics are in `%PROGRAMDATA%\VoiceLoop\setup.log`.
This installer targets Windows x64; Hi-Fi Cable is not a Windows ARM64 driver.

VB-CABLE and Hi-Fi Cable are **donationware by [VB-Audio Software](https://vb-audio.com/Cable/)**;
contributions are welcome. [Vendor licensing terms](https://vb-audio.com/Services/licensing.htm)
apply, including professional/organizational use. VB-Audio software is not MIT
licensed. Hi-Fi Cable is fetched from its vendor, not redistributed in this repo.
Uninstalling Voice Loop preserves recordings and shared drivers.

### macOS

The macOS installer includes unmodified **BlackHole 2ch and 16ch 0.7.1**.
Voice Loop creates public, persistent Core Audio aggregate devices named
**VoiceLoop Mic** (2ch) and **VoiceLoop Speaker** (16ch). These are independent
paths. Only the first two channels are used. On first launch after restarting,
the app finishes creating the named devices without changing system defaults.

The in-app Audio setup also installs BlackHole directly using verified vendor
packages if needed; Homebrew is not required. Grant microphone permission when
macOS asks. Source builds need Xcode command-line tools to compile the small
Core Audio helper; packaged users do not need developer tools.

The macOS implementation and native installer build are provided, but macOS
installation/routing have **not been executed on this Windows development host**.

### Linux

Use PulseAudio or PipeWire with `pipewire-pulse` and `pactl`. Click **Set up audio
devices**, or run `python -m voiceloop setup-linux`. It creates **VoiceLoop Mic**,
**VoiceLoop Speaker**, and an internal microphone feed in the current user audio
session. Recreate them after reboot/audio-server restart. No root is required.
Failed setup unloads only modules created by that attempt.

## Run from source

Requires Python 3.11+. Linux needs `libpulse0`, Qt platform runtime libraries,
and an active graphical/audio session. On Ubuntu install `libgl1 libegl1
libxkbcommon0 libxcb-cursor0 libpulse0` (plus `pulseaudio-utils` for setup).

```sh
git clone https://github.com/alshell7/voice-loop.git
cd voice-loop
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate
python -m pip install -e .
# macOS only, compile the native alias helper once:
python scripts/build_macos.py --helper-only
python -m voiceloop
```

## Recording behavior

During **Record too**, 30 seconds of low speaker-channel energy opens a
**Stop and trim / Keep recording** prompt. Nothing stops until you choose.
Keep recording leaves the WAV files untouched and snoozes reminders for another
30 seconds. Speaker activity resuming dismisses the prompt. Route-only sessions
never show it.

Stop and trim finishes routing and recording, then removes trailing low-energy
audio from both channels. Activity on either channel is retained, so speaking
into your microphone while the remote side is quiet is preserved. A 250 ms
ending buffer is kept after the last detected activity. Trimming spans WAV parts
and updates their lengths, session duration, and trim metadata before automatic
transcription starts. A wholly quiet recording becomes an empty WAV. Ordinary
Turn off saves the full recording without trimming.

This initial detector uses 20 ms RMS windows at **−45 dBFS**, with no external
model or network call. Music/noise above that threshold counts as activity;
very quiet speech below it may count as silence. Silero VAD is not included yet.

- Session start is **manual**. Floating and tray controls start in the selected recording mode; the main Session screen asks at each start. Login startup only opens the app in the tray, with audio off. No device-use or call-detection trigger starts recording.
- Routing/monitoring without recording creates no session directory and writes no audio.
- Audio is 48 kHz, PCM16 stereo. It uses about **691 MB per hour**, split every 30 minutes to stay well below WAV's size limit.
- Each session directory contains `session.json` and `audio-001.wav`, `audio-002.wav`, etc. Metadata describes consent, devices, channel labels, part offsets, duration, completion/error state, and timing diagnostics.
- Headers are updated as audio is written and data is flushed every two seconds. After a crash, WAVs are generally readable through their last flushed header; `status: recording` is displayed as unfinished on next launch. Sudden power loss may lose the last buffered samples. There is no claim of zero-loss recovery or encryption at rest.
- Both channels use one monotonic timeline. Missing input becomes silence instead of shortening one channel. A 250 ms write buffer absorbs normal scheduling jitter. Late/overflow frames are counted. Native device timestamp information is not exposed by SoundCard, so alignment is best effort, not sample-accurate synchronization across independent clocks.
- Capture and playback run in separate processes with bounded queues. Startup, stalled input, disconnected devices, queue saturation, and disk errors stop the session visibly. A hung native worker is terminated after a bounded shutdown grace period. No hidden restart starts recording again.
- Closing the main window keeps the app in the tray when available. **Turn off** or tray **Quit Voice Loop** stops routing and finishes recording. When Voice Loop stops, apps using its virtual endpoints lose the routed signal; select physical devices to bypass it.

Default folders:

| OS | Local data |
| --- | --- |
| Windows | `%LOCALAPPDATA%\VoiceLoop` |
| macOS | `~/Library/Application Support/VoiceLoop` |
| Linux | `$XDG_DATA_HOME/voiceloop` or `~/.local/share/voiceloop` |

Recordings live under `recordings/`. The floating panel and Recordings page show
the current folder; change it on Recordings. Settings and saved contacts remain
in the local data folder. Settings contain device IDs and paths, never credentials.

## Transcription and diarization

### OpenAI

1. Open **Preferences**, enter your OpenAI API key, and click **Save key**.
   Credentials use Windows Credential Manager, macOS Keychain, or Linux Secret
   Service. There is no plaintext fallback. `OPENAI_API_KEY` can override the
   stored key for a launch.
2. Choose a model. **gpt-4o-transcribe-diarize** provides timestamps and speaker
   labels. Other choices are **gpt-transcribe**, **gpt-4o-transcribe**,
   **gpt-4o-mini-transcribe**, and **whisper-1**. Models without segment timestamps
   display approximate chunk times.
3. Select a finished recording and choose **Transcribe**. Confirm the audio
   upload to your OpenAI account; API charges apply. Optionally enable
   **Automatically transcribe recorded sessions** in Preferences. It is off by
   default and applies to future recorded sessions.

Transcription runs in a separate process with progress and cancellation. Audio
is sent in bounded two-minute mono chunks, one channel at a time. The microphone
is labeled **You**. The diarization model distinguishes voices within each
meeting-audio chunk; speaker letters reset across chunks and do not identify
contacts. Chunk boundaries can split speech. Failed or canceled jobs resume
completed chunks on retry when the model and audio are unchanged.

Every successful transcription writes **transcript.json** and a standalone
**transcript.html** beside the WAV files. The session dialog renders the JSON
with speaker labels, timestamps, and playback. **Open HTML** opens the local HTML
in your browser; keep it beside the audio for playback. All transcript text is
escaped. It loads no external scripts, fonts, or services.

Model behavior follows the [OpenAI speech-to-text documentation](https://developers.openai.com/api/docs/guides/speech-to-text).

### Local and custom providers

Recording is independent of transcription. The `Transcriber` protocol in
`src/voiceloop/transcription.py` accepts a WAV and yields timestamped segments.
Cloud adapters must declare `uploads_audio = True`; the processor refuses them
without `allow_upload=True`. A Groq adapter can be added through this interface;
one is not included yet.

An optional **local faster-whisper** adapter is included:

```sh
python -m pip install -e ".[whisper]"
python -m voiceloop transcribe "/path/to/session" --model base
```

Model names download model files on first use; use a local model path for offline operation. Audio remains local. The processor reads bounded two-minute chunks, processes each channel independently, and writes `transcript.json` with session-relative timestamps. Chunk boundaries may split a word; overlapping/chunk-merging and richer diarization are future enhancements.

Local Whisper uses **You** and **Meeting** channel labels, not per-person
diarization. Custom diarization adapters can populate `Segment.speaker`.

## Develop, test, and package

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m voiceloop devices
python scripts/build_windows.py   # Windows .exe installer
python scripts/build_macos.py     # macOS .pkg installer (on macOS)
# Linux portable app:
python -m PyInstaller packaging/VoiceLoop.spec --noconfirm
```

`devices` only enumerates devices; it does not record. `scripts/smoke_audio.py` runs synthetic end-to-end session tests without opening hardware. `scripts/smoke_ui.py` exercises the native Qt controls without recording audio. CI runs core and headless Qt tests on Windows, macOS, and Linux.

Every push to `main`, including a merged pull request, starts the release workflow.
After tests and packaging checks pass, it publishes a GitHub prerelease containing
Windows x64 and macOS Apple Silicon/Intel installers with SHA-256 checksums.
Tags use `v0.3.2-build.<run number>`; the application version remains `0.3.2`.
These automated builds are unsigned and macOS builds are not notarized.
See [the release guide](docs/RELEASING.md) for versioning, manual builds, and
release troubleshooting, and [CHANGELOG.md](CHANGELOG.md) for changes.

See [docs/TESTING.md](docs/TESTING.md) for the verification record and hardware matrix. Windows is the locally exercised host. macOS/Linux audio routing must still be checked on their real audio servers/hardware; passing portable tests is not hardware certification.

### Structure

```text
src/voiceloop/
  ui.py              Native desktop controls and consent
  ui_extras.py       Floating panel, preferences, library, transcript viewer
  desktop.py         Tray controls and single-instance guard
  startup.py         Per-user login startup
  devices.py         Device discovery and route validation
  engine.py          Worker supervision, routing, session lifecycle
  activity.py        Streaming energy activity and silence boundaries
  audio.py           Bounded stereo timeline and PCM conversion
  recording.py       Segmented WAV writer and atomic manifest
  virtual.py         Linux virtual endpoints
  installation.py    Verified downloads and native setup dispatch
  resources/         Windows audio helper, macOS Core Audio helper, icons
  transcription.py   Provider protocol and optional local Whisper
  openai_stt.py      OpenAI transcription and diarization adapter
  credentials.py     OS credential store, no plaintext fallback
  jobs.py            Cancelable transcription worker
  playback.py        Native playback, pause, and seeking
  library.py         Contacts, session index, filters, and pagination
  transcript_html.py Escaped offline HTML export
  config.py          Atomic local settings
```

The runtime dependencies are PySide6 Essentials (native Qt widgets), NumPy,
SoundCard/CFFI, and keyring for OS credentials. OpenAI requests use Python's
standard HTTPS library. Multiple small audio processes trade some memory for
driver isolation; no Electron/browser runtime or background server is involved.

## Contributing

Small, focused changes are welcome. Keep audio routing, storage, UI, and provider integrations separate. Add tests for timeline, lifecycle, and data-integrity changes. Document the OS/device/server used for hardware testing and never commit recordings, tokens, model weights, or drivers. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE), copyright © 2026 alshell7 and Voice Loop contributors.
External drivers and optional model packages retain their own licenses; see
[THIRD_PARTY.md](THIRD_PARTY.md). Report vulnerabilities privately using
[SECURITY.md](SECURITY.md).
