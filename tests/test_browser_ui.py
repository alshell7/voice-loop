"""Browser lifecycle through actual Qt controls, without audio or network access."""

import os
import time
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox
from test_setup import hardware

from voiceloop.call_detection import CallEvent
from voiceloop.config import Settings, atomic_json
from voiceloop.library import Contacts
from voiceloop.ui import App, ConsentDialog, create_application


class FakeBridge:
    pairing_token = "synthetic-test-pairing-code"

    def __init__(self):
        self.events = []
        self.started = self.stopped = False

    def drain(self, limit=64):
        events, self.events = self.events[:limit], self.events[limit:]
        return events

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture(scope="module")
def qt():
    return create_application()


@pytest.fixture
def app(qt, tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self: None)
    window = App(
        settings=Settings(recording_directory=str(tmp_path), browser_detection_enabled=True),
        device_provider=lambda: hardware(True),
        contacts=Contacts(tmp_path / "contacts.json"),
        browser_bridge=FakeBridge(),
    )
    window.timer.stop()
    window.test_starts = []
    window.test_stops = []

    def start(config, root, **options):
        window.test_starts.append(options)
        window.engine.saved_path = None
        window.engine.state = "running"
        window.engine.recording = options["record"]

    def stop(**options):
        window.test_stops.append(options)
        window.engine.state = "idle"
        window.engine.recording = False

    monkeypatch.setattr(window.engine, "start", start)
    monkeypatch.setattr(window.engine, "stop", stop)
    yield window
    window.closing = True
    window.engine.state = "idle"
    window.close()
    qt.processEvents()


def event(state="connected", *, call_id="cliq-test", direction="incoming", provider="zoho_cliq"):
    return CallEvent(
        event_id=f"{call_id}-{state}-{time.time_ns()}",
        call_id=call_id,
        provider=provider,
        state=state,
        direction=direction,
        contact_name="Synthetic Test Contact" if provider == "zoho_cliq" else "",
        contact_email="contact@example.test" if provider == "zoho_cliq" else "",
        title="A complete meeting title from Chrome",
        url="https://cliq.zoho.com/"
        if provider == "zoho_cliq"
        else "https://meet.google.com/abc-defg-hij",
        timestamp=time.time(),
    )


def deliver(app, value):
    app.browser_bridge.events.append(value)
    app.tick()


def test_browser_preferences_are_typed_and_off_by_default(tmp_path):
    path = tmp_path / "settings.json"
    atomic_json(path, {"browser_detection_enabled": "true", "browser_auto_record": 1})
    settings = Settings.load(path)
    assert settings.browser_detection_enabled is False
    assert settings.browser_auto_record is False


def test_construction_does_not_start_bridge_and_pairing_code_is_masked(app, qt):
    assert not app.browser_bridge.started
    assert app.preferences.browser_token.echoMode().name == "Password"
    app.preferences.browser_copy.click()
    assert qt.clipboard().text() == app.browser_bridge.pairing_token
    qt.clipboard().clear()
    assert app.preferences.browser_copy.text() == "Copied"


@pytest.mark.parametrize("direction,state", [("incoming", "ringing"), ("outgoing", "dialing")])
def test_unanswered_calls_never_prompt_or_record(app, direction, state):
    app.set_browser_auto_record(True)
    deliver(app, event(state, direction=direction))
    assert not app.test_starts
    assert app.browser_prompt is None
    deliver(app, event("ended", direction=direction))
    assert not app.test_starts
    assert "Call ended" in app.browser_feedback


def test_connected_call_asks_without_blocking_and_saves_full_metadata(app):
    current = replace(
        event(direction="outgoing"),
        profile_id="work",
        chat_id="456",
        chat_url="https://cliq.zoho.com/company/123/chats/456",
    )
    deliver(app, current)
    prompt = app.browser_prompt
    assert prompt is not None and prompt.isVisible()
    assert prompt.windowModality() == Qt.WindowModality.NonModal
    assert not app.test_starts
    prompt.done(QMessageBox.StandardButton.Yes)
    assert len(app.test_starts) == 1
    assert app.test_starts[0]["record"] is True
    assert app.test_starts[0]["metadata"] == {
        "tool": "Zoho Cliq",
        "contact": current.contact_name,
        "contact_email": current.contact_email,
        "meeting_title": current.title,
        "call_direction": "outgoing",
        "browser_call_id": current.call_id,
        "browser_url": current.url,
        "browser_profile_id": current.profile_id,
        "browser_chat_id": current.chat_id,
        "browser_chat_url": current.chat_url,
        "recording_trigger": "browser_prompt",
    }
    assert app.contacts.names() == [current.contact_name]
    deliver(app, event("ended"))
    assert len(app.test_stops) == 1
    assert app.browser_prompt is None
    assert app.floating.elapsed.text() == "00:00"


