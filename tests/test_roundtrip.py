"""End-to-end: real agent over TLS on localhost, real client."""

from __future__ import annotations

import asyncio
import socket
import sys

import pytest

from recomp_profiler.agent.server import Agent
from recomp_profiler.client import AgentClient, HostConfig
from recomp_profiler.protocol import RpcError
from recomp_profiler.security import cert_fingerprint_from_pem, generate_self_signed_cert


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def agent(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    generate_self_signed_cert(cert, key, "test")
    port = _free_port()
    a = Agent("secret", "127.0.0.1", port, cert, key)
    task = asyncio.create_task(a.serve_forever())
    await asyncio.sleep(0.3)
    yield HostConfig("test", "127.0.0.1", port, "secret", cert_fingerprint_from_pem(cert))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_ping_and_info(agent):
    async with AgentClient(agent) as c:
        assert (await c.call("system.ping"))["pong"]
        info = await c.call("system.info")
        assert info["cpu"]["logical_cores"] >= 1
        assert "system.info" in await c.call("system.methods")


async def test_bad_token_rejected(agent):
    agent.token = "wrong"
    with pytest.raises(Exception):
        async with AgentClient(agent):
            pass


async def test_fingerprint_pinning(agent):
    agent.tls_fingerprint_sha256 = "00" * 32
    with pytest.raises(ConnectionError):
        async with AgentClient(agent):
            pass


async def test_exec_and_spawn(agent):
    async with AgentClient(agent) as c:
        r = await c.call("process.exec", {"argv": [sys.executable, "-c", "print('hi')"]})
        assert r["returncode"] == 0 and r["stdout"].strip() == "hi"
        p = await c.call("process.spawn", {"argv": [sys.executable, "-c", "print('a'); print('b')"]})
        for _ in range(50):
            out = await c.call("process.output", {"id": p["id"]})
            if out["ended"]:
                break
            await asyncio.sleep(0.1)
        assert [l["text"] for l in out["lines"]] == ["a", "b"]
        assert out["returncode"] == 0
        with pytest.raises(RpcError):
            await c.call("profile.start", {"backend": "perf-stat"})


async def test_file_roundtrip(agent, tmp_path):
    src = tmp_path / "build.bin"
    src.write_bytes(bytes(range(256)) * 50_000)
    async with AgentClient(agent) as c:
        await c.push_file(src, str(tmp_path / "remote" / "build.bin"))
        await c.pull_file(str(tmp_path / "remote" / "build.bin"), tmp_path / "back.bin")
    assert (tmp_path / "back.bin").read_bytes() == src.read_bytes()
