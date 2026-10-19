"""Platform helpers for the TUI: status probes, setup steps, ROM-source checks."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import psutil

from ..config import agent_dir
from ..settings import Game, RomSource, Settings

IS_WINDOWS = sys.platform == "win32"


def scripts_dir() -> Path | None:
    """Install scripts: bundled in the wheel, or the repo checkout for editable installs."""
    pkg = Path(__file__).resolve().parents[1]
    for cand in (pkg / "scripts", pkg.parents[1] / "scripts"):
        if (cand / "install").is_dir() or (cand / "windows").is_dir():
            return cand
    return None


@dataclass
class Step:
    id: str
    label: str
    help: str
    needs_admin: bool = False


STEPS = [
    Step("packages", "Install / reinstall tools", "Debuggers, profilers, GPU and system tools via the distro package manager / winget", True),
    Step("venv", "Reinstall agent", "Recreate the Python environment from the configured agent source"),
    Step("init", "Write connection info", "Create token/cert if missing and rewrite connection.json from the Agent settings"),
    Step("service", "Install / restart autostart", "systemd user service (Linux) or logon task (Windows)"),
    Step("perf", "Perf + debugger tuning", "Allow perf and ptrace attach for normal users (Linux, sysctl)", True),
    Step("firewall", "Open firewall port", "ufw / firewalld / Windows Firewall rule for the agent port", True),
    Step("uninstall", "Uninstall agent", "Remove agent, service and credentials; distro packages stay"),
]


def step_command(step: str, settings: Settings) -> list[str] | None:
    d = scripts_dir()
    if d is None:
        return None
    port = str(settings.agent.port)
    if IS_WINDOWS:
        if step == "uninstall" or step == "perf":
            return None  # TODO: install.ps1 -Uninstall; perf tuning has no Windows equivalent
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(d / "windows" / "install.ps1"), "-Only", step, "-Port", port]
        if settings.install.source:
            argv += ["-Source", settings.install.source]
        return argv
    if step == "uninstall":
        return ["bash", str(d / "install" / "uninstall.sh")]
    argv = ["bash", str(d / "install" / "install.sh"), "--only", step, "--port", port]
    if settings.install.source:
        argv += ["--source", settings.install.source]
    return argv


def service_status() -> str:
    if IS_WINDOWS:
        out = _run_sync(["schtasks", "/Query", "/TN", "recomp-agent", "/FO", "LIST"])
        if out is None:
            return "not installed"
        for line in out.splitlines():
            if line.strip().startswith("Status:"):
                return line.split(":", 1)[1].strip()
        return "installed"
    if not shutil.which("systemctl"):
        return "no systemd"
    out = _run_sync(["systemctl", "--user", "is-active", "recomp-agent.service"], ok_codes=None)
    return (out or "unknown").strip()


def _run_sync(argv: list[str], ok_codes: tuple | None = (0,)) -> str | None:
    import subprocess

    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if ok_codes is not None and r.returncode not in ok_codes:
        return None
    return r.stdout


def connection_info() -> dict | None:
    p = agent_dir() / "connection.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def ip_addresses() -> list[tuple[str, str]]:
    out = []
    for iface, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith("127."):
                out.append((iface, a.address))
    return out


# ---------------------------------------------------------------- ROM sources


def game_location(game: Game, settings: Settings) -> Path | None:
    """Where the game's files are reachable on *this* machine, if anywhere."""
    if not game.source:
        return Path(game.recomp_dir).expanduser() / game.source_path if game.recomp_dir else None
    src = settings.source(game.source)
    if src is None:
        return None
    if src.kind == "local":
        return Path(src.path).expanduser() / game.source_path
    if src.mount_point:
        return Path(src.mount_point).expanduser() / src.path.lstrip("/") / game.source_path
    return None  # remote, not mounted: reachable only via the agent's transfer (TODO)


def game_status(game: Game, settings: Settings) -> str:
    loc = game_location(game, settings)
    if loc is None:
        return "remote (not mounted)" if game.source else "no folder set"
    if not loc.exists():
        return "missing"
    if game.format == "image" and loc.is_dir():
        return "expected image, found folder"
    if game.format == "extracted" and loc.is_file():
        return "expected folder, found file"
    return "ok"


async def _capture(argv: list[str], env: dict | None = None, timeout: float = 15) -> tuple[int, str]:
    if shutil.which(argv[0]) is None:
        return 127, f"{argv[0]} not installed"
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **(env or {})},
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode, out.decode(errors="replace")


async def test_source(src: RomSource) -> tuple[bool, str]:
    if src.kind == "local":
        p = Path(src.path).expanduser()
        return p.is_dir(), f"{p} {'exists' if p.is_dir() else 'not found'}"
    if src.mount_point:
        mp = Path(src.mount_point).expanduser()
        if os.path.ismount(mp):
            return True, f"mounted at {mp}"
    if src.kind == "http":
        def head() -> tuple[bool, str]:
            try:
                url = src.host if "://" in src.host else f"http://{src.host}/{src.share}"
                with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=10) as r:
                    return True, f"HTTP {r.status}"
            except Exception as e:
                return False, repr(e)
        return await asyncio.to_thread(head)
    if src.kind == "nfs":
        if IS_WINDOWS:
            return False, "NFS client test not implemented on Windows; use SMB"
        rc, out = await _capture(["showmount", "-e", src.host])
        if rc != 0:
            return False, out.strip()
        # Unraid exports /mnt/user/<share>; accept either the full path or the share name.
        exports = [line.split()[0] for line in out.splitlines()[1:] if line.split()]
        found = any(e == src.share or e.rstrip("/").endswith("/" + src.share.strip("/")) for e in exports)
        return found, ("export found" if found else f"export {src.share!r} not listed") + f"\n{out.strip()}"
    if src.kind == "smb":
        if IS_WINDOWS:
            rc, out = await _capture(["net", "view", f"\\\\{src.host}"])
        elif src.username:
            # smbclient reads the password from $PASSWD, keeping it off the command line.
            rc, out = await _capture(["smbclient", "-L", f"//{src.host}", "-U", src.username],
                                     env={"PASSWD": src.password})
        else:
            rc, out = await _capture(["smbclient", "-L", f"//{src.host}", "-N"])
        if rc != 0:
            return False, out.strip()
        found = any(line.split() and line.split()[0].lower() == src.share.lower() for line in out.splitlines())
        return found, ("share found" if found else f"share {src.share!r} not listed") + f"\n{out.strip()}"
    return False, f"unknown source type {src.kind}"
