# Releasing Voice Loop

Maintainer: **alshell7**. Repository: <https://github.com/alshell7/voice-loop>.

## Automatic GitHub releases

`.github/workflows/build.yml` runs on every push to `main`. This includes both
direct pushes and pull-request merges. Pull requests themselves only run CI;
they cannot publish releases. The workflow can also be run manually on `main`
from GitHub Actions → Release Windows and macOS → Run workflow.

1. Reusable CI runs lint, formatting, tests, and synthetic audio integration on
   Windows, macOS, and Linux with Python 3.11 and 3.13.
2. Native runners build Windows x64, macOS arm64 (Apple Silicon), and macOS x64
   (Intel) installers using Python 3.13. Each also runs tests and frozen-app UI checks.
3. Only when every job passes, the publish job verifies all three installers and
   their SHA-256 files, creates a draft, uploads the complete asset set, and
   publishes it as a prerelease.

The tag is `v<version>-build.<run number>`, for example `v0.3.2-build.1`.
The release points to the exact triggering commit. Build numbers distinguish
multiple releases of the same application version; they are not included in the
app's displayed version. Rerunning the same workflow updates that run's release.
Prereleases are not promoted to GitHub's stable latest release automatically.

Expected assets:

- `VoiceLoop-<version>-windows-x64-setup.exe`
- `VoiceLoop-<version>-macos-arm64.pkg`
- `VoiceLoop-<version>-macos-x64.pkg`
- A matching `.sha256` file for each installer.

GitHub Actions must be enabled. No personal access token or OpenAI key is needed:
the publish job uses GitHub's temporary `GITHUB_TOKEN` with `contents: write`.
All other jobs have read-only repository access. Actions are pinned to commit
SHAs; review upstream releases when updating them. Tests use generated audio and
mock responses, not private recordings or paid API calls.

## Version changes and failures

Update both `pyproject.toml` and `src/voiceloop/__init__.py` together, then add the
user-visible changes to `CHANGELOG.md`. Submit a PR and review the CI result
before merging. Pushing any main commit also publishes a build, including docs changes.

If CI or packaging fails, no public release is created. Inspect the failed job
in Actions, fix it in a new commit, or rerun after a transient download failure.
A failed upload can leave a draft; rerun that workflow to complete it. Do not
manually publish incomplete drafts. Driver and compiler downloads are verified
against pinned checksums; investigate upstream changes rather than bypassing checks.

Dependencies have compatibility ranges, so builds are not guaranteed byte-for-byte
reproducible. The workflow logs record resolved dependencies and build output.
SHA-256 sidecars verify download integrity; they are not code-signing signatures.

## Local packaging and signing status

Install `python -m pip install -e ".[dev]"`, then run the build script on its target OS:

```sh
python scripts/build_windows.py
python scripts/build_macos.py
```

macOS requires Xcode command-line tools. Its app copy preserves framework
symlinks. Windows downloads a verified portable NSIS compiler automatically.
Outputs are in `dist/`; downloaded dependencies, drivers, and build artifacts
are excluded from Git. See [THIRD_PARTY.md](../THIRD_PARTY.md) for redistribution
notices and source/license links.

Current releases are **unsigned and not notarized**. Windows reputation warnings
and macOS security approval may prevent a seamless first launch. Public signing
certificates, Apple Developer signing, and notarization are not configured.
Automated native builds do not prove driver installation, microphone permission,
or real meeting routing; see [TESTING.md](TESTING.md) for outstanding hardware checks.
