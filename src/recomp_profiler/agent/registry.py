"""RPC method registry. Handler modules register coroutines with ``@method``."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

Handler = Callable[..., Awaitable[Any]]

METHODS: dict[str, Handler] = {}


def method(name: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        if name in METHODS:
            raise ValueError(f"duplicate RPC method {name}")
        METHODS[name] = fn
        return fn

    return deco
