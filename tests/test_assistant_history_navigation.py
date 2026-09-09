"""History opens the latest saved job under Recordings without starting audio."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QTextBrowser
from test_setup import hardware

from voiceloop.config import Settings
from voiceloop.library import Contacts
from voiceloop.ui import App, create_application


def test_application_initialization_does_not_restyle_existing_windows(monkeypatch):
    application = create_application()

    def unexpected_restyle(*args):
        raise AssertionError("An existing application must not restyle all retained widgets.")

    monkeypatch.setattr(application, "setStyleSheet", unexpected_restyle)
    monkeypatch.setattr(application, "setStyle", unexpected_restyle)
    assert create_application() is application


def test_history_navigation_uses_saved_job(tmp_path, monkeypatch):
    qt = create_application()
    monkeypatch.setattr(Settings, "save", lambda self: None)
    window = App(
        settings=Settings(recording_directory=str(tmp_path / "recordings")),
        device_provider=lambda: hardware(True),
        contacts=Contacts(tmp_path / "contacts.json"),
        assistant_directory=tmp_path / "assistant",
    )
    try:
        job = {"id": "history-test", "state": "completed", "summary": "Latest summary"}
        window.assistant.store.put(job)
        window.open_assistant_history({"id": job["id"], "summary": "Stale summary"})
        qt.processEvents()
        assert window.pages.currentIndex() == 2
        assert len(window.dialogs) == 1
        viewer = window.dialogs[0]
        assert "Latest summary" in viewer.findChildren(QTextBrowser)[0].toPlainText()
        viewer.stop_playback()
        viewer.close()
        qt.processEvents()
        assert not window.dialogs
        job["recording_path"] = str(tmp_path / "recordings" / "sample")
        window.assistant.store.put(job)
        opened = []
        monkeypatch.setattr(window, "open_session_dialog", opened.append)
        window.open_assistant_history(job)
        assert str(opened[0]) == job["recording_path"]
    finally:
        window.timer.stop()
        window.assistant.close()
        window.close()
        if window.floating:
            window.floating.deleteLater()
        window.deleteLater()
        qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt.processEvents()
