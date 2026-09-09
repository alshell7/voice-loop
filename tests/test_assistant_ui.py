"""Exercise real Qt controls without browsers, audio streams, or API calls."""

import json
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDateTime
from PySide6.QtGui import QPalette

from voiceloop.assistant_config import AssistantSettings, ChatTarget
from voiceloop.assistant_ui import (
    AssistantHistoryDialog,
    AssistantPage,
    AutomationPage,
    render_assistant_job,
)
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


def test_visible_contact_actions_create_edit_delete(page, qt):
    assert page.add_contact_shortcut.isVisible()
    page.add_contact_shortcut.click()
    qt.processEvents()
    assert page.contact_dialog.isVisible()
    page.contact_name.setText("New contact")
    page.contact_url.setText("https://cliq.zoho.com/company/123/chats/789")
    page.save_contact_button.click()
    assert not page.contact_dialog.isVisible()
    assert page.service.config.cliq_company_id == "123"
    assert page.target.currentData() == "789"
    page.tabs.setCurrentIndex(2)
    page.contacts.selectRow(1)
    assert page.edit_contact_button.isEnabled() and page.remove_contact.isEnabled()
    page.edit_contact_button.click()
    assert page.contact_dialog.isVisible() and page.contact_name.text() == "New contact"
    page.contact_name.setText("Renamed contact")
    page.save_contact_button.click()
    assert page.service.config.target("789").name == "Renamed contact"
    page.contacts.selectRow(1)
    page.remove_contact.click()
    assert page.service.config.target("789") is None


def test_numeric_contact_id_uses_separate_workspace(page):
    page.company_id.setText("123")
    page.cliq_origin.setCurrentIndex(page.cliq_origin.findData("https://cliq.zoho.eu"))
    page.save_workspace()
    page.contact_name.setText("Regional contact")
    page.contact_url.setText("789")
    page.save_contact()
    assert page.service.config.target("789").url == "https://cliq.zoho.eu/company/123/chats/789"


@pytest.mark.parametrize("suffix", ["", "/"])
def test_edit_existing_contact_keeps_its_url_after_workspace_change(page, suffix):
    original_url = page.service.config.target("456").url
    page.company_id.setText("999")
    page.cliq_origin.setCurrentIndex(page.cliq_origin.findData("https://cliq.zoho.eu"))
    page.save_workspace()
    page.contacts.selectRow(0)
    page.edit_contact_button.click()
    page.contact_url.setText(original_url + suffix)
    page.contact_name.setText("Renamed original contact")
    page.contact_incoming.setChecked(True)
    page.contact_summary.setChecked(True)
    page.save_contact_button.click()
    target = page.service.config.target("456")
    assert target.name == "Renamed original contact"
    assert target.allow_incoming and target.send_summary
    assert target.url == original_url
    assert page.service.config.cliq_company_id == "999"
    assert page.service.config.cliq_origin == "https://cliq.zoho.eu"

    # Reusing this editor for a different old-workspace URL cannot bypass scope validation.
    page.contacts.selectRow(0)
    page.edit_contact_button.click()
    page.contact_url.setText("https://cliq.zoho.com/company/123/chats/789")
    page.save_contact_button.click()
    assert page.service.config.target("789") is None
    assert page.service.config.target("456").url == original_url
    assert "different Cliq company or region" in page.contact_notice.text()


def test_unmatched_typed_contact_cannot_call_previous_selection(page):
    page.objective.setPlainText("Confirm the appointment.")
    page.target.setEditText("Al")
    assert not page.call_now.isEnabled()
    page.trigger()
    assert not page.service.calls
    page.target.completer().setCompletionPrefix("le")
    assert page.target.completer().completionCount() == 1
    page.target.setEditText("alex")
    assert page.call_now.isEnabled()
    page.trigger()
    assert page.service.calls[0][0] == "456"


def test_call_picker_and_completion_have_light_readable_palette(page):
    for popup in (page.target.view(), page.target.completer().popup()):
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            assert popup.palette().color(group, QPalette.ColorRole.Base).name() == "#ffffff"
            assert popup.palette().color(group, QPalette.ColorRole.Text).name() == "#20242d"


def test_duplicate_contact_names_are_distinguishable(page):
    page.service.config.targets.append(
        ChatTarget.from_url("Alex", "https://cliq.zoho.com/company/123/chats/789")
    )
    page.refresh()
    assert page.target.itemText(0) != page.target.itemText(1)
    page.target.setEditText("Alex")
    page.objective.setPlainText("Confirm the appointment.")
    page.trigger()
    assert not page.service.calls


def test_language_accepts_custom_and_follow_caller(page):
    page.language.setEditText("Malayalam")
    page.save_settings()
    assert page.service.config.language == "Malayalam"
    page.language.setCurrentIndex(page.language.findData("auto"))
    page.save_settings()
    assert page.service.config.language == "auto"


def test_busy_fallback_setting_is_opt_in_and_independent_of_summaries(page):
    assert not page.busy_fallback_enabled.isChecked()
    assert not page.service.config.busy_fallback_enabled
    page.busy_fallback_enabled.setChecked(True)
    page.save_settings()
    assert page.service.config.busy_fallback_enabled
    assert not page.service.config.automation_enabled
    automation = AutomationPage(page.service)
    automation.enabled.setChecked(True)
    automation.save_settings()
    assert page.service.config.busy_fallback_enabled
    page.busy_fallback_enabled.setChecked(False)
    page.save_settings()
    assert not page.service.config.busy_fallback_enabled
    assert page.service.config.automation_enabled
    automation.deleteLater()


