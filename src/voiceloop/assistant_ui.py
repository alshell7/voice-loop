"""Native AI Assistant and Automation pages, backed by an injected local service."""

from __future__ import annotations

import html
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
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
    from voiceloop.ui_extras import search_combo

    result = search_combo(name, [], "Enter " + name.lower())
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


def _history_links(table):
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        item.setForeground(QColor("#006FEE"))
        item.setToolTip("Open this call in Recordings to view the conversation and JSON.")


def _status(value):
    return {
        "not_requested": "Not requested",
        "sent": "Sent to chat",
        "sending": "Sending…",
        "generating": "Writing summary…",
        "ambiguous": "Delivery unconfirmed",
        "disabled": "Summary disabled",
        "preparing": "Preparing call",
        "waiting": "Calling…",
        "active": "On call",
    }.get(value, str(value or "Not requested").replace("_", " ").capitalize())


def _job_time(job):
    value = job.get("scheduled_at") or job.get("started_at") or job.get("created_at")
    try:
        return (
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            .astimezone()
            .strftime("%d %b %Y · %H:%M")
        )
    except ValueError:
        return str(value or "—")


class _HistoryPager(QWidget):
    """Small reusable search and pagination controls; state stays local to its page."""

    def __init__(self, refresh, parent=None):
        super().__init__(parent)
        self.page = 1
        self.page_size = 10
        self._refresh = refresh
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search contact, objective or summary…")
        self.query.setAccessibleName("Search call history")
        self.query.textChanged.connect(self.search)
        layout.addWidget(self.query, 1)
        self.previous = QPushButton("Previous")
        self.previous.clicked.connect(lambda: self.move(-1))
        layout.addWidget(self.previous)
        self.info = _plain("No calls")
        layout.addWidget(self.info)
        self.next = QPushButton("Next")
        self.next.clicked.connect(lambda: self.move(1))
        layout.addWidget(self.next)

    def search(self):
        self.page = 1
        self._refresh()

    def move(self, step):
        self.page = max(1, self.page + step)
        self._refresh()

    def fetch(self, service, snapshot, kind=None):
        if callable(getattr(service, "list_jobs", None)):
            result = service.list_jobs(
                kind=kind, query=self.query.text().strip(), page=self.page, page_size=self.page_size
            )
        else:
            jobs = snapshot.get("jobs", [])
            if kind == "summary":
                jobs = [
                    job
                    for job in jobs
                    if job.get("delivery_status") not in (None, "", "not_requested")
                ]
            query = self.query.text().strip().casefold()
            jobs = [
                job
                for job in jobs
                if not query
                or query
                in " ".join(
                    str(job.get(key, "")) for key in ("target_name", "objective", "summary")
                ).casefold()
            ]
            pages = max(1, (len(jobs) + self.page_size - 1) // self.page_size)
            page = min(self.page, pages)
            result = {
                "items": jobs[(page - 1) * self.page_size : page * self.page_size],
                "total": len(jobs),
                "page": page,
                "pages": pages,
            }
        self.page = result["page"]
        self.previous.setEnabled(self.page > 1)
        self.next.setEnabled(self.page < result["pages"])
        self.info.setText(
            f"{self.page} / {max(1, result['pages'])} · {result['total']} calls"
            if result["total"]
            else "No calls"
        )
        return result["items"]


def render_assistant_job(job: dict) -> str:
    """Render untrusted call text without links, markup, or external resources."""

    def escape(value):
        return html.escape(str(value or "")).replace("\n", "<br>")

    title = escape(job.get("target_name") or "Assistant call")
    state = escape(_status(job.get("state", "")))
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
        parts.append(f"<p><b>Summary delivery</b><br>{escape(_status(job['delivery_status']))}</p>")
        if job["delivery_status"] == "ambiguous":
            parts.append(
                "<p>Check the chat before sending again; delivery could not be confirmed.</p>"
            )
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


class AssistantHistoryDialog(QDialog):
    """Local readable transcript and JSON viewer; never loads remote content."""

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.setWindowTitle(str(job.get("target_name") or "Assistant call") + " · Voice Loop")
        self.resize(820, 690)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Call transcript formats")
        self.reader = QTextBrowser()
        self.reader.setOpenExternalLinks(False)
        self.reader.setOpenLinks(False)
        self.reader.setAccessibleName("Call transcript and summary")
        self.reader.setHtml(render_assistant_job(job))
        self.tabs.addTab(self.reader, "Conversation & summary")
        self.json = QPlainTextEdit()
        self.json.setReadOnly(True)
        self.json.setAccessibleName("Call JSON")
        self.json.setPlainText(json.dumps(job, ensure_ascii=False, indent=2, default=str))
        self.tabs.addTab(self.json, "JSON")
        layout.addWidget(self.tabs)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def stop_playback(self):
        """Share the app's close-dialog contract; assistant history has no audio player."""


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

    def __init__(self, service, parent=None, on_open_history=None):
        super().__init__(service, parent)
        self.on_open_history = on_open_history
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
        self.target = _combo([], "", "Call contact", True)
        self.target.lineEdit().setPlaceholderText("Search saved contacts…")
        _field(
            body,
            "Contact",
            self.target,
            "Only enabled Cliq contacts with outgoing calls allowed can be called "
            "here. Manage them in Contacts.",
        )
        contact_actions = QHBoxLayout()
        self.add_contact_shortcut = QPushButton("+ Add contact")
        self.add_contact_shortcut.clicked.connect(self.new_contact)
        contact_actions.addWidget(self.add_contact_shortcut)
        manage = QPushButton("Manage contacts")
        manage.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        contact_actions.addWidget(manage)
        contact_actions.addStretch()
        body.addLayout(contact_actions)
        self.target.currentTextChanged.connect(self._update_call_buttons)
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
        self.language = _combo(
            [("Follow the caller", "auto")]
            + [
                (value, value)
                for value in ("English", "Arabic", "French", "German", "Hindi", "Spanish", "Tamil")
            ],
            self.service.config.language,
            "Conversation language",
            True,
        )
        if self.service.config.language == "auto":
            self.language.setCurrentIndex(self.language.findData("auto"))
        _field(
            body,
            "Conversation language",
            self.language,
            "Choose or type a language. Follow the caller lets the assistant adapt "
            "to the caller’s language.",
        )
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
        body.addWidget(label("Your Cliq workspace", "sectionTitle"))
        company_row = QHBoxLayout()
        self.company_id = QLineEdit(self.service.config.cliq_company_id)
        self.company_id.setPlaceholderText("Company ID from your Cliq link")
        self.cliq_origin = _combo(
            [
                (domain, "https://cliq.zoho." + domain)
                for domain in ("com", "eu", "in", "com.au", "jp", "ca", "com.cn", "sa")
            ],
            self.service.config.cliq_origin,
            "Cliq region",
        )
        for title, widget in (("Company ID", self.company_id), ("Cliq region", self.cliq_origin)):
            column = QVBoxLayout()
            _field(
                column,
                title,
                widget,
                "Used to turn a numeric chat ID into your exact Cliq chat link.",
            )
            company_row.addLayout(column, 2 if widget is self.company_id else 1)
        body.addLayout(company_row)
        save_workspace = QPushButton("Save workspace")
        save_workspace.clicked.connect(self.save_workspace)
        body.addWidget(save_workspace, alignment=Qt.AlignmentFlag.AlignLeft)
        body.addWidget(label("Allowed contacts and meetings", "sectionTitle"))
        body.addWidget(
            _plain(
                "Each link defines exactly where the assistant may participate. Google "
                "Meet entries permit assistance after you join; they do not join a "
                "meeting for you.",
                "muted",
            )
        )
        toolbar = QHBoxLayout()
        self.add_contact_button = QPushButton("+ Add contact")
        self.add_contact_button.setObjectName("primary")
        self.add_contact_button.clicked.connect(self.new_contact)
        toolbar.addWidget(self.add_contact_button)
        self.edit_contact_button = QPushButton("Edit contact")
        self.edit_contact_button.setEnabled(False)
        self.edit_contact_button.clicked.connect(self.edit_contact)
        toolbar.addWidget(self.edit_contact_button)
        self.remove_contact = QPushButton("Delete contact")
        self.remove_contact.setEnabled(False)
        self.remove_contact.clicked.connect(self.delete_contact)
        toolbar.addWidget(self.remove_contact)
        toolbar.addStretch()
        body.addLayout(toolbar)
        self.contacts = _table(
            ["Contact or meeting", "Incoming", "Outgoing / joined", "Summary"],
            "Allowed assistant contacts",
        )
        self.contacts.itemSelectionChanged.connect(self._contact_selected)
        self.contacts.itemDoubleClicked.connect(lambda: self.edit_contact())
        body.addWidget(self.contacts)
        self.contact_empty = _plain(
            "Add a contact using a Cliq chat link or chat ID to get started."
        )
        body.addWidget(self.contact_empty)
        body.addStretch()
        self.contact_dialog = QDialog(self)
        self.contact_dialog.setModal(True)
        self.contact_dialog.setWindowTitle("Add contact · Voice Loop")
        self.contact_dialog.setMinimumWidth(530)
        body = QVBoxLayout(self.contact_dialog)
        body.setContentsMargins(24, 24, 24, 24)
        body.setSpacing(12)
        self.contact_heading = label("Add a contact", "sectionTitle")
        body.addWidget(self.contact_heading)
        self.contact_notice = _plain()
        self.contact_notice.hide()
        body.addWidget(self.contact_notice)
        self.contact_name = QLineEdit()
        self.contact_url = QLineEdit()
        self.contact_url.setPlaceholderText("Paste a full chat link or enter a chat ID")
        _field(body, "Contact or meeting name", self.contact_name)
        _field(
            body,
            "Chat link or ID / Meet link",
            self.contact_url,
            "Paste the exact Cliq chat link, a numeric chat ID using your saved workspace, "
            "or a Google Meet link. A full Cliq link can fill an empty workspace setting.",
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
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.contact_dialog.reject)
        buttons.addWidget(cancel)
        buttons.addStretch()
        body.addLayout(buttons)
        self.clear_contact()

    def _build_history(self):
        panel, body = card()
        self.tabs.addTab(panel, "History")
        body.addWidget(label("Calls and schedules", "sectionTitle"))
        self.history_pager = _HistoryPager(self.refresh)
        body.addWidget(self.history_pager)
        self.history = _table(
            ["Contact", "Call status", "Summary", "Scheduled / started"], "Assistant call history"
        )
        self.history.itemSelectionChanged.connect(self.show_job)
        self.history.itemClicked.connect(
            lambda item: self.open_history() if item.column() == 0 else None
        )
        body.addWidget(self.history)
        self.history_empty = _plain("Your assistant calls and schedules will appear here.")
        body.addWidget(self.history_empty)
        self.cancel_button = QPushButton("Cancel selected call")
        self.cancel_button.setToolTip(
            "Cancels a pending schedule or ends the selected active assistant call."
        )
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        actions = QHBoxLayout()
        self.open_history_button = QPushButton("Open in Recordings")
        self.open_history_button.setObjectName("primary")
        self.open_history_button.clicked.connect(self.open_history)
        actions.addWidget(self.open_history_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        body.insertLayout(body.indexOf(self.history), actions)
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
            language=(
                "auto"
                if self.language.currentText() == "Follow the caller"
                else self.language.currentText()
            ),
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

    def _selected_target(self):
        text = self.target.currentText().strip()
        index = self.target.currentIndex()
        if index >= 0 and self.target.itemText(index) == text:
            return self.target.itemData(index)
        # A partly typed name must never silently call the previously selected person.
        matches = [
            self.target.itemData(index)
            for index in range(self.target.count())
            if self.target.itemText(index).casefold() == text.casefold()
        ]
        return matches[0] if len(matches) == 1 else None

    def _update_call_buttons(self):
        if not hasattr(self, "call_now"):
            return
        target = self._selected_target()
        self.call_now.setEnabled(bool(getattr(self, "_ready", False) and target))
        self.schedule_button.setEnabled(bool(self.service.config.enabled and target))

    def _call_values(self):
        target = self._selected_target()
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
        self.edit_contact_button.setEnabled(False)
        self.contact_heading.setText("Add a contact")
        self.contact_notice.hide()

    def new_contact(self):
        self.clear_contact()
        self.contact_dialog.setWindowTitle("Add contact · Voice Loop")
        self.contact_dialog.open()
        self.contact_name.setFocus()

    def _contact_selected(self):
        row = self.contacts.currentRow()
        selected = self.contacts.selectedItems() and 0 <= row < len(self.service.config.targets)
        self.edit_contact_button.setEnabled(bool(selected))
        self.remove_contact.setEnabled(bool(selected))

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
        self.contact_heading.setText("Edit contact")
        self.contact_notice.hide()
        self.contact_dialog.setWindowTitle("Edit contact · Voice Loop")
        self.contact_dialog.open()
        self.contact_name.setFocus()

    def save_workspace(self):
        if self.save(
            cliq_company_id=self.company_id.text().strip(),
            cliq_origin=self.cliq_origin.currentData(),
        ):
            self.notify("Cliq workspace saved. You can now add contacts using their chat ID.")

    def save_contact(self):
        try:
            config = replace(
                self.service.config,
                cliq_company_id=self.company_id.text().strip(),
                cliq_origin=self.cliq_origin.currentData(),
            )
            flags = dict(
                enabled=self.contact_enabled.isChecked(),
                allow_incoming=self.contact_incoming.isChecked(),
                allow_outgoing=self.contact_outgoing.isChecked(),
                send_summary=self.contact_summary.isChecked(),
            )
            value = self.contact_url.text().strip()
            existing = config.target(self._editing_target_id) if self._editing_target_id else None
            edited = (
                ChatTarget.from_url(self.contact_name.text(), value, **flags)
                if existing and "://" in value
                else None
            )
            if edited and edited.url == existing.url:
                target = edited
            elif value.startswith("https://meet.google.com/"):
                target = ChatTarget.from_url(self.contact_name.text(), value, **flags)
            else:
                target = config.make_cliq_target(self.contact_name.text(), value, **flags)
            if target.provider != "zoho_cliq" and target.send_summary:
                raise ValueError("Summary messages are supported for Cliq chats only.")
            targets = [
                item for item in self.service.config.targets if item.id != self._editing_target_id
            ]
            targets.append(target)
            if self.save(
                targets=targets,
                cliq_company_id=config.cliq_company_id,
                cliq_origin=config.cliq_origin,
            ):
                self.clear_contact()
                self.refresh()
                self.target.setCurrentIndex(self.target.findData(target.id))
                self.company_id.setText(self.service.config.cliq_company_id)
                self.cliq_origin.setCurrentIndex(
                    self.cliq_origin.findData(self.service.config.cliq_origin)
                )
                self.contact_dialog.accept()
                self.notify("Contact saved.")
            else:
                self.contact_notice.setText(self.notice.text())
                self.contact_notice.show()
        except ValueError as exc:
            self.notify(str(exc))
            self.contact_notice.setText(str(exc))
            self.contact_notice.show()

    def delete_contact(self):
        row = self.contacts.currentRow()
        if not self.contacts.selectedItems() or not 0 <= row < len(self.service.config.targets):
            return
        target_id = self.service.config.targets[row].id
        if self.save(
            targets=[target for target in self.service.config.targets if target.id != target_id]
        ):
            self.clear_contact()
            self.refresh()
            self.notify(
                "Contact removed. Automatic calls and summaries for this contact are disabled."
            )

    def show_job(self):
        row = self.history.currentRow()
        selected = self._jobs[row] if 0 <= row < len(self._jobs) else None
        self.open_history_button.setEnabled(bool(selected))
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

    def open_history(self):
        row = self.history.currentRow()
        if 0 <= row < len(self._jobs):
            if self.on_open_history:
                self.on_open_history(dict(self._jobs[row]))
            else:
                self.history_dialog = AssistantHistoryDialog(self._jobs[row], self)
                self.history_dialog.show()

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
        self._ready = self.service.config.enabled and not missing
        self._update_call_buttons()
        targets = self.service.config.targets
        fingerprint = repr(targets)
        if fingerprint != self._target_fingerprint:
            selected = self._selected_target()
            self.target.blockSignals(True)
            self.target.clear()
            names = [target.name.casefold() for target in targets]
            for target in targets:
                if target.enabled and target.allow_outgoing and target.provider == "zoho_cliq":
                    text = (
                        target.name + " · " + target.chat_id
                        if names.count(target.name.casefold()) > 1
                        else target.name
                    )
                    self.target.addItem(text, target.id)
                    self.target.setItemData(
                        self.target.count() - 1, target.url, Qt.ItemDataRole.ToolTipRole
                    )
            if selected:
                self.target.setCurrentIndex(max(0, self.target.findData(selected)))
            self.target.blockSignals(False)
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
            self._contact_selected()
            self._update_call_buttons()
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
        try:
            jobs = self.history_pager.fetch(self.service, snapshot)
        except (ValueError, RuntimeError, OSError) as exc:
            self.notify(str(exc))
            return
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
                        _status(job.get("state", "")),
                        _status(job.get("delivery_status", "not_requested")),
                        _job_time(job),
                    )
                    for job in jobs
                ],
            )
            _history_links(self.history)
            self.history.blockSignals(False)
            row = next((index for index, job in enumerate(jobs) if job.get("id") == selected_id), 0)
            if jobs:
                self.history.selectRow(row)
            self.history_empty.setVisible(not jobs)
            self.show_job()
            self._job_fingerprint = fingerprint


