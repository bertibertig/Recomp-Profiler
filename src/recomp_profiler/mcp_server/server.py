"""MCP server exposing registered target machines to Claude Code.

Runs on the dev machine (stdio transport). Keeps one persistent connection per
host so spawned processes and profiling sessions can be followed across calls.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..client import AgentClient, load_hosts
from ..config import captures_dir

mcp = MCPServer("recomp-profiler", instructions="Remote debug/profile/control of bare-metal test machines for recomp builds. Start with list_hosts.")
_clients: dict[str, AgentClient] = {}


def _params(**kw: Any) -> dict[str, Any]:
    return {k: v for k, v in kw.items() if v is not None}


async def _client(host: str) -> AgentClient:
    c = _clients.get(host)
    if c is not None and c.is_open:
        return c
    hosts = load_hosts()
    if host not in hosts:
        raise ValueError(f"unknown host {host!r}; registered: {sorted(hosts)}")
    c = AgentClient(hosts[host])
    await c.connect()
    _clients[host] = c
    return c


@mcp.tool()
async def list_hosts() -> list[dict[str, Any]]:
    """List registered target machines and whether they are reachable."""
    out = []
    for name, h in load_hosts().items():
        entry: dict[str, Any] = {"name": name, "url": h.url, "platform": h.platform}
        try:
            entry["ping"] = await (await _client(name)).call("system.ping", timeout=5)
        except Exception as e:
            entry["error"] = repr(e)
        out.append(entry)
    return out


@mcp.tool()
async def host_info(host: str) -> dict:
    """Hardware/OS inventory of a target: CPU, RAM, GPUs + drivers, distro, display session."""
    return await (await _client(host)).call("system.info")


@mcp.tool()
async def host_metrics(host: str, pids: list[int] | None = None) -> dict:
    """One sample of CPU per core, memory, temperatures, and per-process stats for `pids`."""
    return await (await _client(host)).call("system.metrics", _params(pids=pids))


@mcp.tool()
async def run_command(
    host: str,
    shell: str | None = None,
    argv: list[str] | None = None,
    cwd: str | None = None,
    timeout: float = 60,
) -> dict:
    """Run a short command on the target to completion. Pass `shell` (string) OR `argv` (list)."""
    params = _params(shell=shell, argv=argv, cwd=cwd, timeout=timeout)
    return await (await _client(host)).call("process.exec", params, timeout=timeout + 15)


@mcp.tool()
async def launch_process(
    host: str, argv: list[str], cwd: str | None = None, env: dict[str, str] | None = None
) -> dict:
    """Start a long-running process (the recomp under test). Returns a managed process id."""
    return await (await _client(host)).call("process.spawn", _params(argv=argv, cwd=cwd, env=env))


@mcp.tool()
async def process_output(host: str, id: int, since: int = 0, limit: int = 500) -> dict:
    """Fetch buffered stdout/stderr lines of a managed process with seq > `since`; also reports exit status."""
    return await (await _client(host)).call("process.output", {"id": id, "since": since, "limit": limit})


@mcp.tool()
async def list_processes(host: str) -> list[dict]:
    """List processes launched through the agent."""
    return await (await _client(host)).call("process.list")


@mcp.tool()
async def kill_process(host: str, id: int, force: bool = False) -> dict:
    """Terminate (or with force=True, kill) a managed process."""
    return await (await _client(host)).call("process.kill", {"id": id, "force": force})


@mcp.tool()
async def push_file(host: str, local_path: str, remote_path: str, executable: bool = False) -> dict:
    """Upload a local file (e.g. a fresh recomp build) to the target."""
    c = await _client(host)
    return await c.push_file(Path(local_path).expanduser(), remote_path, 0o755 if executable else None)


@mcp.tool()
async def pull_file(host: str, remote_path: str, local_path: str | None = None) -> dict:
    """Download a file (capture, log, core dump) from the target. Defaults into the captures dir."""
    dst = (
        Path(local_path).expanduser()
        if local_path
        else captures_dir() / host / f"{int(time.time())}-{Path(remote_path).name}"
    )
    return await (await _client(host)).pull_file(remote_path, dst)


@mcp.tool()
async def list_dir(host: str, path: str) -> list[dict]:
    """List a directory on the target."""
    return await (await _client(host)).call("fs.list", {"path": path})


@mcp.tool()
async def profile_backends(host: str) -> dict:
    """Profiling backends the target supports (perf, MangoHud, PresentMon, WPR, ...)."""
    return await (await _client(host)).call("profile.backends")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
