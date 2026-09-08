# Voice Loop

<!-- impeccable:product-schema 1 -->

## Platform
Cross-platform desktop: Windows, macOS, Linux (confirmed by the user). Version
0.3 is implemented with native Qt widgets. Windows is the locally rendered and
tested platform; macOS and Linux rendering and end-to-end audio setup require
validation on their respective systems. Automatic Windows driver setup supports
x64.

## Stack
Delegated by the user: choose simple, lightweight, robust technologies. Python
3.11+, PySide6 Essentials, NumPy, SoundCard, and keyring for operating-system
credentials. Qt replaces the initial Tkinter interface. No Voice Loop account,
web server, browser runtime, or database is required. OpenAI transcription is
optional and uses the user's API account; HTML transcripts open in a browser.

## Users and purpose
A personal, open-source foundation for building meeting notetakers without a
meeting bot. Select physical microphones and speakers, route through virtual
devices, and optionally save local stereo audio for later transcription and
diarization.

## Capabilities and constraints
Simple setup exposes only physical Microphone and Speaker selectors. It chooses
the virtual bridge automatically when both named paths are complete; otherwise
it uses the selected speaker's system-audio loopback when available. Advanced
exposes Direct capture or Virtual bridge, meeting input, the virtual microphone
feed in bridge mode, and paired left/right recording roles. Changing a channel
assignment swaps the other channel so microphone and meeting audio stay separate;
these assignments do not change what either participant hears.

The meeting-facing device names are exactly **VoiceLoop Mic** and **VoiceLoop
Speaker**. Windows device lists may append a VB-Audio manufacturer suffix.
VoiceLoop Mic Feed is the internal playback path, not the microphone selected in
the meeting app. A bridge session must remain active while the meeting uses its
virtual devices. Direct capture also includes other apps playing through the
selected physical speaker.

Audio setup offers one action to install or repair the required virtual devices.
Windows uses VB-CABLE and VB-Audio Hi-Fi Cable; macOS uses BlackHole 2ch and 16ch
with named device aliases; Linux creates endpoints in the current PulseAudio or
PipeWire session. Windows and macOS setup may require operating-system approval
and a restart. Voice Loop configures existing audio drivers rather than shipping
its own kernel driver. Setup does not capture audio.

Audio starts manually. The floating panel offers a visible Route only / Record
too dropdown before Turn on; its last choice is remembered and is locked while
audio is active. Route only creates no recording files. Turn off finishes the
session. The main Session screen retains its explicit Record session, Route audio
only (bridge) or Monitor only (direct), and Cancel dialog before devices open.
Cancel has initial focus. Audio without saving remains a first-class choice.
Local stereo PCM WAV recordings default to microphone left and meeting audio
right, alongside a session manifest. Recording and transcription are separate.

Both session timers reset when Turn off is clicked, while saved audio keeps its
duration. Recorded sessions prompt after 30 seconds of low speaker energy;
route-only sessions do not. Stop and trim finishes the session and trims trailing
low-energy audio while retaining detected activity from either channel plus
250 ms. Keep recording preserves all audio and snoozes reminders for 30 seconds;
speaker activity resuming dismisses the prompt. The current detector uses 20 ms
RMS energy windows at −45 dBFS, not Silero or speech classification. Ordinary
Turn off does not trim.

Floating controls stay above other windows and expose on/off, mute, elapsed time,
and written routing/recording state. Mute silences the virtual microphone feed and
local microphone recording; Direct capture also requires muting the meeting app's
physical microphone. The panel can collapse meeting details, minimize to the tray,
and change opacity from 65–100% in Preferences. The expanded panel shows the
storage path and editable tool/contact fields. Tool tags are manual; contact
names are searched and saved locally. No call detection is implemented. Tags are
locked during capture and can be edited afterward in the session viewer.

Session, Audio setup, and Preferences share input meters, Start/Stop, mute, and
elapsed time. Recordings uses the available height for its library; the global
status badge and status text remain visible, and floating/tray controls provide
session access. Route and setup controls are locked during an active session.
Recordings supports contact/tool/date search, tool/status/date filters, eight
sessions per page, folder actions, native playback, and transcript viewing.
Playback uses the selected physical speaker and requires the live session to be
off. The viewer has pause, a seek slider with keyboard steps, timestamp links,
editable tags, and JSON/HTML/folder actions. Recording location can change between
sessions.

The app launches at login by default, with audio off and tray controls available;
Preferences can disable login startup. Closing the main window keeps the app
running when the tray or floating controls are available. The tray exposes
physical microphone and speaker choices; a switch during capture finishes that
session and starts another in the same recording mode. Quit Voice Loop finishes
audio and exits. Force quit is a separate recovery action and can leave a
recording marked unfinished.
The notification-area waveform has a green activity dot, red when active and
muted, and grey when off. Written tooltip state accompanies the colour.

OpenAI transcription supports a user-selected model, upload confirmation for
manual jobs, progress, cancellation, and resumable completed chunks. Automatic
upload/transcription is off by default and applies only to future recorded
sessions after the user enables it. API keys use Windows Credential Manager,
macOS Keychain, or Linux Secret Service, with no plaintext fallback; an
OPENAI_API_KEY environment value can override a stored key. Credentials are kept
outside settings and recordings. Completed jobs save transcript.json and an
offline transcript.html beside the audio. The native viewer renders the JSON;
the HTML uses local audio and loads no external assets. Diarization labels are
scoped to each meeting-audio chunk and do not establish contact identity.

## Brand commitments
Name: Voice Loop. Clear, calm, practical language. Open-source developer
foundation. The confirmed visual direction is a clean, modern, HeroUI-inspired
native desktop interface: white surfaces, blue actions, restrained rounded
controls, and familiar keyboard behavior. HeroUI is a visual reference, not a
runtime dependency. Product naming uses the space; meeting-facing device names
use VoiceLoop without it.

## Assumptions
Manual session controls remain the activation boundary. Login startup never
starts audio capture. Default storage is the user's local data directory. The
implementation also retains the transcription plugin contract and optional local
Whisper adapter. Windows is the local verification host; real macOS/Linux audio
and desktop integration need validation on their respective systems.
