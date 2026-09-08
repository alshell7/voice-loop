"""Opt-in paid API check using generated speech only. Key is read from stdin."""

import argparse
import getpass
import json
import wave
from pathlib import Path

import numpy as np

from voiceloop.openai_stt import OpenAITranscriber
from voiceloop.recording import Recording
from voiceloop.transcription import transcribe_session


def read_mono(path):
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        assert source.getsampwidth() == 2
        data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
        data = data.reshape(-1, source.getnchannels()).mean(axis=1) / 32768
    return np.interp(
        np.arange(round(len(data) * 48000 / rate)) * rate / 48000, np.arange(len(data)), data
    ).astype(np.float32)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--speech", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    speech = read_mono(args.speech)
    recording = Recording(
        args.output,
        {},
        metadata={
            "tool": "Other",
            "contact": "Synthetic API test · Alex and Maya",
        },
    )
    # All voices are synthetic, on the meeting channel for diarization.
    recording.write(np.column_stack((np.zeros(len(speech)), speech)))
    directory = recording.close()
    key = getpass.getpass("OpenAI API key (hidden): ")
    try:
        output = transcribe_session(directory, OpenAITranscriber(key), allow_upload=True)
        result = json.loads(output.read_text(encoding="utf-8"))
        assert result["segments"], "Expected synthetic speech to be transcribed."
        speakers = {s["speaker"] for s in result["segments"]}
        report = {
            "status": "passed",
            "model": result["provider"],
            "segments": len(result["segments"]),
            "speaker_labels": len(speakers),
            "json": str(output),
            "html": str(directory / "transcript.html"),
        }
        (args.output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
    except Exception as exc:
        # Adapter errors intentionally omit API response bodies and credentials.
        print(json.dumps({"status": "failed", "error": str(exc)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
