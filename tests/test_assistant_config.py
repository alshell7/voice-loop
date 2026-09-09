"""Assistant configuration is an authorization boundary, including time and URL scope."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from voiceloop.assistant_config import AssistantSettings, ChatTarget, parse_target_url

CHAT = "https://cliq.zoho.com/company/123/chats/456"


@pytest.mark.parametrize("suffix", ("com", "eu", "in", "com.au", "jp", "ca", "com.cn", "sa"))
def test_cliq_region_and_exact_identity(suffix):
    target = ChatTarget.from_url("Alex", f"https://cliq.zoho.{suffix}/company/123/chats/456/")
    assert target.id == target.chat_id == "456"
    assert target.provider == "zoho_cliq"
    assert target.enabled and target.allow_outgoing
    assert not target.allow_incoming and not target.send_summary


@pytest.mark.parametrize(
    "url",
    (
        "http://cliq.zoho.com/company/123/chats/456",
        "https://cliq.zoho.com.evil.example/company/123/chats/456",
        "https://other.example/company/123/chats/456",
        "https://user@cliq.zoho.com/company/123/chats/456",
        "https://cliq.zoho.com:443/company/123/chats/456",
        CHAT + "?redirect=https://evil.example",
        CHAT + "#other",
        CHAT + "/extra",
        "https://cliq.zoho.com/company/123/chats/%34%35%36",
        "https://meet.google.com/lookup/secret",
        "https://meet.google.com/abc-defg-hij?authuser=1",
    ),
)
def test_call_target_rejects_ambiguous_links(url):
    with pytest.raises(ValueError):
        parse_target_url(url)


def test_meet_scope_and_forged_target_id():
    target = ChatTarget.from_url("Standup", "https://meet.google.com/abc-defg-hij")
    assert target.id == "abc-defg-hij" and target.chat_id == ""
    assert target.provider == "google_meet"
    with pytest.raises(ValueError, match="match"):
        ChatTarget("different", "Alex", CHAT)


def test_save_round_trip_has_no_secret_field(tmp_path):
    path = tmp_path / "assistant.json"
    config = AssistantSettings(enabled=True, targets=[ChatTarget.from_url("Alex", CHAT)])
    config.save(path)
    loaded = AssistantSettings.load(path)
    assert loaded == config
    assert loaded.target("456").name == "Alex"
    raw = json.loads(path.read_text())
    assert not {"api_key", "key", "token"} & raw.keys()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "value",
    (
        {"enabled": "false"},
        {"enabled": True, "auto_answer": 1},
        {"enabled": True, "targets": [{}]},
        {"version": 2, "enabled": True},
        {"enabled": True, "timezone": "not/a/timezone"},
        {"enabled": True, "work_days": [True]},
        {"enabled": True, "targets": "all"},
        {"enabled": True, "max_duration_seconds": 900},
    ),
)
def test_invalid_persisted_policies_fail_closed(tmp_path, value):
    path = tmp_path / "assistant.json"
    path.write_text(json.dumps(value))
    config = AssistantSettings.load(path)
    assert not config.enabled and not config.auto_answer and not config.targets


def test_duplicate_chats_rejected():
    target = ChatTarget.from_url("Alex", CHAT)
    with pytest.raises(ValueError, match="once"):
        AssistantSettings(targets=[target, target]).validate()


def test_working_hours_timezone_and_boundaries():
    config = AssistantSettings(timezone="Asia/Kolkata", availability="inside_hours").validate()
    assert not config.permits(datetime(2026, 9, 7, 3, 29, tzinfo=UTC))
    assert config.permits(datetime(2026, 9, 7, 3, 30, tzinfo=UTC))
    assert not config.permits(datetime(2026, 9, 7, 12, 30, tzinfo=UTC))
    assert not config.permits(datetime(2026, 9, 6, 5, tzinfo=UTC))
    with pytest.raises(ValueError, match="aware"):
        config.permits(datetime(2026, 9, 7, 10))


def test_overnight_shift_belongs_to_start_day():
    config = AssistantSettings(work_days=(4,), work_start="22:00", work_end="06:00")
    assert config.within_working_hours(datetime(2026, 9, 11, 23, tzinfo=UTC))
    assert config.within_working_hours(datetime(2026, 9, 12, 5, 59, tzinfo=UTC))
    assert not config.within_working_hours(datetime(2026, 9, 12, 6, tzinfo=UTC))
    assert not config.within_working_hours(datetime(2026, 9, 11, 5, tzinfo=UTC))


def test_dst_timezone_and_busy_policy():
    config = AssistantSettings(timezone="America/New_York", work_days=tuple(range(7)))
    assert config.within_working_hours(datetime(2026, 7, 6, 13, tzinfo=UTC))
    assert not config.within_working_hours(datetime(2026, 1, 5, 13, tzinfo=UTC))
    now = datetime.now(UTC)
    assert not replace(config, availability="busy").permits(now)
    assert replace(config, availability="busy", busy=True).permits(now)
