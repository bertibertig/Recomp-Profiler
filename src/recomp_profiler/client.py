"""Async client for a single agent, with TLS certificate pinning."""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from . import protocol
from .config import hosts_dir
from .protocol import RpcError
from .security import fingerprint_der

CHUNK = 8 * 1024 * 1024


@dataclass
class HostConfig:
    name: str
    address: str
    port: int
    token: str
    tls_fingerprint_sha256: str | None = None
    platform: str | None = None
    trust: str = "own"  # "external" = someone else's machine: never push game data

    @classmethod
    def load(cls, path: Path) -> "HostConfig":
        d = json.loads(path.read_text())
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    @property
    def url(self) -> str:
        scheme = "wss" if self.tls_fingerprint_sha256 else "ws"
        return f"{scheme}://{self.address}:{self.port}"


def load_hosts() -> dict[str, HostConfig]:
    d = hosts_dir()
    if not d.is_dir():
        return {}
    hosts = (HostConfig.load(p) for p in sorted(d.glob("*.json")))
    return {h.name: h for h in hosts}


class AgentClient:
    def __init__(self, host: HostConfig):
        self.host = host
        self._ws: ClientConnection | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None

    async def __aenter__(self) -> "AgentClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self) -> None:
        ctx = None
        if self.host.tls_fingerprint_sha256:
            # Self-signed cert: skip CA validation, pin the exact certificate instead.
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self._ws = await connect(
            self.host.url,
            ssl=ctx,
            additional_headers={"Authorization": f"Bearer {self.host.token}"},
            max_size=None,
            open_timeout=10,
        )
        if ctx is not None:
            der = self._ws.transport.get_extra_info("ssl_object").getpeercert(binary_form=True)
            if fingerprint_der(der) != self.host.tls_fingerprint_sha256.lower():
                await self._ws.close()
                raise ConnectionError(f"TLS fingerprint mismatch for {self.host.name}: possible MITM")
        self._reader = asyncio.create_task(self._read_loop())

    @property
    def is_open(self) -> bool:
        return self._ws is not None and self._reader is not None and not self._reader.done()

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
        if self._reader:
            self._reader.cancel()

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                fut = self._pending.pop(msg.get("id"), None)
                if fut and not fut.done():
                    fut.set_result(msg)
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("agent connection closed"))
            self._pending.clear()

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = 120) -> Any:
        req_id = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._ws.send(protocol.make_request(req_id, method, params))
        msg = await asyncio.wait_for(fut, timeout)
        if "error" in msg:
            e = msg["error"]
            raise RpcError(e["code"], e["message"], e.get("data"))
        return msg["result"]

    async def push_file(self, local: Path, remote: str, mode: int | None = None) -> dict:
        size = local.stat().st_size
        offset = 0
        with open(local, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                params = {
                    "path": remote,
                    "data_b64": base64.b64encode(chunk).decode(),
                    "offset": offset,
                    "truncate": offset == 0,
                }
                if mode is not None:
                    params["mode"] = mode
                await self.call("fs.write", params)
                offset += len(chunk)
                if len(chunk) < CHUNK:
                    break
        return {"remote": remote, "bytes": size}

    async def pull_file(self, remote: str, local: Path) -> dict:
        local.parent.mkdir(parents=True, exist_ok=True)
        offset = 0
        with open(local, "wb") as f:
            while True:
                r = await self.call("fs.read", {"path": remote, "offset": offset, "length": CHUNK})
                data = base64.b64decode(r["data_b64"])
                f.write(data)
                offset += len(data)
                if not data or offset >= r["size"]:
                    break
        return {"local": str(local), "bytes": offset}
