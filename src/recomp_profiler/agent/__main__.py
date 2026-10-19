"""``recomp-agent`` entry point.

Defaults come from ``config.toml`` (edit with ``recomp-profiler tui``); flags override.

    recomp-agent init   [--host-address IP] [--port N] [--name NAME] [--force]
    recomp-agent serve  [--bind ADDR] [--port N] [--insecure]
    recomp-agent show   # print connection.json for pasting into the dev machine
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import socket
import sys

from .. import __version__
from .. import settings as settings_mod
from ..config import agent_dir
from ..protocol import DEFAULT_PORT
from ..security import cert_fingerprint_from_pem, generate_self_signed_cert, generate_token


def _guess_lan_ip() -> str:
    # UDP "connect" picks the outbound interface without sending anything.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def init_agent(
    force: bool = False, name: str | None = None, address: str | None = None, port: int | None = None
) -> dict:
    """Create token/cert if missing (or rotate with force) and write connection.json."""
    agent = settings_mod.load().agent
    d = agent_dir()
    d.mkdir(parents=True, exist_ok=True)
    token_file, cert, key = d / "token", d / "cert.pem", d / "key.pem"
    if force or not token_file.exists():
        token_file.write_text(generate_token())
        token_file.chmod(0o600)
    if force or not cert.exists():
        generate_self_signed_cert(cert, key)
    conn = {
        "name": name or agent.name or socket.gethostname(),
        "address": address or agent.address or _guess_lan_ip(),
        "port": port or agent.port,
        "token": token_file.read_text().strip(),
        "tls_fingerprint_sha256": cert_fingerprint_from_pem(cert),
        "platform": sys.platform,
        "agent_version": __version__,
    }
    out = d / "connection.json"
    out.write_text(json.dumps(conn, indent=2) + "\n")
    out.chmod(0o600)
    return conn


def cmd_init(args: argparse.Namespace) -> int:
    conn = init_agent(args.force, args.name, args.host_address, args.port)
    print(f"wrote {agent_dir() / 'connection.json'}")
    print(json.dumps(conn, indent=2))
    return 0


def cmd_show(_: argparse.Namespace) -> int:
    print((agent_dir() / "connection.json").read_text())
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import Agent

    d = agent_dir()
    token_file = d / "token"
    if not token_file.exists():
        print("no token found, run `recomp-agent init` first", file=sys.stderr)
        return 1
    cfg = settings_mod.load().agent
    logging.getLogger().setLevel(logging.DEBUG if args.verbose else cfg.log_level)
    cert = None if args.insecure else d / "cert.pem"
    key = None if args.insecure else d / "key.pem"
    agent = Agent(
        token_file.read_text().strip(),
        args.bind or cfg.bind,
        args.port or cfg.port,
        cert,
        key,
        allowed_clients=cfg.allowed_clients,
    )
    try:
        asyncio.run(agent.serve_forever())
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="recomp-agent")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="generate token + TLS cert and write connection.json")
    pi.add_argument("--host-address", help="address the dev machine should connect to")
    pi.add_argument("--port", type=int, help=f"default from config.toml, else {DEFAULT_PORT}")
    pi.add_argument("--name")
    pi.add_argument("--force", action="store_true", help="rotate token and certificate")
    pi.set_defaults(fn=cmd_init)

    ps = sub.add_parser("serve", help="run the agent")
    ps.add_argument("--bind", help="default from config.toml (0.0.0.0)")
    ps.add_argument("--port", type=int, help=f"default from config.toml, else {DEFAULT_PORT}")
    ps.add_argument("--insecure", action="store_true", help="plain ws:// (testing only)")
    ps.set_defaults(fn=cmd_serve)

    sub.add_parser("show", help="print connection.json").set_defaults(fn=cmd_show)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
