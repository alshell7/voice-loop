"""Exercise real Qt controls without browsers, audio streams, or API calls."""

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDateTime

from voiceloop.assistant_config import AssistantSettings, ChatTarget
from voiceloop.assistant_ui import AssistantPage, AutomationPage, render_assistant_job
from voiceloop.ui import create_application


class Service:
    def __init__(self):
        self.config = AssistantSettings(
            enabled=True,
            targets=[ChatTarget.from_url("Alex", "https://cliq.zoho.com/company/123/chats/456")],
        )
        self.calls = []
        self.schedules = []
        self.cancelled = []
        self.jobs = []
        self.prerequisites = {"browser": True, "audio": True, "key": True}

    def save_config(self, config):
        self.config = config

    def trigger(self, target_id, objective):
        self.calls.append((target_id, objective))

    def schedule(self, target_id, objective, when):
        self.schedules.append((target_id, objective, when))

    def cancel(self, job_id):
        self.cancelled.append(job_id)

    def snapshot(self):
        return {
            "prerequisites": self.prerequisites,
            "jobs": self.jobs,
            "profiles": [
                {"profile_id": "profile-a", "name": "Work"},
                {"profile_id": "profile-b", "name": "Personal"},
            ],
        }


@pytest.fixture(scope="module")
def qt():
    return create_application()


@pytest.fixture
def page(qt):
    page = AssistantPage(Service())
    page.resize(850, 780)
    page.show()
    qt.processEvents()
    yield page
    page.close()
    page.deleteLater()
    qt.processEvents()


def test_call_validation_and_exact_contact(page):
    page.trigger()
    assert not page.service.calls
    assert "objective" in page.notice.text()
    page.objective.setPlainText("Confirm the appointment time.")
    page.trigger()
    assert page.service.calls == [("456", "Confirm the appointment time.")]


def test_schedule_uses_aware_time_and_rejects_past(page):
    page.objective.setPlainText("A reminder.")
    page.when.setDateTime(QDateTime.currentDateTime().addSecs(-60))
    page.schedule()
    assert not page.service.schedules
    page.when.setDateTime(QDateTime.currentDateTime().addSecs(120))
    page.schedule()
    assert page.service.schedules[0][2].tzinfo is not None


def test_config_pages_preserve_each_others_fields(page):
    page.service.config = replace(page.service.config, automation_enabled=True)
    page.model.setCurrentText("gpt-realtime")
    page.profile.setCurrentIndex(page.profile.findData("profile-b"))
    page.save_settings()
    assert page.service.config.automation_enabled
    assert page.service.config.profile_id == "profile-b"
    automation = AutomationPage(page.service)
    automation.enabled.setChecked(False)
    automation.save_settings()
    assert page.service.config.enabled and page.service.config.profile_id == "profile-b"
    assert not page.service.config.automation_enabled
    automation.deleteLater()


def test_add_contact_rejects_foreign_url_and_defaults_safe(page):
    page.contact_name.setText("Other")
    page.contact_url.setText("https://example.com/chats/456")
    page.save_contact()
    assert len(page.service.config.targets) == 1
    page.contact_url.setText("https://cliq.zoho.eu/company/123/chats/789")
    page.save_contact()
    target = page.service.config.target("789")
    assert target and not target.allow_incoming and not target.send_summary
    assert page.target.count() == 2


def test_prerequisites_disable_calls_and_multiple_profiles_not_guessed(page):
    assert page.profile.currentData() == ""
    page.service.prerequisites["audio"] = False
    page.refresh()
    assert not page.call_now.isEnabled()
    assert "virtual audio bridge" in page.status.text()


def test_history_cancel_and_escaped_reader(page):
    page.service.jobs = [
        {
            "id": "job-a",
            "target_name": "Alex <script>",
            "state": "active",
            "transcript": [{"role": "assistant", "text": "<img src=https://evil>"}],
        }
    ]
    page.refresh()
    assert page.cancel_button.isEnabled()
    page.cancel()
    assert page.service.cancelled == ["job-a"]
    assert "<img src=https://evil>" in page.reader.toPlainText()
    rendered = render_assistant_job(page.service.jobs[0])
    assert "<script>" not in rendered and "<img" not in rendered
    assert "&lt;script&gt;" in rendered
