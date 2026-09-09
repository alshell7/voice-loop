"""Company-scoped explicit calls never grant automatic incoming-call permission."""

import json
from dataclasses import asdict, replace
from datetime import timedelta

import pytest
from test_assistant import CHAT, event
from test_assistant import service as service

from voiceloop.assistant_config import AssistantSettings, ChatTarget

NEW_CHAT = "https://cliq.zoho.com/company/123/chats/987654321"


def configure(service, **changes):
    service.save_config(replace(service.config, cliq_company_id="123", **changes))


def legacy(*urls):
    return {
        "enabled": True,
        "targets": [asdict(ChatTarget.from_url("Contact", url)) for url in urls],
    }


def test_legacy_single_company_migrates_its_region_without_widening_permissions(tmp_path):
    original = legacy(
        "https://cliq.zoho.eu/company/123/chats/456",
        "https://cliq.zoho.eu/company/123/chats/789",
        "https://meet.google.com/abc-defg-hij",
    )
    path = tmp_path / "assistant.json"
    path.write_text(json.dumps(original), encoding="utf-8")
    migrated = AssistantSettings.load(path)
    assert migrated.cliq_company_id == "123"
    assert migrated.cliq_origin == "https://cliq.zoho.eu"
    assert migrated.language == "English"
    assert not migrated.auto_answer
    assert all(not target.allow_incoming and not target.send_summary for target in migrated.targets)
    migrated.save(path)
    assert AssistantSettings.load(path) == migrated


@pytest.mark.parametrize(
    "other",
    ["https://cliq.zoho.com/company/999/chats/789", "https://cliq.zoho.in/company/123/chats/789"],
)
def test_legacy_multiple_scopes_require_explicit_company_selection(other):
    config = AssistantSettings.from_dict(legacy(CHAT, other))
    assert config.cliq_company_id == ""
    with pytest.raises(ValueError, match="company ID"):
        config.make_cliq_target("New Contact", "987654321")


def test_explicit_empty_company_is_not_silently_migrated_from_old_contacts():
    config = AssistantSettings.from_dict({**legacy(CHAT), "cliq_company_id": ""})
    assert config.cliq_company_id == ""


def test_numeric_contact_uses_configured_region_and_full_link_can_initialize_it():
    config = AssistantSettings(cliq_company_id="123", cliq_origin="https://cliq.zoho.in/")
    target = config.make_cliq_target("Contact", "987654321")
    assert target.url == "https://cliq.zoho.in/company/123/chats/987654321"
    assert target.company_id == "123"
    first = AssistantSettings()
    target = first.make_cliq_target("Contact", "https://cliq.zoho.eu/company/777/chats/12345")
    assert first.cliq_company_id == "777" and first.cliq_origin == "https://cliq.zoho.eu"
    assert not target.allow_incoming and not target.send_summary


@pytest.mark.parametrize(
    "changes",
    [
        {"cliq_company_id": "12/34"},
        {"cliq_company_id": 123},
        {"cliq_origin": "https://cliq.zoho.com.evil.example"},
        {"cliq_origin": "https://user@cliq.zoho.com"},
        {"cliq_origin": "https://cliq.zoho.com:443"},
        {"cliq_origin": "https://cliq.zoho.com/company/123"},
        {"language": "English\nNew line"},
        {"language": "x" * 81},
    ],
)
def test_invalid_company_origin_or_language_fails_closed_when_loaded(tmp_path, changes):
    path = tmp_path / "assistant.json"
    path.write_text(json.dumps({"enabled": True, "auto_answer": True, **changes}))
    loaded = AssistantSettings.load(path)
    assert not loaded.enabled and not loaded.auto_answer


@pytest.mark.parametrize("value", ["987654321", NEW_CHAT + "/"])
def test_explicit_new_chat_is_persisted_with_outgoing_only_permissions(service, value):
    configure(service)
    job = service.trigger(value, "Confirm the appointment.", contact_name="  Zoë Ahmed  ")
    target = AssistantSettings.load(service.config_path).target("987654321")
    assert target.name == "Zoë Ahmed" and target.url == NEW_CHAT
    assert target.enabled and target.allow_outgoing
    assert not target.allow_incoming and not target.send_summary
    assert job["target_name"] == "Zoë Ahmed" and job["chat_url"] == NEW_CHAT
    assert job["profile_id"] == "work" and job["state"] == "queued"
    assert not service.test_workers and not service.test_bridge.commands


def test_explicit_full_link_sets_company_only_after_valid_request(service):
    assert not service.config.cliq_company_id
    job = service.trigger(NEW_CHAT, "Confirm the appointment.")
    loaded = AssistantSettings.load(service.config_path)
    assert loaded.cliq_company_id == "123"
    assert loaded.target(job["target_id"]).url == NEW_CHAT


