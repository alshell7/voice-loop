"""Build a small, deterministic Chrome ZIP without local settings or test data."""

import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "manifest.json",
    "background.js",
    "protocol.mjs",
    "detector.js",
    "content.js",
    "commands.js",
    "popup.html",
    "popup.css",
    "popup.js",
    "README.md",
)


def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    source = ROOT / "extension/chrome"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != version:
        raise ValueError("Chrome and desktop versions must match before release.")
    entries = {name: (source / name).read_bytes() for name in FILES}
    entries["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    destination = ROOT / "dist" / f"VoiceLoop-{version}-chrome.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in sorted(entries.items()):
            info = zipfile.ZipInfo(f"voice-loop-chrome/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, contents)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="ascii"
    )
    print(destination)


if __name__ == "__main__":
    main()
