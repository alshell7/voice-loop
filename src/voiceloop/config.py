"""Small, atomic local settings. Audio and secrets never belong in settings."""

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def data_directory() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "VoiceLoop"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/VoiceLoop"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "voiceloop"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, indent=2, ensure_ascii=False, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


@dataclass
class Settings:
    microphone_id: str = ""
    speaker_id: str = ""
    meeting_input_id: str = ""
    virtual_mic_output_id: str = ""
    mode: str = "direct"
    setup_level: str = "simple"
    left_channel: str = "microphone"
    right_channel: str = "meeting"
    recording_directory: str = ""
    launch_at_login: bool = True
    floating_opacity: int = 95
    capture_protection: bool = False
    session_mode: str = "route"
    meeting_tool: str = ""
    contact_name: str = ""
    openai_model: str = "gpt-4o-transcribe-diarize"
    auto_transcribe: bool = False
    browser_detection_enabled: bool = False
    browser_auto_record: bool = False

    @property
    def recordings(self) -> Path:
        return (
            Path(self.recording_directory).expanduser()
            if self.recording_directory
            else (data_directory() / "recordings")
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or data_directory() / "settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return cls()
            fields = cls.__dataclass_fields__
            values = {
                k: v for k, v in data.items() if k in fields and type(v) is type(fields[k].default)
            }
            result = cls(**values)
            result.floating_opacity = max(65, min(100, result.floating_opacity))
            return result
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        atomic_json(path or data_directory() / "settings.json", asdict(self))
