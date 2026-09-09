"""Floating controls, preferences, searchable library, and session reader."""

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from voiceloop.library import TOOLS, SessionLibrary, audio_parts, update_metadata
from voiceloop.openai_stt import MODELS
from voiceloop.transcript_html import render_transcript, save_html, timecode
from voiceloop.ui import card, icon, label

MICROPHONE_MUTE_HELP = (
    "Mute VoiceLoop's microphone feed and local microphone recording. In Direct capture, "
    "also mute your meeting app's physical microphone."
)


def assistant_call_display(assistant):
    """Only connected assistant audio owns an elapsed timer; setup is not a call."""
    try:
        job = assistant.store.get(assistant.active_id)
    except (ValueError, OSError):
        return "AI Assistant · preparing…", 0
    state = job.get("state", "")
    if job.get("browser_ended") or state in {"cancelled", "completed", "failed", "interrupted"}:
        return "AI Assistant · stopping…", 0
    if state == "active":
        duration = 0
        try:
            started = datetime.fromisoformat(job.get("started_at", ""))
            if started.tzinfo is not None and started.utcoffset() is not None:
                duration = max(0, (assistant.now() - started).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
        return "AI Assistant · on call", duration
    if state == "waiting":
        if job.get("action") == "answer":
            return "AI Assistant · answering…", 0
        if job.get("browser_state") == "ringing":
            return "AI Assistant · ringing…", 0
        if job.get("browser_state") == "dialing":
            return "AI Assistant · calling…", 0
        return "AI Assistant · waiting for answer…", 0
    return "AI Assistant · preparing…", 0


def search_combo(name, values, placeholder):
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.addItems(values)
    combo.setCurrentIndex(-1)
    combo.lineEdit().setPlaceholderText(placeholder)
    combo.setAccessibleName(name)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    combo.setMinimumWidth(0)
    combo.setMinimumContentsLength(10)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    # QCompleter owns a top-level popup, so the QComboBox descendant rule does
    # not reach it. Set every palette group as well as selection styling so a
    # dark Windows palette cannot leak into this intentionally light surface.
    popup = combo.completer().popup()
    popup.setAccessibleName(name + " suggestions")
    palette = popup.palette()
    for role, color in (
        (QPalette.ColorRole.Base, "#FFFFFF"),
        (QPalette.ColorRole.Window, "#FFFFFF"),
        (QPalette.ColorRole.Text, "#20242D"),
        (QPalette.ColorRole.WindowText, "#20242D"),
        (QPalette.ColorRole.Highlight, "#EAF2FF"),
        (QPalette.ColorRole.HighlightedText, "#005BC4"),
    ):
        palette.setColor(QPalette.ColorGroup.All, role, QColor(color))
    popup.setPalette(palette)
    popup.setStyleSheet(
        "QAbstractItemView {background:#FFFFFF; color:#20242D; border:1px solid #DCE2EA;"
        "selection-background-color:#EAF2FF; selection-color:#005BC4; padding:5px;}"
        "QAbstractItemView::item {min-height:28px; padding:4px 8px;}"
        "QAbstractItemView::item:selected {background:#EAF2FF; color:#005BC4;}"
        "QAbstractItemView::item:hover {background:#F4F7FC; color:#20242D;}"
    )
    return combo


class FloatingControls(QWidget):
    def __init__(self, app):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.app = app
        self.drag_start = None
        self.compact = False
        self.setWindowTitle("Voice Loop controls")
        self.setWindowIcon(icon("session", "#006FEE"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(420)
        self.setWindowOpacity(app.settings.floating_opacity / 100)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("floatingSurface")
        panel.setStyleSheet(
            "QFrame#floatingSurface{background:#FAFCFF;border:1px solid #DCE4EF;border-radius:20px;}"
        )
        outer.addWidget(panel)
        self.surface = panel
        body = QVBoxLayout(panel)
        body.setContentsMargins(20, 16, 20, 18)
        body.setSpacing(15)
        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon("session", "#006FEE", 20).pixmap(20, 20))
        header.addWidget(mark)
        header.addWidget(label("Voice Loop", "brand"))
        header.addStretch()
        for glyph, name, action in (
            ("collapse", "Collapse meeting details", self.toggle_compact),
            ("minimize", "Minimize to tray", self.minimize),
            ("expand", "Open Voice Loop", app.show_main),
        ):
            button = QToolButton()
            button.setIcon(icon(glyph, size=17))
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.clicked.connect(action)
            header.addWidget(button)
            if glyph == "collapse":
                self.collapse_button = button
        body.addLayout(header)
        status_row = QHBoxLayout()
        self.state = label("Off · ready when you are", "muted")
        status_row.addWidget(self.state, 1)
        self.elapsed = label("00:00", "timer")
        self.elapsed.setStyleSheet("font-size:23px")
        status_row.addWidget(self.elapsed)
        body.addLayout(status_row)
        self.mode = QComboBox()
        self.mode.setAccessibleName("Session recording mode")
        self.mode.addItem("Route only", False)
        self.mode.addItem("Record too", True)
        self.mode.setCurrentIndex(1 if app.settings.session_mode == "record" else 0)
        self.mode.setToolTip(
            "Route only keeps audio in memory. Record too also saves stereo audio to your storage folder. Choose before turning on."
        )
        self.mode.currentIndexChanged.connect(self.save_mode)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self.mode, 1)
        self.power = QPushButton(icon("power", "white", 17), "Turn on")
        self.power.setObjectName("primary")
        self.power.setToolTip(
            "Start with the selected recording mode. Turn off to end and save the session."
        )
        self.power.clicked.connect(self.toggle_power)
        controls.addWidget(self.power)
        self.mute = QPushButton(icon("mic", size=17), "Mute")
        self.mute.setCheckable(True)
        self.mute.setToolTip(MICROPHONE_MUTE_HELP)
        self.mute.clicked.connect(app.toggle_mute)
        controls.addWidget(self.mute)
        body.addLayout(controls)
        self.browser_event = label("", "small", True)
        self.browser_event.setTextFormat(Qt.TextFormat.PlainText)
        self.browser_event.setAccessibleName("Browser call detection status")
        self.browser_event.hide()
        body.addWidget(self.browser_event)
        self.details = QWidget()
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(8)
        details.addWidget(label("Meeting details", "fieldLabel"))
        self.tool = search_combo("Meeting tool", TOOLS, "Tool · Zoom, Meet, Teams…")
        self.tool.setCurrentText(app.settings.meeting_tool)
        self.tool.setToolTip(
            "Tag manual sessions here. The paired Chrome extension fills this in for detected calls."
        )
        details.addWidget(self.tool)
        self.contact = search_combo("Contact name", app.contacts.names(), "Search or add a contact")
        self.contact.setCurrentText(app.settings.contact_name)
        self.contact.setToolTip(
            "Search saved contacts or type a new name. New names save automatically when you finish editing."
        )
        details.addWidget(self.contact)
        self.tool.lineEdit().editingFinished.connect(
            lambda: QTimer.singleShot(0, self.save_tags_after_edit)
        )
        self.contact.lineEdit().editingFinished.connect(
            lambda: QTimer.singleShot(0, self.save_tags_after_edit)
        )
        details.addWidget(label("Contact names are saved on this device.", "small"))
        body.addWidget(self.details)
        self.storage = QLabel()
        self.storage.setObjectName("small")
        self.storage.setWordWrap(True)
        self.storage.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.storage)
        bottom = QHBoxLayout()
        self.last_session = QPushButton(icon("folder", size=16), "Recordings")
        self.last_session.clicked.connect(lambda: app.show_main(2))
        bottom.addWidget(self.last_session)
        bottom.addStretch()
        preferences = QToolButton()
        preferences.setIcon(icon("settings", size=18))
        preferences.setAccessibleName("Preferences and opacity")
        preferences.setToolTip("Preferences · screen privacy, browser calls, opacity, and startup")
        preferences.clicked.connect(lambda: app.show_main(3))
        bottom.addWidget(preferences)
        body.addLayout(bottom)
        self.notice = label("", "small", True)
        self.notice.hide()
        body.addWidget(self.notice)
        self.refresh()
        self.adjustSize()

    def save_mode(self):
        self.app.settings.session_mode = "record" if self.mode.currentData() else "route"
        self.app.save_preferences()

    def save_tags(self):
        if self.app.engine.active:
            return
        try:
            name = self.app.contacts.remember(self.contact.currentText())
            current = self.contact.currentText()
            self.contact.blockSignals(True)
            names = self.app.contacts.names()
            if names != [self.contact.itemText(i) for i in range(self.contact.count())]:
                self.contact.clear()
                self.contact.addItems(names)
            self.contact.setCurrentText(name or current)
            self.contact.blockSignals(False)
            self.app.settings.contact_name = name
            self.app.settings.meeting_tool = self.tool.currentText().strip()[:120]
            self.app.save_preferences()
        except OSError as exc:
            self.show_notice("Could not save contact: " + str(exc))

    def save_tags_after_edit(self):
        # Opening a native completion popup can move focus away from the edit.
        # Let Qt commit its selection before saving or replacing its item model.
        if not any(combo.completer().popup().isVisible() for combo in (self.tool, self.contact)):
            self.save_tags()

    def toggle_power(self):
        if self.app.assistant.active:
            self.app.assistant.cancel(self.app.assistant.active_id)
            self.refresh()
        elif self.app.engine.active:
            self.app.stop_session()
        else:
            self.save_tags()
            self.app.start(record=self.mode.currentData())

    def show_notice(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))
        self.resize_contents()

    def toggle_compact(self):
        self.compact = not self.compact
        self.details.setVisible(not self.compact)
        self.storage.setVisible(not self.compact)
        name = "Expand meeting details" if self.compact else "Collapse meeting details"
        self.collapse_button.setAccessibleName(name)
        self.collapse_button.setToolTip(name)
        self.collapse_button.setIcon(icon("chevron" if self.compact else "collapse", size=17))
        self.resize_contents()
        QTimer.singleShot(0, self.resize_contents)

    def resize_contents(self):
        layout = self.surface.layout()
        layout.invalidate()
        margins = layout.contentsMargins()
        width = self.width() - margins.left() - margins.right()
        heights = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.isEmpty():
                continue
            height = item.heightForWidth(width) if item.hasHeightForWidth() else -1
            heights.append(max(item.minimumSize().height(), height, item.sizeHint().height()))
        height = (
            sum(heights)
            + layout.spacing() * max(0, len(heights) - 1)
            + margins.top()
            + margins.bottom()
            + self.surface.frameWidth() * 2
        )
        self.setFixedHeight(max(180, height))
        # Windows can retain the previous native minimum during a layout change.
        # Explicitly resize on the deferred pass, even if the fixed size is unchanged.
        self.resize(self.width(), max(180, height))

    def minimize(self):
        if self.app.tray and self.app.tray.isSystemTrayAvailable():
            self.hide()
        else:
            self.app.show_main()
            self.hide()

    def refresh(self):
        engine = self.app.engine
        assistant_active = self.app.assistant.active
        active = engine.active or assistant_active
        self.mode.setEnabled(not active and not self.app.install_future)
        self.tool.setEnabled(not active)
        self.contact.setEnabled(not active)
        self.power.setEnabled(engine.state != "stopping" and not self.app.install_future)
        self.power.setText("Turn off" if active else "Turn on")
        self.power.setIcon(icon("stop" if active else "power", "white", 17))
        self.mute.setChecked(engine.muted)
        self.mute.setText("Unmute" if engine.muted else "Mute")
        self.mute.setIcon(icon("muted" if engine.muted else "mic", size=17))
        self.mute.setEnabled(not assistant_active)
        duration = engine.duration if engine.state == "running" else 0
        title = {
            "idle": "Off · ready when you are",
            "starting": "Opening audio…",
            "stopping": "Finishing session…",
            "error": "Off · needs attention",
        }.get(engine.state, "Recording locally" if engine.recording else "On · routing only")
        if active and engine.muted:
            title = "Mic muted · " + ("recording" if engine.recording else "routing")
        if assistant_active:
            title, duration = assistant_call_display(self.app.assistant)
            self.mute.setToolTip("Your physical microphone is not used during an AI call.")
        else:
            self.mute.setToolTip(MICROPHONE_MUTE_HELP)
        self.elapsed.setText(timecode(duration)[3:] if duration < 3600 else timecode(duration))
        self.state.setText(title)
        folder = str(self.app.settings.recordings)
        self.storage.setText("Storage · " + folder)
        self.storage.setToolTip(folder)
        browser_text = (
            self.app.browser_feedback or self.app.browser_status
            if self.app.settings.browser_detection_enabled
            else ""
        )
        if browser_text != self.browser_event.toolTip():
            # Long contact and meeting names remain available in the tooltip;
            # the always-visible event summary keeps compact controls compact.
            self.browser_event.setText(
                browser_text[:190] + ("…" if len(browser_text) > 190 else "")
            )
            self.browser_event.setToolTip(browser_text)
            self.browser_event.setVisible(bool(browser_text))
            self.resize_contents()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_start)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_start = None

    def closeEvent(self, event):
        if not self.app.closing:
            self.minimize()
            event.ignore()
        else:
            event.accept()


