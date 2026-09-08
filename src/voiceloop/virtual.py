"""Create only Voice Loop's own user-session PulseAudio/PipeWire endpoints."""

import json
import shutil
import subprocess
import sys

# pactl joins arguments before sending them to the server. Preserve both quoting
# layers: module arguments first, then the property list containing a spaced name.
MODULES = (
    (
        "module-null-sink",
        "sink_name=voiceloop_output",
        "rate=48000",
        "channels=2",
        "sink_properties=\"device.description='VoiceLoop Speaker'\"",
    ),
    (
        "module-null-sink",
        "sink_name=voiceloop_mic",
        "rate=48000",
        "channels=2",
        "sink_properties=\"device.description='VoiceLoop Mic Feed'\"",
    ),
    (
        "module-remap-source",
        "master=voiceloop_mic.monitor",
        "source_name=voiceloop_input",
        "source_properties=\"device.description='VoiceLoop Mic'\"",
    ),
)


def _pactl(*args) -> str:
    result = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "PulseAudio/PipeWire is not available.")
    return result.stdout.strip()


def ensure_linux_devices() -> list[str]:
    if not sys.platform.startswith("linux") or not shutil.which("pactl"):
        raise RuntimeError(
            "Automatic setup requires Linux, pactl, and PulseAudio or pipewire-pulse."
        )
    existing = json.loads(_pactl("--format=json", "list", "modules"))
    created = []
    try:
        for module in MODULES:
            identity = next(
                arg for arg in module[1:] if arg.startswith(("sink_name=", "source_name="))
            )
            if any(
                m["name"] == module[0] and identity in m.get("argument", "").split()
                for m in existing
            ):
                continue
            created.append(_pactl("load-module", *module))
    except Exception:
        for module_id in reversed(created):
            try:
                _pactl("unload-module", module_id)
            except RuntimeError:
                pass
        raise
    return created
