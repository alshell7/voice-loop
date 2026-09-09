import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from voiceloop.config import Settings
from voiceloop.devices import Device, Devices
from voiceloop.ui import App


@pytest.fixture
def window(tmp_path):
    qt = QApplication.instance() or QApplication([])
    mic = Device("mic", "Physical mic", 2)
    speaker = Device("speaker", "Physical speaker", 2)
    virtual_mic = Device("virtual-mic", "VoiceLoop Mic", 2)
    feed = Device("feed", "VoiceLoop Mic Feed", 2)
    meeting = Device("meeting", "VoiceLoop Speaker", 2)
    devices = Devices(
        [mic, virtual_mic, Device("meeting", "VoiceLoop Speaker", 2, True)],
        [speaker, feed, meeting],
        mic.id,
        speaker.id,
    )
    result = App(
        settings=Settings(speaker_id="speaker", recording_directory=str(tmp_path)),
        device_provider=lambda: devices,
    )
    yield result
    result.closing = True
    result.close()
    qt.processEvents()


def test_assistant_audio_uses_independent_bridge_endpoints(window, monkeypatch):
    captured = []
    monkeypatch.setattr(
        "voiceloop.assistant_audio.CableAudio",
        lambda source, feed, monitor: captured.append((source, feed, monitor)),
    )
    window.assistant_audio()
    source, feed, monitor = captured[0]
    assert (source.id, feed.id, monitor.id) == ("meeting", "feed", "speaker")
    assert "mic" not in {source.id, feed.id, monitor.id}


def test_assistant_without_bridge_fails_before_dial(window):
    window.devices = Devices([], [])
    assert not window.assistant.snapshot()["prerequisites"]["audio"]
    with pytest.raises(ValueError, match="Install VoiceLoop"):
        window.assistant_audio()


def test_assistant_audio_readiness_requires_physical_speaker(window):
    assert window.assistant.snapshot()["prerequisites"]["audio"]
    window.settings.speaker_id = "meeting"
    assert not window.assistant.snapshot()["prerequisites"]["audio"]


def test_assistant_pages_and_manual_audio_exclusion(window):
    window.navigate(4)
    assert window.page_title.text() == "AI Assistant"
    assert window.transport.isHidden()
    window.assistant.active_id = "test-owned-call"
    assert not window.start(record=False)
    window.assistant.active_id = ""
    window.navigate(5)
    assert window.page_title.text() == "Automation"


def test_quit_keeps_bridge_alive_until_assistant_cleanup_acknowledged(window, monkeypatch):
    state = {"ready": False, "began": 0}
    monkeypatch.setattr(window.assistant, "begin_shutdown", lambda: state.update(began=1))
    monkeypatch.setattr(window.assistant, "shutdown_ready", lambda: state["ready"])
    first = QCloseEvent()
    window.closeEvent(first)
    assert not first.isAccepted()
    assert window.closing and state["began"] == 1
    assert window.timer.isActive()
    state["ready"] = True
    final = QCloseEvent()
    window.closeEvent(final)
    assert final.isAccepted()
    assert not window.timer.isActive()


def test_quit_grace_is_bounded_when_browser_stops_responding(window, monkeypatch):
    monkeypatch.setattr(window.assistant, "shutdown_ready", lambda: False)
    window.closing = True
    window._assistant_shutdown_deadline = time.monotonic() - 1
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_quit_grace_delivers_only_assistant_browser_events(window, monkeypatch):
    received = []
    event = object()
    window.closing = True
    window._assistant_shutdown_deadline = time.monotonic() + 8
    window.browser_bridge = SimpleNamespace(drain=lambda limit: [event], stop=lambda: None)
    monkeypatch.setattr(window.assistant, "handle_event", received.append)
    window.tick_browser()
    assert received == [event]
