"""Capture the native Qt window at desktop and compact sizes. No audio capture."""

import argparse
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from voiceloop.config import Settings
from voiceloop.ui import App, ConsentDialog, create_application


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path, default=Path(".impeccable/review"))
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    qt = create_application()
    with tempfile.TemporaryDirectory(prefix="voiceloop-ui-") as directory:
        with patch.object(Settings, "save"):
            app = App(settings=Settings(recording_directory=directory))
            app.show()
            for width, height, level, page, name in (
                (1060, 820, 0, 0, "desktop-simple"),
                (820, 640, 0, 0, "compact-simple"),
                (1060, 1000, 1, 0, "desktop-advanced"),
                (1060, 820, 0, 1, "desktop-setup"),
                (1060, 820, 0, 2, "desktop-library"),
            ):
                app.resize(width, height)
                app.level_group.button(level).click()
                app.navigate(page)
                app.nav_buttons[page].setFocus()
                if page == 1:
                    next(
                        w
                        for w in app.findChildren(QLabel)
                        if w.accessibleName() == "Audio driver attribution and licensing"
                    ).setFocus()
                QTest.qWait(150)
                qt.processEvents()
                if page != 2:
                    assert app.start_button.isVisible()
                    assert (
                        app.start_button.mapTo(app, app.start_button.rect().bottomRight()).y()
                        < app.height()
                    )
                assert app.grab().save(str(args.screenshots / f"{name}.png"))
            dialog = ConsentDialog(directory, True, app)
            dialog.show()
            QTest.qWait(150)
            qt.processEvents()
            assert dialog.grab().save(str(args.screenshots / "consent.png"))
            dialog.reject()
            assert dialog.choice is None
            assert not list(Path(directory).iterdir())
            app.close()
    print("PASS: native Qt screenshots, visible transport, consent cancellation, no recordings.")


if __name__ == "__main__":
    main()
