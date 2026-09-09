"""Native screenshots of v0.3 surfaces using explicitly synthetic library data."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtTest import QTest

from voiceloop.config import Settings, atomic_json
from voiceloop.library import Contacts
from voiceloop.recording import Recording
from voiceloop.ui import App, create_application


def main():
    qt = create_application()
    destination = Path(".impeccable/review/v03")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voiceloop-ui-") as root:
        root = Path(root)
        recordings = root / "recordings"
        contacts = Contacts(root / "contacts.json")
        contacts.remember("Maya Shah")
        contacts.remember("Alex Morgan")
        for index in range(19):
            recording = Recording(
                recordings,
                {},
                metadata={
                    "contact": "Maya Shah" if index % 2 else "Alex Morgan",
                    "tool": ("Zoom", "Google Meet", "Microsoft Teams")[index % 3],
                },
            )
            recording.write(np.zeros((4800, 2)))
            directory = recording.close()
            manifest = recording.manifest
            manifest["started_at"] = f"2026-09-{min(28, index + 1):02d}T10:30:00+00:00"
            manifest["duration_seconds"] = 1680 + index * 70
            atomic_json(directory / "session.json", manifest)
        atomic_json(
            directory / "transcript.json",
            {
                "metadata": recording.manifest["metadata"],
                "started_at": "2026-09-08T10:30:00+00:00",
                "speaker_labels": (
                    "Synthetic design preview. Speaker labels are scoped to each audio clip."
                ),
                "segments": [
                    {
                        "start": 0,
                        "end": 5,
                        "speaker": "You",
                        "text": (
                            "Let's review the Voice Loop release. "
                            "The floating control is ready for the next test."
                        ),
                    },
                    {
                        "start": 6,
                        "end": 14,
                        "speaker": "Speaker A · clip 1",
                        "text": (
                            "The recording and routing options are much easier to find. "
                            "I will test device switching and send the results tomorrow."
                        ),
                    },
                    {
                        "start": 16,
                        "end": 24,
                        "speaker": "You",
                        "text": (
                            "Great. Let's include the new installer and check "
                            "the transcript exports before Friday."
                        ),
                    },
                ],
            },
        )
        with patch.object(Settings, "save"):
            app = App(
                settings=Settings(
                    recording_directory=str(recordings),
                    meeting_tool="Zoom",
                    contact_name="Maya Shah",
                ),
                contacts=contacts,
                assistant_directory=root / "assistant",
            )
            app.show()
            app.show_floating()

            def capture(widget, name):
                QTest.qWait(150)
                qt.processEvents()
                image = widget.grab()
                assert not image.isNull()
                assert image.save(str(destination / (name + ".png")))

            capture(app.floating, "floating-off")
            app.floating.mode.setCurrentIndex(1)
            app.engine.state, app.engine.recording, app.engine.duration = "running", True, 123
            app.engine.set_muted(True)
            app.floating.refresh()
            capture(app.floating, "floating-recording-muted")
            app.floating.toggle_compact()
            capture(app.floating, "floating-compact")
            assert 180 <= app.floating.height() <= 300
            app.engine.state = "idle"
            app.engine.set_muted(False)
            app.floating.hide()
            app.last_state = "running"
            app.tick()
            app.resize(1060, 900)
            app.navigate(2)
            app.refresh_library()
            capture(app, "library-desktop")
            app.resize(820, 640)
            capture(app, "library-compact")
            app.resize(1060, 900)
            app.navigate(3)
            capture(app, "preferences")
            app.open_session_dialog(directory)
            viewer = app.dialogs[-1]
            capture(viewer, "transcript")
            viewer.close()
            app.closing = True
            app.close()
    print(
        json.dumps(
            {
                "status": "passed",
                "screenshots": str(destination),
                "data": "synthetic",
                "audio_opened": False,
            }
        )
    )


if __name__ == "__main__":
    main()
