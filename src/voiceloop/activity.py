"""Small streaming energy detector; replaceable by a speech VAD later."""

import numpy as np

from voiceloop.audio import SAMPLE_RATE

QUIET_SECONDS = 30
ENERGY_THRESHOLD_DBFS = -45
TAIL_PADDING_SECONDS = 0.25


class EnergyActivity:
    """Observe 20 ms windows on canonical microphone / meeting channels.

    This detects energy, not speech: music and noise above the threshold also
    count as activity. State is bounded regardless of session length.
    """

    def __init__(self, threshold_dbfs=ENERGY_THRESHOLD_DBFS):
        self.threshold = 10 ** (threshold_dbfs / 20)
        self.window_frames = SAMPLE_RATE // 50
        self.frames = 0
        self.last_active = [0, 0]
        self.pending = np.empty((0, 2), dtype=np.float32)

    def _observe(self, windows, lengths):
        energy = np.sqrt(np.mean(np.square(windows, dtype=np.float64), axis=1))
        for levels, count in zip(energy, lengths, strict=True):
            self.frames += count
            for channel in (0, 1):
                if levels[channel] >= self.threshold:
                    self.last_active[channel] = self.frames

    def update(self, samples):
        data = np.concatenate((self.pending, samples))
        count = len(data) // self.window_frames
        end = count * self.window_frames
        if count:
            self._observe(
                data[:end].reshape(count, self.window_frames, 2),
                [self.window_frames] * count,
            )
        self.pending = data[end:].copy()

    def finish(self):
        if len(self.pending):
            self._observe(self.pending[None, :, :], [len(self.pending)])
            self.pending = np.empty((0, 2), dtype=np.float32)

    @property
    def speaker_quiet_seconds(self):
        return (self.frames - self.last_active[1]) / SAMPLE_RATE

    @property
    def trim_frame(self):
        last_voice = max(self.last_active)
        # A wholly quiet session becomes an empty WAV, not 250 ms of silence.
        return (
            min(self.frames, last_voice + int(TAIL_PADDING_SECONDS * SAMPLE_RATE))
            if last_voice
            else 0
        )
