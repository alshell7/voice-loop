from dataclasses import replace
from datetime import UTC, datetime

import pytest

from voiceloop.call_detection import CallController, CallEvent


def payload(**changes):
    result = {
        "version": 1,
        "event_id": "event-1",
        "call_id": "call-1",
        "provider": "zoho_cliq",
        "state": "ringing",
        "direction": "incoming",
        "contact": {"name": "Example Contact", "email": "example@example.com"},
        "title": "Weekly review",
        "url": "https://cliq.zoho.com/",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return result | changes


def event(state="connected", **changes):
    return CallEvent.from_payload(payload(state=state, **changes))


def kinds(actions):
    return [action.kind for action in actions]


def test_payload_preserves_contact_direction_and_title():
    call = event("dialing", direction="outgoing")
    assert call.tool_name == "Zoho Cliq"
    assert call.contact_name == "Example Contact"
    assert call.contact_email == "example@example.com"
    assert call.title == "Weekly review"
    assert call.direction == "outgoing"
    meeting = event(provider="google_meet", url="https://meet.google.com/abc-defg-hij", contact={})
    assert meeting.display_name == "Weekly review"
    assert meeting.tool_name == "Google Meet"


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 2},
        {"provider": "zoom"},
        {"provider": []},
        {"state": "open"},
        {"state": {}},
        {"direction": []},
        {"event_id": "has spaces"},
        {"call_id": ""},
        {"contact": "name"},
        {"contact": {"name": "line\nbreak"}},
        {"contact": {"email": "x" * 321}},
        {"title": "x" * 513},
        {"url": "http://cliq.zoho.com/"},
        {"url": "https://cliq.zoho.com.attacker.test/"},
        {"url": "https://user:password@cliq.zoho.com/"},
        {"timestamp": "2026-09-08T12:00:00"},
        {"timestamp": "not a date"},
    ],
)
def test_invalid_payload_is_rejected(change):
    with pytest.raises(ValueError):
        CallEvent.from_payload(payload(**change))


def test_replayed_and_future_payloads_are_rejected():
    value = payload(timestamp="2026-09-08T12:00:00Z")
    stamp = datetime(2026, 9, 8, 12, tzinfo=UTC).timestamp()
    assert CallEvent.from_payload(value, now=stamp + 119)
    for current in (stamp + 121, stamp - 31):
        with pytest.raises(ValueError):
            CallEvent.from_payload(value, now=current)


@pytest.mark.parametrize("initial,direction", [("ringing", "incoming"), ("dialing", "outgoing")])
def test_auto_record_waits_for_attendance_and_ends_owned_session(initial, direction):
    controller = CallController(auto_record=True)
    ringing = event(initial, direction=direction)
    assert kinds(controller.handle(ringing, now=0)) == ["feedback"]
    connected = replace(
        ringing, event_id="connected", state="connected", timestamp=ringing.timestamp + 1
    )
    assert kinds(controller.handle(connected, now=1)) == ["feedback", "start_recording"]
    assert controller.owned_call_id == ringing.call_id
    ended = replace(connected, event_id="ended", state="ended", timestamp=connected.timestamp + 1)
    assert kinds(controller.handle(ended, session_active=True, now=2)) == [
        "stop_recording",
        "feedback",
    ]
    assert controller.owned_call_id is None


def test_unanswered_call_never_prompts_or_records():
    controller = CallController()
    ringing = event("ringing")
    assert kinds(controller.handle(ringing)) == ["feedback"]
    ended = replace(ringing, event_id="ended", state="ended", timestamp=ringing.timestamp + 1)
    assert kinds(controller.handle(ended)) == ["feedback"]


def test_prompt_acceptance_starts_once_and_decline_suppresses_all_heartbeats():
    controller = CallController()
    connected = event()
    assert kinds(controller.handle(connected)) == ["feedback", "prompt_record"]
    assert kinds(controller.respond(connected.call_id, False)) == ["dismiss_prompt", "feedback"]
    assert controller.handle(replace(connected, event_id="heartbeat")) == []
    assert controller.respond(connected.call_id, True) == []
    next_call = replace(connected, call_id="next", event_id="new-call")
    controller.handle(replace(connected, event_id="ended", state="ended"))
    assert "prompt_record" in kinds(controller.handle(next_call))
    assert kinds(controller.respond("next", True)) == ["dismiss_prompt", "start_recording"]
    assert controller.respond("next", True) == []


