# Changelog

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
