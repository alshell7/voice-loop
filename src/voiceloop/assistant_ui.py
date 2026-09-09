"""Native AI Assistant and Automation pages, backed by an injected local service."""

from __future__ import annotations

import html
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from voiceloop.assistant_config import ChatTarget
from voiceloop.ui import card, label

EXTRA_STYLE = """
QPlainTextEdit, QDateTimeEdit, QTimeEdit, QSpinBox {
 background:#F4F5F7; border:1px solid #E5E8ED; border-radius:10px; padding:10px;
 selection-background-color:#EAF2FF; selection-color:#005BC4;
 placeholder-text-color:#626977;
}
QPlainTextEdit:focus, QDateTimeEdit:focus, QTimeEdit:focus, QSpinBox:focus {
 border:2px solid #338EF7;
}
QTabWidget::pane { border:none; background:transparent; }
QTabBar::tab { background:transparent; color:#626977; padding:12px 18px; margin-bottom:10px; }
QTabBar::tab:selected { background:#EAF2FF; color:#005BC4; border-radius:10px; }
QTabBar::tab:hover { color:#005BC4; }
QTabBar::tab:focus { border:2px solid #338EF7; border-radius:10px; }
"""


def _plain(text: str = "", name: str = "small"):
    result = label(text, name, True)
    result.setTextFormat(Qt.TextFormat.PlainText)
    return result


def _field(layout, title, widget, tooltip=""):
    caption = label(title, "fieldLabel")
    caption.setBuddy(widget)
    widget.setAccessibleName(title)
    if tooltip:
        widget.setToolTip(tooltip)
    layout.addWidget(caption)
    layout.addWidget(widget)
    return widget


def _text_edit(value, name, height=92):
    widget = QPlainTextEdit(value)
    widget.setAccessibleName(name)
    widget.setMinimumHeight(height)
    widget.setMaximumHeight(height + 40)
    widget.setTabChangesFocus(True)
    return widget


def _combo(items, current, name, editable=False):
    if editable:
        from voiceloop.ui_extras import search_combo

        result = search_combo(name, [], "Enter " + name.lower())
    else:
        result = QComboBox()
    result.setAccessibleName(name)
    result.setEditable(editable)
    result.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    for text, value in items:
        result.addItem(text, value)
    if editable:
        result.setCurrentText(current)
    else:
        result.setCurrentIndex(max(0, result.findData(current)))
    result.setMinimumWidth(0)
    result.setMinimumContentsLength(10)
    result.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    return result


def _table(headers, name):
    table = QTableWidget(0, len(headers))
    table.setAccessibleName(name)
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(50)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.setMinimumHeight(165)
    return table


def _fill_table(table, rows):
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(row, column, item)


def render_assistant_job(job: dict) -> str:
    """Render untrusted call text without links, markup, or external resources."""

    def escape(value):
        return html.escape(str(value or "")).replace("\n", "<br>")

    title = escape(job.get("target_name") or "Assistant call")
    state = escape(job.get("state", ""))
    objective = escape(job.get("objective", ""))
    parts = [
        '<html><body style="font-family:Segoe UI, sans-serif;color:#20242D">',
        f'<h2>{title}</h2><p style="color:#626977">{state}</p>',
        f"<p><b>Objective</b><br>{objective}</p>",
    ]
    for key, caption in (("summary", "Summary"), ("error", "Status details")):
        if job.get(key):
            parts.append(f"<p><b>{caption}</b><br>{escape(job[key])}</p>")
    if job.get("delivery_status"):
        parts.append(f"<p><b>Summary delivery</b><br>{escape(job['delivery_status'])}</p>")
    transcript = job.get("transcript") or []
    if transcript:
        parts.append("<h3>Conversation</h3>")
        if isinstance(transcript, str):
            parts.append(f"<p>{escape(transcript)}</p>")
        else:
            for turn in transcript:
                if isinstance(turn, dict):
                    speaker = turn.get("role") or turn.get("speaker") or "Speaker"
                    parts.append(
                        f"<p><b>{escape(speaker)}</b><br>{escape(turn.get('text', ''))}</p>"
                    )
    else:
        parts.append(
            '<p style="color:#626977">A transcript appears here after the assistant speaks.</p>'
        )
    parts.append("</body></html>")
    return "".join(parts)


