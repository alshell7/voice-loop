"""Diagnostic windows must not recover live assistant jobs or open MCP control."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from voiceloop.assistant_store import AssistantStore
from voiceloop.config import Settings
from voiceloop.desktop import enable_desktop
from voiceloop.devices import Devices
from voiceloop.library import Contacts
from voiceloop.ui import App, create_application


def test_diagnostic_directory_and_disabled_control_preserve_user_state(tmp_path, monkeypatch):
    application = create_application()
    user_directory = tmp_path / "simulated-user-data"
    user_database = user_directory / "assistant-jobs.sqlite3"
    store = AssistantStore(user_database)
    store.put({"id": "live-call", "state": "active", "delivery_status": "not_requested"})
    store.close()
    original_database = user_database.read_bytes()
    user_token = user_directory / "assistant-control-token"
    user_token.write_text("synthetic-existing-token", encoding="utf-8")
    monkeypatch.setattr("voiceloop.assistant.data_directory", lambda: user_directory)
    isolated = tmp_path / "diagnostic-assistant"
    window = App(
        settings=Settings(recording_directory=str(tmp_path / "recordings")),
        device_provider=lambda: Devices([], []),
        contacts=Contacts(tmp_path / "contacts.json"),
        assistant_directory=isolated,
    )
    window.timer.stop()
    enabled = []
    monkeypatch.setattr(window, "enable_assistant", lambda: enabled.append(True))
    try:
        enable_desktop(window, register_startup=False, assistant_control=False)
        window.tray_timer.stop()
        assert not enabled
        assert not window.assistant.runtime_enabled
        assert window.assistant_control is None
        assert window.assistant.directory == isolated
        assert (isolated / "assistant-jobs.sqlite3").is_file()
        assert not window.assistant.store.list()
        assert not (isolated / "assistant-control-token").exists()
        assert user_database.read_bytes() == original_database
        assert user_token.read_text(encoding="utf-8") == "synthetic-existing-token"
    finally:
        window.closing = True
        window.close()
        application.processEvents()
