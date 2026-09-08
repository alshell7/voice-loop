import io
import json
import urllib.error
import wave

import numpy as np
import pytest

from voiceloop.openai_stt import OpenAITranscriber
from voiceloop.recording import Recording
from voiceloop.transcript_html import render_transcript
from voiceloop.transcription import Segment, transcribe_session


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        output.writeframes(np.ones(48000, dtype="<i2").tobytes())
    return path


def test_diarization_request_and_response(audio):
    class Transport:
        def open(self, request, timeout):
            assert request.full_url == "https://api.openai.com/v1/audio/transcriptions"
            assert request.get_header("Authorization") == "Bearer test-key"
            assert b"diarized_json" in request.data and b"chunking_strategy" in request.data
            assert b"auto" in request.data and timeout == 120
            return io.BytesIO(
                json.dumps(
                    {
                        "segments": [
                            {"start": 0.1, "end": 0.5, "text": "Hello", "speaker": "A"},
                            {"start": 0.6, "end": 1.0, "text": "Hi", "speaker": "B"},
                        ]
                    }
                ).encode()
            )

    result = OpenAITranscriber("test-key", opener=Transport()).transcribe(audio)
    assert [s.speaker for s in result] == ["A", "B"]


def test_plain_transcription_reports_chunk_time(audio):
    transport = type(
        "Transport", (), {"open": lambda *_args, **_kwargs: io.BytesIO(b'{"text":"Hi"}')}
    )()
    provider = OpenAITranscriber("test-key", "gpt-4o-mini-transcribe", opener=transport)
    assert provider.transcribe(audio) == [Segment(0, 1, "Hi")]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_errors_never_echo_credentials(audio, status):
    class Transport:
        def open(self, *_args, **_kwargs):
            raise urllib.error.HTTPError(
                "https://api.openai.com",
                status,
                "secret-should-never-appear",
                {},
                io.BytesIO(b"secret-key"),
            )

    with pytest.raises(RuntimeError) as error:
        OpenAITranscriber("secret-key", opener=Transport()).transcribe(audio)
    assert str(status) in str(error.value)
    assert "secret" not in str(error.value)


def test_resume_does_not_upload_completed_channels(tmp_path):
    recording = Recording(tmp_path, {})
    recording.write(np.ones((480, 2)) * 0.1)
    directory = recording.close()

    class Provider:
        name, uploads_audio, diarizes = "test-cloud", True, True
        calls = 0
        fail = True

        def transcribe(self, path):
            self.calls += 1
            if self.calls == 2 and self.fail:
                raise RuntimeError("connection lost")
            return [Segment(0, 0.005, "Hello", "A")]

    provider = Provider()
    with pytest.raises(RuntimeError, match="connection"):
        transcribe_session(directory, provider, allow_upload=True)
    assert not (directory / "transcript.json").exists()
    provider.fail = False
    output = transcribe_session(directory, provider, allow_upload=True)
    assert provider.calls == 3  # Only the failed channel is retried.
    result = json.loads(output.read_text(encoding="utf-8"))
    assert len(result["segments"]) == 2
    assert result["segments"][0]["speaker"] == "You"
    assert result["segments"][1]["speaker"] == "Speaker A · clip 1"
    assert result["segments"][1]["speaker_scope"] == "meeting-1-1"
    assert (directory / "transcript.html").is_file()
    assert not (directory / "transcription-progress.json").exists()


def test_html_escapes_model_text_and_contact():
    result = render_transcript(
        {
            "metadata": {"contact": '<img src=x onerror="bad()">'},
            "segments": [
                {"start": 1, "speaker": "<script>", "text": "</section><script>alert(1)</script>"}
            ],
        },
        native=True,
    )
    assert "<script>" not in result and "<img " not in result
    assert "&lt;script&gt;" in result and 'href="seek:1.000"' in result
