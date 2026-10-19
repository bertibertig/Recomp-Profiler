"""Run short commands, and launch/observe/kill long-running processes (the recomp)."""

from __future__ import annotations

import asyncio
import itertools
import os
import time
from collections import deque
from dataclasses import dataclass, field

from ...protocol import NOT_FOUND, RpcError
from ..registry import method

MAX_EXEC_OUTPUT = 256 * 1024
RING_LINES = 20_000


@dataclass
class Managed:
    id: int
    argv: list[str]
    proc: asyncio.subprocess.Process
    started: float
    lines: deque = field(default_factory=lambda: deque(maxlen=RING_LINES))
    seq: itertools.count = field(default_factory=lambda: itertools.count(1))
    ended: float | None = None

    def summary(self) -> dict:
        return {
            "id": self.id,
            "pid": self.proc.pid,
            "argv": self.argv,
            "started": self.started,
            "ended": self.ended,
            "returncode": self.proc.returncode,
        }


_procs: dict[int, Managed] = {}
_ids = itertools.count(1)


def _env(extra: dict[str, str] | None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(extra or {})
    return env


@method("process.exec")
async def exec_(
    argv: list[str] | None = None,
    shell: str | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> dict:
    """Run to completion and return output. Pass either argv or shell."""
    if (argv is None) == (shell is None):
        raise TypeError("pass exactly one of argv or shell")
    kw = dict(stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd, env=_env(env))
    t0 = time.monotonic()
    if shell is not None:
        proc = await asyncio.create_subprocess_shell(shell, **kw)
    else:
        proc = await asyncio.create_subprocess_exec(*argv, **kw)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        out, err = await proc.communicate()
        timed_out = True
    return {
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "duration_s": round(time.monotonic() - t0, 3),
        "stdout": out[-MAX_EXEC_OUTPUT:].decode(errors="replace"),
        "stderr": err[-MAX_EXEC_OUTPUT:].decode(errors="replace"),
    }


async def _pump(m: Managed, stream: asyncio.StreamReader, name: str) -> None:
    while line := await stream.readline():
        m.lines.append((next(m.seq), time.time(), name, line.decode(errors="replace").rstrip("\n")))


async def _watch(m: Managed, pumps: list[asyncio.Task]) -> None:
    await asyncio.gather(*pumps)
    await m.proc.wait()
    m.ended = time.time()


@method("process.spawn")
async def spawn(argv: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> dict:
    """Start a long-running process (e.g. the recomp build). Output is buffered on the agent."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        cwd=cwd,
        env=_env(env),
    )
    m = Managed(id=next(_ids), argv=argv, proc=proc, started=time.time())
    pumps = [
        asyncio.create_task(_pump(m, proc.stdout, "stdout")),
        asyncio.create_task(_pump(m, proc.stderr, "stderr")),
    ]
    asyncio.create_task(_watch(m, pumps))
    _procs[m.id] = m
    return m.summary()


def _get(id: int) -> Managed:
    try:
        return _procs[id]
    except KeyError:
        raise RpcError(NOT_FOUND, f"no managed process {id}")


@method("process.output")
async def output(id: int, since: int = 0, limit: int = 2000) -> dict:
    """Lines with seq > since. Poll with the returned ``next`` value."""
    m = _get(id)
    lines = [l for l in m.lines if l[0] > since][:limit]
    return {
        **m.summary(),
        "lines": [{"seq": s, "t": t, "stream": n, "text": x} for s, t, n, x in lines],
        "next": lines[-1][0] if lines else since,
    }


@method("process.list")
async def list_() -> list[dict]:
    return [m.summary() for m in _procs.values()]


@method("process.kill")
async def kill(id: int, force: bool = False) -> dict:
    m = _get(id)
    if m.proc.returncode is None:
        m.proc.kill() if force else m.proc.terminate()
        try:
            await asyncio.wait_for(m.proc.wait(), 10)
        except asyncio.TimeoutError:
            m.proc.kill()
            await m.proc.wait()
    return m.summary()
