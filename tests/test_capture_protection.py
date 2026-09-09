import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QDialog, QWidget

from voiceloop.capture_protection import CaptureProtection
from voiceloop.config import Settings, atomic_json
from voiceloop.devices import Devices
from voiceloop.library import Contacts
from voiceloop.ui import App, create_application


class Backend:
    supported = True
    limitation = "Synthetic backend"

    def __init__(self):
        self.calls = []
        self.fail = False

    def apply(self, handle, enabled):
        self.calls.append((handle, enabled))
        if self.fail:
            raise OSError("Synthetic native failure")


@pytest.fixture
def windows():
    qt = create_application()
    owner = QWidget()
    backend = Backend()
    manager = CaptureProtection(owner, backend=backend)
    owner.show()
    qt.processEvents()
    yield qt, owner, manager, backend
    manager.close()
    for window in qt.topLevelWidgets():
        if manager.owns(window):
            window.close()
    owner.deleteLater()
    qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt.processEvents()


def test_live_toggle_restores_capture_and_does_not_touch_other_apps(windows):
    qt, owner, manager, backend = windows
    unrelated = QWidget()
    unrelated.show()
    try:
        assert not backend.calls
        manager.set_enabled(True)
        assert (int(owner.winId()), True) in backend.calls
        assert all(handle != int(unrelated.winId()) for handle, _ in backend.calls)
        manager.set_enabled(False)
        assert backend.calls[-1] == (int(owner.winId()), False)
    finally:
        unrelated.close()


def test_protection_applies_before_new_floating_and_dialog_windows_show(windows):
    qt, owner, manager, backend = windows
    manager.set_enabled(True)
    floating = QWidget(None, Qt.WindowType.Tool)
    manager.register(floating)
    floating.show()
    dialog = QDialog(floating)
    dialog.show()
    qt.processEvents()
    assert (int(floating.winId()), True) in backend.calls
    assert (int(dialog.winId()), True) in backend.calls
    manager.set_enabled(False)
    assert (int(floating.winId()), False) in backend.calls
    assert (int(dialog.winId()), False) in backend.calls
    dialog.close()
    floating.close()


def test_recreated_handle_and_hide_show_reapply_protection(windows):
    qt, owner, manager, backend = windows
    manager.set_enabled(True)
    backend.calls.clear()
    qt.sendEvent(owner, QEvent(QEvent.Type.WinIdChange))
    assert backend.calls == [(int(owner.winId()), True)]
    owner.hide()
    owner.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    owner.show()
    qt.processEvents()
    assert backend.calls[-1] == (int(owner.winId()), True)


def test_native_failure_is_visible_and_can_be_retried_or_disabled(windows):
    _qt, owner, manager, backend = windows
    backend.fail = True
    manager.set_enabled(True)
    assert "Could not apply" in manager.status
    assert "Synthetic native failure" in manager.status
    backend.fail = False
    manager.set_enabled(True)
    assert "Could not apply" not in manager.status
    backend.fail = True
    manager.set_enabled(False)
    assert "Could not apply" in manager.status  # Must not claim capture was restored.
    backend.fail = False
    manager.set_enabled(False)
    assert manager.status.startswith("Off")
    assert backend.calls[-1] == (int(owner.winId()), False)


def test_unsupported_backend_never_claims_protection(windows):
    _qt, _owner, manager, backend = windows
    backend.supported = False
    manager.set_enabled(True)
    assert "Unavailable" in manager.status
    assert not backend.calls


def test_saved_capture_setting_is_opt_in_and_strictly_boolean(tmp_path):
    path = tmp_path / "settings.json"
    assert not Settings.load(path).capture_protection
    Settings(capture_protection=True).save(path)
    assert Settings.load(path).capture_protection is True
    atomic_json(path, {"capture_protection": "false"})
    assert Settings.load(path).capture_protection is False


def test_enabled_at_startup_is_applied_before_window_show_event(windows):
    _qt, owner, manager, backend = windows
    manager.set_enabled(True)

    class ObservedDialog(QDialog):
        def showEvent(self, event):
            assert (int(self.winId()), True) in backend.calls
            super().showEvent(event)

    dialog = ObservedDialog(owner)
    dialog.show()
    dialog.close()


def test_preferences_toggle_controls_actual_app_windows_and_persists(tmp_path, monkeypatch):
    qt = create_application()
    saved = []
    monkeypatch.setattr(
        Settings, "save", lambda settings: saved.append(settings.capture_protection)
    )
    app = App(
        settings=Settings(recording_directory=str(tmp_path)),
        contacts=Contacts(tmp_path / "contacts.json"),
        assistant_directory=tmp_path / "assistant",
        device_provider=lambda: Devices([], []),
    )
    backend = Backend()
    app.capture_protection.backend = backend
    app.preferences.capture_protection.setEnabled(True)
    try:
        app.show()
        app.preferences.capture_protection.setChecked(True)
        app.show_floating()
        qt.processEvents()
        assert saved[-1] is True
        assert (int(app.winId()), True) in backend.calls
        assert (int(app.floating.winId()), True) in backend.calls
        popup = app.floating.contact.completer().popup()
        assert app.capture_protection.owns(popup)
        assert app.preferences.capture_status.text() == app.capture_protection.status
        app.preferences.capture_protection.setChecked(False)
        assert saved[-1] is False
        assert (int(app.winId()), False) in backend.calls
        assert (int(app.floating.winId()), False) in backend.calls
    finally:
        app.closing = True
        app.close()
        if app.floating:
            app.floating.deleteLater()
        app.deleteLater()
        qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt.processEvents()
