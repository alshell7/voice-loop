from dataclasses import replace
from datetime import timedelta

import pytest
from test_assistant import CHAT, event, summarized_call, waiting
from test_assistant import service as service
from test_browser_bridge import poll

from voiceloop.assistant_store import AssistantStore
from voiceloop.browser_bridge import BrowserBridge


def hangups(service):
    return [c for c in service.test_bridge.commands if c["action"] == "hangup"]


def cancelled_before_call_identity(service):
    job, worker = waiting(service)
    service.test_bridge.cancel_command = lambda _command: "ambiguous"
    service.cancel(job["id"])
    worker.result = {"reason": "cancelled", "transcript": []}
    worker.events.append({"type": "completed"})
    service.tick()
    assert not service.active and not hangups(service)
    return job


def test_meet_hangup_uses_actual_bridge_provider_contract(service, tmp_path):
    bridge = BrowserBridge(tmp_path / "real-bridge-token", port=0)
    bridge.start()
    try:
        assert poll(bridge, "work")[0] == 200
        service.bridge_provider = lambda: bridge
        job = {
            "profile_id": "work",
            "provider": "google_meet",
            "call_id": "meet-call-1",
            "chat_id": "",
            "chat_url": "https://meet.google.com/abc-defg-hij",
            "error": "",
        }
        service._hangup(job)
        assert job["error"] == ""
        command = poll(bridge, "work")[1]["commands"][0]
        assert command["provider"] == "google_meet"
        assert command["call_id"] == "meet-call-1" and command["profile_id"] == "work"
        assert command["chat_url"] == command["chat_id"] == ""
    finally:
        bridge.stop()


def test_late_leased_call_result_is_ended_after_cancelled_worker_finishes(service):
    job = cancelled_before_call_identity(service)
    service.test_bridge.results.append(
        {"command_id": job["command_id"], "status": "succeeded", "call_id": "late-call"}
    )
    service.tick()
    assert len(hangups(service)) == 1
    assert hangups(service)[0]["call_id"] == "late-call"
    assert hangups(service)[0]["chat_url"] == CHAT
    assert service.store.get(job["id"])["state"] == "cancelled"


def test_late_correlated_event_is_ended_even_if_command_result_was_lost(service):
    job = cancelled_before_call_identity(service)
    connected = event(service, call_id="late-call", command_id=job["command_id"])
    assert service.handle_event(connected)
    assert service.handle_event(connected)
    assert len(hangups(service)) == 1
    assert hangups(service)[0]["call_id"] == "late-call"


@pytest.mark.parametrize("mismatch", ["profile", "chat", "command"])
def test_late_event_cleanup_never_targets_an_unrelated_call(service, mismatch):
    job = cancelled_before_call_identity(service)
    patches = {
        "profile": {"profile": "another-profile"},
        "chat": {"chat_id": "999"},
        "command": {"command_id": "unrelated-command"},
    }
    args = {"call_id": "unrelated-call", "command_id": job["command_id"], **patches[mismatch]}
    assert not service.handle_event(event(service, **args))
    assert not hangups(service)


def test_late_command_result_cannot_replace_a_known_call_identity(service):
    job, worker = waiting(service)
    service.handle_event(event(service, command_id=job["command_id"], call_id="owned-call"))
    service.cancel(job["id"])
    worker.events.append({"type": "completed"})
    service.tick()
    service.test_bridge.results.append(
        {"command_id": job["command_id"], "status": "succeeded", "call_id": "unrelated-call"}
    )
    service.tick()
    assert service.store.get(job["id"])["call_id"] == "owned-call"
    assert [c["call_id"] for c in hangups(service)] == ["owned-call"]


@pytest.mark.parametrize("initial_state", ["dialing", "connected"])
@pytest.mark.parametrize("later_state", ["connected", "ended"])
def test_correlated_event_cannot_replace_a_known_call_identity(service, initial_state, later_state):
    job, worker = waiting(service)
    service.handle_event(
        event(service, initial_state, command_id=job["command_id"], call_id="owned-call")
    )
    activated = worker.activated
    assert not service.handle_event(
        event(service, later_state, command_id=job["command_id"], call_id="unrelated-call")
    )
    saved = service.store.get(job["id"])
    assert saved["call_id"] == "owned-call"
    assert not saved.get("browser_ended")
    assert worker.activated == activated
    worker.events.append({"type": "completed"})
    service.tick()
    assert [c["call_id"] for c in hangups(service)] == ["owned-call"]


