"""User-editable configuration (``config.toml``), edited mainly through the TUI.

Every field carries UI metadata (label, choices, help) so forms are generated
from the dataclasses. Fields marked ``secret`` are stored in ``secrets.toml``
(mode 0600) instead of ``config.toml``.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import tomli_w

from .config import secrets_file, settings_file
from .protocol import DEFAULT_PORT

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PLATFORMS = ("xbox", "gamecube", "ps2", "xbox360", "ps3")
RENDER_BACKENDS = ("cpu", "vulkan", "opengl", "d3d11", "d3d12")
SOURCE_KINDS = ("local", "nfs", "smb", "http")
GAME_FORMATS = ("extracted", "image")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
TRUST_LEVELS = ("own", "external")


def ui(label: str, help: str = "", choices: Any = None, secret: bool = False, **kw: Any) -> dict:
    """Field metadata consumed by the TUI form generator.

    ``choices`` is a tuple of values, or ``"@rom_sources"`` for a choice that is
    resolved at runtime from the current settings.
    """
    return {"label": label, "help": help, "choices": choices, "secret": secret, **kw}


@dataclass
class AgentSettings:
    name: str = field(default="", metadata=ui("Host name", "Shown to Claude; defaults to the hostname"))
    bind: str = field(default="0.0.0.0", metadata=ui("Bind address", "0.0.0.0 = all interfaces"))
    port: int = field(default=DEFAULT_PORT, metadata=ui("Port"))
    address: str = field(default="", metadata=ui("Advertised address", "IP the dev machine connects to; empty = auto-detect"))
    allowed_clients: list[str] = field(
        default_factory=list, metadata=ui("Allowed clients", "Comma-separated IPs/CIDRs; empty = any (token still required)")
    )
    log_level: str = field(default="INFO", metadata=ui("Log level", choices=LOG_LEVELS))
    autostart: bool = field(default=True, metadata=ui("Start with desktop session"))


@dataclass
class StorageSettings:
    gamedata_dir: str = field(default="", metadata=ui("Game data store", "Where game files are cached; empty = default data dir"))
    max_gamedata_gb: int = field(default=0, metadata=ui("Game data size limit (GB)", "0 = unlimited"))
    captures_dir: str = field(default="", metadata=ui("Captures directory", "Empty = default"))
    keep_captures_days: int = field(default=30, metadata=ui("Keep captures (days)", "0 = forever"))


@dataclass
class ProfilingSettings:
    warmup_s: int = field(default=10, metadata=ui("Benchmark warm-up (s)"))
    duration_s: int = field(default=60, metadata=ui("Benchmark duration (s)"))
    frametime_capture: bool = field(default=True, metadata=ui("Capture frame times by default"))
    cpu_sampling: bool = field(default=False, metadata=ui("CPU sampling (perf/WPR) by default"))


@dataclass
class RomSource:
    name: str = field(default="", metadata=ui("Name", "e.g. nas-games"))
    kind: str = field(default="nfs", metadata=ui("Type", choices=SOURCE_KINDS))
    host: str = field(default="", metadata=ui("Server", "e.g. 192.0.2.10 (not used for local)"))
    share: str = field(default="", metadata=ui("Share / export", "SMB share name or NFS export path, e.g. games or /mnt/user/games"))
    path: str = field(default="", metadata=ui("Base path", "Sub-folder inside the share, or the folder for local"))
    mount_point: str = field(default="", metadata=ui("Mount point", "Where it is/will be mounted locally; empty = access without mounting"))
    username: str = field(default="", metadata=ui("Username", "SMB only"))
    password: str = field(default="", metadata=ui("Password", "SMB only; stored in secrets.toml", secret=True))


@dataclass
class Game:
    id: str = field(default="", metadata=ui("ID", "Short slug, e.g. ssx3"))
    title: str = field(default="", metadata=ui("Title", "e.g. SSX 3"))
    platform: str = field(default="xbox", metadata=ui("Platform", choices=PLATFORMS))
    recomp_dir: str = field(default="", metadata=ui("Recomp project folder", "Local checkout of the recomp"))
    source: str = field(default="", metadata=ui("ROM source", "Empty = files are in the recomp project folder", choices="@rom_sources"))
    source_path: str = field(default="", metadata=ui("Path in source", "File or folder relative to the source / project folder"))
    format: str = field(default="extracted", metadata=ui("Stored as", "Extracted files or a disc image", choices=GAME_FORMATS))
    extractor_cmd: str = field(default="", metadata=ui("Extractor command", "Images only; {image} and {out} are substituted"))
    backends: list[str] = field(default_factory=lambda: ["cpu"], metadata=ui("Supported render backends", choices=RENDER_BACKENDS))
    default_backend: str = field(default="cpu", metadata=ui("Default render backend", choices=RENDER_BACKENDS))


@dataclass
class InstallSettings:
    source: str = field(default="", metadata=ui("Agent source", "Checkout or URL used to (re)install the agent"))


@dataclass
class Settings:
    agent: AgentSettings = field(default_factory=AgentSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    profiling: ProfilingSettings = field(default_factory=ProfilingSettings)
    install: InstallSettings = field(default_factory=InstallSettings)
    rom_sources: list[RomSource] = field(default_factory=list)
    games: list[Game] = field(default_factory=list)

    SECTIONS = ("agent", "storage", "profiling", "install")

    def source(self, name: str) -> RomSource | None:
        return next((s for s in self.rom_sources if s.name == name), None)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not 1 <= self.agent.port <= 65535:
            errors.append(f"agent.port {self.agent.port} out of range")
        for c in self.agent.allowed_clients:
            try:
                ipaddress.ip_network(c, strict=False)
            except ValueError:
                errors.append(f"allowed client {c!r} is not an IP or CIDR")
        errors += _unique("ROM source", [s.name for s in self.rom_sources])
        errors += _unique("game", [g.id for g in self.games])
        for s in self.rom_sources:
            if s.kind in ("nfs", "smb", "http") and not s.host:
                errors.append(f"ROM source {s.name}: server is required for {s.kind}")
            if s.kind == "local" and not s.path:
                errors.append(f"ROM source {s.name}: base path is required for local")
        for g in self.games:
            if g.source and not self.source(g.source):
                errors.append(f"game {g.id}: unknown ROM source {g.source!r}")
            if g.default_backend not in g.backends:
                errors.append(f"game {g.id}: default backend {g.default_backend} is not in supported backends")
            if g.format == "image" and not g.extractor_cmd:
                errors.append(f"game {g.id}: disc images need an extractor command")
        return errors


def _unique(what: str, names: list[str]) -> list[str]:
    errors = [f"{what} without a name" for n in names if not n]
    errors += [f"duplicate {what} {n!r}" for n in sorted(set(names)) if n and names.count(n) > 1]
    return errors


def _build(cls: type, data: dict[str, Any]) -> Any:
    """Construct a dataclass from a dict, ignoring unknown keys (forward compat)."""
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def _split_secrets(obj: Any) -> tuple[dict, dict]:
    public, secret = {}, {}
    for f in fields(obj):
        v = getattr(obj, f.name)
        (secret if f.metadata.get("secret") else public)[f.name] = v
    return public, {k: v for k, v in secret.items() if v}


def load(path: Path | None = None) -> Settings:
    path = path or settings_file()
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    sec_path = path.with_name("secrets.toml") if path != settings_file() else secrets_file()
    secrets = tomllib.loads(sec_path.read_text()) if sec_path.exists() else {}
    s = Settings()
    for name in Settings.SECTIONS:
        setattr(s, name, _build(type(getattr(s, name)), data.get(name, {})))
    src_secrets = secrets.get("rom_sources", {})
    s.rom_sources = [_build(RomSource, {**d, **src_secrets.get(d.get("name", ""), {})}) for d in data.get("rom_sources", [])]
    s.games = [_build(Game, d) for d in data.get("games", [])]
    return s


def save(s: Settings, path: Path | None = None) -> None:
    path = path or settings_file()
    sec_path = path.with_name("secrets.toml") if path != settings_file() else secrets_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {name: asdict(getattr(s, name)) for name in Settings.SECTIONS}
    data["rom_sources"], src_secrets = [], {}
    for src in s.rom_sources:
        public, secret = _split_secrets(src)
        data["rom_sources"].append(public)
        if secret:
            src_secrets[src.name] = secret
    data["games"] = [asdict(g) for g in s.games]
    path.write_text("# Edit with `recomp-profiler tui` (values from hand edits are kept, comments are not).\n" + tomli_w.dumps(data))
    if src_secrets:
        sec_path.write_text(tomli_w.dumps({"rom_sources": src_secrets}))
        os.chmod(sec_path, 0o600)
    elif sec_path.exists():
        sec_path.unlink()


def set_value(s: Settings, dotted: str, raw: str) -> None:
    """``section.field = raw`` for scalar section fields (used by install scripts)."""
    section, _, name = dotted.partition(".")
    if section not in Settings.SECTIONS:
        raise KeyError(f"unknown section {section!r}")
    obj = getattr(s, section)
    f = next((f for f in fields(obj) if f.name == name), None)
    if f is None:
        raise KeyError(f"unknown setting {dotted!r}")
    current = getattr(obj, name)
    if isinstance(current, bool):
        value: Any = raw.lower() in ("1", "true", "yes", "on")
    elif isinstance(current, int):
        value = int(raw)
    elif isinstance(current, list):
        value = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        value = raw
    setattr(obj, name, value)


def default_of(f) -> Any:
    if f.default is not MISSING:
        return f.default
    return f.default_factory()  # type: ignore[misc]
