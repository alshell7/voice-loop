"""Explicit packaging check: synthetic files, no audio, upload, or login changes."""

import json
import tempfile
import time
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QMessageBox

from voiceloop import __version__
from voiceloop.audio import SAMPLE_RATE
from voiceloop.config import Settings
from voiceloop.credentials import _backend
from voiceloop.desktop import enable_desktop, update_tray_status
from voiceloop.devices import Devices
from voiceloop.jobs import TranscriptionJob
from voiceloop.library import Contacts
from voiceloop.recording import Recording
from voiceloop.ui import App, create_application


def check_ui(output):
    application = create_application()
    with tempfile.TemporaryDirectory(prefix="voiceloop-ui-check-") as directory:
        root = Path(directory)
        window = App(
            settings=Settings(recording_directory=str(root / "recordings")),
            device_provider=lambda: Devices([], []),
            contacts=Contacts(root / "contacts.json"),
            assistant_directory=root / "assistant",
        )
        job = None
        try:
            window.show()
            enable_desktop(window, register_startup=False, assistant_control=False)
            window.show_floating()
            application.processEvents()
            if window.grab().isNull():
                raise RuntimeError("Qt could not render the application window.")
            combo = window.floating.tool
            combo.completer().setCompletionPrefix("a")
            combo.completer().complete()
            application.processEvents()
            popup = combo.completer().popup()
            if not popup.isVisible() or popup.grab().isNull():
                raise RuntimeError("Search suggestions did not render.")
            popup.grab().save(str(Path(output).with_suffix(".suggestions.png")))
            popup.hide()
            window.floating.toggle_compact()
            for _ in range(4):
                application.processEvents()
                time.sleep(0.03)
            floating = window.floating
            if not 180 <= floating.height() <= 300 or floating.grab().isNull():
                raise RuntimeError("Floating controls did not resize to compact mode.")
            if floating.mode.currentData() is not False:
                raise RuntimeError("Fresh controls should default to routing only.")
            actions = {action.text(): action for action in window.tray_menu.actions()}
            for title in ("Microphone", "Speaker", "Quit Voice Loop", "Force quit"):
                if title not in actions:
                    raise RuntimeError("Missing tray action: " + title)
            actions["Mute microphone"].trigger()
            if not window.engine.muted:
                raise RuntimeError("Tray mute did not reach the audio controller.")
            icon_keys = []
            for state, muted, expected in (
                ("idle", True, "off"),
                ("running", False, "active"),
                ("running", True, "muted"),
            ):
                window.engine.state = state
                window.engine.set_muted(muted)
                update_tray_status(window)
                icon_keys.append(window.tray.icon().cacheKey())
                if window.tray_state != expected:
                    raise RuntimeError("Tray icon has the wrong session state.")
            if len(set(icon_keys)) != 3:
                raise RuntimeError("Tray status icons did not change.")

            window.engine.state, window.engine.recording, window.engine.duration = (
                "running",
                True,
                31,
            )
            window.engine.activity.update(np.zeros((SAMPLE_RATE * 31, 2), dtype=np.float32))
            window.tick()
            application.processEvents()
            prompt = window.silence_prompt
            if prompt is None or prompt.grab().isNull():
                raise RuntimeError("The speaker silence prompt did not render.")
            prompt.grab().save(str(Path(output).with_suffix(".silence-prompt.png")))
            prompt.button(QMessageBox.StandardButton.No).click()
            if window.engine.state != "running" or window.engine._trim_silence:
                raise RuntimeError("Keep recording changed the live session.")
            window.stop_session()
            window.engine.state = "idle"
            window.tick()
            if floating.elapsed.text() != "00:00" or window.clock.text() != "00:00:00":
                raise RuntimeError("The session timers did not reset after Turn off.")

            # Silence bypasses the API entirely, but exercises the real spawned
            # transcription job, dependency imports, JSON, and HTML in a bundle.
            recording = Recording(root / "recordings", {})
            recording.write(np.zeros((4800, 2), dtype=np.float32))
            session = recording.close()
            job = TranscriptionJob(session, "diagnostic-no-network", "gpt-4o-transcribe-diarize")
            deadline = time.monotonic() + 12
            messages = []
            while not job.finished and time.monotonic() < deadline:
                application.processEvents()
                messages.extend(job.poll())
                time.sleep(0.03)
            if not any(kind == "complete" for kind, _ in messages):
                raise RuntimeError("Packaged transcription worker failed: " + str(messages))
            if not (session / "transcript.html").is_file():
                raise RuntimeError("Transcription did not write its HTML export.")
            report = {
                "version": __version__,
                "ui": "ok",
                "audio_started": False,
                "network_used": False,
                "startup_changed": False,
                "assistant_store_isolated": True,
                "assistant_control_started": window.assistant_control is not None,
                "width": window.width(),
                "height": window.height(),
                "floating_height": floating.height(),
                "tray_available": window.tray.isSystemTrayAvailable(),
                "tray_actions": "ok",
                "credential_backend": type(_backend()).__name__,
                "transcription_worker": "ok",
                "speaker_silence_prompt": "ok",
                "timer_reset": "ok",
                "search_suggestions": "ok",
                "tray_status_icons": "ok",
            }
            Path(output).write_text(json.dumps(report), encoding="utf-8")
        finally:
            if job:
                job.close()
            window.engine.state = "idle"
            window.dismiss_silence_prompt()
            window.closing = True
            if window.tray:
                window.tray.hide()
            window.close()
            application.processEvents()