@pytest.mark.parametrize("initial_state", ["dialing", "connected"])
def test_unpairing_stops_owned_worker_without_confirming_call_end(service, initial_state):
    job, worker = waiting(service)
    service.handle_event(event(service, initial_state, command_id=job["command_id"]))
    service.save_config(
        replace(
            service.config,
            automation_enabled=True,
            targets=[replace(service.config.targets[0], send_summary=True)],
        )
    )
    service.summary_factory = lambda *_args, **_kwargs: pytest.fail("Summary after unpairing")
    disconnected = replace(
        event(service, "ended", command_id=job["command_id"]), event_id="unpaired-123"
    )
    assert service.handle_event(disconnected)
    assert worker.stopped
    saved = service.store.get(job["id"])
    assert not saved.get("browser_ended")
    assert saved["browser_state"] == "disconnected"
    assert "Chrome" in saved["error"]
    assert ("work", "zoho_cliq", "call-a") not in service._ended_calls
    worker.result = {"transcript": [{"role": "user", "text": "Test audio."}]}
    worker.events.append({"type": "completed"})
    service.tick()
    assert service.store.get(job["id"])["delivery_status"] == "disabled"
    assert not [c for c in service.test_bridge.commands if c["action"] == "send_summary"]


def test_unpairing_does_not_release_pending_summary_or_stop_an_unrelated_call(service):
    job = summarized_call(service)
    disconnected = replace(
        event(service, "ended", command_id=job["command_id"]), event_id="unpaired-123"
    )
    assert service.handle_event(disconnected)
    service.tick()
    assert not service.store.get(job["id"]).get("browser_ended")
    assert not [c for c in service.test_bridge.commands if c["action"] == "send_summary"]
    assert job["id"] not in service._summaries


def test_unpair_event_with_reused_command_cannot_stop_another_call(service):
    job, worker = waiting(service)
    service.handle_event(event(service, command_id=job["command_id"], call_id="owned-call"))
    unrelated = replace(
        event(service, "ended", call_id="unrelated-call", command_id=job["command_id"]),
        event_id="unpaired-123",
    )
    assert not service.handle_event(unrelated)
    assert not worker.stopped
    assert service.store.get(job["id"])["call_id"] == "owned-call"


def test_second_browser_call_stops_audio_and_ends_only_owned_call(service):
    job, worker = waiting(service)
    service.handle_event(event(service, command_id=job["command_id"], call_id="owned-call"))
    assert not service.handle_event(event(service, chat_id="999", call_id="manual-call"))
    assert worker.stopped
    assert [c["call_id"] for c in hangups(service)] == ["owned-call"]
    assert "Another browser call" in service.store.get(job["id"])["error"]


def test_close_persists_finished_worker_transcript_without_summary_side_effect(service):
    service.save_config(
        replace(
            service.config,
            automation_enabled=True,
            targets=[replace(service.config.targets[0], send_summary=True)],
        )
    )
    service.summary_factory = lambda *_args, **_kwargs: pytest.fail("Summary started during close")
    job, worker = waiting(service)
    service.handle_event(event(service, command_id=job["command_id"]))
    worker.result = {
        "reason": "cancelled",
        "transcript": [{"role": "user", "text": "Audio works."}],
    }
    service.close()
    store = AssistantStore(service.directory / "assistant-jobs.sqlite3")
    try:
        saved = store.get(job["id"])
        assert saved["state"] == "cancelled"
        assert saved["transcript"][0]["text"] == "Audio works."
        assert saved["transcript_path"].endswith("transcript.json")
        assert saved["delivery_status"] != "generating"
    finally:
        store.close()


def test_shutdown_preserves_schedules_and_prevents_new_work(service):
    future = service.schedule("456", "Later", service.test_clock[0] + timedelta(minutes=5))
    queued = service.trigger("456", "Now")
    service.begin_shutdown()
    assert service.shutdown_ready()
    service.tick()
    assert not service.test_workers and not service.test_bridge.commands
    assert service.store.get(future["id"])["state"] == "scheduled"
    assert service.store.get(queued["id"])["state"] == "queued"
    with pytest.raises(ValueError, match="shutting down"):
        service.trigger("456", "Another")
    with pytest.raises(ValueError, match="shutting down"):
        service.schedule("456", "Another", service.test_clock[0] + timedelta(minutes=6))


def test_shutdown_waits_for_leased_call_result_and_exact_hangup(service):
    job, worker = waiting(service)
    service.test_bridge.cancel_command = lambda _: "ambiguous"
    service.begin_shutdown()
    assert not service.shutdown_ready()
    worker.events.append({"type": "completed"})
    service.tick()
    assert not service.shutdown_ready()
    service.test_bridge.results.append(
        {"command_id": job["command_id"], "status": "succeeded", "call_id": "late-call"}
    )
    service.tick()
    assert not service.shutdown_ready()
    service.test_bridge.results.append(
        {
            "command_id": hangups(service)[0]["command_id"],
            "status": "succeeded",
            "call_id": "late-call",
        }
    )
    service.tick()
    assert service.shutdown_ready()


def test_shutdown_is_ready_after_undelivered_call_is_cancelled(service):
    _, worker = waiting(service)
    service.test_bridge.cancel_command = lambda _: "cancelled"
    service.begin_shutdown()
    worker.events.append({"type": "completed"})
    service.tick()
    assert service.shutdown_ready() and not hangups(service)


def test_shutdown_does_not_deliver_a_completed_summary(service):
    job = summarized_call(service)
    service.begin_shutdown()
    service.handle_event(event(service, "ended", command_id=job["command_id"]))
    service.tick()
    assert not [c for c in service.test_bridge.commands if c["action"] == "send_summary"]