def test_call_ending_cancels_stale_prompt(app):
    deliver(app, event())
    prompt = app.browser_prompt
    deliver(app, event("ended"))
    assert app.browser_prompt is None
    prompt.done(QMessageBox.StandardButton.Yes)
    assert not app.test_starts


def test_decline_and_manual_stop_suppress_repeat_heartbeats(app):
    deliver(app, event())
    app.browser_prompt.done(QMessageBox.StandardButton.No)
    deliver(app, event())
    assert app.browser_prompt is None and not app.test_starts
    app.set_browser_auto_record(True)
    deliver(app, event("ended"))
    deliver(app, event(call_id="next-call"))
    assert len(app.test_starts) == 1
    app.stop_session()
    deliver(app, event(call_id="next-call"))
    assert len(app.test_starts) == 1
    assert "recording stopped" in app.browser_feedback


@pytest.mark.parametrize("record", [False, True])
def test_existing_manual_session_is_not_hijacked_or_stopped(app, record):
    app.start(record=record)
    app.set_browser_auto_record(True)
    deliver(app, event())
    assert len(app.test_starts) == 1
    assert "current session continues" in app.browser_feedback
    deliver(app, event("ended"))
    assert not app.test_stops and app.engine.active
    assert app.browser_prompt is None


def test_manually_starting_during_prompt_dismisses_it(app):
    deliver(app, event())
    app.start(record=False)
    assert app.browser_prompt is None
    deliver(app, event())
    assert len(app.test_starts) == 1
    assert app.test_starts[0]["record"] is False


def test_meet_auto_records_after_join_and_disabling_detection_finishes_it(app):
    app.set_browser_auto_record(True)
    joined = event(provider="google_meet", direction="unknown")
    deliver(app, joined)
    assert len(app.test_starts) == 1
    metadata = app.test_starts[0]["metadata"]
    assert metadata["tool"] == "Google Meet" and metadata["meeting_title"] == joined.title
    assert metadata["recording_trigger"] == "browser_auto_record"
    assert not app.contacts.names()
    bridge = app.browser_bridge
    app.preferences.browser_enabled.setChecked(False)
    assert bridge.stopped and app.browser_bridge is None
    assert len(app.test_stops) == 1
    assert not app.preferences.browser_automatic.isEnabled()


def test_connection_loss_stops_only_owned_session(app, monkeypatch):
    app.set_browser_auto_record(True)
    deliver(app, event())
    monkeypatch.setattr(app.browser_controller, "heartbeat_timeout", 0)
    app.tick()
    assert len(app.test_stops) == 1
    assert "connection lost" in app.browser_feedback


def test_floating_feedback_remains_visible_in_compact_mode(app, qt):
    app.show_floating()
    app.floating.toggle_compact()
    current = replace(event("ringing"), contact_name="<b>Synthetic contact</b>")
    deliver(app, current)
    qt.processEvents()
    assert app.floating.browser_event.isVisible()
    assert app.floating.browser_event.textFormat() == Qt.TextFormat.PlainText
    assert "<b>" in app.floating.browser_event.text()
    assert not app.floating.details.isVisible()
    assert app.floating.power.geometry().bottom() < app.floating.height()


def test_pending_call_end_prevents_device_switch_restart(app):
    from voiceloop.devices import Device

    app.set_browser_auto_record(True)
    deliver(app, event())
    app.last_state = "running"
    replacement = Device("second-mic", "Second microphone", 2)
    app.devices.inputs.append(replacement)
    app.switch_device("microphone", replacement)
    deliver(app, event("ended"))
    assert not app.pending_switch
    assert len(app.test_starts) == 1


def test_backlogged_connected_then_ended_does_not_start_late_recording(app):
    app.set_browser_auto_record(True)
    app.browser_bridge.events.extend([event(), event("ended")])
    app.tick()
    assert not app.test_starts


def test_end_after_many_queued_heartbeats_is_seen_before_starting(app):
    app.set_browser_auto_record(True)
    app.browser_bridge.events.extend([event() for _ in range(100)] + [event("ended")])
    app.tick()
    assert not app.test_starts


@pytest.mark.parametrize("next_ended", [False, True])
def test_next_call_waits_for_previous_recording_to_finish(app, monkeypatch, next_ended):
    app.set_browser_auto_record(True)
    deliver(app, event())
    monkeypatch.setattr(app.engine, "stop", lambda: setattr(app.engine, "state", "stopping"))
    deliver(app, event("ended"))
    deliver(app, event(call_id="next-call"))
    assert len(app.test_starts) == 1
    if next_ended:
        deliver(app, event("ended", call_id="next-call"))
    app.engine.state = "idle"
    app.tick()
    assert len(app.test_starts) == (1 if next_ended else 2)