@pytest.mark.parametrize("value", ["456", CHAT, CHAT + "/"])
@pytest.mark.parametrize("permission", ["enabled", "allow_outgoing"])
def test_existing_contact_cannot_bypass_disabled_policy_by_using_a_link(service, value, permission):
    configure(service, targets=[replace(service.config.targets[0], **{permission: False})])
    original = service.config_path.read_bytes()
    with pytest.raises(ValueError):
        service.trigger(value, "A reminder.", contact_name="Replacement name")
    assert service.config_path.read_bytes() == original
    assert service.config.target("456").name == "Alex"
    assert not service.store.list() and not service.test_bridge.commands


@pytest.mark.parametrize(
    "url",
    [
        "https://cliq.zoho.com/company/999/chats/987654321",
        "https://cliq.zoho.in/company/123/chats/987654321",
    ],
)
def test_new_chat_cannot_escape_the_configured_company_or_region(service, url):
    configure(service)
    original = service.config_path.read_bytes()
    with pytest.raises(ValueError, match="different Cliq company or region"):
        service.trigger(url, "A reminder.")
    assert service.config_path.read_bytes() == original
    assert not service.store.list()


@pytest.mark.parametrize(
    "failure", ["objective", "profile", "audio", "platform", "availability", "shutdown"]
)
def test_failed_request_does_not_persist_new_contact_or_inferred_company(service, failure):
    service.save_config(service.config)
    objective = "A reminder."
    if failure == "objective":
        objective = " "
    elif failure == "profile":
        service.test_bridge.connected_profiles = []
    elif failure == "audio":
        service.audio_busy = lambda: True
    elif failure == "platform":
        service.save_config(replace(service.config, platforms=()))
    elif failure == "availability":
        service.save_config(replace(service.config, availability="busy", busy=False))
    else:
        service.begin_shutdown()
    original = service.config_path.read_bytes()
    with pytest.raises(ValueError):
        service.trigger(NEW_CHAT, objective, contact_name="New Contact")
    assert service.config_path.read_bytes() == original
    assert not service.config.cliq_company_id
    assert service.config.target("987654321") is None
    assert not service.store.list() and not service.test_bridge.commands


def test_new_outgoing_contact_does_not_auto_answer_incoming_after_cancellation(service):
    configure(service, auto_answer=True)
    job = service.trigger("987654321", "A reminder.")
    service.cancel(job["id"])
    assert not service.handle_event(
        event(service, "ringing", direction="incoming", chat_id="987654321")
    )
    assert not service.test_workers and not service.test_bridge.commands


def test_selected_language_model_voice_and_instructions_reach_the_worker(service):
    configure(
        service,
        language="Marathi",
        model="gpt-realtime",
        voice="cedar",
        system_instructions="Use short sentences.",
    )
    service.trigger("987654321", "Confirm the appointment.")
    service.tick()
    config = service.test_workers[0].config
    assert config.language == "Marathi" and config.voice == "cedar"
    assert config.model == "gpt-realtime" and config.instructions == "Use short sentences."
    assert config.objective == "Confirm the appointment."
    assert not service.test_bridge.commands


@pytest.mark.parametrize("policy", ["platform", "working_hours", "disabled_contact"])
def test_scheduling_enforces_platform_future_availability_and_existing_contact_policy(
    service, policy
):
    changes = {
        "platform": {"platforms": ()},
        "working_hours": {
            "availability": "inside_hours",
            "work_start": "12:00",
            "work_end": "18:00",
        },
        "disabled_contact": {"targets": [replace(service.config.targets[0], allow_outgoing=False)]},
    }
    configure(service, **changes[policy])
    original = service.config_path.read_bytes()
    value = CHAT if policy == "disabled_contact" else NEW_CHAT
    with pytest.raises(ValueError):
        service.schedule(value, "A reminder.", service.test_clock[0] + timedelta(minutes=10))
    assert service.config_path.read_bytes() == original
    assert not service.store.list()


def test_schedule_uses_future_working_hours_and_persists_only_outgoing_permission(service):
    configure(service, availability="inside_hours", work_start="12:00", work_end="18:00")
    when = service.test_clock[0] + timedelta(hours=3)
    job = service.schedule("987654321", "A reminder.", when, contact_name="New Contact")
    assert job["state"] == "scheduled" and job["scheduled_at"] == when.isoformat()
    assert not AssistantSettings.load(service.config_path).target("987654321").allow_incoming
    service.tick()
    assert not service.test_workers and not service.test_bridge.commands


@pytest.mark.parametrize("when_delta", [timedelta(days=-1), timedelta(days=367)])
def test_invalid_schedule_time_does_not_add_contact(service, when_delta):
    configure(service)
    original = service.config_path.read_bytes()
    with pytest.raises(ValueError):
        service.schedule(NEW_CHAT, "A reminder.", service.test_clock[0] + when_delta)
    assert service.config_path.read_bytes() == original
    assert service.config.target("987654321") is None
