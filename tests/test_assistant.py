"""Exercise call authorization and durable orchestration without network or audio."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from voiceloop.assistant import AssistantService
from voiceloop.assistant_config import AssistantSettings, ChatTarget
from voiceloop.assistant_store import AssistantStore
from voiceloop.call_detection import CallEvent

CHAT = "https://cliq.zoho.com/company/123/chats/456"


class FakeBridge:
    def __init__(self):
        self.is_running = True
        self.connected_profiles = [{"profile_id": "work", "capabilities": ["call-control-v1"]}]
        self.commands = []
        self.results = []
        self.cancelled = []

    def profiles(self):
        return self.connected_profiles

    def submit_command(self, action, **kwargs):
        command = {"action": action, "command_id": f"command-{len(self.commands)}", **kwargs}
        self.commands.append(command)
        return command["command_id"]

    def cancel_command(self, command_id):
        self.cancelled.append(command_id)

    def drain_results(self):
        results, self.results = self.results, []
        return results


class FakeAudio:
    def stop(self):
        pass


def test_unexpected_preflight_failure_is_not_retried_or_exposed(service):
    attempts = []

    def broken_audio():
        attempts.append(1)
        raise AttributeError("private implementation detail")

    service.audio_factory = broken_audio
    job = service.trigger("456", "Confirm audio")
    service.tick()
    service.tick()
    assert attempts == [1]
    stored = service.store.get(job["id"])
    assert stored["state"] == "failed"
    assert "private implementation" not in stored["error"]
    assert not service.test_bridge.commands


class FakeWorker:
    def __init__(self, key, config, audio):
        self.config = config
        self.audio = audio
        self.started = False
        self.activated = 0
        self.stopped = False
        self.events = []
        self.result = {}

    def start(self):
        self.started = True

    def activate(self):
        self.activated += 1

    def stop(self):
        self.stopped = True

    def join(self, timeout):
        pass

    def drain_events(self):
        events, self.events = self.events, []
        return events


@pytest.fixture
def service(tmp_path):
    bridge = FakeBridge()
    workers = []
    clock = [datetime(2026, 9, 9, 10, tzinfo=UTC)]

    def factory(*args):
        worker = FakeWorker(*args)
        workers.append(worker)
        return worker

    config = AssistantSettings(
        enabled=True,
        default_objective="Confirm the test audio works, then thank the person.",
        targets=[ChatTarget.from_url("Alex", CHAT, allow_incoming=True)],
    )
    result = AssistantService(
        bridge_provider=lambda: bridge,
        audio_factory=FakeAudio,
        config=config,
        directory=tmp_path,
        key_provider=lambda: "test-credential",
        worker_factory=factory,
        now=lambda: clock[0],
    )
    result.runtime_enabled = True
    result.test_bridge = bridge
    result.test_workers = workers
    result.test_clock = clock
    yield result
    bridge.is_running = True
    result.close()


def event(
    service,
    state="connected",
    *,
    profile="work",
    chat_id="456",
    call_id="call-a",
    direction="outgoing",
    command_id="",
    provider="zoho_cliq",
):
    url = f"https://cliq.zoho.com/company/123/chats/{chat_id}"
    return CallEvent(
        event_id="event-" + state,
        call_id=call_id,
        provider=provider,
        state=state,
        direction=direction,
        contact_name="Alex",
        contact_email="",
        title="Call",
        url="https://cliq.zoho.com/",
        timestamp=service.test_clock[0].timestamp(),
        profile_id=profile,
        chat_id=chat_id,
        chat_url=url,
        command_id=command_id,
    )


def prepared(service):
    job = service.trigger("456", "Run a short audio test.")
    service.tick()
    return job, service.test_workers[-1]


def waiting(service):
    job, worker = prepared(service)
    worker.events.append({"type": "ready"})
    service.tick()
    return service.store.get(job["id"]), worker


def test_no_call_or_audio_activation_before_sdk_ready_and_call_connected(service):
    job, worker = prepared(service)
    assert worker.started and not worker.activated
    assert not service.test_bridge.commands
    worker.events.append({"type": "ready"})
    service.tick()
    assert service.test_bridge.commands[0]["action"] == "call"
    assert not worker.activated
    job = service.store.get(job["id"])
    assert service.handle_event(event(service, command_id=job["command_id"]))
    assert worker.activated == 1
    assert service.store.get(job["id"])["state"] == "active"


def test_repeated_connected_heartbeats_do_not_activate_twice(service):
    job, worker = waiting(service)
    connected = event(service, command_id=job["command_id"])
    assert service.handle_event(connected)
    assert service.handle_event(connected)
    assert worker.activated == 1


def test_profile_selection_never_guesses_between_accounts(service):
    service.test_bridge.connected_profiles.append(
        {"profile_id": "personal", "capabilities": ["call-control-v1"]}
    )
    with pytest.raises(ValueError, match="profile"):
        service.trigger("456", "A reminder.")
    service.save_config(replace(service.config, profile_id="work"))
    job = service.trigger("456", "A reminder.")
    assert job["profile_id"] == "work"


def test_wrong_profile_cannot_connect_the_pending_call(service):
    job, worker = waiting(service)
    assert not service.handle_event(
        event(service, profile="personal", command_id=job["command_id"])
    )
    assert not worker.activated


def test_wrong_chat_cannot_connect_the_pending_call(service):
    job, worker = waiting(service)
    assert not service.handle_event(event(service, chat_id="999", command_id=job["command_id"]))
    assert not worker.activated


def test_double_click_cannot_queue_two_immediate_calls(service):
    service.trigger("456", "A reminder.")
    with pytest.raises(ValueError):
        service.trigger("456", "A reminder.")


@pytest.mark.parametrize("change", ("disabled", "target", "platform", "hours"))
def test_policy_is_rechecked_after_realtime_preparation(service, change):
    _, worker = prepared(service)
    changes = {
        "disabled": {"enabled": False},
        "target": {"targets": [replace(service.config.targets[0], enabled=False)]},
        "platform": {"platforms": ()},
        "hours": {"availability": "busy", "busy": False},
    }
    service.save_config(replace(service.config, **changes[change]))
    worker.events.append({"type": "ready"})
    service.tick()
    assert not [command for command in service.test_bridge.commands if command["action"] == "call"]
    assert not worker.activated


def test_missing_key_fails_before_any_call_side_effect(service):
    service.key_provider = lambda: ""
    job = service.trigger("456", "A reminder.")
    service.tick()
    assert service.store.get(job["id"])["state"] == "failed"
    assert not service.test_workers and not service.test_bridge.commands


def test_manual_audio_session_blocks_assistant(service):
    service.audio_busy = lambda: True
    with pytest.raises(ValueError, match="session"):
        service.trigger("456", "A reminder.")
    assert not service.test_workers


def test_expired_schedule_is_not_called_after_sleep(service):
    job = service.schedule("456", "A reminder.", service.test_clock[0] + timedelta(minutes=10))
    service.test_clock[0] += timedelta(minutes=20)
    service.tick()
    assert service.store.get(job["id"])["state"] == "expired"
    assert not service.test_workers and not service.test_bridge.commands


def test_schedule_stays_pending_until_due_and_can_be_cancelled(service):
    job = service.schedule("456", "A reminder.", service.test_clock[0] + timedelta(minutes=10))
    service.tick()
    assert service.store.get(job["id"])["state"] == "scheduled"
    service.cancel(job["id"])
    service.test_clock[0] += timedelta(minutes=10)
    service.tick()
    assert service.store.get(job["id"])["state"] == "cancelled"
    assert not service.test_workers


def test_incoming_connecting_during_preparation_is_not_answered_twice(service):
    service.save_config(replace(service.config, auto_answer=True))
    assert service.handle_event(event(service, "ringing", direction="incoming"))
    worker = service.test_workers[-1]
    assert service.handle_event(event(service, "connected", direction="incoming"))
    worker.events.append({"type": "ready"})
    service.tick()
    assert worker.activated == 1
    assert not [
        command for command in service.test_bridge.commands if command["action"] == "answer"
    ]


def test_incoming_ended_during_preparation_does_not_answer(service):
    service.save_config(replace(service.config, auto_answer=True))
    assert service.handle_event(event(service, "ringing", direction="incoming"))
    worker = service.test_workers[-1]
    assert service.handle_event(event(service, "ended", direction="incoming"))
    worker.events.append({"type": "ready"})
    service.tick()
    assert worker.stopped and not worker.activated
    assert not service.test_bridge.commands


def test_cancelled_call_cannot_reactivate_from_late_connected_event(service):
    job, worker = waiting(service)
    service.cancel(job["id"])
    service.handle_event(event(service, command_id=job["command_id"]))
    assert not worker.activated
    assert worker.stopped


def test_disabled_automatic_behavior_ignores_incoming(service):
    assert not service.handle_event(event(service, "ringing", direction="incoming"))
    assert not service.test_workers and not service.test_bridge.commands


def test_restart_never_retries_an_uncertain_browser_action(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    store = AssistantStore(path)
    store.put({"id": "uncertain-call", "state": "waiting", "delivery_status": "not_requested"})
    store.put({"id": "uncertain-send", "state": "completed", "delivery_status": "sending"})
    store.close()
    reopened = AssistantStore(path)
    assert reopened.get("uncertain-call")["state"] == "interrupted"
    assert reopened.get("uncertain-send")["delivery_status"] in ("interrupted", "ambiguous")
    reopened.close()


def test_another_call_starting_during_preparation_blocks_dialing(service):
    _, worker = prepared(service)
    service.handle_event(event(service, call_id="other-call", chat_id="999"))
    worker.events.append({"type": "ready"})
    service.tick()
    assert not [command for command in service.test_bridge.commands if command["action"] == "call"]
    assert worker.stopped and not worker.activated


def test_browser_bridge_stopping_ends_active_assistant_audio(service):
    job, worker = waiting(service)
    service.handle_event(event(service, command_id=job["command_id"]))
    service.test_bridge.is_running = False
    service.tick()
    assert worker.stopped


def test_cancel_succeeds_while_browser_is_offline(service):
    job, worker = waiting(service)
    service.test_bridge.is_running = False
    service.cancel(job["id"])
    assert worker.stopped
    assert service.store.get(job["id"])["state"] == "cancelled"


def summarized_call(service):
    service.save_config(
        replace(
            service.config,
            automation_enabled=True,
            targets=[replace(service.config.targets[0], send_summary=True)],
        )
    )
    service.summary_factory = lambda *_args, **_kwargs: "Audio confirmed. No follow-up needed."
    job, worker = waiting(service)
    service.handle_event(event(service, command_id=job["command_id"]))
    worker.result = {"transcript": [{"role": "user", "text": "Yes, I can hear you."}]}
    worker.events.append({"type": "completed"})
    service.tick()
    service._summaries[job["id"]].result(timeout=1)
    return service.store.get(job["id"])


def test_summary_waits_for_browser_end_and_sends_to_exact_original_chat(service):
    job = summarized_call(service)
    assert not [
        command for command in service.test_bridge.commands if command["action"] == "send_summary"
    ]
    service.handle_event(event(service, "ended", command_id=job["command_id"]))
    service.tick()
    messages = [
        command for command in service.test_bridge.commands if command["action"] == "send_summary"
    ]
    assert len(messages) == 1
    assert messages[0]["chat_id"] == "456" and messages[0]["chat_url"] == CHAT
    assert messages[0]["profile_id"] == "work"
    service.tick()
    assert (
        len(
            [
                command
                for command in service.test_bridge.commands
                if command["action"] == "send_summary"
            ]
        )
        == 1
    )


def test_summary_opt_out_before_delivery_prevents_message(service):
    job = summarized_call(service)
    service.save_config(replace(service.config, automation_enabled=False))
    service.handle_event(event(service, "ended", command_id=job["command_id"]))
    service.tick()
    assert not [
        command for command in service.test_bridge.commands if command["action"] == "send_summary"
    ]
    assert service.store.get(job["id"])["delivery_status"] == "disabled"


def test_summary_never_posts_when_call_end_remains_uncertain(service):
    job = summarized_call(service)
    service.test_clock[0] += timedelta(seconds=61)
    service.tick()
    assert not [
        command for command in service.test_bridge.commands if command["action"] == "send_summary"
    ]
    assert service.store.get(job["id"])["delivery_status"] == "failed"


def test_automatic_answering_revoked_during_preparation_does_not_answer(service):
    service.save_config(replace(service.config, auto_answer=True))
    service.handle_event(event(service, "ringing", direction="incoming"))
    worker = service.test_workers[-1]
    service.save_config(replace(service.config, auto_answer=False))
    worker.events.append({"type": "ready"})
    service.tick()
    assert not service.test_bridge.commands
    assert worker.stopped and not worker.activated


def test_automatic_outgoing_assistance_revoked_during_preparation_does_not_speak(service):
    service.save_config(replace(service.config, auto_assist_outgoing=True))
    service.handle_event(event(service, "connected"))
    worker = service.test_workers[-1]
    service.save_config(replace(service.config, auto_assist_outgoing=False))
    worker.events.append({"type": "ready"})
    service.tick()
    assert worker.stopped and not worker.activated
