"""User-level login startup. Logging in never opens an audio stream."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> list[str]:
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return [str(executable), "--background"]
    if sys.platform == "win32" and executable.with_name("pythonw.exe").exists():
        executable = executable.with_name("pythonw.exe")
    return [str(executable), "-m", "voiceloop", "--background"]


def startup_file(platform=None, home=None) -> Path:
    home = Path(home or Path.home())
    if (platform or sys.platform) == "darwin":
        return home / "Library/LaunchAgents/org.voiceloop.desktop.plist"
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return config / "autostart/voiceloop.desktop"


def set_enabled(enabled: bool, *, command=None, platform=None, home=None) -> None:
    platform = platform or sys.platform
    command = command or launch_command()
    if platform == "win32":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(
                    key, "VoiceLoop", 0, winreg.REG_SZ, subprocess.list2cmdline(command)
                )
            else:
                try:
                    winreg.DeleteValue(key, "VoiceLoop")
                except FileNotFoundError:
                    pass
        return
    path = startup_file(platform, home)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform == "darwin":
        data = plistlib.dumps(
            {
                "Label": "org.voiceloop.desktop",
                "ProgramArguments": command,
                "RunAtLoad": True,
                "ProcessType": "Interactive",
            }
        )
    else:
        # Desktop Entry Exec has its own quoting rules; it is not a shell script.
        def quote(value):
            if any(c in value for c in "\r\n"):
                raise ValueError("Startup paths cannot contain newlines.")
            value = value.replace("%", "%%")
            for character in ("\\", '"', "`", "$"):
                value = value.replace(character, "\\" + character)
            return '"' + value + '"'

        entry = " ".join(quote(arg) for arg in command)
        data = (
            "[Desktop Entry]\nType=Application\nName=Voice Loop\n"
            f"Exec={entry}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n"
        ).encode()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.chmod(0o600)
    temporary.replace(path)