def test_manual_off_invalidates_deferred_device_restart(app, qt):
    from voiceloop.devices import Device

    app.start(record=False)
    app.last_state = "running"
    replacement = Device("second-mic", "Second microphone", 2)
    app.devices.inputs.append(replacement)
    app.switch_device("microphone", replacement)
    app.tick()  # Schedules Qt's device-switch restart for the next event-loop turn.
    app.stop_session()
    qt.processEvents()
    assert len(app.test_starts) == 1


def test_completed_recording_is_handled_before_next_browser_start(app, tmp_path, monkeypatch):
    app.set_browser_auto_record(True)
    app.settings.auto_transcribe = True
    handled = []
    monkeypatch.setattr(
        app, "transcribe_directory", lambda path, **kwargs: handled.append((path, kwargs))
    )
    deliver(app, event())
    deliver(app, event("ended"))
    saved = tmp_path / "finished-recording"
    app.engine.saved_path = saved
    deliver(app, event(call_id="next-call"))
    assert handled == [(saved, {"automatic": True})]
    assert len(app.test_starts) == 2


def test_browser_session_started_during_manual_consent_keeps_ownership(app, monkeypatch):
    app.set_browser_auto_record(True)
    original_exec = ConsentDialog.exec

    def consent_with_incoming_browser_event(dialog):
        def connect_then_accept_manual_consent():
            deliver(app, event())
            dialog.choose(False)

        QTimer.singleShot(0, connect_then_accept_manual_consent)
        return original_exec(dialog)

    monkeypatch.setattr(ConsentDialog, "exec", consent_with_incoming_browser_event)
    assert app.start() is False
    assert len(app.test_starts) == 1
    assert app.test_starts[0]["record"] is True
    assert app.test_starts[0]["metadata"]["recording_trigger"] == "browser_auto_record"
    assert app.browser_controller.owned_call_id == "cliq-test"
    assert app._browser_recording_event.call_id == "cliq-test"
    deliver(app, event("ended"))
    assert len(app.test_stops) == 1
    assert not app.engine.active


def test_deferred_call_expires_during_slow_device_shutdown(app, monkeypatch):
    from types import SimpleNamespace

    import voiceloop.ui as ui

    wall_clock = time.time()
    monotonic_clock = [100.0]
    monkeypatch.setattr(
        ui,
        "time",
        SimpleNamespace(monotonic=lambda: monotonic_clock[0], time=lambda: wall_clock),
    )
    app.set_browser_auto_record(True)
    deliver(app, event())
    monkeypatch.setattr(app.engine, "stop", lambda: setattr(app.engine, "state", "stopping"))
    deliver(app, event("ended"))
    deliver(app, event(call_id="next-call"))
    assert app._browser_deferred_events
    monotonic_clock[0] += 180
    app.engine.state = "idle"
    app.tick()
    assert len(app.test_starts) == 1
    assert not app._browser_deferred_events
    assert "expired" in app.browser_feedback


def test_old_connected_event_in_bridge_queue_cannot_start_recording(app):
    app.set_browser_auto_record(True)
    deliver(app, replace(event(), timestamp=time.time() - 180))
    assert not app.test_starts
    assert app.browser_prompt is None


def test_old_ended_event_still_finishes_owned_recording(app, monkeypatch):
    from types import SimpleNamespace

    import voiceloop.ui as ui

    wall_clock = [time.time() - 240]
    monkeypatch.setattr(
        ui, "time", SimpleNamespace(monotonic=time.monotonic, time=lambda: wall_clock[0])
    )
    app.set_browser_auto_record(True)
    connected = replace(event(), timestamp=wall_clock[0])
    deliver(app, connected)
    wall_clock[0] += 240
    # Even delayed terminal evidence must finish the owned recording.
    deliver(app, replace(event("ended"), timestamp=wall_clock[0] - 180))
    assert len(app.test_stops) == 1
    assert not app.engine.active


@pytest.mark.parametrize("ended_queued", [False, True])
def test_prompt_acceptance_rechecks_browser_before_starting(app, monkeypatch, ended_queued):
    deliver(app, event())
    prompt = app.browser_prompt
    if ended_queued:
        app.browser_bridge.events.append(event("ended"))
    else:
        monkeypatch.setattr(app.browser_controller, "heartbeat_timeout", 0)
    # Simulate a queued click being handled before the regular GUI timer.
    prompt.done(QMessageBox.StandardButton.Yes)
    assert not app.test_starts
    assert app.browser_prompt is None
