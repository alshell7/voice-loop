import argparse
import json
import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Voice Loop — local meeting audio, without a bot")
    parser.add_argument(
        "--background", action="store_true", help="Start in the tray with audio off"
    )
    commands = parser.add_subparsers(dest="command")
    devices = commands.add_parser("devices", help="List native audio devices as JSON")
    devices.add_argument(
        "--output", help="Save device JSON to a file (also works in packaged apps)"
    )
    ui_check = commands.add_parser("check-ui", help="Check packaged Qt rendering without audio")
    ui_check.add_argument("--output", required=True, help="Write diagnostic JSON to this file")
    capture_check = commands.add_parser(
        "check-capture", help="Verify native window capture protection without audio"
    )
    capture_check.add_argument("--output", required=True)
    capture_check.add_argument(
        "--pixels", action="store_true", help="Also verify Windows desktop screenshots"
    )
    commands.add_parser(
        "setup-linux", help="Create Voice Loop virtual endpoints for this audio session"
    )
    transcribe = commands.add_parser(
        "transcribe", help="Transcribe a saved session with local Whisper"
    )
    transcribe.add_argument("session", help="Directory containing session.json")
    transcribe.add_argument(
        "--model", default="base", help="Local path or Whisper model name (downloads on first use)"
    )
    args = parser.parse_args()
    try:
        if args.command == "devices":
            from voiceloop.devices import discover

            device_json = json.dumps(discover().to_dict(), indent=2, ensure_ascii=False)
            if args.output:
                from pathlib import Path

                Path(args.output).write_text(device_json + "\n", encoding="utf-8")
            else:
                print(device_json)
        elif args.command == "check-ui":
            from voiceloop.diagnostics import check_ui

            check_ui(args.output)
        elif args.command == "check-capture":
            from voiceloop.capture_diagnostics import check_capture

            check_capture(args.output, pixels=args.pixels)
        elif args.command == "setup-linux":
            from voiceloop.virtual import ensure_linux_devices

            created = ensure_linux_devices()
            print(f"Voice Loop endpoints ready. Created {len(created)} modules.")
        elif args.command == "transcribe":
            from pathlib import Path

            from voiceloop.transcription import WhisperLocal, transcribe_session

            print(transcribe_session(Path(args.session), WhisperLocal(args.model)))
        else:
            from voiceloop.ui import launch

            launch(background=args.background)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Voice Loop: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
