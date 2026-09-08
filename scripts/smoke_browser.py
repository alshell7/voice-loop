"""Verify HTTP → Qt call control → real audio workers using generated tones only."""

import json
import multiprocessing
import os
import tempfile
import time
import uuid
import wave
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QMessageBox
from smoke_audio import synthetic_capture, synthetic_playback

from voiceloop.audio import SAMPLE_RATE
from voiceloop.browser_bridge import BrowserBridge
from voiceloop.config import Settings
from voiceloop.devices import Device, Devices, SessionConfig
from voiceloop.library import Contacts
from voiceloop.ui import App, create_application


def main():
    application = create_application()
    microphone = Device("mic", "Synthetic microphone", 2)
    meeting = Device("meeting", "Synthetic meeting", 2)
    speaker = Device("speaker", "Synthetic speaker", 2)
    configuration = SessionConfig(microphone, meeting, speaker)
    with (
        tempfile.TemporaryDirectory(prefix="voiceloop-browser-smoke-") as directory,
        patch("voiceloop.engine._capture", synthetic_capture),
        patch("voiceloop.engine._playback", synthetic_playback),
        patch.object(Settings, "save", return_value=None),
    ):
        root = Path(directory)
        bridge = BrowserBridge(root / "pairing-token", port=0)
        bridge.start()
        window = App(
            settings=Settings(
                recording_directory=str(root / "recordings"),
                browser_detection_enabled=True,
                auto_transcribe=False,
            ),
            device_provider=lambda: Devices([microphone, meeting], [speaker]),
            contacts=Contacts(root / "contacts.json"),
            browser_bridge=bridge,
        )
        window.timer.stop()
        window.configuration = lambda: configuration

        def wait_for(predicate, timeout=15):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                application.processEvents()
                window.tick()
                if predicate():
                    return
                time.sleep(0.02)
            raise AssertionError(("Timed out", window.engine.state, window.engine.error))

        def send(state, call_id="synthetic-cliq", provider="zoho_cliq"):
            payload = {
                "version": 1,
                "event_id": str(uuid.uuid4()),
                "call_id": call_id,
                "provider": provider,
                "state": state,
                "direction": "incoming" if provider == "zoho_cliq" else "unknown",
                "contact": {"name": "Synthetic Contact" if provider == "zoho_cliq" else ""},
                "title": "Synthetic planning meeting",
                "url": "https://cliq.zoho.com/"
                if provider == "zoho_cliq"
                else "https://meet.google.com/abc-defg-hij",
                "timestamp": datetime.now(UTC).isoformat(),
            }
            client = HTTPConnection("127.0.0.1", bridge.port, timeout=3)
            try:
                client.request(
                    "POST",
                    "/v1/events",
                    json.dumps(payload),
                    {
                        "Authorization": "Bearer " + bridge.pairing_token,
                        "Content-Type": "application/json",
                        "Origin": "chrome-extension://" + "a" * 32,
                    },
                )
                response = client.getresponse()
                assert response.status == 202, response.read()
            finally:
                client.close()
            window.tick()

        def finish_and_verify(call_id, provider):
            wait_for(lambda: window.engine.state == "running")
            wait_for(lambda: window.engine.duration >= 0.6)
            send("ended", call_id, provider)
            wait_for(lambda: not window.engine.active)
            assert not window.engine.error, window.engine.error
            path = window.engine.saved_path
            manifest = json.loads((path / "session.json").read_text())
            assert manifest["status"] == "complete"
            assert manifest["metadata"]["browser_call_id"] == call_id
            with wave.open(str(path / "audio-001.wav"), "rb") as source:
                data = np.frombuffer(source.readframes(source.getnframes()), "<i2").reshape(-1, 2)
            assert len(data) == manifest["frames"]
            chunk = data[SAMPLE_RATE // 5 : SAMPLE_RATE // 2].astype(float)
            for channel, frequency in enumerate((220, 660)):
                frequencies = np.fft.rfftfreq(len(chunk), 1 / SAMPLE_RATE)
                peak = frequencies[np.argmax(abs(np.fft.rfft(chunk[:, channel])))]
                assert abs(peak - frequency) < 8, (channel, peak)
            return manifest

        try:
            send("ringing")
            assert window.browser_prompt is None and not window.engine.active
            assert not list(root.glob("recordings/*/session.json"))
            send("connected")
            assert window.browser_prompt is not None and not window.engine.active
            window.browser_prompt.done(QMessageBox.StandardButton.Yes)
            manifest = finish_and_verify("synthetic-cliq", "zoho_cliq")
            assert manifest["metadata"]["contact"] == "Synthetic Contact"
            assert manifest["metadata"]["recording_trigger"] == "browser_prompt"
            window.set_browser_auto_record(True)
            send("connected", "synthetic-meet", "google_meet")
            assert window.browser_prompt is None
            manifest = finish_and_verify("synthetic-meet", "google_meet")
            assert manifest["metadata"]["meeting_title"] == "Synthetic planning meeting"
            assert manifest["metadata"]["recording_trigger"] == "browser_auto_record"
            assert len(list(root.glob("recordings/*/session.json"))) == 2
            assert not multiprocessing.active_children(), "Leaked audio processes"
        finally:
            window.engine.stop()
            window.engine.wait(10)
            bridge.stop()
            window.closing = True
            window.close()
            application.processEvents()
    print(
        "PASS: authenticated call events, attendance prompt, auto-record, saved stereo and metadata"
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
