"""Check packaged MCP initialization and SDK imports without any external actions."""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def handshake(executable):
    command = str(executable) if executable else sys.executable
    arguments = [] if executable else ["-m", "voiceloop.assistant_mcp"]
    parameters = StdioServerParameters(command=command, args=arguments)
    async with asyncio.timeout(30):
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                assert result.serverInfo.name == "Voice Loop"
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert set(tools) == {
                    "voice_loop_status",
                    "voice_loop_job",
                    "voice_loop_call",
                    "voice_loop_schedule",
                    "voice_loop_cancel",
                }
                assert tools["voice_loop_status"].annotations.readOnlyHint is True
                assert tools["voice_loop_call"].annotations.idempotentHint is False
                # No tool is invoked: no call, local history, token or API key is read.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--executable", type=Path, help="Path to the packaged VoiceLoopMCP executable"
    )
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True) if args.executable else None
    if executable:
        check = subprocess.run(
            [str(executable), "--check-runtime"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        report = json.loads(check.stdout)
        assert report["assistant_runtime"] == "passed"
        assert report["audio_opened"] is False and report["network_used"] is False
    asyncio.run(handshake(executable))
    print(
        "PASS: MCP initialization and five tool schemas; no tools invoked, audio or network used."
    )


if __name__ == "__main__":
    main()
