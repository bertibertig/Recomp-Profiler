"""``recomp-profiler`` dev-machine CLI: manage hosts and poke agents by hand.

    recomp-profiler add-host connection.json [--name NAME]
    recomp-profiler hosts
    recomp-profiler call HOST METHOD [JSON_PARAMS]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .client import AgentClient, HostConfig, load_hosts
from .config import hosts_dir


def cmd_add_host(args: argparse.Namespace) -> int:
    src = Path(args.connection_file)
    data = json.loads(src.read_text())
    if args.name:
        data["name"] = args.name
    d = hosts_dir()
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"{data['name']}.json"
    dst.write_text(json.dumps(data, indent=2) + "\n")
    dst.chmod(0o600)
    print(f"registered {data['name']} -> {dst}")
    return 0


def cmd_hosts(_: argparse.Namespace) -> int:
    for name, h in load_hosts().items():
        print(f"{name:20} {h.url:32} {h.platform or '?'}")
    return 0


async def _call(host: HostConfig, method: str, params: dict) -> object:
    async with AgentClient(host) as c:
        return await c.call(method, params)


def cmd_call(args: argparse.Namespace) -> int:
    hosts = load_hosts()
    if args.host not in hosts:
        print(f"unknown host {args.host}; known: {', '.join(hosts) or 'none'}", file=sys.stderr)
        return 1
    result = asyncio.run(_call(hosts[args.host], args.method, json.loads(args.params)))
    print(json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="recomp-profiler")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-host", help="register a target from its connection.json")
    a.add_argument("connection_file")
    a.add_argument("--name")
    a.set_defaults(fn=cmd_add_host)
    sub.add_parser("hosts", help="list registered targets").set_defaults(fn=cmd_hosts)
    c = sub.add_parser("call", help="invoke a raw RPC method")
    c.add_argument("host")
    c.add_argument("method")
    c.add_argument("params", nargs="?", default="{}")
    c.set_defaults(fn=cmd_call)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
