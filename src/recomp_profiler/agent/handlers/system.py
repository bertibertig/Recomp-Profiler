"""Host identity, hardware inventory and live system metrics."""

from __future__ import annotations

import os
import platform
import socket
import sys
import time

import psutil

from ... import __version__
from ...protocol import PROTOCOL_VERSION
from ..registry import METHODS, method
from ._util import run_capture


@method("system.ping")
async def ping() -> dict:
    return {"pong": True, "time": time.time(), "protocol": PROTOCOL_VERSION, "agent": __version__}


@method("system.methods")
async def list_methods() -> list[str]:
    return sorted(METHODS)


def _cpu_model() -> str:
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


async def _gpus() -> list[dict]:
    gpus: list[dict] = []
    nv = await run_capture(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"]
    )
    if nv:
        for line in nv.strip().splitlines():
            name, driver, mem = (x.strip() for x in line.split(","))
            gpus.append({"name": name, "driver": driver, "vram": mem, "source": "nvidia-smi"})
    if sys.platform == "win32":
        ps = await run_capture(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,DriverVersion,AdapterRAM | ConvertTo-Json",
            ]
        )
        if ps:
            import json

            data = json.loads(ps)
            for g in data if isinstance(data, list) else [data]:
                gpus.append({"name": g.get("Name"), "driver": g.get("DriverVersion"), "source": "wmi"})
    elif not gpus:
        lspci = await run_capture(["lspci", "-mm"])
        for line in (lspci or "").splitlines():
            if any(k in line for k in ('"VGA', '"3D controller', '"Display controller')):
                gpus.append({"name": line.split('" "', 2)[-1].strip('"'), "source": "lspci"})
    # TODO: vulkaninfo --summary for API/driver versions (Mesa vs proprietary).
    return gpus


@method("system.info")
async def info() -> dict:
    vm = psutil.virtual_memory()
    freq = psutil.cpu_freq()
    return {
        "hostname": socket.gethostname(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "distro": _linux_distro(),
        },
        "cpu": {
            "model": _cpu_model(),
            "arch": platform.machine(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "max_mhz": freq.max if freq else None,
        },
        "memory": {"total_bytes": vm.total},
        "gpus": await _gpus(),
        "session": {
            "display": os.environ.get("DISPLAY"),
            "wayland_display": os.environ.get("WAYLAND_DISPLAY"),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP"),
        },
        "python": sys.version.split()[0],
    }


def _linux_distro() -> dict | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        return dict(platform.freedesktop_os_release())
    except OSError:
        return None


@method("system.metrics")
async def metrics(pids: list[int] | None = None) -> dict:
    """One sample of system-wide and (optionally) per-process load."""
    out: dict = {
        "time": time.time(),
        "cpu_percent_per_core": psutil.cpu_percent(interval=0.2, percpu=True),
        "memory": psutil.virtual_memory()._asdict(),
        "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else None,
    }
    temps = getattr(psutil, "sensors_temperatures", lambda: {})()
    out["temperatures"] = {k: [t._asdict() for t in v] for k, v in temps.items()}
    procs = {}
    for pid in pids or []:
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                procs[pid] = {
                    "name": p.name(),
                    "cpu_percent": p.cpu_percent(interval=None),
                    "rss": p.memory_info().rss,
                    "threads": p.num_threads(),
                }
        except psutil.Error as e:
            procs[pid] = {"error": repr(e)}
    out["processes"] = procs
    return out
