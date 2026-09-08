"""User-initiated, platform-native virtual audio setup. Never captures audio."""

import base64
import hashlib
import os
import platform
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

RESOURCES = Path(__file__).with_name("resources")
BLACKHOLE = (
    ("2ch", "57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf"),
    ("16ch", "57254e2f76cd40db7f3f715238b1a2cb2bd08819d38abf4087f2944f71a3641a"),
)


def download_verified(url: str, destination: Path, expected: str) -> None:
    if not url.startswith("https://"):
        raise ValueError("Driver downloads require HTTPS.")
    digest = hashlib.sha256()
    partial = destination.with_suffix(destination.suffix + ".partial")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; VoiceLoop; +https://github.com/alshell7/voice-loop)",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            if not response.url.startswith("https://"):
                raise RuntimeError("Driver download redirected to an insecure URL.")
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise RuntimeError("Driver download exceeds the expected size limit.")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != expected.lower():
            raise RuntimeError("Driver checksum does not match. No installer was run.")
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def install_windows() -> str:
    if platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("The VB-CABLE + Hi-Fi installer currently supports Windows x64.")
    script = RESOURCES / "windows-audio.ps1"
    # The encoded outer command preserves paths containing spaces, apostrophes or $. UAC
    # belongs to Windows; cancelling it is a setup failure, never an implicit success.
    args = subprocess.list2cmdline(
        ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    )
    command = (
        "$ErrorActionPreference='Stop'; "
        "$p=Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden "
        f"-ArgumentList {powershell_literal(args)} -Wait -PassThru; exit $p.ExitCode"
    )
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 3010:
        return "Drivers installed. Restart Windows, then use Audio setup to finish naming devices."
    if result.returncode:
        log = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "VoiceLoop/setup.log"
        raise RuntimeError(
            f"Windows audio setup did not finish (code {result.returncode}). "
            f"If you cancelled the administrator prompt, retry. Details: {log}"
        )
    return "VoiceLoop Mic and VoiceLoop Speaker are ready. Refresh devices in your meeting app."


def mac_alias_helper() -> Path:
    helper = RESOURCES / "voiceloop-audio-setup"
    if helper.is_file():
        return helper
    raise RuntimeError(
        "The macOS audio helper is missing. Use the macOS installer, or run "
        "python scripts/build_macos.py --helper-only from the source checkout."
    )


def finalize_mac_devices() -> str:
    result = subprocess.run([str(mac_alias_helper())], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Restart macOS to finish loading BlackHole.")
    return result.stdout.strip()


def install_mac() -> str:
    mac_alias_helper()  # Validate our helper before changing the system.
    with tempfile.TemporaryDirectory(prefix="voiceloop-drivers-") as directory:
        commands = []
        for channels, checksum in BLACKHOLE:
            receipt = subprocess.run(
                ["/usr/sbin/pkgutil", "--pkg-info", f"audio.existential.BlackHole{channels}"],
                capture_output=True,
            )
            if receipt.returncode == 0:
                continue
            filename = f"BlackHole{channels}-0.7.1.pkg"
            package = Path(directory) / filename
            download_verified(f"https://existential.audio/downloads/{filename}", package, checksum)
            subprocess.run(
                ["/usr/sbin/pkgutil", "--check-signature", str(package)],
                check=True,
                capture_output=True,
            )
            commands.append(f"/usr/sbin/installer -pkg {shlex.quote(str(package))} -target /")
        if commands:
            shell = " && ".join(commands)
            escaped = shell.replace("\\", "\\\\").replace('"', '\\"')
            result = subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    f'do shell script "{escaped}" with administrator privileges',
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "BlackHole installation was cancelled.")
        try:
            return finalize_mac_devices()
        except RuntimeError as exc:
            return f"BlackHole is installed. Restart macOS, then reopen Voice Loop. {exc}"


def install_audio_devices() -> str:
    if sys.platform == "win32":
        return install_windows()
    if sys.platform == "darwin":
        return install_mac()
    if sys.platform.startswith("linux"):
        from voiceloop.virtual import ensure_linux_devices

        ensure_linux_devices()
        return "VoiceLoop Mic and VoiceLoop Speaker are ready for this audio-server session."
    raise RuntimeError("Automatic audio setup supports Windows, macOS, and Linux.")
