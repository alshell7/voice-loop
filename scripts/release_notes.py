"""Generate public release notes without copying commit messages into shell code."""

import argparse
import os
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    repository = os.environ.get("GITHUB_REPOSITORY", "alshell7/voice-loop")
    commit = os.environ.get("GITHUB_SHA", "local")
    args.output.write_text(
        f"# Voice Loop {version}\n\n"
        "By **alshell7**. Automated prerelease from `main`.\n\n"
        f"Source: https://github.com/{repository}/commit/{commit}\n\n"
        "## Downloads\n\n"
        "- Windows x64: `*-windows-x64-setup.exe`\n"
        "- macOS Apple Silicon: `*-macos-arm64.pkg`\n"
        "- macOS Intel: `*-macos-x64.pkg`\n"
        "- Each installer has a SHA-256 checksum sidecar.\n\n"
        "## Before installing\n\n"
        "These builds are unsigned and not notarized. OS approval may be required. "
        "Windows setup includes VB-CABLE and downloads Hi-Fi Cable from VB-Audio; "
        "macOS includes BlackHole 2ch/16ch. Driver approval or a restart may be needed. "
        "Third-party drivers retain their own licenses.\n\n"
        "Automated tests and packaging checks do not certify real meeting audio, "
        "every device, or macOS installation. See the verification matrix before use.\n\n"
        f"[Setup and usage](https://github.com/{repository}/blob/{commit}/README.md) · "
        f"[Verification](https://github.com/{repository}/blob/{commit}/docs/TESTING.md) · "
        f"[Changelog](https://github.com/{repository}/blob/{commit}/CHANGELOG.md)\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
