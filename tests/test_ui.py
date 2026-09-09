"""Real Qt widgets, injected device inventory; never opens an audio stream."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_setup import hardware

from voiceloop.config import Settings
from voiceloop.devices import Devices
from voiceloop.library import Contacts
from voiceloop.ui import App, ConsentDialog, HelpButton, create_application


@pytest.fixture(scope="module")
def qt():
    return create_application()


@pytest.fixture
def app(qt, tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self: None)
    window = App(
        settings=Settings(recording_directory=str(tmp_path)),
        device_provider=lambda: hardware(True),
        contacts=Contacts(tmp_path / "contacts.json"),
    )
    window.show()
    qt.processEvents()
    yield window
    window.timer.stop()
    window.engine.state = "idle"
    window.close()
    qt.processEvents()


def test_simple_only_shows_physical_choices(app):
    assert not app.advanced.isVisible()
    assert app.microphone.count() == 1
    assert app.speaker.count() == 1
    assert app.configuration().mode == "bridge"


def test_advanced_channel_swap_and_tooltips(app, qt):
    QTest.mouseClick(app.level_group.button(1), Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert app.advanced.isVisible()
    assert "Direct capture" in app.mode.toolTip()
    assert "Virtual bridge" in app.mode.toolTip()
    app.left_channel.setCurrentIndex(1)
    assert app.right_channel.currentData() == "microphone"
    assert app.configuration().left_channel == "meeting"
    assert all(
        button.toolTip() and button.accessibleName() for button in app.findChildren(HelpButton)
    )


@pytest.mark.parametrize("choice", [True, False, None])
def test_consent_is_explicit(qt, tmp_path, choice):
    dialog = ConsentDialog(tmp_path, True)
    dialog.show()
    qt.processEvents()
    assert dialog.choice is None
    if choice is None:
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        QTest.mouseClick(
            dialog.record_button if choice else dialog.route_button, Qt.MouseButton.LeftButton
        )
    assert dialog.choice is choice
    assert not list(tmp_path.iterdir())


def test_recording_locks_configuration(app):
    app.engine.state = "running"
    app.update_enabled()
    assert not app.microphone.isEnabled()
    assert not app.start_button.isEnabled()
    assert app.stop_button.isEnabled()


def test_missing_saved_devices_require_selection(app):
    app.fill(app.microphone, hardware().inputs[:1], "disconnected")
    assert app.selected(app.microphone) is None
    with pytest.raises(ValueError, match="available"):
        app.configuration()


def test_refresh_preserves_advanced_source(app):
    app.level_group.button(1).click()
    app.mode.setCurrentIndex(0)
    app.meeting.setCurrentIndex(app.meeting.count() - 1)
    chosen = app.selected(app.meeting).id
    app.refresh_devices()
    assert app.selected(app.meeting).id == chosen


def test_empty_devices_and_compact_transport(app, qt):
    app.device_provider = lambda: Devices([], [])
    app.refresh_devices()
    assert app.selected(app.microphone) is None
    app.resize(820, 640)
    qt.processEvents()
    position = app.start_button.mapTo(app, app.start_button.rect().bottomRight())
    assert position.x() <= app.width() and position.y() <= app.height()
    assert app.start_button.isVisible()


def test_floating_record_mode_tags_mute_and_off(app, qt, monkeypatch):
    calls = []

    def start(config, root, **options):
        calls.append(options)
        app.engine.state = "running"
        app.engine.recording = options["record"]

    monkeypatch.setattr(app.engine, "start", start)
    app.show_floating()
    floating = app.floating
    assert floating.mode.currentData() is False
    floating.tool.setCurrentText("Zoom")
    floating.contact.setCurrentText("Maya Shah")
    floating.mode.setCurrentIndex(1)
    floating.power.click()
    app.tick()
    qt.processEvents()
    assert calls[0] == {"record": True, "metadata": {"tool": "Zoom", "contact": "Maya Shah"}}
    assert app.contacts.names() == ["Maya Shah"]
    assert not floating.mode.isEnabled()
    assert floating.power.text() == "Turn off"
    floating.mute.click()
    assert app.engine.muted
    floating.power.click()
    assert app.engine.state == "stopping"


def test_tray_device_switch_preserves_mode_and_manual_off_cancels(app, qt, monkeypatch):
    from voiceloop.devices import Device

    device = Device("second-mic", "Second microphone", 2)
    app.devices.inputs.append(device)
    calls = []
    monkeypatch.setattr(app.engine, "start", lambda *args, **kwargs: calls.append(kwargs))
    app.engine.state, app.engine.recording, app.last_state = "running", False, "running"
    app.switch_device("microphone", device)
    assert app.engine.state == "stopping"
    app.engine.state = "idle"
    app.tick()
    qt.processEvents()
    assert app.selected(app.microphone).id == "second-mic"
    assert calls[0]["record"] is False
    app.engine.state = "running"
    app.switch_device("microphone", hardware(True).inputs[0])
    app.stop_session()
    assert not app.pending_switch
    app.engine.state = "idle"
    app.tick()
    qt.processEvents()
    assert len(calls) == 1


@pytest.mark.parametrize("record", [True, False])
def test_tray_start_updates_floating_mode_to_actual_session(app, record, monkeypatch):
    app.show_floating()
    app.floating.mode.setCurrentIndex(0 if record else 1)
    monkeypatch.setattr(app.engine, "start", lambda *args, **kwargs: None)
    app.start(record=record)
    assert app.floating.mode.currentData() is record
    assert app.settings.session_mode == ("record" if record else "route")


def test_floating_compact_and_opacity(app, qt):
    app.show_floating()
    full_height = app.floating.height()
    app.floating.toggle_compact()
    qt.processEvents()
    assert app.floating.height() < full_height
    assert 180 <= app.floating.height() <= 300
    assert (
        app.floating.power.mapTo(app.floating, app.floating.power.rect().bottomRight()).y()
        < app.floating.height()
    )
    assert app.floating.mode.isVisible() and app.floating.power.isVisible()
    app.preferences.opacity.setValue(80)
    assert app.settings.floating_opacity == 80
    assert abs(app.floating.windowOpacity() - 0.8) < 0.01


def test_library_viewer_renders_safe_transcript_and_prevents_live_playback(app, tmp_path, qt):
    import numpy as np

    from voiceloop.config import atomic_json
    from voiceloop.recording import Recording

    recording = Recording(tmp_path, {}, metadata={"tool": "Zoom", "contact": "Maya"})
    recording.write(np.zeros((4800, 2)))
    directory = recording.close()
    atomic_json(
        directory / "transcript.json",
        {
            "segments": [
                {"start": 0, "end": 0.1, "text": "Hello <script>", "speaker": "Maya"},
            ]
        },
    )
    app.refresh_library()
    app.library_panel.open()
    qt.processEvents()
    viewer = app.dialogs[-1]
    assert "Hello <script>" in viewer.browser.toPlainText()
    assert viewer.html_button.isEnabled()
    app.engine.state = "running"
    viewer.toggle_play()
    assert viewer.player is None
    assert "Turn off" in viewer.status.text()


def test_single_instance_reuses_existing_window(qt, tmp_path, monkeypatch):
    from voiceloop import desktop

    monkeypatch.setattr(desktop, "data_directory", lambda: tmp_path)
    first, second = desktop.SingleInstance(), desktop.SingleInstance()
    assert first.acquire()
    try:
        assert second.acquire() is False
    finally:
        first.close()


def test_playback_keyboard_seeks_but_timer_updates_do_not(app, tmp_path, qt):
    import threading
    from types import SimpleNamespace

    from voiceloop.config import atomic_json
    from voiceloop.ui_extras import SessionDialog

    atomic_json(tmp_path / "session.json", {"duration_seconds": 30, "status": "complete"})
    viewer = SessionDialog(app, tmp_path)
    calls = []
    viewer.player = SimpleNamespace(
        seek=calls.append,
        position=SimpleNamespace(value=96000),
        paused=threading.Event(),
        poll=lambda: None,
        close=lambda: None,
    )
    viewer.show()
    viewer.timer.stop()
    viewer.position.setFocus()
    QTest.keyClick(viewer.position, Qt.Key.Key_Right)
    assert calls == [1.0]
    QTest.keyClick(viewer.position, Qt.Key.Key_PageUp)
    assert calls == [1.0, 11.0]
    viewer.tick()
    assert viewer.position.value() == 2000
    assert calls == [1.0, 11.0]
    QTest.keyClick(viewer.position, Qt.Key.Key_End)
    assert calls[-1] == 30.0
    viewer.close()


def test_turn_off_resets_both_timers_without_losing_recorded_duration(app, qt):
    app.show_floating()
    app.engine.state, app.engine.duration = "running", 123
    app.tick()
    assert app.floating.elapsed.text() == "02:03"
    app.floating.power.click()
    assert app.floating.elapsed.text() == "00:00"
    assert app.clock.text() == "00:00:00"
    app.engine.state = "idle"
    app.tick()
    assert app.floating.elapsed.text() == "00:00"
    assert app.engine.duration == 123


def assistant_controls(app, monkeypatch, job):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    app.timer.stop()
    app.assistant.close()
    cancelled = []

    def cancel(job_id):
        cancelled.append(job_id)
        job["state"] = "cancelled"

    assistant = SimpleNamespace(
        active=True,
        active_id="control-test",
        store=SimpleNamespace(get=lambda _job_id: job),
        now=lambda: datetime(2026, 9, 9, 10, 2, 3, tzinfo=UTC),
        cancel=cancel,
        close=lambda: None,
        begin_shutdown=lambda: None,
        shutdown_ready=lambda: True,
        cancelled=cancelled,
    )
    monkeypatch.setattr(app, "assistant", assistant)
    return assistant


def test_assistant_floating_lifecycle_timer_and_mute_tooltip(app, monkeypatch):
    job = {"state": "preparing", "started_at": "2026-09-09T10:00:00+00:00", "action": "call"}
    assistant = assistant_controls(app, monkeypatch, job)
    app.engine.duration = 987
    app.show_floating()
    floating = app.floating
    assert "preparing" in floating.state.text()
    assert floating.elapsed.text() == "00:00"
    assert not floating.mute.isEnabled()
    assert "not used during an AI call" in floating.mute.toolTip()

    job.update(state="waiting", browser_state="dialing")
    floating.refresh()
    assert "calling" in floating.state.text() and floating.elapsed.text() == "00:00"
    job["browser_state"] = "ringing"
    floating.refresh()
    assert "ringing" in floating.state.text() and floating.elapsed.text() == "00:00"
    job["state"] = "active"
    floating.refresh()
    assert "on call" in floating.state.text() and floating.elapsed.text() == "02:03"

    floating.power.click()
    assert assistant.cancelled == ["control-test"]
    assert "stopping" in floating.state.text()
    assert floating.elapsed.text() == "00:00"
    assistant.active = False
    assistant.active_id = ""
    floating.refresh()
    assert floating.state.text().startswith("Off")
    assert floating.elapsed.text() == "00:00"
    assert floating.mute.isEnabled()
    assert "Direct capture" in floating.mute.toolTip()


@pytest.mark.parametrize(
    "started_at", ("", "invalid", "2026-09-09T10:00:00", "2026-09-10T10:00:00+00:00")
)
def test_assistant_floating_invalid_or_future_time_is_zero(app, monkeypatch, started_at):
    assistant_controls(app, monkeypatch, {"state": "active", "started_at": started_at})
    app.show_floating()
    assert app.floating.elapsed.text() == "00:00"


def test_assistant_floating_resets_after_browser_end(app, monkeypatch):
    assistant_controls(
        app,
        monkeypatch,
        {
            "state": "active",
            "started_at": "2026-09-09T10:00:00+00:00",
            "browser_ended": True,
        },
    )
    app.show_floating()
    assert "stopping" in app.floating.state.text()
    assert app.floating.elapsed.text() == "00:00"


def test_assistant_blocks_library_and_direct_viewer_playback(app, tmp_path, qt, monkeypatch):
    import numpy as np

    from voiceloop.recording import Recording

    assistant_controls(app, monkeypatch, {"state": "preparing"})
    recording = Recording(tmp_path, {}, metadata={"tool": "Zoho Cliq", "contact": "Alex"})
    recording.write(np.zeros((4800, 2)))
    recording.close()
    app.refresh_library()
    assert not app.library_panel.play_button.isEnabled()
    assert "AI Assistant" in app.library_panel.play_button.toolTip()
    app.library_panel.open()
    qt.processEvents()
    viewer = app.dialogs[-1]
    viewer.toggle_play()
    assert viewer.player is None
    assert "AI Assistant" in viewer.status.text()
    viewer.tick()
    assert not viewer.play_button.isEnabled()
    viewer.close()


@pytest.mark.parametrize("action", ("tick", "toggle_play"))
def test_assistant_stops_existing_or_paused_playback(app, tmp_path, monkeypatch, action):
    import threading
    from types import SimpleNamespace

    from voiceloop.config import atomic_json
    from voiceloop.ui_extras import SessionDialog

    assistant_controls(app, monkeypatch, {"state": "active"})
    atomic_json(tmp_path / "session.json", {"duration_seconds": 30, "status": "complete"})
    viewer = SessionDialog(app, tmp_path)
    viewer.timer.stop()
    closed = []
    paused = threading.Event()
    if action == "toggle_play":
        paused.set()
    viewer.player = SimpleNamespace(
        close=lambda: closed.append(True),
        paused=paused,
        position=SimpleNamespace(value=96000),
        poll=lambda: None,
    )
    getattr(viewer, action)()
    assert closed == [True]
    assert viewer.player is None
    assert "AI Assistant" in viewer.status.text()
    if action == "toggle_play":
        assert paused.is_set(), "The guarded Play action must not resume paused audio."
    viewer.close()


def quiet_session(app):
    import numpy as np

    from voiceloop.audio import SAMPLE_RATE

    app.engine.state, app.engine.recording, app.engine.duration = "running", True, 31
    app.engine.activity.update(np.zeros((SAMPLE_RATE * 31, 2)))


def test_quiet_prompt_decline_snoozes_and_route_only_never_prompts(app):
    from PySide6.QtWidgets import QMessageBox

    quiet_session(app)
    app.engine.recording = False
    app.tick()
    assert app.silence_prompt is None
    app.engine.recording = True
    app.tick()
    prompt = app.silence_prompt
    assert prompt is not None
    app.tick()
    assert app.silence_prompt is prompt
    prompt.button(QMessageBox.StandardButton.No).click()
    assert app.silence_prompt is None and app.engine.state == "running"
    assert not app.engine._trim_silence
    app.engine.duration = 60.9
    app.tick()
    assert app.silence_prompt is None
    app.engine.duration = 61
    app.tick()
    assert app.silence_prompt is not None
    app.stop_session()
    assert app.silence_prompt is None


def test_quiet_prompt_accepts_stop_and_trim(app):
    from PySide6.QtWidgets import QMessageBox

    quiet_session(app)
    app.tick()
    app.silence_prompt.button(QMessageBox.StandardButton.Yes).click()
    assert app.silence_prompt is None
    assert app.engine.state == "stopping"
    assert app.engine._trim_silence


def test_resuming_speaker_activity_dismisses_prompt(app):
    import numpy as np

    quiet_session(app)
    app.tick()
    assert app.silence_prompt is not None
    app.engine.activity.update(np.full((960, 2), 0.1))
    app.tick()
    assert app.silence_prompt is None
    assert app.engine.state == "running" and not app.engine._trim_silence


def test_tray_icon_follows_activity_mute_and_off(app):
    from voiceloop.desktop import enable_desktop, update_tray_status

    enable_desktop(app, register_startup=False, assistant_control=False)
    app.tray_timer.stop()
    icons = [app.tray.icon().cacheKey()]
    assert app.tray_state == "off"
    app.engine.state = "running"
    update_tray_status(app)
    icons.append(app.tray.icon().cacheKey())
    assert app.tray_state == "active" and "Routing" in app.tray.toolTip()
    app.engine.set_muted(True)
    update_tray_status(app)
    icons.append(app.tray.icon().cacheKey())
    assert app.tray_state == "muted" and "Mic muted" in app.tray.toolTip()
    assert len(set(icons)) == 3
    app.engine.state = "idle"
    update_tray_status(app)
    assert app.tray.icon().cacheKey() == icons[0]
    assert app.tray.toolTip() == "Voice Loop · Off"
    app.closing = True
