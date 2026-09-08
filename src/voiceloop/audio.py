"""Deterministic, bounded, stereo timeline. No audio hardware dependency."""

import numpy as np

SAMPLE_RATE = 48_000
BLOCK_FRAMES = 960


def stereo(data: np.ndarray) -> np.ndarray:
    data = np.nan_to_num(np.asarray(data, dtype=np.float32), nan=0, posinf=1, neginf=-1)
    if data.ndim == 1:
        data = data[:, None]
    if data.ndim != 2 or data.shape[1] < 1:
        raise ValueError("Expected audio as frames × channels.")
    return np.repeat(data, 2, axis=1) if data.shape[1] == 1 else data[:, :2]


def mono(data: np.ndarray) -> np.ndarray:
    return stereo(data).mean(axis=1, dtype=np.float32)


def pcm16(data: np.ndarray) -> bytes:
    finite = np.nan_to_num(data, nan=0, posinf=1, neginf=-1)
    return np.rint(np.clip(finite, -1, 1) * 32767).astype("<i2").tobytes()


class Timeline:
    """Two tracks on a shared frame clock. Absent frames remain silence.

    The consumer owns this object. Capacity and all insert/read operations are
    bounded. Late packets are counted and discarded, never shifted into the future.
    """

    def __init__(self, capacity: int = SAMPLE_RATE * 4):
        if capacity < 1:
            raise ValueError("Timeline capacity must be positive.")
        self.capacity = capacity
        self.data = np.zeros((capacity, 2), dtype=np.float32)
        self.cursor = 0
        self.late_frames = 0
        self.overflow_frames = 0

    def insert(self, channel: int, start: int, samples: np.ndarray) -> None:
        if channel not in (0, 1):
            raise ValueError("A stereo channel must be 0 or 1.")
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        skip = min(len(values), max(0, self.cursor - start))
        self.late_frames += skip
        values = values[skip:]
        start += skip
        if start >= self.cursor + self.capacity:
            self.overflow_frames += len(values)
            return
        count = min(len(values), self.cursor + self.capacity - start)
        self.overflow_frames += len(values) - count
        if count:
            indexes = (np.arange(count) + start) % self.capacity
            self.data[indexes, channel] = values[:count]

    def read(self, count: int) -> np.ndarray:
        if not 0 <= count <= self.capacity:
            raise ValueError("Read must fit inside the timeline capacity.")
        indexes = (np.arange(count) + self.cursor) % self.capacity
        result = self.data[indexes].copy()
        self.data[indexes] = 0
        self.cursor += count
        return result