class _ServicePage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setStyleSheet(EXTRA_STYLE)
        self.content = QVBoxLayout(self)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(18)
        self.notice = _plain()
        self.notice.setAccessibleName("Assistant action status")
        self.notice.hide()
        self.content.addWidget(self.notice)

    def notify(self, text):
        self.notice.setText(str(text))
        self.notice.setVisible(bool(text))

    def save(self, **changes):
        try:
            config = replace(self.service.config, **changes).validate()
            self.service.save_config(config)
            self.notify("Settings saved.")
            return True
        except (ValueError, OSError, RuntimeError) as exc:
            self.notify(str(exc))
            return False


class AssistantPage(_ServicePage):
    """Call, settings, contacts, and history controls for the local assistant service."""

    def __init__(self, service, parent=None):
        super().__init__(service, parent)
        self._jobs = []
        self._job_fingerprint = None
        self._target_fingerprint = None
        self._profile_fingerprint = None
        self._editing_target_id = None
        self.status = _plain("Checking assistant prerequisites…", "muted")
        self.status.setAccessibleName("AI Assistant readiness")
        self.content.addWidget(self.status)
        switches = QHBoxLayout()
        self.enabled = QCheckBox("Enable AI Assistant")
        self.enabled.setChecked(service.config.enabled)
        self.enabled.setToolTip(
            "Allow assistant calls under the saved contact and availability rules. "
            "Turning this off cancels assistant activity."
        )
        self.enabled.toggled.connect(lambda checked: self._toggle("enabled", checked))
        switches.addWidget(self.enabled)
        self.busy = QCheckBox("I’m busy")
        self.busy.setChecked(service.config.busy)
        self.busy.setToolTip(
            "Used when availability is set to ‘Only while I’m busy’. This does not "
            "change your Cliq presence."
        )
        self.busy.toggled.connect(lambda checked: self._toggle("busy", checked))
        switches.addWidget(self.busy)
        switches.addStretch()
        self.content.addLayout(switches)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("AI Assistant sections")
        self.content.addWidget(self.tabs)
        self._build_call()
        self._build_settings()
        self._build_contacts()
        self._build_history()
        self.tabs.currentChanged.connect(self._fit_tab)
        self._fit_tab()
        self.refresh()

    def _fit_tab(self, _index=None):
        # Hidden settings should not force the quick-call page to be several screens tall.
        for index in range(self.tabs.count()):
            policy = (
                QSizePolicy.Policy.Preferred
                if index == self.tabs.currentIndex()
                else QSizePolicy.Policy.Ignored
            )
            self.tabs.widget(index).setSizePolicy(policy, policy)
        self.tabs.updateGeometry()
        self.updateGeometry()

    def _toggle(self, field, value):
        if not self.save(**{field: value}):
            widget = getattr(self, field)
            widget.blockSignals(True)
            widget.setChecked(getattr(self.service.config, field))
            widget.blockSignals(False)
        self.refresh()

    def _build_call(self):
        panel, body = card()
        self.tabs.addTab(panel, "Call")
        body.addWidget(label("Give your assistant an objective", "sectionTitle"))
        body.addWidget(
            _plain(
                "The assistant introduces itself, keeps the conversation brief, and "
                "thanks the person before ending the call.",
                "muted",
            )
        )
        self.target = _combo([], "", "Call contact")
        _field(
            body,
            "Contact",
            self.target,
            "Only enabled Cliq contacts with outgoing calls allowed can be called "
            "here. Manage them in Contacts.",
        )
        self.objective = _text_edit(self.service.config.default_objective, "Call objective", 90)
        self.objective.setPlaceholderText("What should the assistant convey or find out?")
        _field(body, "Objective", self.objective)
        action = QHBoxLayout()
        self.call_now = QPushButton("Call now")
        self.call_now.setObjectName("primary")
        self.call_now.clicked.connect(self.trigger)
        action.addWidget(self.call_now)
        self.schedule_enabled = QCheckBox("Schedule for later")
        self.schedule_enabled.toggled.connect(self._schedule_mode)
        action.addWidget(self.schedule_enabled)
        action.addStretch()
        body.addLayout(action)
        self.schedule_row = QWidget()
        scheduled = QHBoxLayout(self.schedule_row)
        scheduled.setContentsMargins(0, 0, 0, 0)
        self.when = QDateTimeEdit(QDateTime.currentDateTime().addSecs(300))
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("ddd, d MMM yyyy · HH:mm")
        self.when.setAccessibleName("Scheduled call date and time")
        self.when.setToolTip(
            "Uses this computer’s local time. Voice Loop and the paired Chrome "
            "profile must be running at that time."
        )
        scheduled.addWidget(self.when, 1)
        self.schedule_button = QPushButton("Schedule call")
        self.schedule_button.setObjectName("primary")
        self.schedule_button.clicked.connect(self.schedule)
        scheduled.addWidget(self.schedule_button)
        self.schedule_row.hide()
        body.addWidget(self.schedule_row)
        body.addWidget(
            _plain(
                "Calls send audio to OpenAI using your API account. Voice Loop and the "
                "paired Chrome profile must stay running. Missed schedules expire; they "
                "do not place an unexpected late call."
            )
        )
        body.addStretch()

    def _build_settings(self):
        panel, body = card()
        self.tabs.addTab(panel, "Settings")
        body.addWidget(label("Voice and behavior", "sectionTitle"))
        pair = QHBoxLayout()
        self.model = _combo(
            [(value, value) for value in ("gpt-realtime", "gpt-realtime-mini")],
            self.service.config.model,
            "Realtime model",
            True,
        )
        self.voice = _combo(
            [
                (value, value)
                for value in (
                    "marin",
                    "cedar",
                    "alloy",
                    "ash",
                    "ballad",
                    "coral",
                    "echo",
                    "sage",
                    "shimmer",
                    "verse",
                )
            ],
            self.service.config.voice,
            "Assistant voice",
            True,
        )
        for title, widget in (("Realtime model", self.model), ("Voice", self.voice)):
            column = QVBoxLayout()
            _field(
                column,
                title,
                widget,
                "Choose a supported OpenAI Realtime value. Changes apply to the next call.",
            )
            pair.addLayout(column, 1)
        body.addLayout(pair)
        self.instructions = _text_edit(
            self.service.config.system_instructions, "System instructions", 110
        )
        _field(body, "System instructions", self.instructions)
        self.default_objective = _text_edit(
            self.service.config.default_objective, "Default objective", 72
        )
        _field(
            body,
            "Default objective",
            self.default_objective,
            "Required before automatically handling incoming or already-connected "
            "calls. An instant call can use its own objective.",
        )
        self.duration = QSpinBox()
        self.duration.setRange(15, 600)
        self.duration.setSuffix(" seconds")
        self.duration.setValue(self.service.config.max_duration_seconds)
        _field(
            body,
            "Maximum call duration",
            self.duration,
            "A hard time limit ends the assistant’s call even if its objective is unfinished.",
        )
        self.profile = _combo([], "", "Paired Chrome profile")
        _field(
            body,
            "Chrome profile",
            self.profile,
            "Choose the paired profile that owns the meeting account. Voice Loop "
            "never switches to a different account to place a call.",
        )
        body.addWidget(label("Automatic behavior", "sectionTitle"))
        self.auto_answer = QCheckBox("Answer allowed incoming Cliq calls")
        self.auto_assist_outgoing = QCheckBox(
            "Assist allowed outgoing Cliq calls after they connect"
        )
        self.auto_assist_meet = QCheckBox("Assist allowed Google Meet meetings after I join")
        for name in ("auto_answer", "auto_assist_outgoing", "auto_assist_meet"):
            widget = getattr(self, name)
            widget.setChecked(getattr(self.service.config, name))
            widget.setToolTip(
                "Requires the assistant to be enabled, an allowed contact or meeting, a "
                "saved objective, and availability rules to match."
            )
            body.addWidget(widget)
        platform_row = QHBoxLayout()
        self.cliq = QCheckBox("Zoho Cliq")
        self.meet = QCheckBox("Google Meet")
        for provider, widget in (("zoho_cliq", self.cliq), ("google_meet", self.meet)):
            widget.setChecked(provider in self.service.config.platforms)
            platform_row.addWidget(widget)
        platform_row.addStretch()
        body.addLayout(platform_row)
        self.availability = _combo(
            [
                ("Any time", "any"),
                ("During working hours", "inside_hours"),
                ("Outside working hours", "outside_hours"),
                ("Only while I’m busy", "busy"),
            ],
            self.service.config.availability,
            "Assistant availability",
        )
        _field(
            body,
            "Availability",
            self.availability,
            "Applies to immediate, scheduled, and automatic calls. ‘I’m busy’ is "
            "controlled at the top of this page.",
        )
        self.timezone = QLineEdit(self.service.config.timezone)
        _field(
            body,
            "Working-hours time zone",
            self.timezone,
            "Use an IANA time zone, such as Asia/Kolkata, Europe/London, or "
            "America/New_York. Daylight saving changes are handled automatically.",
        )
        hours = QHBoxLayout()
        self.work_start = QTimeEdit()
        self.work_end = QTimeEdit()
        for title, widget, value in (
            ("Work starts", self.work_start, self.service.config.work_start),
            ("Work ends", self.work_end, self.service.config.work_end),
        ):
            widget.setDisplayFormat("HH:mm")
            widget.setTime(widget.time().fromString(value, "HH:mm"))
            column = QVBoxLayout()
            _field(
                column,
                title,
                widget,
                "Overnight hours belong to the weekday on which the shift starts.",
            )
            hours.addLayout(column)
        body.addLayout(hours)
        days = QHBoxLayout()
        self.days = []
        for index, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            checkbox = QCheckBox(name)
            checkbox.setAccessibleName("Working day " + name)
            checkbox.setChecked(index in self.service.config.work_days)
            self.days.append(checkbox)
            days.addWidget(checkbox)
        days.addStretch()
        body.addLayout(days)
        save = QPushButton("Save assistant settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save_settings)
        body.addWidget(save)
        body.addWidget(
            _plain(
                "The assistant shares the OpenAI key saved in Preferences. Keys stay in "
                "the operating system credential store."
            )
        )

    def _build_contacts(self):
        panel, body = card()
        self.tabs.addTab(panel, "Contacts")
        body.addWidget(label("Allowed contacts and meetings", "sectionTitle"))
        body.addWidget(
            _plain(
                "Each link defines exactly where the assistant may participate. Google "
                "Meet entries permit assistance after you join; they do not join a "
                "meeting for you.",
                "muted",
            )
        )
        self.contacts = _table(
            ["Contact or meeting", "Incoming", "Outgoing / joined", "Summary"],
            "Allowed assistant contacts",
        )
        self.contacts.itemSelectionChanged.connect(self.edit_contact)
        body.addWidget(self.contacts)
        self.contact_empty = _plain("Add a Cliq chat or Meet link below to get started.")
        body.addWidget(self.contact_empty)
        self.contact_name = QLineEdit()
        self.contact_url = QLineEdit()
        self.contact_url.setPlaceholderText("https://cliq.zoho.com/company/…/chats/…")
        _field(body, "Contact or meeting name", self.contact_name)
        _field(
            body,
            "Chat or meeting link",
            self.contact_url,
            "Paste the exact Cliq chat link from your browser or a Google Meet "
            "link. Other websites and redirects are rejected.",
        )
        self.contact_enabled = QCheckBox("Enabled")
        self.contact_incoming = QCheckBox("Allow incoming")
        self.contact_outgoing = QCheckBox("Allow outgoing / joined")
        self.contact_summary = QCheckBox("Send a summary to this Cliq chat")
        self.contact_summary.setToolTip(
            "Also requires Automation to be enabled. Summarize AI Assistant calls or "
            "finished browser call recordings after their separately authorized transcription."
        )
        flags = QGridLayout()
        for index, widget in enumerate(
            (
                self.contact_enabled,
                self.contact_incoming,
                self.contact_outgoing,
                self.contact_summary,
            )
        ):
            flags.addWidget(widget, index // 2, index % 2)
        body.addLayout(flags)
        buttons = QHBoxLayout()
        self.save_contact_button = QPushButton("Add contact")
        self.save_contact_button.setObjectName("primary")
        self.save_contact_button.clicked.connect(self.save_contact)
        buttons.addWidget(self.save_contact_button)
        new = QPushButton("Clear form")
        new.clicked.connect(self.clear_contact)
        buttons.addWidget(new)
        self.remove_contact = QPushButton("Remove contact")
        self.remove_contact.clicked.connect(self.delete_contact)
        buttons.addWidget(self.remove_contact)
        buttons.addStretch()
        body.addLayout(buttons)
        self.clear_contact()

    def _build_history(self):
        panel, body = card()
        self.tabs.addTab(panel, "History")
        body.addWidget(label("Calls and schedules", "sectionTitle"))
        self.history = _table(
            ["Contact", "Status", "Scheduled / started"], "Assistant call history"
        )
        self.history.itemSelectionChanged.connect(self.show_job)
        body.addWidget(self.history)
        self.history_empty = _plain("Your assistant calls and schedules will appear here.")
        body.addWidget(self.history_empty)
        self.cancel_button = QPushButton("Cancel selected call")
        self.cancel_button.setToolTip(
            "Cancels a pending schedule or ends the selected active assistant call."
        )
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        body.addWidget(self.cancel_button)
        self.reader = QTextBrowser()
        self.reader.setAccessibleName("Assistant transcript and summary")
        self.reader.setOpenExternalLinks(False)
        self.reader.setOpenLinks(False)
        self.reader.setMinimumHeight(240)
        body.addWidget(self.reader)

    def _schedule_mode(self, checked):
        self.schedule_row.setVisible(checked)
        self.call_now.setVisible(not checked)

    def save_settings(self):
        if self.save(
            model=self.model.currentText(),
            voice=self.voice.currentText(),
            system_instructions=self.instructions.toPlainText(),
            default_objective=self.default_objective.toPlainText(),
            max_duration_seconds=self.duration.value(),
            profile_id=self.profile.currentData() or "",
            auto_answer=self.auto_answer.isChecked(),
            auto_assist_outgoing=self.auto_assist_outgoing.isChecked(),
            auto_assist_meet=self.auto_assist_meet.isChecked(),
            platforms=tuple(
                provider
                for provider, widget in (("zoho_cliq", self.cliq), ("google_meet", self.meet))
                if widget.isChecked()
            ),
            availability=self.availability.currentData(),
            timezone=self.timezone.text(),
            work_start=self.work_start.time().toString("HH:mm"),
            work_end=self.work_end.time().toString("HH:mm"),
            work_days=tuple(index for index, day in enumerate(self.days) if day.isChecked()),
        ):
            if not self.objective.toPlainText().strip():
                self.objective.setPlainText(self.service.config.default_objective)
            self.refresh()

    def _call_values(self):
        target = self.target.currentData()
        objective = self.objective.toPlainText().strip()
        if not target:
            raise ValueError("Add and select an enabled Cliq contact with outgoing calls allowed.")
        if not objective or len(objective) > 4000:
            raise ValueError("Enter a call objective of 1–4000 characters.")
        return target, objective

    def trigger(self):
        try:
            target, objective = self._call_values()
            self.service.trigger(target, objective)
            self.notify("Call requested. Track its progress in History.")
            self.refresh()
        except (ValueError, RuntimeError, OSError) as exc:
            self.notify(str(exc))

    def schedule(self):
        try:
            target, objective = self._call_values()
            when = datetime.fromtimestamp(self.when.dateTime().toSecsSinceEpoch(), UTC)
            if when <= datetime.now(UTC) + timedelta(seconds=1):
                raise ValueError("Choose a future date and time for the call.")
            self.service.schedule(target, objective, when)
            self.notify(
                "Call scheduled. Voice Loop and the paired Chrome profile must stay running."
            )
            self.refresh()
        except (ValueError, RuntimeError, OSError) as exc:
            self.notify(str(exc))

    def clear_contact(self):
        self._editing_target_id = None
        self.contacts.clearSelection()
        self.contact_name.clear()
        self.contact_url.clear()
        self.contact_enabled.setChecked(True)
        self.contact_incoming.setChecked(False)
        self.contact_outgoing.setChecked(True)
        self.contact_summary.setChecked(False)
        self.save_contact_button.setText("Add contact")
        self.remove_contact.setEnabled(False)

    def edit_contact(self):
        row = self.contacts.currentRow()
        if row < 0 or row >= len(self.service.config.targets):
            return
        target = self.service.config.targets[row]
        self._editing_target_id = target.id
        self.contact_name.setText(target.name)
        self.contact_url.setText(target.url)
        self.contact_enabled.setChecked(target.enabled)
        self.contact_incoming.setChecked(target.allow_incoming)
        self.contact_outgoing.setChecked(target.allow_outgoing)
        self.contact_summary.setChecked(target.send_summary)
        self.save_contact_button.setText("Save contact")
        self.remove_contact.setEnabled(True)

    def save_contact(self):
        try:
            target = ChatTarget.from_url(
                self.contact_name.text(),
                self.contact_url.text(),
                enabled=self.contact_enabled.isChecked(),
                allow_incoming=self.contact_incoming.isChecked(),
                allow_outgoing=self.contact_outgoing.isChecked(),
                send_summary=self.contact_summary.isChecked(),
            )
            if target.provider != "zoho_cliq" and target.send_summary:
                raise ValueError("Summary messages are supported for Cliq chats only.")
            targets = [
                item for item in self.service.config.targets if item.id != self._editing_target_id
            ]
            targets.append(target)
            if self.save(targets=targets):
                self.clear_contact()
                self.refresh()
                self.notify("Contact saved.")
        except ValueError as exc:
            self.notify(str(exc))

    def delete_contact(self):
        if self._editing_target_id and self.save(
            targets=[
                target
                for target in self.service.config.targets
                if target.id != self._editing_target_id
            ]
        ):
            self.clear_contact()
            self.refresh()
            self.notify("Contact removed. New calls to this link are no longer allowed.")

    def show_job(self):
        row = self.history.currentRow()
        selected = self._jobs[row] if 0 <= row < len(self._jobs) else None
        self.cancel_button.setEnabled(
            bool(
                selected
                and selected.get("state")
                in (
                    "scheduled",
                    "queued",
                    "starting",
                    "preparing",
                    "waiting",
                    "dialing",
                    "ringing",
                    "connected",
                    "active",
                    "running",
                )
            )
        )
        self.reader.setHtml(render_assistant_job(selected)) if selected else self.reader.clear()

    def cancel(self):
        row = self.history.currentRow()
        if not 0 <= row < len(self._jobs):
            return
        try:
            self.service.cancel(self._jobs[row]["id"])
            self.notify("Cancellation requested.")
            self.refresh()
        except (ValueError, RuntimeError, OSError) as exc:
            self.notify(str(exc))

    def refresh(self):
        try:
            snapshot = self.service.snapshot()
        except (ValueError, RuntimeError, OSError) as exc:
            self.status.setText(str(exc))
            return
        prerequisites = snapshot.get("prerequisites", {})
        missing = [
            title
            for key, title in (
                ("browser", "paired Chrome extension"),
                ("audio", "virtual audio bridge"),
                ("key", "OpenAI API key"),
            )
            if not prerequisites.get(key)
        ]
        status = str(snapshot.get("status") or ("Ready" if not missing else "Setup needed"))
        self.status.setText(status + (" · Needs " + ", ".join(missing) if missing else ""))
        for name in ("enabled", "busy"):
            widget = getattr(self, name)
            widget.blockSignals(True)
            widget.setChecked(getattr(self.service.config, name))
            widget.blockSignals(False)
        ready = self.service.config.enabled and not missing
        self.call_now.setEnabled(ready and bool(self.target.currentData()))
        self.schedule_button.setEnabled(
            self.service.config.enabled and bool(self.target.currentData())
        )
        targets = self.service.config.targets
        fingerprint = repr(targets)
        if fingerprint != self._target_fingerprint:
            selected = self.target.currentData()
            self.target.clear()
            for target in targets:
                if target.enabled and target.allow_outgoing and target.provider == "zoho_cliq":
                    self.target.addItem(target.name, target.id)
            if selected:
                self.target.setCurrentIndex(max(0, self.target.findData(selected)))
            self.contacts.blockSignals(True)
            _fill_table(
                self.contacts,
                [
                    (
                        target.name + (" · disabled" if not target.enabled else ""),
                        "Allowed" if target.allow_incoming else "Off",
                        "Allowed" if target.allow_outgoing else "Off",
                        "On" if target.send_summary else "Off",
                    )
                    for target in targets
                ],
            )
            self.contacts.blockSignals(False)
            self.contact_empty.setVisible(not targets)
            self._target_fingerprint = fingerprint
            self.call_now.setEnabled(ready and bool(self.target.currentData()))
            self.schedule_button.setEnabled(
                self.service.config.enabled and bool(self.target.currentData())
            )
        profiles = snapshot.get("profiles", [])
        fingerprint = repr(profiles)
        if fingerprint != self._profile_fingerprint:
            selected = self.profile.currentData() or self.service.config.profile_id
            self.profile.clear()
            self.profile.addItem("Choose automatically only when one profile is connected", "")
            for profile in profiles:
                profile_id = str(profile.get("id") or profile.get("profile_id") or "")
                self.profile.addItem(
                    str(profile.get("name") or profile.get("label") or profile_id), profile_id
                )
            if selected and self.profile.findData(selected) < 0:
                self.profile.addItem("Saved profile · currently disconnected", selected)
            self.profile.setCurrentIndex(max(0, self.profile.findData(selected)))
            self._profile_fingerprint = fingerprint
        jobs = snapshot.get("jobs", [])[:100]
        fingerprint = repr(jobs)
        if fingerprint != self._job_fingerprint:
            row = self.history.currentRow()
            selected_id = self._jobs[row].get("id") if 0 <= row < len(self._jobs) else None
            self._jobs = jobs
            self.history.blockSignals(True)
            _fill_table(
                self.history,
                [
                    (
                        job.get("target_name", "Call"),
                        job.get("state", ""),
                        job.get("scheduled_at") or job.get("started_at") or "Now",
                    )
                    for job in jobs
                ],
            )
            self.history.blockSignals(False)
            row = next((index for index, job in enumerate(jobs) if job.get("id") == selected_id), 0)
            if jobs:
                self.history.selectRow(row)
            self.history_empty.setVisible(not jobs)
            self.show_job()
            self._job_fingerprint = fingerprint


class AutomationPage(_ServicePage):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
        self._jobs = []
        self._fingerprint = None
        panel, body = card()
        body.addWidget(label("Send the outcome to the chat", "sectionTitle"))
        body.addWidget(
            _plain(
                "Post a brief summary to the original Cliq chat after an AI Assistant call "
                "or a browser call recording finishes transcription.",
                "muted",
            )
        )
        self.enabled = QCheckBox("Send call summaries automatically")
        self.enabled.setChecked(service.config.automation_enabled)
        self.enabled.setToolTip(
            "Requires ‘Send a summary’ on the Cliq contact. Posts through the paired Chrome "
            "extension. Recording and transcription need their own consent."
        )
        body.addWidget(self.enabled)
        self.model = _combo(
            [(value, value) for value in ("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini")],
            service.config.summary_model,
            "Summary model",
            True,
        )
        _field(
            body,
            "Summary model",
            self.model,
            "A text model available to your OpenAI API account. Summary requests "
            "are billed separately from Realtime audio.",
        )
        self.instructions = _text_edit(
            service.config.summary_instructions, "Summary instructions", 110
        )
        _field(body, "Summary instructions", self.instructions)
        self.contact_status = _plain()
        body.addWidget(self.contact_status)
        save = QPushButton("Save automation settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save_settings)
        body.addWidget(save)
        body.addWidget(
            _plain(
                "Enable ‘Send a summary’ for each recipient in AI Assistant → Contacts. "
                "Recording summaries need verified browser chat details and a completed "
                "transcription; enabling Automation alone does not record or transcribe. "
                "Failed or uncertain delivery is shown below; Voice Loop avoids sending "
                "duplicate messages."
            )
        )
        self.content.addWidget(panel)
        panel, body = card()
        body.addWidget(label("Summary delivery", "sectionTitle"))
        self.history = _table(
            ["Contact", "Delivery status", "Call status"], "Summary delivery history"
        )
        self.history.itemSelectionChanged.connect(self.show_job)
        body.addWidget(self.history)
        self.empty = _plain("Call summaries and their delivery status will appear here.")
        body.addWidget(self.empty)
        self.reader = QTextBrowser()
        self.reader.setAccessibleName("Summary delivery details")
        self.reader.setOpenExternalLinks(False)
        self.reader.setOpenLinks(False)
        self.reader.setMinimumHeight(220)
        body.addWidget(self.reader)
        self.content.addWidget(panel)
        self.refresh()

    def save_settings(self):
        if self.save(
            automation_enabled=self.enabled.isChecked(),
            summary_model=self.model.currentText(),
            summary_instructions=self.instructions.toPlainText(),
        ):
            self.refresh()

    def show_job(self):
        row = self.history.currentRow()
        if 0 <= row < len(self._jobs):
            self.reader.setHtml(render_assistant_job(self._jobs[row]))
        else:
            self.reader.clear()

    def refresh(self):
        targets = [
            target.name
            for target in self.service.config.targets
            if target.enabled and target.send_summary and target.provider == "zoho_cliq"
        ]
        self.contact_status.setText(
            "Summary recipients: " + ", ".join(targets)
            if targets
            else "No summary recipients yet. Enable summaries for a Cliq contact in AI "
            "Assistant → Contacts."
        )
        try:
            snapshot = self.service.snapshot()
        except (ValueError, RuntimeError, OSError) as exc:
            self.notify(str(exc))
            return
        jobs = [
            job
            for job in snapshot.get("jobs", [])
            if job.get("summary")
            or job.get("delivery_status")
            or job.get("state") in ("completed", "failed", "cancelled", "ended")
        ][:100]
        fingerprint = repr(jobs)
        if fingerprint != self._fingerprint:
            row = self.history.currentRow()
            selected_id = self._jobs[row].get("id") if 0 <= row < len(self._jobs) else None
            self._jobs = jobs
            self.history.blockSignals(True)
            _fill_table(
                self.history,
                [
                    (
                        job.get("target_name", "Call"),
                        job.get("delivery_status") or "Not requested",
                        job.get("state", ""),
                    )
                    for job in jobs
                ],
            )
            self.history.blockSignals(False)
            row = next((index for index, job in enumerate(jobs) if job.get("id") == selected_id), 0)
            if jobs:
                self.history.selectRow(row)
            self.empty.setVisible(not jobs)
            self.show_job()
            self._fingerprint = fingerprint