def test_ended_call_closes_prompt_and_cannot_be_accepted_or_replayed():
    controller = CallController()
    connected = event()
    controller.handle(connected)
    ended = replace(connected, event_id="ended", state="ended", timestamp=connected.timestamp + 1)
    assert kinds(controller.handle(ended)) == ["dismiss_prompt", "feedback"]
    assert controller.respond(connected.call_id, True) == []
    assert (
        controller.handle(replace(connected, event_id="late", timestamp=ended.timestamp + 1)) == []
    )


def test_manual_session_is_never_stopped_or_taken_over():
    controller = CallController(auto_record=True)
    connected = event()
    assert "start_recording" not in kinds(controller.handle(connected, session_active=True))
    assert controller.handle(replace(connected, event_id="heartbeat"), session_active=False) == []
    assert "stop_recording" not in kinds(
        controller.handle(replace(connected, event_id="end", state="ended"), session_active=True)
    )


def test_manual_stop_and_start_failure_suppress_repeated_auto_record():
    controller = CallController(auto_record=True)
    connected = event()
    controller.handle(connected)
    assert kinds(controller.session_stopped()) == ["feedback"]
    assert controller.handle(replace(connected, event_id="heartbeat")) == []
    controller.reset()
    controller.handle(connected)
    assert kinds(controller.recording_failed(connected.call_id)) == ["feedback"]
    assert controller.owned_call_id is None
    assert controller.handle(replace(connected, event_id="heartbeat")) == []


def test_new_manual_session_between_prompt_and_accept_does_not_get_taken_over():
    controller = CallController()
    connected = event()
    controller.handle(connected)
    assert "start_recording" not in kinds(
        controller.respond(connected.call_id, True, session_active=True)
    )
    assert controller.owned_call_id is None


def test_overlapping_calls_cannot_stop_another_owned_call():
    controller = CallController(auto_record=True)
    first = event()
    controller.handle(first, now=0)
    other = replace(first, call_id="other", event_id="other")
    assert controller.handle(other, session_active=True, now=1) == []
    assert controller.handle(replace(other, event_id="other-ended", state="ended"), now=2) == []
    assert controller.owned_call_id == first.call_id
    assert controller.active_event == first
    assert "stop_recording" in kinds(controller.reset())


def test_heartbeat_timeout_stops_only_owned_session_and_rejects_resurrection():
    controller = CallController(auto_record=True)
    connected = event()
    controller.handle(connected, now=10)
    assert controller.tick(now=54) == []
    heartbeat = replace(connected, event_id="heartbeat", timestamp=connected.timestamp + 10)
    assert controller.handle(heartbeat, session_active=True, now=20) == []
    assert controller.tick(now=64) == []
    assert kinds(controller.tick(now=65)) == ["stop_recording", "feedback"]
    assert controller.handle(replace(heartbeat, event_id="late"), now=66) == []
    manual = CallController(auto_record=True)
    manual.handle(connected, session_active=True, now=0)
    assert "stop_recording" not in kinds(manual.tick(now=46))


def test_duplicates_out_of_order_and_connected_to_ringing_regression_are_ignored():
    controller = CallController(auto_record=True)
    connected = event()
    controller.handle(connected, now=0)
    assert controller.handle(connected, now=30) == []
    assert (
        controller.handle(
            replace(connected, event_id="old", state="ended", timestamp=connected.timestamp - 1),
            now=31,
        )
        == []
    )
    assert (
        controller.handle(
            replace(
                connected, event_id="ringing", state="ringing", timestamp=connected.timestamp + 1
            ),
            now=32,
        )
        == []
    )
    assert "stop_recording" in kinds(controller.tick(now=45))


def test_reset_dismisses_prompt_without_stopping_manual_audio():
    controller = CallController()
    controller.handle(event())
    assert kinds(controller.reset()) == ["dismiss_prompt", "feedback"]
    assert controller.active_event is None
    assert controller.owned_call_id is None


def test_call_memory_is_bounded_and_live_owner_survives_many_new_calls():
    controller = CallController(auto_record=True)
    first = event()
    controller.handle(first, now=0)
    for index in range(1100):
        controller.handle(replace(first, event_id=f"e{index}", call_id=f"c{index}"), now=1)
    assert controller.owned_call_id == first.call_id
    assert len(controller._calls) == 64
    assert len(controller._seen) == 1024
