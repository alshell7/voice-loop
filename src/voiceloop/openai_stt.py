"""Small bounded HTTP adapter for the official OpenAI transcription endpoint."""

import json
import math
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

from voiceloop.credentials import normalize_key
from voiceloop.transcription import Segment

MODELS = {
    "gpt-4o-transcribe-diarize": "Transcription + speaker diarization",
    "gpt-transcribe": "Transcription",
    "gpt-4o-transcribe": "GPT-4o transcription",
    "gpt-4o-mini-transcribe": "Fast transcription",
    "whisper-1": "Whisper transcription + timestamps",
}
ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward this credential to another host.


class OpenAITranscriber:
    uploads_audio = True

    def __init__(self, api_key: str, model="gpt-4o-transcribe-diarize", *, opener=None):
        if model not in MODELS:
            raise ValueError("Choose a supported OpenAI transcription model.")
        self._key = normalize_key(api_key)
        self.model = model
        self.name = "openai/" + model
        self.diarizes = model == "gpt-4o-transcribe-diarize"
        self.opener = opener or urllib.request.build_opener(NoRedirect)

    def transcribe(self, wav_path: Path):
        if wav_path.stat().st_size > 24_000_000:
            raise ValueError(
                "Audio exceeds the upload limit. Use session transcription to split it."
            )
        with wave.open(str(wav_path), "rb") as source:
            duration = source.getnframes() / source.getframerate()
        fields = {"model": self.model, "response_format": "json"}
        if self.diarizes:
            fields.update(response_format="diarized_json", chunking_strategy="auto")
        elif self.model == "whisper-1":
            fields["response_format"] = "verbose_json"
        boundary = "voiceloop-" + uuid.uuid4().hex
        body = bytearray()
        for key, value in fields.items():
            body.extend(
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
                    f"\r\n\r\n{value}\r\n"
                ).encode()
            )
        body.extend(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                'filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'
            ).encode()
        )
        body.extend(wav_path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            ENDPOINT,
            data=bytes(body),
            method="POST",
            headers={
                "Authorization": "Bearer " + self._key,
                "Content-Type": "multipart/form-data; boundary=" + boundary,
            },
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                data = json.loads(response.read(8_000_000))
        except urllib.error.HTTPError as exc:
            # Never display response bodies: authentication errors can echo a key.
            explanations = {
                401: "API key was rejected. Replace it in Preferences.",
                403: "This API key cannot use the selected model.",
                429: "Quota or rate limit reached. Check API billing and retry later.",
                413: "Audio upload is too large.",
            }
            detail = explanations.get(exc.code, "Request failed. Retry or choose another model.")
            raise RuntimeError(f"OpenAI {exc.code}: {detail}") from None
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "OpenAI could not be reached or returned invalid data. Retry later."
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError("OpenAI returned an unexpected transcription response.")
        segments = data.get("segments")
        if segments is None and isinstance(data.get("text"), str) and not self.diarizes:
            return [Segment(0, duration, data["text"].strip())]
        if not isinstance(segments, list):
            raise RuntimeError("OpenAI did not return the requested speaker segments.")
        result = []
        for segment in segments:
            try:
                start, end = float(segment["start"]), float(segment["end"])
                text = segment["text"]
                if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
                    raise ValueError()
                if not isinstance(text, str):
                    raise ValueError()
                speaker = (
                    str(segment["speaker"]) if self.diarizes and "speaker" in segment else None
                )
                result.append(
                    Segment(min(start, duration), min(end, duration), text.strip(), speaker)
                )
            except (TypeError, ValueError, KeyError):
                raise RuntimeError("OpenAI returned invalid transcript segments.") from None
        return result
