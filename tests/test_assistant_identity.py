"""Incoming caller identity uses learned IDs, never display names or open chats."""

from dataclasses import replace

import pytest
from test_assistant import CHAT, event, waiting
from test_assistant import service as service

from voiceloop.assistant_store import AssistantStore

PARTICIPANT = "111222333"
SCOPE = "work|cliq.zoho.com"


def incoming(service, **patch):
    return replace(
        event(service, "ringing", direction="incoming"),
        chat_id="",
        chat_url="",
        url=CHAT,
        participant_id=PARTICIPANT,
        **patch,
    )


def test_correlated_connected_outbound_call_learns_durable_participant_identity(service):
    job, _ = waiting(service)
    service.handle_event(
        replace(event(service, command_id=job["command_id"]), participant_id=PARTICIPANT)
    )
    assert service.store.resolve(SCOPE, PARTICIPANT) == CHAT
    # The identity table survives a new reader/process; no browser action occurs.
    other = AssistantStore(service.directory / "assistant-jobs.sqlite3")
    try:
        assert other.resolve(SCOPE, PARTICIPANT) == CHAT
    finally:
        other.close()


@pytest.mark.parametrize(
    "mismatch", ["profile", "command", "chat", "not_connected", "incoming_direction"]
)
def test_unmatched_or_non_outbound_event_cannot_teach_a_contact(service, mismatch):
    job, _ = waiting(service)
    current = replace(event(service, command_id=job["command_id"]), participant_id=PARTICIPANT)
    patches = {
        "profile": {"profile_id": "personal"},
        "command": {"command_id": "unrelated-command"},
        "chat": {"chat_url": "https://cliq.zoho.com/company/123/chats/999"},
        "not_connected": {"state": "dialing"},
        "incoming_direction": {"direction": "incoming"},
    }
    service.handle_event(replace(current, **patches[mismatch]))
    assert not service.store.resolve(SCOPE, PARTICIPANT)


def test_learned_identity_allows_only_exact_profile_host_and_participant(service):
    service.store.learn(SCOPE, PARTICIPANT, CHAT)
    assert service.event_chat_url(incoming(service)) == CHAT
    for patch in (
        {"profile_id": "personal"},
        {"participant_id": "999999999"},
        {"url": "https://cliq.zoho.eu/company/123/chats/456"},
    ):
        # replace separately so the helper's intentional default identity stays clear.
        assert not service.event_chat_url(replace(incoming(service), **patch))


def test_ambiguous_mapping_and_missing_identity_never_fall_back_to_open_chat(service):
    service.save_config(replace(service.config, auto_answer=True))
    unknown = incoming(service)
    assert not service.event_chat_url(unknown)
    assert not service.handle_event(unknown)
    service.store.learn(SCOPE, PARTICIPANT, CHAT)
    service.store.learn(SCOPE, PARTICIPANT, "https://cliq.zoho.com/company/123/chats/999")
    assert not service.event_chat_url(unknown)
    assert not service.handle_event(unknown)
    assert not service.test_workers and not service.test_bridge.commands


def test_unambiguous_learned_caller_is_answered_with_native_participant_id(service):
    service.save_config(replace(service.config, auto_answer=True))
    service.store.learn(SCOPE, PARTICIPANT, CHAT)
    assert service.handle_event(incoming(service))
    worker = service.test_workers[-1]
    assert not worker.activated and not service.test_bridge.commands
    worker.events.append({"type": "ready"})
    service.tick()
    command = service.test_bridge.commands[0]
    assert command["action"] == "answer"
    assert (
        command["profile_id"],
        command["chat_id"],
        command["chat_url"],
        command["participant_id"],
    ) == ("work", "456", CHAT, PARTICIPANT)


def test_meet_retains_joined_meeting_url_without_cliq_identity(service):
    meet = replace(
        event(service, provider="google_meet"),
        url="https://meet.google.com/abc-defg-hij",
        chat_url="",
        chat_id="",
    )
    assert service.event_chat_url(meet) == "https://meet.google.com/abc-defg-hij"
