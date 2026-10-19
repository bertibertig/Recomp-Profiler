"""Wire protocol shared by agent and client.

JSON-RPC 2.0 messages carried as WebSocket text frames. Authentication happens
during the HTTP upgrade (``Authorization: Bearer <token>``); transport security
is TLS with a self-signed certificate whose SHA-256 fingerprint the client pins.
"""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = 1
DEFAULT_PORT = 47800

# JSON-RPC error codes (standard + application range).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
NOT_IMPLEMENTED = -32001
NOT_FOUND = -32002


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


def make_request(req_id: int, method: str, params: dict[str, Any] | None = None) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})


def make_result(req_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


def make_error(req_id: Any, error: RpcError) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": error.to_dict()})
