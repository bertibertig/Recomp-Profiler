"""Profiling backends (planned). Each backend captures to a file on the agent
which the client pulls with fs.read and analyses locally.

Planned backends:
  linux:   perf record/stat, MangoHud frametime log, gpu counters
           (nvidia-smi dmon / radeontop / intel_gpu_top), bpftrace, tracy capture
  windows: PresentMon (frametimes), WPR/ETW (CPU sampling, context switches),
           nvidia-smi, ETW GPU events
"""

from __future__ import annotations

from ...protocol import NOT_IMPLEMENTED, RpcError
from ..registry import method

BACKENDS = {
    "linux": ["perf-stat", "perf-record", "mangohud", "gpu-counters", "tracy"],
    "win32": ["presentmon", "wpr", "gpu-counters", "tracy"],
}


@method("profile.backends")
async def backends() -> dict:
    # TODO: probe which tools are actually installed and usable (perf_event_paranoid etc.).
    return BACKENDS


@method("profile.start")
async def start(backend: str, target_pid: int | None = None, options: dict | None = None) -> dict:
    raise RpcError(NOT_IMPLEMENTED, f"profile backend {backend!r} not implemented yet")


@method("profile.stop")
async def stop(session: int) -> dict:
    raise RpcError(NOT_IMPLEMENTED, "profile.stop not implemented yet")
