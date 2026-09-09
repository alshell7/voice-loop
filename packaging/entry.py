import multiprocessing
import sys
from pathlib import Path

from voiceloop.__main__ import main


def check_assistant_runtime():
    """Exercise frozen SDK/data imports without credentials, audio or network."""
    import asyncio
    import json
    import ssl
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import certifi
    import openai
    from openai import AsyncOpenAI
    from openai.types.realtime.realtime_session_create_request import RealtimeSessionCreateRequest

    from voiceloop.realtime import RealtimeConfig, session_configuration

    ssl.create_default_context(cafile=certifi.where())
    zone = ZoneInfo("Asia/Kolkata")
    assert datetime(2026, 1, 1, tzinfo=zone).utcoffset().total_seconds() == 19800
    assert ZoneInfo("America/New_York") is not None
    session = RealtimeSessionCreateRequest.model_validate(
        session_configuration(RealtimeConfig("Synthetic packaging check"))
    )
    assert session.audio.input.format.rate == 24000

    async def check_client():
        client = AsyncOpenAI(
            api_key="voiceloop-packaging-check-not-a-key",
            base_url="https://api.openai.com/v1",
        )
        try:
            # Construct, but deliberately never enter, the WebSocket manager.
            assert client.realtime.connect(model="gpt-realtime", max_retries=0) is not None
            assert client.responses is not None
        finally:
            await client.close()

    asyncio.run(check_client())
    print(
        json.dumps(
            {
                "assistant_runtime": "passed",
                "openai_version": openai.__version__,
                "certificate_bundle": "passed",
                "timezones": "passed",
                "realtime_schema": "passed",
                "audio_opened": False,
                "network_used": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if Path(sys.executable).stem == "VoiceLoopMCP":
        if sys.argv[1:] == ["--check-runtime"]:
            raise SystemExit(check_assistant_runtime())
        from voiceloop.assistant_mcp import main
    raise SystemExit(main())
