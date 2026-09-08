"""Native Qt desktop UI with a restrained, HeroUI-inspired visual system."""

import html
import math
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from voiceloop import __version__
from voiceloop.activity import QUIET_SECONDS
from voiceloop.config import Settings
from voiceloop.devices import (
    Device,
    Devices,
    SessionConfig,
    bridge_endpoints,
    discover,
    is_virtual,
    loopback_for,
    simple_config,
)
from voiceloop.engine import Engine
from voiceloop.library import Contacts

STYLE = """
QWidget { color: #20242D; font-family: 'Segoe UI', 'Helvetica Neue', sans-serif; font-size: 14px; }
QMainWindow, QWidget#workspace { background: #F6F7F9; }
QFrame#sidebar { background: white; border-right: 1px solid #E9EBF0; }
QFrame#card, QFrame#transport { background: white; border: 1px solid #E9EBF0; border-radius: 20px; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 19px; font-weight: 700; }
QLabel#pageTitle { font-size: 28px; font-weight: 700; }
QLabel#sectionTitle { font-size: 18px; font-weight: 600; }
QLabel#muted { color: #626977; }
QLabel#small { color: #626977; font-size: 12px; }
QLabel#fieldLabel { font-size: 13px; font-weight: 600; }
QLabel#badge { background: #ECEEF2; color: #596170; border-radius: 12px; padding: 7px 12px; font-size: 12px; }
QLabel#timer { font-family: 'Consolas', 'Menlo', monospace; font-size: 26px; }
QPushButton { background: #F0F2F5; color: #333B49; border: 1px solid transparent;
              border-radius: 11px; padding: 11px 17px; font-weight: 500; }
QPushButton:hover { background: #E5E9EF; }
QPushButton:pressed { background: #D9E0EA; }
QPushButton:focus, QComboBox:focus, QToolButton:focus { border: 2px solid #338EF7; }
QPushButton:disabled { background: #F2F3F5; color: #A0A5AE; }
QPushButton#primary { background: #006FEE; color: white; }
QPushButton#primary:hover { background: #005BC4; }
QPushButton#primary:disabled { background: #DFEAF8; color: #778FAE; }
QPushButton#nav { text-align: left; padding: 12px 16px; background: transparent; color: #626977; }
QPushButton#nav:hover { background: #F4F6F9; }
QPushButton#nav:checked { background: #EAF2FF; color: #005BC4; font-weight: 600; }
QFrame#segments { background: #F0F2F5; border-radius: 11px; }
QPushButton#segment { padding: 7px 16px; background: transparent; color: #626977; border-radius: 8px; }
QPushButton#segment:checked { background: white; color: #20242D; }
QComboBox { background: #F4F5F7; border: 1px solid #E5E8ED; border-radius: 11px;
            padding: 10px 16px; min-height: 21px; }
QComboBox:hover { background: #EDEFF3; border-color: #CDD4DF; }
QComboBox:disabled { color: #626977; background: #F4F5F7; }
QComboBox::drop-down { width: 30px; border: none; }
QComboBox::down-arrow { image: url("@CHEVRON@"); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: white; color: #20242D; border: 1px solid #DCE2EA;
                            selection-background-color: #EAF2FF; selection-color: #005BC4; padding: 5px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 3px; }
QToolButton:hover { background: #EAF2FF; }
QToolTip { background: #242A35; color: white; border: none; padding: 10px; }
QProgressBar { background: #EDEFF3; border: none; border-radius: 3px; height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #17A673; border-radius: 3px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: #CDD3DC; border-radius: 3px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTableWidget { border: none; background: white; selection-background-color: #EAF2FF;
               selection-color: #005BC4; outline: none; }
QHeaderView::section { background: #F4F5F7; color: #626977; border: none; padding: 12px; font-size: 12px; }
QTableWidget::item { padding: 10px; }
QDialog { background: white; }
QLineEdit { background:#F4F5F7; border:1px solid #E5E8ED; border-radius:10px; padding:11px 13px; placeholder-text-color:#626977; }
QLineEdit:focus, QSlider:focus, QCheckBox:focus { border:2px solid #338EF7; }
QComboBox QLineEdit { background:transparent; border:none; padding:0; }
QCheckBox { spacing:10px; padding:6px 0; }
QCheckBox::indicator { width:18px; height:18px; border:1px solid #8F99A8; border-radius:5px; background:white; }
QCheckBox::indicator:checked { background:#006FEE; border-color:#005BC4; image:url("@CHECK@"); }
QSlider::groove:horizontal { height:6px; border-radius:3px; background:#DFE4EB; }
QSlider::sub-page:horizontal { background:#006FEE; border-radius:3px; }
QSlider::handle:horizontal { background:#006FEE; border:2px solid white; width:16px; margin:-6px 0; border-radius:9px; }
QPushButton:checked { background:#EAF2FF; color:#005BC4; border:1px solid #B3D3FA; }
QTextBrowser { border:1px solid #E9EBF0; border-radius:12px; padding:14px; background:white; }
QMenu { background:white; color:#20242D; border:1px solid #DCE2EA; padding:6px; }
QMenu::item { padding:9px 24px; border-radius:5px; }
QMenu::item:selected { background:#EAF2FF; color:#005BC4; }
QMenu::item:disabled { color:#87909D; }
"""

