"""Debugger bridge (planned).

Plan: run gdb (Linux) / cdb or lldb (Windows) under the agent speaking the
Debug Adapter Protocol (``gdb -i dap``, ``lldb-dap``) and relay DAP messages so
the MCP server can set breakpoints, read registers/memory and fetch backtraces.
Crash dumps: collect core files (coredumpctl) / minidumps (WER LocalDumps).
"""

from __future__ import annotations

from ...protocol import NOT_IMPLEMENTED, RpcError
from ..registry import method


@method("debug.attach")
async def attach(pid: int) -> dict:
    raise RpcError(NOT_IMPLEMENTED, "debug.attach not implemented yet")


@method("debug.crashdumps")
async def crashdumps() -> list[dict]:
    raise RpcError(NOT_IMPLEMENTED, "debug.crashdumps not implemented yet")
