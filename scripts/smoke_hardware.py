"""Explicit manual hardware check. Captures into memory; never saves audio."""

import argparse
import multiprocessing
import tempfile
import time
from pathlib import Path

from voiceloop.devices import SessionConfig, discover, loopback_for
from voiceloop.engine import Engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--monitor",
        action="store_true",
        required=True,
        help="Open the default microphone and speaker loopback without recording",
    )
    parser.add_argument("--seconds", type=float, default=3)
    args = parser.parse_args()
    if not 0 < args.seconds <= 60:
        parser.error("Use a duration greater than zero and no more than 60 seconds.")
    devices = discover()
    microphone = next(d for d in devices.inputs if d.id == devices.default_input)
    speaker = next(d for d in devices.outputs if d.id == devices.default_output)
    meeting = loopback_for(speaker, devices)
    if meeting is None:
        raise SystemExit("No native loopback. Configure a virtual device and test in the GUI.")
    with tempfile.TemporaryDirectory(prefix="voiceloop-hardware-") as temporary:
        engine = Engine()
        engine.start(SessionConfig(microphone, meeting, speaker), Path(temporary), record=False)
        try:
            deadline = time.monotonic() + 15
            while engine.state == "starting" and time.monotonic() < deadline:
                time.sleep(0.05)
            assert engine.state == "running", engine.error
            time.sleep(args.seconds)
        finally:
            engine.stop()
            assert engine.wait(10), "Hardware shutdown timed out"
        assert not engine.error, engine.error
        assert not list(Path(temporary).iterdir()), "Monitor mode wrote files"
        assert not multiprocessing.active_children(), "Audio workers leaked"
    print(
        f"PASS: native microphone + speaker loopback monitored for {args.seconds:g}s; "
        "no audio saved"
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