PATHS = {
    "mic": '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
    "speaker": '<path d="M11 5 6 9H3v6h3l5 4V5ZM16 8a6 6 0 0 1 0 8M19 5a10 10 0 0 1 0 14"/>',
    "session": '<path d="M3 10v4M7 6v12M12 3v18M17 6v12M21 10v4"/>',
    "devices": '<rect x="3" y="4" width="18" height="12" rx="3"/><path d="M8 21h8M12 16v5M7 9h.01M11 9h6"/>',
    "folder": '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    "refresh": '<path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3"/>',
    "record": '<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
    "power": '<path d="M12 2v10M6 5a9 9 0 1 0 12 0"/>',
    "muted": '<path d="m3 3 18 18M9 9v3a3 3 0 0 0 5 2M9 5a3 3 0 0 1 6 0v4M5 10v2a7 7 0 0 0 12 5M19 10v2M12 19v3M8 22h8"/>',
    "play": '<path d="m8 4 12 8-12 8V4Z"/>',
    "expand": '<path d="M14 3h7v7M21 3l-9 9M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
    "minimize": '<path d="M5 17h14"/>',
    "collapse": '<path d="m6 14 6-6 6 6"/>',
    "chevron": '<path d="m6 10 6 6 6-6"/>',
    "previous": '<path d="m14 5-7 7 7 7"/>',
    "next": '<path d="m10 5 7 7-7 7"/>',
    "settings": '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2" fill="white"/><circle cx="15" cy="12" r="2" fill="white"/><circle cx="8" cy="18" r="2" fill="white"/>',
}


def icon(name, color="#697386", size=22):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" color="{color}" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def label(text, name="", wrap=False):
    result = QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


class HelpButton(QToolButton):
    def __init__(self, title, explanation):
        super().__init__()
        self.setIcon(icon("info", size=16))
        self.setIconSize(QSize(16, 16))
        self.setAccessibleName(title)
        self.setToolTip(f"<qt>{html.escape(explanation)}</qt>")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.show_help)

    def show_help(self):
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height() + 4)), self.toolTip(), self)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.show_help()

    def focusOutEvent(self, event):
        QToolTip.hideText()
        super().focusOutEvent(event)


def field(title, tooltip, glyph=None):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    row = QHBoxLayout()
    row.setSpacing(7)
    if glyph:
        image = QLabel()
        image.setPixmap(icon(glyph, size=17).pixmap(17, 17))
        row.addWidget(image)
    caption = label(title, "fieldLabel")
    row.addWidget(caption)
    row.addWidget(HelpButton("About " + title.lower(), tooltip))
    row.addStretch()
    layout.addLayout(row)
    combo = QComboBox()
    combo.setAccessibleName(title)
    combo.setToolTip(f"<qt>{html.escape(tooltip)}</qt>")
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    combo.setMinimumWidth(0)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(12)
    caption.setBuddy(combo)
    layout.addWidget(combo)
    return widget, combo


def card():
    result = QFrame()
    result.setObjectName("card")
    layout = QVBoxLayout(result)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(14)
    return result, layout