def test_busy_fallback_history_renders_message_without_inventing_conversation(page):
    job = {
        "id": "busy-call",
        "target_name": "Alex",
        "state": "failed",
        "objective": "Confirm tomorrow’s appointment.",
        "delivery_kind": "busy_fallback",
        "delivery_status": "sent",
        "fallback_reason": "Recipient is on another call <busy>",
        "fallback_text": "Reminder: confirm the appointment.\n<img src=https://invalid>",
        "transcript": [],
    }
    page.service.jobs = [job]
    page.refresh()
    assert page.history.item(0, 1).text() == "Recipient busy"
    assert page.history.item(0, 2).text() == "Sent to chat"
    assert "Busy fallback message" in page.reader.toPlainText()
    assert "Message delivery" in page.reader.toPlainText()
    assert "Summary delivery" not in page.reader.toPlainText()
    assert "A transcript appears here" not in page.reader.toPlainText()
    rendered = render_assistant_job(job)
    assert "<img" not in rendered and "&lt;img" in rendered
    assert "&lt;busy&gt;" in rendered
    dialog = AssistantHistoryDialog(job)
    assert dialog.tabs.tabText(0) == "Busy fallback message"
    assert json.loads(dialog.json.toPlainText())["fallback_text"] == job["fallback_text"]
    dialog.deleteLater()


def test_automation_history_distinguishes_busy_messages_and_summaries(page):
    page.service.jobs = [
        {
            "id": "busy",
            "state": "failed",
            "delivery_kind": "busy_fallback",
            "delivery_status": "sent",
            "fallback_text": "A brief reminder.",
        },
        {
            "id": "summary",
            "state": "completed",
            "delivery_status": "sent",
            "summary": "Appointment confirmed.",
        },
    ]
    automation = AutomationPage(page.service)
    assert automation.history.rowCount() == 2
    assert automation.history.item(0, 3).text() == "Busy fallback"
    assert automation.history.item(1, 3).text() == "Call summary"
    assert "A brief reminder." in automation.reader.toPlainText()
    assert not automation.enabled.isChecked()
    automation.deleteLater()


def test_history_paging_search_and_open_callback(page):
    opened = []
    page.on_open_history = opened.append
    page.service.jobs = [
        {
            "id": f"job-{index}",
            "target_name": f"Contact {index}",
            "state": "completed",
            "delivery_status": "sent",
            "summary": f"Outcome {index}",
        }
        for index in range(26)
    ]
    page.refresh()
    assert page.history.rowCount() == 10
    assert "1 / 3" in page.history_pager.info.text()
    assert page.history.item(0, 2).text() == "Sent to chat"
    page.history_pager.next.click()
    assert page._jobs[0]["id"] == "job-10"
    page.open_history_button.click()
    assert opened[0]["id"] == "job-10"
    page.history.selectRow(1)
    page.history.itemClicked.emit(page.history.item(1, 0))
    assert opened[-1]["id"] == "job-11"
    page.history_pager.next.click()
    assert page.history.rowCount() == 6 and not page.history_pager.next.isEnabled()
    page.history_pager.query.setText("Outcome 25")
    assert page.history_pager.page == 1 and page.history.rowCount() == 1
    assert page._jobs[0]["id"] == "job-25"


def test_server_pagination_does_not_limit_history_to_snapshot(page):
    requests = []

    def list_jobs(**options):
        requests.append(options)
        return {
            "items": [{"id": "older", "target_name": "Older call"}],
            "total": 251,
            "pages": 26,
            "page": options["page"],
        }

    page.service.list_jobs = list_jobs
    page.refresh()
    page.history_pager.next.click()
    assert requests[-1] == {"kind": None, "query": "", "page": 2, "page_size": 10}
    assert "2 / 26" in page.history_pager.info.text()
    assert page._jobs[0]["id"] == "older"


def test_automation_excludes_unrequested_summaries_and_opens_history(page):
    opened = []
    page.service.jobs = [
        {"id": "no-summary", "delivery_status": "not_requested", "state": "completed"},
        {"id": "sent", "delivery_status": "sent", "summary": "Brief result"},
        {"id": "unknown", "delivery_status": "ambiguous", "summary": "Check delivery"},
    ]
    automation = AutomationPage(page.service, on_open_history=opened.append)
    assert automation.history.rowCount() == 2
    assert automation.history.item(0, 1).text() == "Sent to chat"
    assert automation.history.item(1, 1).text() == "Delivery unconfirmed"
    automation.history.selectRow(1)
    assert "Check the chat before sending again" in automation.reader.toPlainText()
    automation.open_history_button.click()
    assert opened[0]["id"] == "unknown"
    automation.deleteLater()


def test_assistant_viewer_displays_escaped_html_and_complete_json(qt):
    job = {
        "id": "job",
        "target_name": "<script>",
        "state": "completed",
        "transcript": [{"role": "user", "text": "مرحبا <img src=https://invalid>"}],
    }
    dialog = AssistantHistoryDialog(job)
    assert json.loads(dialog.json.toPlainText()) == job
    assert "<img src=https://invalid>" in dialog.reader.toPlainText()
    assert "مرحبا" in dialog.reader.toPlainText()
    assert not dialog.reader.openLinks() and not dialog.reader.openExternalLinks()
    dialog.deleteLater()
