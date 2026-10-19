"""WebSocket JSON-RPC server."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from http import HTTPStatus
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request

from .. import protocol
from ..protocol import RpcError
from ..security import tokens_equal
from . import handlers  # noqa: F401  (registers methods)
from .registry import METHODS

log = logging.getLogger("recomp-agent")

# 64 MiB frames: enough for chunked file transfer; large builds go in pieces.
MAX_FRAME = 64 * 1024 * 1024


class Agent:
    def __init__(self, token: str, host: str, port: int, cert: Path | None, key: Path | None):
        self.token = token
        self.host = host
        self.port = port
        self.cert = cert
        self.key = key

    def _check_auth(self, connection: ServerConnection, request: Request):
        header = request.headers.get("Authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not tokens_equal(value, self.token):
            log.warning("rejected connection from %s: bad token", connection.remote_address)
            return connection.respond(HTTPStatus.UNAUTHORIZED, "invalid token\n")
        return None

    async def _dispatch(self, ws: ServerConnection, raw: str) -> None:
        req_id: Any = None
        try:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as e:
                raise RpcError(protocol.PARSE_ERROR, str(e))
            req_id = msg.get("id")
            name = msg.get("method")
            params = msg.get("params") or {}
            if not isinstance(name, str) or not isinstance(params, dict):
                raise RpcError(protocol.INVALID_REQUEST, "expected method:str and params:object")
            fn = METHODS.get(name)
            if fn is None:
                raise RpcError(protocol.METHOD_NOT_FOUND, f"unknown method {name}")
            try:
                result = await fn(**params)
            except TypeError as e:
                raise RpcError(protocol.INVALID_PARAMS, str(e))
            await ws.send(protocol.make_result(req_id, result))
        except RpcError as e:
            await ws.send(protocol.make_error(req_id, e))
        except Exception as e:  # report, never kill the connection
            log.exception("handler failed")
            await ws.send(protocol.make_error(req_id, RpcError(protocol.INTERNAL_ERROR, repr(e))))

    async def _handle(self, ws: ServerConnection) -> None:
        log.info("client connected: %s", ws.remote_address)
        tasks: set[asyncio.Task] = set()
        try:
            async for raw in ws:
                # Requests run concurrently so a long exec doesn't block pings.
                t = asyncio.create_task(self._dispatch(ws, raw))
                tasks.add(t)
                t.add_done_callback(tasks.discard)
        finally:
            log.info("client disconnected: %s", ws.remote_address)

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not self.cert:
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert, self.key)
        return ctx

    async def serve_forever(self) -> None:
        ctx = self._ssl_context()
        async with serve(
            self._handle,
            self.host,
            self.port,
            ssl=ctx,
            process_request=self._check_auth,
            max_size=MAX_FRAME,
        ) as server:
            log.info("listening on %s://%s:%d", "wss" if ctx else "ws", self.host, self.port)
            await server.serve_forever()