class ConsentDialog(QDialog):
    def __init__(self, directory, bridge, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record this session?")
        self.setMinimumWidth(520)
        self.choice = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)
        layout.addWidget(label("Record this session?", "pageTitle"))
        layout.addWidget(
            label(
                "Save your voice and meeting audio on this device.\n"
                "Make sure everyone knows you are recording.",
                "muted",
                True,
            )
        )
        layout.addWidget(label(str(directory), "small", True))
        row = QHBoxLayout()
        self.record_button = QPushButton("Record session")
        self.record_button.setObjectName("primary")
        self.record_button.setAutoDefault(False)
        self.record_button.clicked.connect(lambda: self.choose(True))
        row.addWidget(self.record_button)
        self.route_button = QPushButton("Route audio only" if bridge else "Monitor only")
        self.route_button.setAutoDefault(False)
        self.route_button.setToolTip("Audio stays in memory. No recording files are created.")
        self.route_button.clicked.connect(lambda: self.choose(False))
        row.addWidget(self.route_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.cancel_button.setFocus()

    def choose(self, record):
        self.choice = record
        self.accept()


class App(QMainWindow):
    def __init__(self, *, settings=None, device_provider=discover, engine=None, contacts=None):
        super().__init__()
        self.settings = settings or Settings.load()
        self.device_provider = device_provider
        self.engine = engine or Engine()
        self.contacts = contacts or Contacts()
        self.tray = self.floating = None
        self.desktop_enabled = False
        self.dialogs = []
        self.job = None
        self.job_queue = deque()
        self.pending_switch = {}
        self.resume_record = None
        self._run_auto = False
        self._handled_paths = set()
        self.silence_prompt = None
        self._silence_snooze_until = 0.0
        self.devices = Devices([], [])
        self.last_state = "idle"
        self.closing = False
        self.install_future = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voiceloop-setup")
        self.setWindowTitle("Voice Loop")
        self.setWindowIcon(icon("session", "#006FEE", 32))
        self.resize(1060, 820)
        self.setMinimumSize(820, 640)
        self._build()
        self.refresh_devices()
        self.refresh_library()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def _build(self):
        root = QWidget()
        root.setObjectName("workspace")
        self.setCentralWidget(root)
        horizontal = QHBoxLayout(root)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(16, 28, 16, 22)
        nav.setSpacing(8)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon("session", "#006FEE", 25).pixmap(25, 25))
        brand.addWidget(mark)
        brand.addWidget(label("Voice Loop", "brand"))
        brand.addStretch()
        nav.addLayout(brand)
        nav.addSpacing(30)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for index, (name, glyph) in enumerate(
            (
                ("Session", "session"),
                ("Audio setup", "devices"),
                ("Recordings", "folder"),
                ("Preferences", "settings"),
            )
        ):
            button = QPushButton(icon(glyph), name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setIconSize(QSize(19, 19))
            self.nav_group.addButton(button, index)
            nav.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_group.idClicked.connect(self.navigate)
        self.nav_buttons[0].setChecked(True)
        nav.addStretch()
        float_button = QPushButton(icon("expand", size=17), "Floating controls")
        float_button.clicked.connect(self.show_floating)
        nav.addWidget(float_button)
        nav.addWidget(label("Your audio stays yours.", "small"))
        nav.addWidget(label(f"Voice Loop {__version__}", "small"))
        horizontal.addWidget(sidebar)
        main = QVBoxLayout()
        main.setContentsMargins(26, 22, 26, 18)
        main.setSpacing(14)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(5)
        self.page_title = label("Session", "pageTitle")
        self.page_subtitle = label("Good notes start with clear audio.", "muted")
        heading.addWidget(self.page_title)
        heading.addWidget(self.page_subtitle)
        header.addLayout(heading)
        header.addStretch()
        self.badge = label("Not recording", "badge")
        header.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
        main.addLayout(header)
        self.pages = QStackedWidget()
        for build in (
            self._session_page,
            self._setup_page,
            self._library_page,
            self._preferences_page,
        ):
            page = QWidget()
            page.setObjectName("workspace")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 4, 0)
            layout.setSpacing(18)
            build(layout)
            if build.__name__ == "_library_page":
                self.pages.addWidget(page)
                continue
            layout.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.pages.addWidget(scroll)
        main.addWidget(self.pages, 1)
        self._transport(main)
        horizontal.addLayout(main, 1)

    def _session_page(self, layout):
        panel, content = card()
        header = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(5)
        title.addWidget(label("Audio devices", "sectionTitle"))
        title.addWidget(label("Choose what you speak into and listen through.", "muted", True))
        header.addLayout(title, 1)
        self.refresh_button = QPushButton(icon("refresh", size=17), "Refresh")
        self.refresh_button.setToolTip("Find connected devices. Available between sessions.")
        self.refresh_button.clicked.connect(self.refresh_devices)
        header.addWidget(self.refresh_button)
        content.addLayout(header)
        segmented = QFrame()
        segmented.setObjectName("segments")
        row = QHBoxLayout(segmented)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(3)
        self.level_group = QButtonGroup(self)
        for index, text in enumerate(("Simple", "Advanced")):
            button = QPushButton(text)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setToolTip(
                "Choose a physical microphone and speaker. Routing is automatic."
                if index == 0
                else "Choose routing mode, virtual paths, and left/right recording channels."
            )
            self.level_group.addButton(button, index)
            row.addWidget(button)
        self.level_group.button(1 if self.settings.setup_level == "advanced" else 0).setChecked(
            True
        )
        self.level_group.idClicked.connect(self.level_changed)
        segment_row = QHBoxLayout()
        segment_row.addWidget(segmented)
        segment_row.addStretch()
        content.addLayout(segment_row)
        self.device_controls = []
        for name, title, tip, glyph in (
            (
                "microphone",
                "Microphone",
                "Your physical microphone. Your voice is delivered to VoiceLoop Mic when virtual devices are ready.",
                "mic",
            ),
            (
                "speaker",
                "Speaker",
                "Your physical headphones or speakers. Meeting audio plays here. Headphones help prevent echo.",
                "speaker",
            ),
        ):
            widget, combo = field(title, tip, glyph)
            setattr(self, name, combo)
            self.device_controls.append(combo)
            combo.currentIndexChanged.connect(self.physical_changed)
            content.addWidget(widget)
        self.advanced = QWidget()
        advanced = QVBoxLayout(self.advanced)
        advanced.setContentsMargins(0, 8, 0, 0)
        advanced.setSpacing(18)
        routing, self.mode = field(
            "Audio routing",
            "Direct capture records microphone and speaker audio without rerouting your meeting. Virtual bridge routes through VoiceLoop Mic and VoiceLoop Speaker; it requires installed virtual devices.",
        )
        self.mode.addItem("Direct capture", "direct")
        self.mode.addItem("Virtual bridge", "bridge")
        self.mode.setCurrentIndex(1 if self.settings.mode == "bridge" else 0)
        self.mode.currentIndexChanged.connect(self.routing_changed)
        advanced.addWidget(routing)
        widget, self.meeting = field(
            "Meeting audio source",
            "Audio from the other participants. In Direct capture use your speaker's system-audio loopback. In Virtual bridge use VoiceLoop Speaker.",
        )
        advanced.addWidget(widget)
        self.feed_field, self.feed = field(
            "Virtual microphone feed",
            "The playback side of the microphone cable. Voice Loop sends your microphone here so the meeting receives VoiceLoop Mic. Keep this path separate from VoiceLoop Speaker.",
        )
        advanced.addWidget(self.feed_field)
        channels = QHBoxLayout()
        for name, title in (("left_channel", "Left channel"), ("right_channel", "Right channel")):
            widget, combo = field(
                title,
                "Choose what is saved on this WAV channel. This changes the recording layout, not what you or the meeting hears.",
            )
            combo.addItem("Microphone", "microphone")
            combo.addItem("Meeting audio", "meeting")
            combo.setCurrentIndex(0 if getattr(self.settings, name) == "microphone" else 1)
            setattr(self, name, combo)
            channels.addWidget(widget, 1)
        self.left_channel.currentIndexChanged.connect(
            lambda i: self.right_channel.setCurrentIndex(1 - i)
        )
        self.right_channel.currentIndexChanged.connect(
            lambda i: self.left_channel.setCurrentIndex(1 - i)
        )
        advanced.addLayout(channels)
        self.device_controls += [
            self.mode,
            self.meeting,
            self.feed,
            self.left_channel,
            self.right_channel,
        ]
        content.addWidget(self.advanced)
        self.advanced.setVisible(self.level_group.checkedId() == 1)
        layout.addWidget(panel)
        panel, content = card()
        heading = QHBoxLayout()
        heading.addWidget(label("In your meeting app", "sectionTitle"))
        heading.addStretch()
        self.path_badge = label("Checking devices", "badge")
        heading.addWidget(self.path_badge)
        content.addLayout(heading)
        self.path_text = label("", "muted", True)
        content.addWidget(self.path_text)
        self.setup_link = QPushButton("Set up VoiceLoop devices")
        self.setup_link.clicked.connect(lambda: self.navigate(1))
        content.addWidget(self.setup_link, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(panel)

    def _setup_page(self, layout):
        panel, content = card()
        content.addWidget(label("One setup. Two familiar names.", "sectionTitle"))
        content.addWidget(
            label(
                "Select these devices in your meeting app. Your physical devices stay selectable in Voice Loop.",
                "muted",
                True,
            )
        )
        for glyph, name, description in (
            ("mic", "VoiceLoop Mic", "Your voice, delivered to the meeting"),
            ("speaker", "VoiceLoop Speaker", "Meeting audio, delivered to your speaker"),
        ):
            row = QHBoxLayout()
            image = QLabel()
            image.setPixmap(icon(glyph, "#006FEE", 25).pixmap(25, 25))
            row.addWidget(image)
            column = QVBoxLayout()
            column.addWidget(label(name, "fieldLabel"))
            column.addWidget(label(description, "small", True))
            row.addLayout(column, 1)
            content.addLayout(row)
        self.setup_status = label("Checking installed devices…", "muted", True)
        content.addWidget(self.setup_status)
        self.install_button = QPushButton("Set up audio devices")
        self.install_button.setObjectName("primary")
        self.install_button.setToolTip(
            "Install virtual audio drivers and configure the VoiceLoop names. Your operating system may ask for administrator approval and a restart."
        )
        self.install_button.clicked.connect(self.install_devices)
        content.addWidget(self.install_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.setup_progress = QProgressBar()
        self.setup_progress.setRange(0, 0)
        self.setup_progress.hide()
        content.addWidget(self.setup_progress)
        layout.addWidget(panel)
        panel, content = card()
        content.addWidget(label("Audio drivers", "sectionTitle"))
        if sys.platform == "win32":
            detail = "Windows setup uses VB-CABLE for the microphone path and VB-Audio Hi-Fi Cable for the speaker path. A restart may be needed after installation."
            attribution = '<a href="https://vb-audio.com/Cable/">VB-Audio Software</a> · Donationware; contributions are welcome.'
        elif sys.platform == "darwin":
            detail = "macOS setup installs BlackHole 2ch and 16ch, then creates named VoiceLoop devices. Allow microphone access when macOS asks. A restart may be required."
            attribution = '<a href="https://github.com/ExistentialAudio/BlackHole">BlackHole by Existential Audio</a> · Open-source audio routing.'
        else:
            detail = "Linux setup creates virtual devices in your PulseAudio or PipeWire session. No administrator access is needed."
            attribution = "Powered by your existing PulseAudio or PipeWire service."
        content.addWidget(label(detail, "muted", True))
        attribution = attribution.replace("<a href=", '<a style="color:#005BC4" href=')
        link = label(attribution, "small", True)
        link.setAccessibleName("Audio driver attribution and licensing")
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        link.setOpenExternalLinks(True)
        content.addWidget(link)
        layout.addWidget(panel)

    def _library_page(self, layout):
        from voiceloop.ui_extras import LibraryPanel

        self.library_panel = LibraryPanel(self)
        layout.addWidget(self.library_panel, 1)
        self.library = self.library_panel.table
        self.folder_label = self.library_panel.folder
        self.change_folder_button = self.library_panel.change_folder

    def _preferences_page(self, layout):
        from voiceloop.ui_extras import Preferences

        self.preferences = Preferences(self)
        layout.addWidget(self.preferences)

    def _transport(self, main):
        transport = QFrame()
        self.transport = transport
        transport.setObjectName("transport")
        content = QVBoxLayout(transport)
        content.setContentsMargins(20, 16, 20, 16)
        content.setSpacing(14)
        row = QHBoxLayout()
        row.setSpacing(20)
        self.meters, self.level_labels = [], []
        for title in ("Microphone", "Meeting audio"):
            column = QVBoxLayout()
            labels = QHBoxLayout()
            labels.addWidget(label(title, "small"))
            labels.addStretch()
            level = label("—", "small")
            labels.addWidget(level)
            column.addLayout(labels)
            meter = QProgressBar()
            meter.setRange(0, 100)
            meter.setValue(0)
            meter.setTextVisible(False)
            meter.setAccessibleName(title + " level")
            meter.setToolTip("Live input level. No audio is captured until a session starts.")
            column.addWidget(meter)
            row.addLayout(column, 1)
            self.meters.append(meter)
            self.level_labels.append(level)
        content.addLayout(row)
        controls = QHBoxLayout()
        self.start_button = QPushButton(icon("record", "white", 17), "Start session")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start)
        self.start_button.setToolTip("Choose whether to record before any audio device opens.")
        self.stop_button = QPushButton(icon("stop", size=16), "Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_session)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        self.mute_button = QPushButton("Mute mic")
        self.mute_button.setCheckable(True)
        self.mute_button.setToolTip(
            "Mutes VoiceLoop's microphone feed and recording. In Direct capture, mute the meeting app too."
        )
        self.mute_button.clicked.connect(self.toggle_mute)
        controls.addWidget(self.mute_button)
        controls.addStretch()
        self.clock = label("00:00:00", "timer")
        controls.addWidget(self.clock)
        content.addLayout(controls)
        main.addWidget(transport)
        self.status = label("Ready when you are. Recording is always your choice.", "small", True)
        self.status.setAccessibleName("Session status")
        main.addWidget(self.status)

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.transport.setVisible(index != 2)
        self.nav_buttons[index].setChecked(True)
        self.page_title.setText(("Session", "Audio setup", "Recordings", "Preferences")[index])
        self.page_subtitle.setText(
            (
                "Good notes start with clear audio.",
                "Connect once. Keep every meeting simple.",
                "Your conversations, kept locally.",
                "Make Voice Loop fit your day.",
            )[index]
        )

    @staticmethod
    def selected(combo):
        data = combo.currentData()
        return data if isinstance(data, Device) else None

    @staticmethod
    def fill(combo, items, preferred=""):
        combo.blockSignals(True)
        combo.clear()
        for device in items:
            combo.addItem(device.label, device)
            combo.setItemData(combo.count() - 1, device.label, Qt.ItemDataRole.ToolTipRole)
        match = next((i for i, d in enumerate(items) if d.id == preferred), -1)
        combo.setCurrentIndex(match if preferred else (0 if items else -1))
        combo.setPlaceholderText(
            "Device unavailable — choose another" if preferred else "No devices found"
        )
        combo.blockSignals(False)

    def refresh_devices(self):
        if self.engine.active or self.install_future:
            return
        before = {
            name: self.selected(getattr(self, name))
            for name in ("microphone", "speaker", "meeting", "feed")
        }
        try:
            if sys.platform == "darwin":
                from voiceloop.installation import finalize_mac_devices

                try:
                    finalize_mac_devices()
                except (RuntimeError, OSError):
                    pass  # Audio setup explains missing drivers; ordinary discovery still works.
            self.devices = self.device_provider()
            for name, items, saved, default in (
                (
                    "microphone",
                    [d for d in self.devices.inputs if not d.loopback and not is_virtual(d)],
                    self.settings.microphone_id,
                    self.devices.default_input,
                ),
                (
                    "speaker",
                    [d for d in self.devices.outputs if not is_virtual(d)],
                    self.settings.speaker_id,
                    self.devices.default_output,
                ),
                ("meeting", self.devices.inputs, self.settings.meeting_input_id, ""),
                ("feed", self.devices.outputs, self.settings.virtual_mic_output_id, ""),
            ):
                preferred = before[name].id if before[name] else saved
                if not preferred and any(d.id == default for d in items):
                    preferred = default
                self.fill(getattr(self, name), items, preferred)
            self.feed_field.setVisible(self.mode.currentData() == "bridge")
            if not (before["meeting"] or self.settings.meeting_input_id):
                self.routing_changed()
            self.status.setText("Devices refreshed. Ready when you are.")
        except Exception as exc:
            self.status.setText(
                f"Could not read audio devices: {exc}. Check permissions and refresh."
            )
        self.update_paths()
        self.update_enabled()

    def physical_changed(self, *_):
        if self.mode.currentData() == "direct" and (speaker := self.selected(self.speaker)):
            if source := loopback_for(speaker, self.devices):
                self.fill(self.meeting, self.devices.inputs, source.id)
        self.update_paths()

    def routing_changed(self, *_):
        bridge = self.mode.currentData() == "bridge"
        self.feed_field.setVisible(bridge)
        if bridge:
            if endpoints := bridge_endpoints(self.devices):
                self.fill(self.meeting, self.devices.inputs, endpoints.meeting_source.id)
                self.fill(self.feed, self.devices.outputs, endpoints.microphone_feed.id)
        else:
            self.physical_changed()
        self.update_paths()

    def level_changed(self, index):
        self.advanced.setVisible(index == 1)
        self.update_paths()

    def update_paths(self):
        ready = bridge_endpoints(self.devices) is not None
        use_bridge = (
            ready if self.level_group.checkedId() == 0 else self.mode.currentData() == "bridge"
        )
        self.path_badge.setText(
            "Virtual devices ready"
            if ready
            else "Direct capture available"
            if sys.platform != "darwin"
            else "Setup needed"
        )
        self.path_text.setText(
            "Microphone:  VoiceLoop Mic\nSpeaker:  VoiceLoop Speaker\nKeep this session running while your meeting uses these devices."
            if use_bridge
            else "Use the same physical microphone and speaker selected above. Direct capture includes other apps playing on that speaker."
        )
        self.setup_link.setVisible(not ready)
        self.setup_status.setText(
            "VoiceLoop Mic and VoiceLoop Speaker are installed and ready."
            if ready
            else "Complete audio setup to use the VoiceLoop devices in your meeting app."
        )
        self.install_button.setText("Repair audio setup" if ready else "Set up audio devices")

    def configuration(self):
        microphone, speaker = self.selected(self.microphone), self.selected(self.speaker)
        if not microphone or not speaker:
            raise ValueError("Choose an available microphone and speaker first.")
        if self.level_group.checkedId() == 0:
            return simple_config(microphone, speaker, self.devices)
        meeting = self.selected(self.meeting)
        if meeting is None:
            raise ValueError("Choose a meeting audio source in Advanced.")
        config = SessionConfig(
            microphone,
            meeting,
            speaker,
            self.selected(self.feed) if self.mode.currentData() == "bridge" else None,
            self.mode.currentData(),
            self.left_channel.currentData(),
            self.right_channel.currentData(),
        )
        config.validate()
        return config

    def start(self, _checked=False, *, record=None):
        if self.engine.active or self.install_future:
            return
        try:
            if self.floating:
                self.floating.save_tags()
            config = self.configuration()
            if record is None:
                dialog = ConsentDialog(self.settings.recordings, config.mode == "bridge", self)
                dialog.exec()
                if dialog.choice is None:
                    return
                record = dialog.choice
            self.settings.session_mode = "record" if record else "route"
            if self.floating:
                self.floating.mode.blockSignals(True)
                self.floating.mode.setCurrentIndex(1 if record else 0)
                self.floating.mode.blockSignals(False)
            self.settings.microphone_id, self.settings.speaker_id = (
                config.microphone.id,
                config.speaker.id,
            )
            self.settings.meeting_input_id = config.meeting.id
            if config.virtual_mic:
                self.settings.virtual_mic_output_id = config.virtual_mic.id
            self.settings.mode = config.mode
            self.settings.setup_level = (
                "advanced" if self.level_group.checkedId() == 1 else "simple"
            )
            self.settings.left_channel, self.settings.right_channel = (
                config.left_channel,
                config.right_channel,
            )
            self.settings.save()
            for viewer in self.dialogs:
                viewer.stop_playback()
            self.engine.start(
                config,
                self.settings.recordings,
                record=record,
                metadata={
                    "tool": self.settings.meeting_tool,
                    "contact": self.settings.contact_name,
                },
            )
            self.dismiss_silence_prompt()
            self._silence_snooze_until = 0.0
            self._run_auto = bool(record and self.settings.auto_transcribe)
            if self.floating:
                self.floating.show_notice("")
            self.status.setText("Opening your audio devices…")
            self.update_enabled()
        except Exception as exc:
            self.status.setText("Cannot start: " + str(exc))
            if self.floating and self.floating.isVisible():
                self.floating.show_notice(str(exc))
            else:
                QMessageBox.warning(self, "Cannot start session", str(exc))

    def update_enabled(self):
        active = self.engine.active or self.install_future is not None
        for control in self.device_controls + self.level_group.buttons():
            control.setEnabled(not active)
        for button in (
            self.start_button,
            self.refresh_button,
            self.change_folder_button,
            self.install_button,
        ):
            button.setEnabled(not active)
        self.stop_button.setEnabled(self.engine.state in ("starting", "running"))
        self.library_panel.update_actions()

    def tick(self):
        seconds = int(self.engine.duration) if self.engine.state == "running" else 0
        self.clock.setText(f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}")
        for index, meter in enumerate(self.meters):
            db = 20 * math.log10(max(self.engine.levels[index], 1e-6))
            meter.setValue(round(max(0, min(100, (db + 60) / 60 * 100))))
            self.level_labels[index].setText(
                f"{db:.0f} dB" if self.engine.state == "running" and db > -60 else "—"
            )
        state = self.engine.state
        if self.floating:
            self.floating.refresh()
        self.check_speaker_silence()
        if state != self.last_state:
            self.update_enabled()
            if state == "running":
                self.badge.setText(
                    "Recording" if self.engine.recording else "Audio active · not recording"
                )
                self.status.setText(
                    "Recording locally. Stop the session to finish saving."
                    if self.engine.recording
                    else "Audio is active. No recording files are being saved."
                )
            elif state in ("starting", "stopping"):
                self.badge.setText("Starting…" if state == "starting" else "Finishing…")
            else:
                self.badge.setText("Session stopped" if self.engine.error else "Not recording")
                self.status.setText(
                    self.engine.error
                    or (
                        "Recording saved to " + str(self.engine.saved_path)
                        if self.engine.saved_path
                        else "Session ended. No audio was saved."
                    )
                )
                self.refresh_library()
                path = self.engine.saved_path
                if path and path not in self._handled_paths:
                    self._handled_paths.add(path)
                    if self._run_auto and not self.engine.error and not self.closing:
                        self.transcribe_directory(path, automatic=True)
                if self.floating and self.engine.error:
                    self.floating.show_notice(self.engine.error)
                if self.closing:
                    self.close()
                elif self.pending_switch:
                    switches, self.pending_switch = self.pending_switch, {}
                    record, self.resume_record = self.resume_record, None
                    for name, device in switches.items():
                        items = (
                            self.devices.inputs if name == "microphone" else self.devices.outputs
                        )
                        self.fill(
                            getattr(self, name),
                            [d for d in items if not is_virtual(d) and not d.loopback],
                            device.id,
                        )
                    self.physical_changed()
                    if not self.engine.error and record is not None:
                        QTimer.singleShot(0, lambda: self.start(record=record))
            self.last_state = state
        self.tick_transcription()
        if self.install_future and self.install_future.done():
            future, self.install_future = self.install_future, None
            self.setup_progress.hide()
            try:
                result = future.result()
                self.refresh_devices()
                self.setup_status.setText(result)
                self.status.setText(result)
            except Exception as exc:
                self.setup_status.setText("Setup needs attention: " + str(exc))
                self.status.setText("Audio setup was not completed. See Audio setup for details.")
            self.update_enabled()

    def install_devices(self):
        if self.engine.active or self.install_future:
            return
        from voiceloop.installation import install_audio_devices

        self.setup_status.setText(
            "Setting up audio devices. Approve the operating-system prompt if it appears. This can take a few minutes."
        )
        self.setup_progress.show()
        self.install_future = self.executor.submit(install_audio_devices)
        self.update_enabled()

    def refresh_library(self):
        self.library_panel.refresh()

    def open_selected(self):
        self.library_panel.open()

    def open_path(self, path):
        try:
            path.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise OSError("Your file manager could not open this folder.")
        except OSError as exc:
            QMessageBox.warning(self, "Cannot open folder", str(exc))

    def change_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Save recordings to", str(self.settings.recordings)
        )
        if folder:
            previous = self.settings.recording_directory
            try:
                self.settings.recording_directory = folder
                self.settings.save()
                self.folder_label.setText(folder)
                self.refresh_library()
            except OSError as exc:
                self.settings.recording_directory = previous
                QMessageBox.warning(self, "Cannot save settings", str(exc))

    def save_preferences(self):
        try:
            self.settings.save()
        except OSError as exc:
            self.status.setText("Could not save preferences: " + str(exc))

    def show_main(self, index=None):
        # clicked() supplies a bool; it must not unexpectedly switch the page.
        if type(index) is int:
            self.navigate(index)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_floating(self):
        if self.floating is None:
            from voiceloop.ui_extras import FloatingControls

            self.floating = FloatingControls(self)
            geometry = self.screen().availableGeometry()
            self.floating.move(
                geometry.right() - self.floating.width() - 24,
                geometry.bottom() - self.floating.sizeHint().height() - 32,
            )
        self.floating.show()
        self.floating.raise_()
        self.floating.activateWindow()

    def toggle_mute(self, *_):
        self.engine.set_muted(not self.engine.muted)
        self.mute_button.setChecked(self.engine.muted)
        self.mute_button.setText("Unmute mic" if self.engine.muted else "Mute mic")
        if self.engine.muted:
            direct = self.settings.mode == "direct"
            self.status.setText(
                "Microphone muted in Voice Loop."
                + (" Direct capture: your meeting app's microphone is unchanged." if direct else "")
            )
            if self.floating:
                self.floating.show_notice(
                    "Direct capture: mute the microphone in your meeting app too." if direct else ""
                )
        elif self.floating:
            self.floating.show_notice("")

    def stop_session(self, *, trim_silence=False):
        self.dismiss_silence_prompt()
        self.pending_switch = {}
        self.resume_record = None
        self.engine.stop(trim_silence=True) if trim_silence else self.engine.stop()
        if self.floating:
            self.floating.refresh()
        self.clock.setText("00:00:00")

    def dismiss_silence_prompt(self):
        if self.silence_prompt is not None:
            prompt, self.silence_prompt = self.silence_prompt, None
            prompt.reject()
            prompt.deleteLater()

    def check_speaker_silence(self):
        quiet = (
            self.engine.state == "running"
            and self.engine.recording
            and not self.closing
            and self.engine.activity.speaker_quiet_seconds >= QUIET_SECONDS
        )
        if not quiet:
            self.dismiss_silence_prompt()
            return
        if self.silence_prompt is not None or self.engine.duration < self._silence_snooze_until:
            return
        parent = self.floating if self.floating and self.floating.isVisible() else self
        prompt = QMessageBox(parent)
        self.silence_prompt = prompt
        prompt.setWindowTitle("Speaker has been quiet")
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setText("No voice energy on the speaker for 30 seconds. Stop recording?")
        prompt.setInformativeText(
            "Stop and trim ends this session and audio routing, then removes trailing silence. "
            "Speech from either channel is kept, with a short ending buffer. "
            "Keep recording leaves the audio untouched."
        )
        prompt.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        prompt.button(QMessageBox.StandardButton.Yes).setText("Stop and trim")
        prompt.button(QMessageBox.StandardButton.No).setText("Keep recording")
        prompt.setDefaultButton(QMessageBox.StandardButton.No)
        prompt.setEscapeButton(QMessageBox.StandardButton.No)
        prompt.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        def answered(choice):
            if self.silence_prompt is not prompt:
                return
            self.silence_prompt = None
            prompt.deleteLater()
            if choice == QMessageBox.StandardButton.Yes:
                if self.engine.state == "running" and self.engine.recording:
                    self.stop_session(trim_silence=True)
            else:
                self._silence_snooze_until = self.engine.duration + QUIET_SECONDS

        prompt.finished.connect(answered)
        prompt.open()

    def switch_device(self, name, device):
        if self.install_future or is_virtual(device):
            return
        current = self.selected(getattr(self, name))
        if current and current.id == device.id:
            return
        if self.engine.active:
            self.pending_switch[name] = device
            if self.resume_record is None:
                self.resume_record = self.engine.recording
            self.engine.stop()
            self.status.setText("Finishing this session, then starting with the new device…")
        else:
            items = self.devices.inputs if name == "microphone" else self.devices.outputs
            self.fill(
                getattr(self, name),
                [d for d in items if not is_virtual(d) and not d.loopback],
                device.id,
            )
            self.physical_changed()
            setattr(self.settings, name + "_id", device.id)
            self.save_preferences()

    def open_session_dialog(self, directory, *, play=False):
        from voiceloop.ui_extras import SessionDialog

        try:
            viewer = SessionDialog(self, directory)
            self.dialogs.append(viewer)
            viewer.finished.connect(
                lambda *_: self.dialogs.remove(viewer) if viewer in self.dialogs else None
            )
            viewer.show()
            if play:
                viewer.toggle_play()
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Cannot open session", str(exc))

    def transcribe_directory(self, directory, *, automatic=False):
        directory = Path(directory).resolve()
        if (self.job and self.job.directory == directory) or any(
            path == directory for path, _ in self.job_queue
        ):
            self.library_panel.job_status.setText(
                "This recording is already queued for transcription."
            )
            return
        if not automatic:
            answer = QMessageBox.question(
                self,
                "Transcribe with OpenAI?",
                "Upload this recording's audio to OpenAI using your configured model and API key? "
                "API charges apply. The JSON and HTML transcript will be saved beside the audio.",
                defaultButton=QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.job_queue.append((directory, self.settings.openai_model))
        self.tick_transcription()

    def tick_transcription(self):
        if self.job:
            for kind, message in self.job.poll():
                self.library_panel.job_status.setText(
                    message
                    if kind != "complete"
                    else "Transcript saved. Select View transcript to read it."
                )
                if kind == "complete":
                    self.refresh_library()
                    for viewer in self.dialogs:
                        if viewer.directory.resolve() == self.job.directory:
                            viewer.reload()
                elif kind == "error" and self.floating:
                    self.floating.show_notice(message)
            if self.job.finished:
                self.job.close()
                self.job = None
        if self.job is None and self.job_queue and not self.closing:
            from voiceloop.credentials import get_key
            from voiceloop.jobs import TranscriptionJob

            directory, model = self.job_queue.popleft()
            try:
                key = get_key()
                if not key:
                    raise RuntimeError(
                        "Add your OpenAI API key in Preferences, then retry this recording."
                    )
                self.job = TranscriptionJob(directory, key, model)
                self.library_panel.job_status.setText("Transcribing with " + model + "…")
            except (RuntimeError, OSError, ValueError) as exc:
                self.library_panel.job_status.setText(str(exc))
                if self.floating:
                    self.floating.show_notice(str(exc))
        self.library_panel.cancel_job.setVisible(self.job is not None)

    def cancel_transcription(self):
        self.job_queue.clear()
        if self.job:
            self.job.close()
            self.job = None
        self.library_panel.job_status.setText(
            "Transcription canceled. Retry to resume completed chunks."
        )
        self.library_panel.cancel_job.hide()

    def quit_app(self):
        if self.install_future:
            self.show_main(1)
            self.status.setText(
                "Let audio driver setup finish before quitting. Force quit is available from the tray."
            )
            return
        self.closing = True
        self.dismiss_silence_prompt()
        self.pending_switch = {}
        self.cancel_transcription()
        for viewer in list(self.dialogs):
            viewer.close()
        self.engine.stop()
        self.close()

    def force_quit(self):
        import os

        self.closing = True
        self.cancel_transcription()
        for viewer in list(self.dialogs):
            viewer.stop_playback()
        self.engine.stop()
        self.engine.wait(8)
        self.engine.terminate_workers()
        # Only the explicit Force quit action takes this path. Native audio workers
        # normally finish first; unfinished WAV headers remain recoverable.
        os._exit(0)

    def closeEvent(self, event):
        if (
            self.desktop_enabled
            and not self.closing
            and (self.tray.isSystemTrayAvailable() or (self.floating and self.floating.isVisible()))
        ):
            self.hide()
            event.ignore()
            return
        if self.install_future:
            self.status.setText("Please let audio setup finish before closing Voice Loop.")
            event.ignore()
            return
        if self.engine.active:
            if self.closing:
                self.engine.stop()
                event.ignore()
                return
            answer = QMessageBox.question(
                self,
                "End session?",
                "Stop audio routing, finish any recording, and close Voice Loop?",
                defaultButton=QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.closing = True
                self.engine.stop()
            event.ignore()
            return
        self.executor.shutdown(wait=False)
        self.timer.stop()
        if self.floating:
            self.closing = True
            self.floating.close()
        if self.tray:
            self.tray.hide()
        self.cancel_transcription()
        for viewer in list(self.dialogs):
            viewer.close()
        event.accept()
        if self.desktop_enabled:
            QApplication.instance().quit()


def create_application():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Voice Loop")
    app.setOrganizationName("VoiceLoop")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI" if sys.platform == "win32" else "Helvetica Neue", 10))
    chevron = Path(__file__).with_name("resources") / "chevron.svg"
    check = Path(__file__).with_name("resources") / "check.svg"
    app.setStyleSheet(
        STYLE.replace("@CHEVRON@", chevron.as_posix()).replace("@CHECK@", check.as_posix())
    )
    return app


def launch(*, background=False):
    app = create_application()
    from voiceloop.desktop import SingleInstance, enable_desktop

    instance = SingleInstance()
    if not instance.acquire():
        return
    window = App()
    instance.server.newConnection.connect(lambda: instance.activate(window))
    enable_desktop(window)
    if not background:
        window.show_floating()
    elif not window.tray.isSystemTrayAvailable():
        window.show_main()
    app.exec()
    instance.close()
