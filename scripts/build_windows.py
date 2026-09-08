"""Reproducible Windows app/installer build with a portable NSIS compiler."""

import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from voiceloop import __version__
from voiceloop.installation import download_verified

ROOT = Path(__file__).resolve().parents[1]


def unpack(archive, destination):
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            if not (destination / entry.filename).resolve().is_relative_to(destination):
                raise ValueError("Unsafe path in build dependency archive.")
        package.extractall(destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cable-package", type=Path, help="Complete extracted original VB-CABLE Pack45"
    )
    parser.add_argument(
        "--skip-app", action="store_true", help="Reuse an already built dist/VoiceLoop"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Build the Windows installer on Windows x64.")
    cache = ROOT / ".tools/installers"
    cache.mkdir(parents=True, exist_ok=True)
    vendor = ROOT / "packaging/vendor/vbcable"
    if args.cable_package:
        if args.cable_package.resolve() != vendor.resolve():
            shutil.copytree(args.cable_package, vendor, dirs_exist_ok=True)
    if not (vendor / "VBCABLE_Setup_x64.exe").exists():
        archive = cache / "vbcable.zip"
        download_verified(
            "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip",
            archive,
            "b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb",
        )
        unpack(archive, vendor)
    checksum = hashlib.sha256((vendor / "VBCABLE_Setup_x64.exe").read_bytes()).hexdigest()
    if checksum != "734c35dfa6d98f48782a451633ceb471166ec70d60482fd89a1123d0ee3c4f41":
        raise SystemExit("Expected the original VB-CABLE Pack45 x64 installer.")
    compiler = ROOT / ".tools/nsis/nsis-3.12/Bin/makensis.exe"
    if not compiler.exists():
        archive = cache / "nsis.zip"
        download_verified(
            "https://downloads.sourceforge.net/project/nsis/NSIS%203/3.12/nsis-3.12.zip",
            archive,
            "56581f90db321581c5381193d796fffcf2d24b2f8fed2160a6c6a3baa67f2c4f",
        )
        unpack(archive, ROOT / ".tools/nsis")
    if not args.skip_app:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "packaging/VoiceLoop.spec", "--noconfirm"],
            cwd=ROOT,
            check=True,
        )
    subprocess.run(
        [str(compiler), "/V2", f"/DAPP_VERSION={__version__}", "windows.nsi"],
        cwd=ROOT / "packaging",
        check=True,
    )
    output = ROOT / f"dist/VoiceLoop-{__version__}-windows-x64-setup.exe"
    with output.open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
    output.with_suffix(".exe.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
