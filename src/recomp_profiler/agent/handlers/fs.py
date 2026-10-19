"""File transfer for deploying builds and pulling captures.

Skeleton uses base64 chunks inside JSON. TODO: binary WebSocket frames +
rsync-style delta upload so re-deploying a 2 GB build after a small change is cheap.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
from pathlib import Path

from ...protocol import NOT_FOUND, RpcError
from ..registry import method

MAX_CHUNK = 16 * 1024 * 1024


def _p(path: str) -> Path:
    return Path(path).expanduser()


@method("fs.stat")
async def stat(path: str) -> dict:
    p = _p(path)
    if not p.exists():
        raise RpcError(NOT_FOUND, f"{p} does not exist")
    st = p.stat()
    return {"path": str(p), "is_dir": p.is_dir(), "size": st.st_size, "mtime": st.st_mtime}


@method("fs.list")
async def list_(path: str) -> list[dict]:
    p = _p(path)
    if not p.is_dir():
        raise RpcError(NOT_FOUND, f"{p} is not a directory")
    return [
        {"name": c.name, "is_dir": c.is_dir(), "size": c.stat().st_size if c.is_file() else None}
        for c in sorted(p.iterdir())
    ]


@method("fs.read")
async def read(path: str, offset: int = 0, length: int = MAX_CHUNK) -> dict:
    p = _p(path)
    length = min(length, MAX_CHUNK)
    with open(p, "rb") as f:
        f.seek(offset)
        data = f.read(length)
    return {"size": p.stat().st_size, "offset": offset, "data_b64": base64.b64encode(data).decode()}


@method("fs.write")
async def write(path: str, data_b64: str, offset: int = 0, truncate: bool = False, mode: int | None = None) -> dict:
    p = _p(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(data_b64)
    flags = "r+b" if p.exists() and not truncate else "wb"
    with open(p, flags) as f:
        f.seek(offset)
        f.write(data)
    if mode is not None:
        os.chmod(p, mode)
    return {"path": str(p), "written": len(data)}


@method("fs.sha256")
async def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(_p(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@method("fs.mkdir")
async def mkdir(path: str) -> str:
    _p(path).mkdir(parents=True, exist_ok=True)
    return str(_p(path))


@method("fs.remove")
async def remove(path: str) -> str:
    p = _p(path)
    shutil.rmtree(p) if p.is_dir() else p.unlink()
    return str(p)
