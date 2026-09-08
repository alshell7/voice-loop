"""Native capture checks using synthetic UI; never opens audio or personal data."""

import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QWidget

from voiceloop import __version__
from voiceloop.config import Settings
from voiceloop.devices import Devices
from voiceloop.library import Contacts
from voiceloop.ui import App, create_application


def check_capture(output, *, pixels=False):
    qt = create_application()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def settle():
        for _ in range(8):
            qt.processEvents()
            time.sleep(0.04)

    with tempfile.TemporaryDirectory(prefix="voiceloop-capture-") as temporary:
        with patch.object(Settings, "save"):
            app = App(
                settings=Settings(recording_directory=temporary),
                device_provider=lambda: Devices([], []),
                contacts=Contacts(Path(temporary) / "contacts.json"),
            )
            manager = app.capture_protection
            background = QWidget(None, Qt.WindowType.FramelessWindowHint)
            background.setStyleSheet("background: #1536A6;")
            dialog = QDialog(app)
            dialog.setWindowTitle("Voice Loop capture test dialog")
            try:
                if not manager.backend.supported:
                    raise RuntimeError("This check requires a native Windows or macOS Qt session.")
                app.show()
                app.show_floating()
                dialog.show()
                settle()
                windows = [app, app.floating, dialog]
                expected_on = 0x11 if sys.platform == "win32" else 0
                expected_off = 0 if sys.platform == "win32" else 1

                def verify(enabled):
                    app.preferences.capture_protection.setChecked(enabled)
                    settle()
                    expected = expected_on if enabled else expected_off
                    for window in windows:
                        actual = manager.backend.read(int(window.winId()))
                        if actual != expected:
                            raise RuntimeError(f"Native capture state {actual} != {expected}.")
                    if manager._errors:
                        raise RuntimeError(manager.status)

                verify(True)
                # Completion and ordinary combo lists are separate native windows.
                combo = app.floating.contact
                combo.addItem("Synthetic Contact")
                combo.completer().setCompletionPrefix("Synthetic")
                combo.completer().complete()
                settle()
                popup = combo.completer().popup()
                if not popup.isVisible() or manager.backend.read(int(popup.winId())) != expected_on:
                    raise RuntimeError("Contact suggestions did not inherit capture protection.")
                popup.hide()
                app.floating.mode.showPopup()
                settle()
                popup = app.floating.mode.view().window()
                if manager.backend.read(int(popup.winId())) != expected_on:
                    raise RuntimeError("The mode dropdown did not inherit capture protection.")
                app.floating.mode.hidePopup()
                app.floating.toggle_compact()
                app.floating.hide()
                app.floating.show()
                app.hide()
                app.show()
                settle()
                for window in windows:
                    if manager.backend.read(int(window.winId())) != expected_on:
                        raise RuntimeError("Protection was lost after hiding/resizing a window.")
                verify(False)
                report = {
                    "version": __version__,
                    "platform": sys.platform,
                    "native_toggle": "passed",
                    "windows": ["main", "floating", "dialog"],
                    "popup_protection": "passed",
                    "audio_opened": False,
                    "network_used": False,
                    "personal_settings_changed": False,
                    "desktop_pixels": "not_requested",
                    "limitation": manager.backend.limitation,
                }
                if pixels:
                    if sys.platform != "win32":
                        raise RuntimeError("Desktop pixel exclusion is verified only on Windows.")
                    # The solid background bounds the capture to our own synthetic
                    # test surface. QWidget.grab() is deliberately not used: it
                    # renders a widget itself and does not exercise OS exclusion.
                    dialog.hide()
                    app.hide()
                    app.floating.hide()
                    area = qt.primaryScreen().availableGeometry()
                    background.setGeometry(area)
                    background.show()
                    background.raise_()
                    results = {}
                    for name, window in (("main", app), ("floating", app.floating)):
                        window.move(area.topLeft() + QPoint(30, 30))
                        window.show()
                        window.raise_()
                        fractions = []
                        for enabled in (False, True, False):
                            verify(enabled)
                            window.raise_()
                            settle()
                            point = window.mapToGlobal(QPoint(25, 80))
                            pixmap = window.screen().grabWindow(
                                0, point.x(), point.y(), 320, min(120, window.height() - 105)
                            )
                            if pixmap.isNull():
                                raise RuntimeError("Desktop screenshot was empty.")
                            capture = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
                            data = (
                                np.frombuffer(capture.constBits(), np.uint8)
                                .reshape(capture.height(), capture.bytesPerLine())[
                                    :, : capture.width() * 4
                                ]
                                .reshape(capture.height(), capture.width(), 4)
                            )
                            blue = np.array([166, 54, 21], dtype=np.int16)  # BGRA
                            fraction = float(
                                (np.abs(data[:, :, :3].astype(np.int16) - blue) < 5).all(2).mean()
                            )
                            fractions.append(fraction)
                            suffix = ("off", "on", "restored")[len(fractions) - 1]
                            capture.save(str(output.with_suffix(f".{name}-{suffix}.png")))
                        if not (fractions[0] < 0.1 and fractions[1] > 0.95 and fractions[2] < 0.1):
                            raise RuntimeError(f"{name} pixel exclusion failed: {fractions}")
                        results[name] = fractions
                        window.hide()
                    report["desktop_pixels"] = "passed"
                    report["background_fraction_off_on_off"] = results
                output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                return report
            finally:
                manager.set_enabled(False)
                dialog.close()
                background.close()
                app.closing = True
                app.close()
                qt.processEvents()