class AutomationPage(_ServicePage):
    def __init__(self, service, parent=None, on_open_history=None):
        super().__init__(service, parent)
        self.on_open_history = on_open_history
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
        self.history_pager = _HistoryPager(self.refresh)
        body.addWidget(self.history_pager)
        self.history = _table(
            ["Contact", "Delivery status", "Call status"], "Summary delivery history"
        )
        self.history.itemSelectionChanged.connect(self.show_job)
        self.history.itemClicked.connect(
            lambda item: self.open_history() if item.column() == 0 else None
        )
        body.addWidget(self.history)
        self.empty = _plain("Call summaries and their delivery status will appear here.")
        body.addWidget(self.empty)
        self.open_history_button = QPushButton("Open in Recordings")
        self.open_history_button.clicked.connect(self.open_history)
        body.insertWidget(
            body.indexOf(self.history),
            self.open_history_button,
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
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
        self.open_history_button.setEnabled(0 <= row < len(self._jobs))
        if 0 <= row < len(self._jobs):
            self.reader.setHtml(render_assistant_job(self._jobs[row]))
        else:
            self.reader.clear()

    def open_history(self):
        row = self.history.currentRow()
        if 0 <= row < len(self._jobs):
            if self.on_open_history:
                self.on_open_history(dict(self._jobs[row]))
            else:
                self.history_dialog = AssistantHistoryDialog(self._jobs[row], self)
                self.history_dialog.show()

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
        try:
            jobs = self.history_pager.fetch(self.service, snapshot, "summary")
        except (ValueError, RuntimeError, OSError) as exc:
            self.notify(str(exc))
            return
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
                        _status(job.get("delivery_status")),
                        _status(job.get("state", "")),
                    )
                    for job in jobs
                ],
            )
            _history_links(self.history)
            self.history.blockSignals(False)
            row = next((index for index, job in enumerate(jobs) if job.get("id") == selected_id), 0)
            if jobs:
                self.history.selectRow(row)
            self.empty.setVisible(not jobs)
            self.show_job()
            self._fingerprint = fingerprint
