"""Windows cable hardware check using generated tones; no physical mic or audio files."""

import multiprocessing as mp
import sys

import numpy as np

from voiceloop.devices import bridge_endpoints, discover


def capture(device_id, frequency, other, ready, result):
    try:
        import soundcard as sc

        with sc.get_microphone(id=device_id).recorder(samplerate=48000, channels=2) as recorder:
            ready.set()
            data = recorder.record(numframes=48000 * 3).mean(axis=1)
        spectrum = np.abs(np.fft.rfft(data))
        hz = np.fft.rfftfreq(len(data), 1 / 48000)
        signal = float(spectrum[(hz > frequency - 3) & (hz < frequency + 3)].max())
        crosstalk = float(spectrum[(hz > other - 3) & (hz < other + 3)].max())
        result.put(
            {
                "frequency": frequency,
                "rms": float(np.sqrt(np.mean(data**2))),
                "isolation_db": float(20 * np.log10(max(signal, 1e-12) / max(crosstalk, 1e-12))),
            }
        )
    except Exception as exc:
        result.put({"error": str(exc)})
        ready.set()


def playback(device_id, frequency):
    import soundcard as sc

    frames = np.arange(48000 * 3)
    data = np.repeat((0.1 * np.sin(2 * np.pi * frequency * frames / 48000))[:, None], 2, axis=1)
    sc.get_speaker(id=device_id).play(data.astype(np.float32), samplerate=48000)


def main():
    if sys.platform != "win32":
        raise SystemExit("This hardware check targets the Windows VB-CABLE + Hi-Fi setup.")
    devices = discover()
    bridge = bridge_endpoints(devices)
    if not bridge:
        raise SystemExit("Complete Audio setup before running this hardware check.")
    meeting_capture = next(
        d
        for d in devices.inputs
        if not d.loopback and d.name.startswith("VoiceLoop Speaker Capture")
    )
    context = mp.get_context("spawn")
    results = context.Queue()
    workers = []
    try:
        for source, sink, frequency, other in (
            (bridge.microphone, bridge.microphone_feed, 220, 660),
            (meeting_capture, bridge.speaker, 660, 220),
        ):
            ready = context.Event()
            worker = context.Process(
                target=capture, args=(source.id, frequency, other, ready, results)
            )
            worker.start()
            workers.append(worker)
            if not ready.wait(10):
                raise RuntimeError("The cable capture did not open.")
            player = context.Process(target=playback, args=(sink.id, frequency))
            player.start()
            workers.append(player)
        for _ in range(2):
            result = results.get(timeout=15)
            assert "error" not in result, result
            assert result["rms"] > 0.01, result
            assert result["isolation_db"] > 25, result
            print(result)
        for worker in workers:
            worker.join(5)
            assert worker.exitcode == 0, worker.exitcode
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(3)
    print(
        "PASS: both native virtual cables carry independent tones; no physical microphone or files."
    )


if __name__ == "__main__":
    mp.freeze_support()
    main()
