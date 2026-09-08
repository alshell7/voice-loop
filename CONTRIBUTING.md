# Contributing

Create a Python virtual environment and install `pip install -e ".[dev]"`.
Run these checks before proposing a change:

```sh
python -m pytest
python -m ruff check .
python -m ruff format --check .
python scripts/smoke_audio.py
```

Fork [alshell7/voice-loop](https://github.com/alshell7/voice-loop), make a focused
branch, and open a pull request against `main`. Explain the behavior changed
and how you verified it. Add meaningful regression tests for audio integrity,
lifecycle, and security changes. Maintainer: **alshell7**.

CI checks Windows, macOS, and Linux. Merging into `main` automatically publishes
a Windows/macOS prerelease after all release checks pass; see
[docs/RELEASING.md](docs/RELEASING.md). Version changes must update both package
metadata and `src/voiceloop/__init__.py`, plus the changelog.

- Keep recording opt-in per session and cloud uploads separately opt-in.
- Keep native audio work away from the UI thread and keep queues bounded.
- Never silently switch an unavailable device to a different microphone.
- Preserve channel labels, timestamps, silence, and readable WAV output on errors.
- Test each OS's actual audio paths before claiming hardware support.
- Do not commit audio, personal settings, API keys, proprietary drivers, or model weights.
- New providers implement `Transcriber`; declare `uploads_audio` truthfully.

For a bug report include OS, Python/app version, device names, audio server (Linux),
capture mode, and a minimal reproduction. Share manifest diagnostics only after
reviewing device names and paths for personal information. Audio is not needed by default.
