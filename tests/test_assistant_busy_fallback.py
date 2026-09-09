"""Name resolution and opt-in busy messages, without calls or network access."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_assistant import service as service

from voiceloop.assistant_config import ChatTarget, RecipientResolutionError


def waiting(service, *, enabled=True):
    service.config.busy_fallback_enabled = enabled
    job = service.trigger("Alex", "Please confirm tomorrow's appointment.")
    service.tick()
    service.worker.events.append({"type": "ready"})
    service.tick()
    return service.store.get(job["id"])


def busy_result(job, **options):
    return {
        "command_id": job["command_id"],
        "status": "failed",
        "code": "recipient_busy",
        **options,
    }


def messages(service):
    return [c for c in service.test_bridge.commands if c["action"] == "send_summary"]


def test_unique_first_name_resolves_and_schedules(service):
    service.config.targets[0].name = "Alex Morgan"
    when = service.now() + timedelta(hours=3)
    job = service.schedule("  ALEX  ", "Confirm the meeting.", when)
    assert job["target_id"] == "456" and job["scheduled_at"] == when.isoformat()
    assert len(service.config.targets) == 1


def test_ambiguous_and_unknown_names_do_not_place_calls(service):
    service.config.targets[0].name = "Alex Morgan"
    service.config.targets.append(
        ChatTarget.from_url(
            "Alex Stone", "https://cliq.zoho.com/company/123/chats/789", enabled=False
        )
    )
    for name, code in (("Alex", "recipient_ambiguous"), ("Nobody", "recipient_not_found")):
        with pytest.raises(RecipientResolutionError) as error:
            service.trigger(name, "An objective")
        assert error.value.code == code
    assert not service.store.list() and not service.test_bridge.commands


def test_disabled_exact_name_is_not_bypassed(service):
    service.config.targets[0].enabled = False
    with pytest.raises(ValueError, match="disabled"):
        service.trigger("Alex", "An objective")
    assert not service.store.list()


def test_busy_fallback_sends_exact_objective_once_without_summary_opt_in(service):
    job = waiting(service)
    assert service.test_bridge.commands[-1]["busy_fallback"] is True
    assert not service.config.automation_enabled and not service.config.targets[0].send_summary
    service._command_result(busy_result(job))
    service._command_result(busy_result(job))
    assert len(messages(service)) == 1
    message = messages(service)[0]
    assert message["text"] == job["objective"]
    assert message["chat_url"] == job["chat_url"] and message["profile_id"] == job["profile_id"]
    stored = service.store.get(job["id"])
    assert stored["state"] == "failed" and stored["delivery_kind"] == "busy_fallback"
    assert stored["delivery_status"] == "sending" and service.worker.stopped
    service._command_result({"command_id": message["command_id"], "status": "succeeded"})
    assert service.store.get(job["id"])["delivery_status"] == "sent"


@pytest.mark.parametrize(
    "change",
    [
        "off",
        "revoked",
        "cancelled",
        "connected",
        "wrong_id",
        "timeout",
        "profile",
        "target",
        "shutdown",
    ],
)
def test_uncertain_busy_or_changed_policy_never_sends(service, change):
    job = waiting(service, enabled=change != "off")
    result = busy_result(job)
    if change == "revoked":
        service.config.busy_fallback_enabled = False
    elif change == "cancelled":
        service.cancel(job["id"])
    elif change == "connected":
        job["call_id"] = "connected-call"
        service.store.put(job)
    elif change == "wrong_id":
        result["command_id"] = "unrelated"
    elif change == "timeout":
        result.pop("code")
        result["detail"] = "Busy or timed out"
    elif change == "profile":
        service.config.profile_id = "different-profile"
    elif change == "target":
        service.config.targets[0] = replace(service.config.targets[0], allow_outgoing=False)
    elif change == "shutdown":
        service.begin_shutdown()
    service._command_result(result)
    assert not messages(service)


def test_uncertain_delivery_is_not_retried(service):
    job = waiting(service)
    service._command_result(busy_result(job))
    message = messages(service)[0]
    service._command_result({"command_id": message["command_id"], "status": "ambiguous"})
    service._command_result(busy_result(job))
    assert len(messages(service)) == 1
    assert service.store.get(job["id"])["delivery_status"] == "ambiguous"


def test_disabling_fallback_cancels_an_unleased_message(service):
    job = waiting(service)
    service._command_result(busy_result(job))
    service.test_bridge.cancel_command = lambda command_id: "cancelled"
    service.save_config(replace(service.config, busy_fallback_enabled=False))
    assert service.store.get(job["id"])["delivery_status"] == "disabled"
