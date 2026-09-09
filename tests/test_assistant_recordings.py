"""Automation consumes existing transcripts without network, audio, or browser actions."""

from concurrent.futures import Future
from dataclasses import replace

import pytest
from test_assistant import CHAT, event
from test_assistant import service as service

from voiceloop.config import atomic_json


@pytest.fixture
def automated(service, monkeypatch):
    service.save_config(
        replace(
            service.config,
            automation_enabled=True,
            targets=[replace(service.config.targets[0], send_summary=True)],
        )
    )
    submitted = []

    def submit(function, *args, **kwargs):
        future = Future()
        submitted.append((future, function, args, kwargs))
        return future

    monkeypatch.setattr(service._pool, "submit", submit)
    service.summary_factory = lambda *_args, **_kwargs: "Synthetic summary"
    service.test_summary_submissions = submitted
    return service


def recording(service, *, metadata=None, status="complete", transcript=True, segments=None):
    directory = service.directory / "recordings" / "closed-browser-call"
    details = {
        "tool": "Zoho Cliq",
        "recording_trigger": "browser_auto_record",
        "browser_profile_id": "work",
        "browser_call_id": "recorded-call",
        "browser_chat_id": "456",
        "browser_chat_url": CHAT,
        "browser_url": CHAT,
    }
    info = {
        "schema_version": 1,
        "status": status,
        "started_at": "2026-09-09T09:00:00+00:00",
        "ended_at": "2026-09-09T09:01:00+00:00",
        "metadata": details if metadata is None else metadata,
    }
    atomic_json(directory / "session.json", info)
    if transcript:
        atomic_json(
            directory / "transcript.json",
            {
                "schema_version": 1,
                "provider": "synthetic-test",
                "metadata": info["metadata"],
                "segments": segments
                if segments is not None
                else [{"speaker": "Remote", "text": "I can confirm the audio is clear."}],
            },
        )
    return directory, details


def ended(service, **patch):
    service.handle_event(replace(event(service, "ended", call_id="recorded-call"), **patch))


def messages(service):
    return [c for c in service.test_bridge.commands if c["action"] == "send_summary"]


def finish_summary(service):
    service.test_summary_submissions[-1][0].set_result("Audio was clear. No follow-up requested.")
    service.tick()


def test_completed_transcript_sends_once_to_its_exact_original_chat(automated):
    directory, _ = recording(automated)
    ended(automated)
    automated.recording_transcribed(directory)
    assert len(automated.test_summary_submissions) == 1
    args = automated.test_summary_submissions[0][2]
    assert args[1] == [{"role": "user", "text": "Remote: I can confirm the audio is clear."}]
    automated.recording_transcribed(directory / ".")
    assert len(automated.test_summary_submissions) == 1
    finish_summary(automated)
    assert len(messages(automated)) == 1
    message = messages(automated)[0]
    assert (message["profile_id"], message["chat_id"], message["chat_url"]) == ("work", "456", CHAT)
    assert "Audio was clear" in message["text"]
    automated.recording_transcribed(directory)
    automated.tick()
    assert len(messages(automated)) == 1


@pytest.mark.parametrize(
    "setting", ["automation_enabled", "runtime_enabled", "target_enabled", "send_summary"]
)
def test_disabled_recording_automation_never_submits_summary(automated, setting):
    directory, _ = recording(automated)
    ended(automated)
    if setting == "runtime_enabled":
        automated.runtime_enabled = False
    elif setting == "automation_enabled":
        automated.save_config(replace(automated.config, automation_enabled=False))
    else:
        field = "enabled" if setting == "target_enabled" else "send_summary"
        automated.save_config(
            replace(
                automated.config, targets=[replace(automated.config.targets[0], **{field: False})]
            )
        )
    automated.recording_transcribed(directory)
    assert not automated.test_summary_submissions and not messages(automated)


@pytest.mark.parametrize("status", ["recording", "interrupted", "unknown", ""])
def test_only_complete_recordings_can_generate_automation(automated, status):
    directory, _ = recording(automated, status=status)
    ended(automated)
    automated.recording_transcribed(directory)
    assert not automated.test_summary_submissions and not messages(automated)


@pytest.mark.parametrize("field", ["browser_profile_id", "browser_chat_url", "browser_call_id"])
def test_missing_browser_identity_never_infers_target_from_generic_metadata(automated, field):
    directory, metadata = recording(automated)
    metadata.pop(field)
    directory, _ = recording(automated, metadata=metadata)
    ended(automated)
    automated.recording_transcribed(directory)
    assert not automated.test_summary_submissions


def test_generic_recording_and_missing_transcript_are_ignored(automated):
    directory, _ = recording(
        automated, metadata={"tool": "Zoho Cliq", "contact": "Alex"}, transcript=False
    )
    automated.recording_transcribed(directory)
    directory, _ = recording(automated, transcript=False)
    automated.recording_transcribed(directory)
    assert not automated.test_summary_submissions and not messages(automated)


def test_conflicting_chat_id_metadata_is_rejected(automated):
    _, metadata = recording(automated)
    metadata["browser_chat_id"] = "99999"
    directory, _ = recording(automated, metadata=metadata)
    ended(automated)
    automated.recording_transcribed(directory)
    assert not automated.test_summary_submissions and not messages(automated)


def test_changed_profile_before_transcription_or_delivery_never_sends(automated):
    directory, _ = recording(automated)
    ended(automated)
    automated.test_bridge.connected_profiles.append(
        {"profile_id": "personal", "capabilities": ["call-control-v1"]}
    )
    automated.save_config(replace(automated.config, profile_id="personal"))
    automated.recording_transcribed(directory)
    assert not automated.test_summary_submissions
    automated.save_config(replace(automated.config, profile_id="work"))
    automated.recording_transcribed(directory)
    automated.save_config(replace(automated.config, profile_id="personal"))
    finish_summary(automated)
    assert not messages(automated)


@pytest.mark.parametrize("active_call", [False, True])
def test_active_or_unconfirmed_call_holds_summary_until_its_own_ended_event(automated, active_call):
    directory, _ = recording(automated)
    if active_call:
        automated.handle_event(event(automated, call_id="recorded-call"))
    automated.recording_transcribed(directory)
    finish_summary(automated)
    assert not messages(automated)
    ended(automated, profile_id="other-profile")
    automated.tick()
    assert not messages(automated)
    ended(automated)
    automated.tick()
    assert len(messages(automated)) == 1


@pytest.mark.parametrize(
    "bad_file,bad_value",
    [
        ("session.json", []),
        ("session.json", {"status": "complete", "metadata": []}),
        ("transcript.json", []),
        ("transcript.json", {"segments": [42]}),
    ],
)
def test_malformed_recording_or_transcript_fails_closed_without_crashing(
    automated, bad_file, bad_value
):
    directory, _ = recording(automated)
    atomic_json(directory / bad_file, bad_value)
    ended(automated)
    automated.recording_transcribed(directory)
    assert not automated.test_summary_submissions and not messages(automated)
