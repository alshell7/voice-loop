"""Tray integration and a per-user single-instance guard."""

import hashlib

from PySide6.QtCore import QByteArray, QLockFile, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from voiceloop.config import data_directory
from voiceloop.devices import is_virtual
from voiceloop.ui import PATHS

TRAY_COLORS = {"off": "#8F99A8", "active": "#17A673", "muted": "#E5484D"}


def tray_icon(state):
    """Waveform with a contrasting status badge, crisp at native tray sizes."""
    color = TRAY_COLORS[state]
    mark = "#697386" if state == "off" else "#006FEE"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<g transform="translate(0 0) scale(.8)" fill="none" stroke="{mark}" '
        f'stroke-width="2" stroke-linecap="round">{PATHS["session"]}</g>'
        f'<circle cx="18" cy="18" r="4.5" fill="{color}" stroke="white" stroke-width="1.5"/>'
        "</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result


def update_tray_status(window):
    engine = window.engine
    state = "off" if not engine.active else "muted" if engine.muted else "active"
    if state != window.tray_state:
        window.tray.setIcon(window.tray_icons[state])
        window.tray_state = state
    label = {
        "starting": "Starting",
        "stopping": "Finishing session",
        "error": "Off · needs attention",
    }.get(
        engine.state,
        "Recording"
        if engine.active and engine.recording
        else "Routing"
        if engine.active
        else "Off",
    )
    window.tray.setToolTip(
        "Voice Loop · " + label + (" · Mic muted" if engine.muted and engine.active else "")
    )


class SingleInstance:
    def __init__(self):
        root = data_directory()
        root.mkdir(parents=True, exist_ok=True)
        self.name = "VoiceLoop-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:20]
        self.lock = QLockFile(str(root / "desktop.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer()

    def acquire(self):
        if not self.lock.tryLock(0):
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(500):
                socket.write(b"show")
                socket.waitForBytesWritten(500)
                socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError("Could not start Voice Loop's local instance guard.")
        return True

    def activate(self, window):
        connection = self.server.nextPendingConnection()
        if connection:
            connection.disconnectFromServer()
            connection.deleteLater()
        window.show_floating()

    def close(self):
        self.server.close()
        self.lock.unlock()


def enable_desktop(window, *, register_startup=True):
    window.desktop_enabled = True
    QApplication.instance().setQuitOnLastWindowClosed(False)
    window.tray_icons = {state: tray_icon(state) for state in TRAY_COLORS}
    window.tray_state = None
    tray = QSystemTrayIcon(window.tray_icons["off"], window)
    window.tray = tray
    update_tray_status(window)
    menu = QMenu()
    tray.setContextMenu(menu)
    # Keep a Python reference: QSystemTrayIcon does not own its menu.
    window.tray_menu = menu
    window.capture_protection.register(menu)

    def rebuild():
        menu.clear()
        menu.addAction("Show floating controls", window.show_floating)
        menu.addAction("Open Voice Loop", window.show_main)
        if window.engine.active:
            menu.addAction("Turn off · finish session", window.stop_session)
        else:
            menu.addAction("Turn on · route only", lambda: window.start(record=False))
            menu.addAction("Turn on · record too", lambda: window.start(record=True))
        mute = menu.addAction("Mute microphone", window.toggle_mute)
        mute.setCheckable(True)
        mute.setChecked(window.engine.muted)
        menu.addSeparator()
        for name, title, inventory in (
            ("microphone", "Microphone", window.devices.inputs),
            ("speaker", "Speaker", window.devices.outputs),
        ):
            submenu = menu.addMenu(title)
            current = window.selected(getattr(window, name))
            for device in inventory:
                if is_virtual(device) or device.loopback:
                    continue
                action = submenu.addAction(device.name)
                action.setCheckable(True)
                action.setChecked(bool(current and current.id == device.id))
                action.setToolTip("Switching finishes the current session and starts a new one.")
                action.setEnabled(not window.install_future)
                action.triggered.connect(
                    lambda _checked=False, n=name, d=device: window.switch_device(n, d)
                )
        refresh = menu.addAction("Refresh devices", window.refresh_devices)
        refresh.setEnabled(not window.engine.active and not window.install_future)
        menu.addSeparator()
        menu.addAction("Recordings", lambda: window.show_main(2))
        menu.addAction("Preferences", lambda: window.show_main(3))
        menu.addAction("Open storage folder", lambda: window.open_path(window.settings.recordings))
        menu.addSeparator()
        menu.addAction("Quit Voice Loop", window.quit_app)
        menu.addAction("Force quit", window.force_quit)

    menu.aboutToShow.connect(rebuild)
    rebuild()
    tray.activated.connect(
        lambda reason: (
            window.show_floating()
            if reason
            in (
                QSystemTrayIcon.ActivationReason.Trigger,
                QSystemTrayIcon.ActivationReason.DoubleClick,
            )
            else None
        )
    )
    tray.show()
    timer = QTimer(window)
    timer.timeout.connect(lambda: update_tray_status(window))
    timer.start(500)
    window.tray_timer = timer
    try:
        from voiceloop.startup import set_enabled

        if register_startup:
            set_enabled(window.settings.launch_at_login)
    except (OSError, ValueError) as exc:
        window.status.setText("Could not update login startup: " + str(exc))
