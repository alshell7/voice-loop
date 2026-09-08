"""Cancelable transcription jobs isolated from audio and the desktop event loop."""

import multiprocessing as mp
import queue
from pathlib import Path


def _transcribe(directory, key, model, events, cancel):
    from voiceloop.openai_stt import OpenAITranscriber
    from voiceloop.transcription import transcribe_session

    try:
        output = transcribe_session(
            Path(directory),
            OpenAITranscriber(key, model),
            allow_upload=True,
            cancel=cancel,
            progress=lambda message: events.put(("progress", message)),
        )
        events.put(("complete", str(output)))
    except Exception as exc:
        events.put(("error", str(exc)))


class TranscriptionJob:
    def __init__(self, directory: Path, key: str, model: str):
        context = mp.get_context("spawn")
        self.directory = directory
        self.events = context.Queue()
        self.cancelled = context.Event()
        self.process = context.Process(
            target=_transcribe,
            args=(str(directory), key, model, self.events, self.cancelled),
            daemon=True,
        )
        self.process.start()
        self.finished = False

    def poll(self):
        found = []
        try:
            while True:
                item = self.events.get_nowait()
                found.append(item)
                if item[0] in ("complete", "error"):
                    self.finished = True
        except queue.Empty:
            pass
        if not self.finished and self.process.exitcode is not None:
            self.finished = True
            found.append(
                ("error", "Transcription worker stopped. Retry to resume completed chunks.")
            )
        return found

    def close(self):
        self.cancelled.set()
        self.process.join(timeout=0.2)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=1)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=1)
        self.process.close()
        self.events.close()
        self.events.cancel_join_thread()
