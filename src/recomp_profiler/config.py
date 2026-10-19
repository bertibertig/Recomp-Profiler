"""Filesystem locations for agent state and client host registry."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _config_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "recomp-profiler"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "recomp-profiler"


def agent_dir() -> Path:
    """Agent-side state: token, TLS cert/key, connection.json."""
    return Path(os.environ.get("RECOMP_AGENT_DIR", _config_root() / "agent"))


def hosts_dir() -> Path:
    """Client-side registry: one connection JSON per registered target machine."""
    return Path(os.environ.get("RECOMP_HOSTS_DIR", _config_root() / "hosts"))


def captures_dir() -> Path:
    """Client-side store for pulled captures, logs and benchmark results."""
    return Path(os.environ.get("RECOMP_CAPTURES_DIR", _config_root() / "captures"))