class Preferences(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        content = QVBoxLayout(self)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(18)
        panel, body = card()
        body.addWidget(label("Always within reach", "sectionTitle"))
        self.startup = QCheckBox("Launch Voice Loop when I sign in")
        self.startup.setChecked(app.settings.launch_at_login)
        self.startup.setToolTip("Starts in the tray with audio off. No recording starts at login.")
        self.startup.toggled.connect(self.change_startup)
        body.addWidget(self.startup)
        body.addWidget(
            label(
                "Closing the main window keeps the tray controls available. Use Quit from the tray to stop Voice Loop.",
                "muted",
                True,
            )
        )
        row = QHBoxLayout()
        row.addWidget(label("Floating control opacity", "fieldLabel"))
        self.opacity_value = label(f"{app.settings.floating_opacity}%", "small")
        row.addStretch()
        row.addWidget(self.opacity_value)
        body.addLayout(row)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(65, 100)
        self.opacity.setValue(app.settings.floating_opacity)
        self.opacity.setAccessibleName("Floating control opacity")
        self.opacity.valueChanged.connect(self.change_opacity)
        self.opacity.sliderReleased.connect(app.save_preferences)
        body.addWidget(self.opacity)
        content.addWidget(panel)
        panel, body = card()
        body.addWidget(label("Screen privacy", "sectionTitle"))
        self.capture_protection = QCheckBox("Hide Voice Loop from screen capture")
        self.capture_protection.setChecked(app.settings.capture_protection)
        self.capture_protection.setEnabled(app.capture_protection.backend.supported)
        self.capture_protection.setToolTip(
            "Applies immediately to the main window, floating controls, and their dialogs. "
            "Turn off to include them in screenshots or screen sharing. This does not change audio recording."
        )
        self.capture_protection.toggled.connect(app.set_capture_protection)
        body.addWidget(self.capture_protection)
        body.addWidget(label(app.capture_protection.backend.limitation, "small", True))
        self.capture_status = label(app.capture_protection.status, "small", True)
        self.capture_status.setTextFormat(Qt.TextFormat.PlainText)
        app.capture_protection.changed.connect(
            lambda: self.capture_status.setText(app.capture_protection.status)
        )
        body.addWidget(self.capture_status)
        content.addWidget(panel)
        panel, body = card()
        body.addWidget(label("Browser calls", "sectionTitle"))
        body.addWidget(
            label(
                "Connect the Voice Loop Chrome extension to detect Zoho Cliq calls and joined Google Meet meetings.",
                "muted",
                True,
            )
        )
        self.browser_enabled = QCheckBox("Detect calls from the paired Chrome extension")
        self.browser_enabled.setChecked(app.settings.browser_detection_enabled)
        self.browser_enabled.setToolTip(
            "Opt in to local call events. Ringing never starts recording. Turn this off to disconnect Chrome and finish any recording it started."
        )
        self.browser_enabled.toggled.connect(app.configure_browser_detection)
        body.addWidget(self.browser_enabled)
        self.browser_automatic = QCheckBox("Automatically record connected calls")
        self.browser_automatic.setChecked(app.settings.browser_auto_record)
        self.browser_automatic.setToolTip(
            "Applies to the next connected call. Incoming and outgoing Cliq calls must be answered; Meet must be joined. Existing manual sessions are kept."
        )
        self.browser_automatic.toggled.connect(app.set_browser_auto_record)
        body.addWidget(self.browser_automatic)
        body.addWidget(
            label(
                "When automatic recording is off, a popup asks after the call connects. "
                "Turning a recording off keeps it off for the rest of that call. "
                "Transcription and uploads follow their separate preference below.",
                "small",
                True,
            )
        )
        body.addWidget(label("Extension pairing code", "fieldLabel"))
        row = QHBoxLayout()
        self.browser_token = QLineEdit()
        self.browser_token.setReadOnly(True)
        self.browser_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.browser_token.setAccessibleName("Extension pairing code")
        self.browser_token.setPlaceholderText("Enable browser detection to pair")
        self.browser_token.setToolTip(
            "Copy this code into the Voice Loop Chrome extension. It authorizes only local call events, not access to recordings or API keys."
        )
        row.addWidget(self.browser_token, 1)
        self.browser_copy = QPushButton("Copy code")
        self.browser_copy.clicked.connect(self.copy_browser_token)
        self.browser_copy_timer = QTimer(self)
        self.browser_copy_timer.setSingleShot(True)
        self.browser_copy_timer.timeout.connect(lambda: self.browser_copy.setText("Copy code"))
        row.addWidget(self.browser_copy)
        body.addLayout(row)
        self.browser_status = label("", "small", True)
        self.browser_status.setTextFormat(Qt.TextFormat.PlainText)
        body.addWidget(self.browser_status)
        content.addWidget(panel)
        self.refresh_browser()
        panel, body = card()
        body.addWidget(label("OpenAI transcription", "sectionTitle"))
        body.addWidget(
            label(
                "Audio is uploaded to your OpenAI account when you transcribe. Your API usage is billed to that account.",
                "muted",
                True,
            )
        )
        self.model = QComboBox()
        self.model.setAccessibleName("OpenAI transcription model")
        for model, description in MODELS.items():
            self.model.addItem(f"{description}  ·  {model}", model)
        self.model.setCurrentIndex(max(0, self.model.findData(app.settings.openai_model)))
        self.model.setToolTip(
            "The diarization model labels speakers within each audio chunk. Contact tags are separate from speaker identity."
        )
        self.model.currentIndexChanged.connect(self.change_model)
        body.addWidget(self.model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Paste your OpenAI API key")
        self.key.setAccessibleName("OpenAI API key")
        body.addWidget(self.key)
        row = QHBoxLayout()
        save = QPushButton("Save API key")
        save.setObjectName("primary")
        save.clicked.connect(self.save_key)
        row.addWidget(save)
        remove = QPushButton("Remove saved key")
        remove.clicked.connect(self.remove_key)
        row.addWidget(remove)
        row.addStretch()
        body.addLayout(row)
        self.key_status = label(
            "Keys are kept in your system credential store, outside recordings and settings.",
            "small",
            True,
        )
        body.addWidget(self.key_status)
        self.automatic = QCheckBox("Automatically upload and transcribe new recorded sessions")
        self.automatic.setChecked(app.settings.auto_transcribe)
        self.automatic.setToolTip(
            "Applies to new recorded sessions after you turn this on. Route-only sessions are never saved or uploaded."
        )
        self.automatic.toggled.connect(self.change_auto)
        body.addWidget(self.automatic)
        body.addWidget(
            label(
                "Each completed transcription saves transcript.json and an offline transcript.html next to the audio.",
                "small",
                True,
            )
        )
        content.addWidget(panel)

    def refresh_browser(self):
        enabled = self.app.settings.browser_detection_enabled
        self.browser_automatic.setEnabled(enabled)
        token = self.app.browser_bridge.pairing_token if self.app.browser_bridge else ""
        if token != self.browser_token.text():
            self.browser_token.setText(token)
        self.browser_copy.setEnabled(enabled and bool(token))
        self.browser_status.setText(self.app.browser_status)

    def copy_browser_token(self):
        token = self.browser_token.text()
        if token:
            QApplication.clipboard().setText(token)
            self.browser_copy.setText("Copied")
            self.browser_copy_timer.start(1800)

    def change_startup(self, enabled):
        from voiceloop.startup import set_enabled

        previous = self.app.settings.launch_at_login
        try:
            set_enabled(enabled)
            self.app.settings.launch_at_login = enabled
            self.app.save_preferences()
        except (OSError, ValueError) as exc:
            self.startup.blockSignals(True)
            self.startup.setChecked(previous)
            self.startup.blockSignals(False)
            QMessageBox.warning(self, "Could not change startup", str(exc))

    def change_opacity(self, value):
        self.app.settings.floating_opacity = value
        self.opacity_value.setText(f"{value}%")
        if self.app.floating:
            self.app.floating.setWindowOpacity(value / 100)
        self.app.save_preferences()

    def change_model(self):
        self.app.settings.openai_model = self.model.currentData()
        self.app.save_preferences()

    def change_auto(self, checked):
        self.app.settings.auto_transcribe = checked
        self.app.save_preferences()

    def save_key(self):
        from voiceloop.credentials import save_key

        try:
            save_key(self.key.text())
            self.key.clear()
            self.key_status.setText(
                "API key saved securely. Choose a recording to transcribe, or enable automatic transcription."
            )
        except (RuntimeError, ValueError) as exc:
            self.key_status.setText(str(exc))

    def remove_key(self):
        from voiceloop.credentials import delete_key

        try:
            delete_key()
            self.key.clear()
            self.key_status.setText(
                "Saved key removed. An OPENAI_API_KEY environment variable, if set, still applies."
            )
        except RuntimeError as exc:
            self.key_status.setText(str(exc))


class LibraryPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.index, self.page, self.sessions = app, SessionLibrary(), 1, []
        content = QVBoxLayout(self)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        panel, body = card()
        body.setContentsMargins(18, 14, 18, 14)
        body.setSpacing(10)
        refresh = QPushButton(icon("refresh", size=16), "Refresh")
        refresh.clicked.connect(self.refresh)
        self.folder = label(str(app.settings.recordings), "small", True)
        self.folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search contact, tool, or date")
        self.search.setAccessibleName("Search recordings")
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.reset_page)
        self.search.textChanged.connect(lambda: self.debounce.start())
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(refresh)
        body.addLayout(search_row)
        filters = QHBoxLayout()
        self.tool, self.state, self.period = QComboBox(), QComboBox(), QComboBox()
        self.tool.setAccessibleName("Filter by meeting tool")
        self.state.setAccessibleName("Filter by recording status")
        self.period.setAccessibleName("Filter by date")
        self.tool.addItem("All tools", "")
        for tool in TOOLS:
            self.tool.addItem(tool, tool)
        for title, value in (
            ("All recordings", ""),
            ("Transcribed", "transcribed"),
            ("Not transcribed", "not_transcribed"),
            ("Complete", "complete"),
            ("Interrupted", "interrupted"),
            ("Unfinished", "unfinished"),
        ):
            self.state.addItem(title, value)
        for title, days in (
            ("Any date", 0),
            ("Last 24 hours", 1),
            ("Last 7 days", 7),
            ("Last 30 days", 30),
        ):
            self.period.addItem(title, days)
        for combo in (self.tool, self.state, self.period):
            combo.currentIndexChanged.connect(self.reset_page)
            filters.addWidget(combo, 1)
        body.addLayout(filters)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["CONTACT / SESSION", "TOOL", "LENGTH", "STATUS"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(85)
        self.table.cellDoubleClicked.connect(lambda *_: self.open())
        self.table.itemSelectionChanged.connect(self.update_actions)
        body.addWidget(self.table, 1)
        self.empty = label(
            "No recordings yet. Choose Record too in the floating control to save your first session.",
            "muted",
            True,
        )
        body.addWidget(self.empty)
        self.count = label("", "small")
        self.previous, self.next = QToolButton(), QToolButton()
        for button, glyph, caption in (
            (self.previous, "previous", "Previous page"),
            (self.next, "next", "Next page"),
        ):
            button.setIcon(icon(glyph, size=18))
            button.setAccessibleName(caption)
            button.setToolTip(caption)
            button.setFixedSize(28, 32)
        self.previous.clicked.connect(lambda: self.move_page(-1))
        self.next.clicked.connect(lambda: self.move_page(1))
        actions = QHBoxLayout()
        self.play_button = QPushButton(icon("play", "white", 16), "Play")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(lambda: self.open(play=True))
        self.view_button = QPushButton("View transcript")
        self.view_button.clicked.connect(self.open)
        self.transcribe_button = QPushButton("Transcribe")
        self.transcribe_button.clicked.connect(self.transcribe)
        for button in (self.play_button, self.view_button, self.transcribe_button):
            button.setStyleSheet("padding:9px 11px;")
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.count)
        actions.addWidget(self.previous)
        actions.addWidget(self.next)
        body.addLayout(actions)
        content.addWidget(panel, 1)
        folders = QHBoxLayout()
        open_folder = QPushButton(icon("folder", size=16), "Open storage folder")
        open_folder.clicked.connect(lambda: app.open_path(app.settings.recordings))
        folders.addWidget(open_folder)
        self.change_folder = QPushButton("Change folder")
        self.change_folder.clicked.connect(app.change_folder)
        folders.addWidget(self.change_folder)
        folders.addStretch()
        content.addLayout(folders)
        content.addWidget(self.folder)
        self.job_status = label("", "small", True)
        content.addWidget(self.job_status)
        self.cancel_job = QPushButton("Cancel transcription")
        self.cancel_job.clicked.connect(app.cancel_transcription)
        self.cancel_job.hide()
        content.addWidget(self.cancel_job, alignment=Qt.AlignmentFlag.AlignLeft)

    def selected(self):
        row = self.table.currentRow()
        return self.sessions[row] if 0 <= row < len(self.sessions) else None

    def reset_page(self):
        self.page = 1
        self.refresh()

    def move_page(self, amount):
        self.page += amount
        self.refresh()

    def refresh(self):
        selected = self.selected()
        previous = selected.directory if selected else None
        try:
            result = self.index.query(
                self.app.settings.recordings,
                text=self.search.text(),
                tool=self.tool.currentData(),
                state=self.state.currentData(),
                days=self.period.currentData(),
                page=self.page,
                active=self.app.engine.saved_path if self.app.engine.active else None,
            )
            self.page, self.sessions = result.number, result.items
            self.table.setRowCount(len(self.sessions))
            for row, session in enumerate(self.sessions):
                date = str(session.info.get("started_at", session.directory.name))[:19].replace(
                    "T", " "
                )
                contact = session.metadata.get("contact", "")
                state = "Transcribed" if session.transcribed else session.status.title()
                values = (
                    f"{contact}\n{date}" if contact else date,
                    session.metadata.get("tool") or "Untagged",
                    timecode(session.info.get("duration_seconds", 0)),
                    state,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, str(session.directory))
                    self.table.setItem(row, column, item)
                self.table.setRowHeight(row, 62)
            self.empty.setVisible(not self.sessions)
            self.empty.setText(
                "No recordings match these filters."
                if self.search.text()
                or self.tool.currentData()
                or self.state.currentData()
                or self.period.currentData()
                else "No recordings yet. Choose Record too in the floating control to save your first session."
            )
            self.count.setText(f"{result.number} / {result.pages}")
            self.count.setToolTip(
                f"{result.total} recordings · Page {result.number} of {result.pages}"
            )
            self.previous.setEnabled(result.number > 1)
            self.next.setEnabled(result.number < result.pages)
            if self.sessions:
                row = next((i for i, s in enumerate(self.sessions) if s.directory == previous), 0)
                self.table.selectRow(row)
            self.folder.setText(str(self.app.settings.recordings))
            self.update_actions()
        except (OSError, ValueError, TypeError) as exc:
            self.empty.setText("Could not read recordings: " + str(exc))
            self.empty.show()

    def update_actions(self):
        session = self.selected()
        usable = bool(session and session.status != "recording")
        live_audio = self.app.engine.active or self.app.assistant.active
        self.play_button.setEnabled(usable and not live_audio)
        self.play_button.setToolTip(
            "Stop the live session or AI Assistant call before playback."
            if live_audio
            else "Play through your selected physical speaker."
        )
        self.view_button.setEnabled(bool(session))
        self.transcribe_button.setEnabled(usable)

    def open(self, _checked=False, *, play=False):
        if session := self.selected():
            self.app.open_session_dialog(session.directory, play=play)

    def transcribe(self):
        if session := self.selected():
            self.app.transcribe_directory(session.directory)


class SessionDialog(QDialog):
    def __init__(self, app, directory):
        super().__init__(app)
        self.app, self.directory = app, Path(directory)
        self.player = None
        self.setWindowTitle("Voice Loop · Session")
        self.resize(850, 760)
        self.setMinimumSize(650, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(14)
        self.info = json.loads((self.directory / "session.json").read_text(encoding="utf-8"))
        self.duration = float(self.info.get("duration_seconds", 0))
        header = QHBoxLayout()
        header.addWidget(label("Session", "pageTitle"), 1)
        self.transcribe = QPushButton("Transcribe with OpenAI")
        self.transcribe.setToolTip(
            "Upload this session's audio to your OpenAI account and save its transcript locally."
        )
        self.transcribe.clicked.connect(lambda: app.transcribe_directory(self.directory))
        header.addWidget(self.transcribe)
        layout.addLayout(header)
        tags = QHBoxLayout()
        self.tool = search_combo("Session tool", TOOLS, "Meeting tool")
        self.contact = search_combo(
            "Session contact", app.contacts.names(), "Search or add contact"
        )
        self.tool.setCurrentText(self.info.get("metadata", {}).get("tool", ""))
        self.contact.setCurrentText(self.info.get("metadata", {}).get("contact", ""))
        tags.addWidget(self.tool, 1)
        tags.addWidget(self.contact, 1)
        save = QPushButton("Save tags")
        save.clicked.connect(self.save_tags)
        tags.addWidget(save)
        layout.addLayout(tags)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setAccessibleName("Transcript")
        self.browser.document().setDefaultStyleSheet(
            "body{color:#20242D;font-size:15px;} h1{font-size:25px;} .note,.subtitle{color:#626977;font-size:13px;} .byline{margin-top:20px;color:#005BC4;} a{color:#005BC4;} .words{margin-bottom:18px;}"
        )
        self.browser.anchorClicked.connect(self.seek_link)
        layout.addWidget(self.browser, 1)
        controls = QHBoxLayout()
        self.play_button = QPushButton(icon("play", "white", 17), "Play")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, max(1, int(self.duration * 1000)))
        self.position.setSingleStep(1000)
        self.position.setPageStep(10000)
        self.position.setAccessibleName("Playback position")
        self.position.setToolTip("Seek · arrow keys 1 second, Page Up / Down 10 seconds")
        self.position.sliderReleased.connect(lambda: self.seek(self.position.value() / 1000))
        self.position.actionTriggered.connect(self.seek_action)
        controls.addWidget(self.position, 1)
        self.time = label("00:00 / " + timecode(self.duration), "small")
        controls.addWidget(self.time)
        layout.addLayout(controls)
        self.status = label(
            "Playback uses your selected physical speaker. Stop a live session before playing audio.",
            "small",
            True,
        )
        layout.addWidget(self.status)
        bottom = QHBoxLayout()
        self.html_button = QPushButton("Open HTML")
        self.html_button.clicked.connect(self.open_html)
        bottom.addWidget(self.html_button)
        self.json_button = QPushButton("Open JSON")
        self.json_button.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.directory / "transcript.json"))
            )
        )
        bottom.addWidget(self.json_button)
        folder = QPushButton("Open session folder")
        folder.clicked.connect(lambda: app.open_path(self.directory))
        bottom.addWidget(folder)
        bottom.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(150)
        self.reload()

    def reload(self):
        exists = (self.directory / "transcript.json").is_file()
        self.html_button.setEnabled(exists)
        self.json_button.setEnabled(exists)
        self.transcribe.setEnabled(self.info.get("status") != "recording")
        if exists:
            try:
                data = json.loads((self.directory / "transcript.json").read_text(encoding="utf-8"))
                data["metadata"] = self.info.get("metadata", {})
                self.browser.setHtml(render_transcript(data, native=True))
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                self.browser.setPlainText("Could not read transcript: " + str(exc))
        else:
            self.browser.setPlainText(
                "No transcript yet.\n\nListen to your recording below, or choose Transcribe with OpenAI to generate speaker-labeled text. A JSON file and an offline HTML view will be saved beside the audio."
            )

    def save_tags(self):
        try:
            contact = self.app.contacts.remember(self.contact.currentText())
            update_metadata(self.directory, tool=self.tool.currentText(), contact=contact)
            self.info = json.loads((self.directory / "session.json").read_text(encoding="utf-8"))
            self.app.refresh_library()
            self.reload()
            self.status.setText("Tags saved. Contact is available in future sessions.")
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def toggle_play(self):
        if self.app.engine.active or self.app.assistant.active:
            self.stop_playback()
            self.status.setText("Turn off the live session or AI Assistant call before playback.")
            return
        if self.player:
            if self.player.paused.is_set():
                self.player.paused.clear()
            else:
                self.player.paused.set()
            return
        try:
            from voiceloop.playback import Player

            device = self.app.selected(self.app.speaker)
            if device is None:
                raise ValueError("Choose a physical speaker in Session first.")
            paths = audio_parts(self.directory, self.info)
            if not paths:
                raise ValueError("This session has no saved audio.")
            self.player = Player(paths, device, self.position.value() / 1000)
            self.status.setText("Playing through " + device.name)
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def seek(self, seconds):
        seconds = max(0, min(self.duration, seconds))
        self.position.setValue(int(seconds * 1000))
        if self.player:
            self.player.seek(seconds)

    def seek_action(self, _action):
        # actionTriggered is user input; tick's setValue never emits it. During
        # dragging, commit only at release so native playback does not thrash.
        if not self.position.isSliderDown():
            self.seek(self.position.sliderPosition() / 1000)

    def seek_link(self, url):
        if url.scheme() == "seek":
            try:
                self.seek(float(url.toString().split(":", 1)[1]))
                if not self.player:
                    self.toggle_play()
            except ValueError:
                pass

    def tick(self):
        live_audio = self.app.engine.active or self.app.assistant.active
        self.play_button.setEnabled(not live_audio)
        if live_audio and self.player:
            self.stop_playback()
            self.status.setText("Playback stopped for the live session or AI Assistant call.")
        if self.player:
            if not self.position.isSliderDown():
                self.position.setValue(int(self.player.position.value / 48))
            self.play_button.setText("Play" if self.player.paused.is_set() else "Pause")
            if result := self.player.poll():
                self.stop_playback()
                self.status.setText(result[1] or "Playback finished.")
                self.position.setValue(0)
        self.time.setText(timecode(self.position.value() / 1000) + " / " + timecode(self.duration))

    def stop_playback(self):
        if self.player:
            self.player.close()
            self.player = None
        self.play_button.setText("Play")

    def open_html(self):
        try:
            path = save_html(self.directory)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except (OSError, ValueError) as exc:
            self.status.setText("Could not open HTML: " + str(exc))

    def closeEvent(self, event):
        self.stop_playback()
        self.timer.stop()
        event.accept()
