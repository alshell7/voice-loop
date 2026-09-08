"""Build a native macOS helper and a single installer containing app + BlackHole."""

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from voiceloop import __version__
from voiceloop.installation import BLACKHOLE, download_verified

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--helper-only", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("Build macOS installers on macOS with Xcode command-line tools.")
    architecture = {"arm64": "arm64", "x86_64": "x64"}.get(platform.machine())
    if architecture is None:
        raise SystemExit("Unsupported macOS architecture.")
    output = ROOT / f"dist/VoiceLoop-{__version__}-macos-{architecture}.pkg"
    resources = ROOT / "src/voiceloop/resources"
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-O",
            str(resources / "macos-audio.swift"),
            "-o",
            str(resources / "voiceloop-audio-setup"),
        ],
        check=True,
    )
    if args.helper_only:
        return
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "packaging/VoiceLoop.spec", "--noconfirm"],
        cwd=ROOT,
        check=True,
    )
    stage = ROOT / "build/macos-installer"
    payload = stage / "payload/Applications"
    payload.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        ROOT / "dist/VoiceLoop.app", payload / "VoiceLoop.app", dirs_exist_ok=True, symlinks=True
    )
    package = stage / "VoiceLoop-app.pkg"
    subprocess.run(
        [
            "pkgbuild",
            "--root",
            str(stage / "payload"),
            "--identifier",
            "org.voiceloop.desktop",
            "--version",
            __version__,
            "--install-location",
            "/",
            str(package),
        ],
        check=True,
    )
    packages = [package]
    installer_resources = stage / "resources"
    installer_resources.mkdir(parents=True, exist_ok=True)
    for channels, checksum in BLACKHOLE:
        filename = f"BlackHole{channels}-0.7.1.pkg"
        path = stage / filename
        download_verified(f"https://existential.audio/downloads/{filename}", path, checksum)
        subprocess.run(["pkgutil", "--check-signature", str(path)], check=True)
        # Vendor downloads are distribution archives, not component packages.
        # Preserve their payload, scripts and PackageInfo after verifying the
        # signed original; productbuild cannot nest distribution archives.
        with tempfile.TemporaryDirectory(prefix="voiceloop-blackhole-") as temporary:
            expanded = Path(temporary) / "expanded"
            subprocess.run(["pkgutil", "--expand", str(path), str(expanded)], check=True)
            component = stage / f"BlackHole{channels}-component.pkg"
            subprocess.run(
                ["pkgutil", "--flatten", str(expanded / "BlackHole.pkg"), str(component)],
                check=True,
            )
            shutil.copyfile(
                expanded / "Resources/LICENSE", installer_resources / "BlackHole-LICENSE.txt"
            )
            packages.append(component)
    distribution = stage / "Distribution.xml"
    subprocess.run(
        [
            "productbuild",
            "--synthesize",
            *[arg for path in packages for arg in ("--package", str(path))],
            str(distribution),
        ],
        check=True,
    )
    # Carry the vendor distribution's license, system-only install and required
    # restart into our combined installer. Driver payloads remain unchanged.
    tree = ET.parse(distribution)
    document = tree.getroot()
    ET.SubElement(document, "title").text = "Voice Loop"
    ET.SubElement(document, "license", file="BlackHole-LICENSE.txt")
    ET.SubElement(
        document,
        "domains",
        enable_anywhere="false",
        enable_currentUserHome="false",
        enable_localSystem="true",
    )
    for reference in document.findall("pkg-ref"):
        if reference.get("id", "").startswith("audio.existential.BlackHole"):
            reference.set("onConclusion", "RequireRestart")
    tree.write(distribution, encoding="utf-8", xml_declaration=True)
    subprocess.run(
        [
            "productbuild",
            "--distribution",
            str(distribution),
            "--resources",
            str(installer_resources),
            "--package-path",
            str(stage),
            str(output),
        ],
        check=True,
    )
    with output.open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
    output.with_suffix(".pkg.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
