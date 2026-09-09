"""Native dark-palette completion and tray-state previews; synthetic names only."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from voiceloop.config import Settings
from voiceloop.desktop import TRAY_COLORS, tray_icon
from voiceloop.library import Contacts
from voiceloop.ui import App, create_application


def main():
    qt = create_application()
    original_palette = qt.palette()
    dark = QPalette(original_palette)
    for role, color in (
        (QPalette.ColorRole.Window, "#202020"),
        (QPalette.ColorRole.Base, "#202020"),
        (QPalette.ColorRole.Text, "#FFFFFF"),
        (QPalette.ColorRole.Highlight, "#111111"),
        (QPalette.ColorRole.HighlightedText, "#FFFFFF"),
    ):
        dark.setColor(role, QColor(color))
    qt.setPalette(dark)
    output = Path(".impeccable/review/v032")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voiceloop-popup-") as root:
        root = Path(root)
        contacts = Contacts(root / "contacts.json")
        for name in ("Anna Lee", "Maya Shah", "Sam Reed"):
            contacts.remember(name)
        with patch.object(Settings, "save"):
            app = App(
                settings=Settings(recording_directory=str(root)),
                contacts=contacts,
                assistant_directory=root / "assistant",
            )
            app.show_floating()
            for name, combo in (("tool", app.floating.tool), ("contact", app.floating.contact)):
                edit = combo.lineEdit()
                edit.setFocus()
                QTest.keyClicks(edit, "a")
                QTest.qWait(120)
                popup = combo.completer().popup()
                assert popup.isVisible(), "Completion did not open"
                QTest.keyClick(popup, Qt.Key.Key_Down)
                QTest.qWait(50)
                assert popup.grab().save(str(output / f"{name}-suggestions.png"))
                expected = popup.currentIndex().data()
                assert expected, "No keyboard selection"
                QTest.keyClick(popup, Qt.Key.Key_Return)
                QTest.qWait(100)
                assert combo.currentText() == expected
                assert not popup.isVisible()
            app.floating.mode.showPopup()
            QTest.qWait(100)
            assert app.floating.mode.view().grab().save(str(output / "mode-dropdown.png"))
            app.floating.mode.hidePopup()
            preview = QWidget()
            layout = QVBoxLayout(preview)
            for background, foreground in (("#FFFFFF", "#20242D"), ("#202020", "#FFFFFF")):
                row = QWidget()
                row.setStyleSheet(f"background:{background};color:{foreground};")
                columns = QHBoxLayout(row)
                for state in TRAY_COLORS:
                    columns.addWidget(QLabel(state.capitalize()))
                    for size in (16, 32):
                        mark = QLabel()
                        mark.setPixmap(tray_icon(state).pixmap(size, size))
                        columns.addWidget(mark)
                layout.addWidget(row)
            preview.show()
            QTest.qWait(100)
            assert preview.grab().save(str(output / "tray-states.png"))
            preview.close()
            app.closing = True
            app.close()
    qt.setPalette(original_palette)
    print(json.dumps({"status": "passed", "screenshots": str(output), "audio_opened": False}))


if __name__ == "__main__":
    main()
