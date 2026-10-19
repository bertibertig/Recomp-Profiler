# Recomp Profiler

Remote debug, profile and control of **bare-metal Linux and Windows test
machines** for static-recompilation projects — exposed to Claude Code as an MCP
server + skill, so testing a recomp on a friend's old laptop feels the same as
testing it locally.

```
 dev machine (Claude Code)                     test machines (bare metal)
┌──────────────────────────────┐   wss + token   ┌───────────────────────────┐
│ skill: recomp-profiler       │  TLS pinned     │ recomp-agent (user session)│
│ MCP:   recomp-profiler-mcp ──┼────────────────►│  system / process / fs     │
│ CLI:   recomp-profiler       │  JSON-RPC 2.0   │  profile / debug (planned) │
│ hosts: ~/.config/.../hosts/  │                 │  perf, gdb, MangoHud,      │
└──────────────────────────────┘                 │  PresentMon, WPR, ...      │
                                                 └───────────────────────────┘
```

## Quick start

**Target (Linux)** — Debian/Ubuntu/Mint/Pop, Fedora/RHEL/Rocky/Alma, Arch/Manjaro/
EndeavourOS/Garuda/CachyOS, openSUSE:

```bash
./scripts/install/install.sh
```

This installs Python and the agent, then opens the **setup TUI**. Everything
else is done from there: installing debugging/profiling tools, autostart
service, firewall, perf tuning, agent settings, ROM sources and games. For
scripted setups, use `install.sh --all [--open-firewall --perf-tuning]` or
`install.sh --only <step>`.

Or push from the dev machine over SSH (no GitHub access needed on the target):

```bash
./scripts/deploy-agent.sh user@192.168.1.50 --open-firewall
```

**Target (Windows)**:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -OpenFirewall
```

**Dev machine**:

```bash
uv venv && uv pip install -e '.[mcp,dev]'
.venv/bin/recomp-profiler tui        # hosts, ROM sources, games, settings
.venv/bin/recomp-profiler add-host connection.json
.venv/bin/recomp-profiler call my-laptop system.info
```

`.mcp.json` in this repo registers the MCP server for Claude Code; the skill is in
`skills/recomp-profiler/`.

## Security

The agent executes arbitrary commands as the desktop user, which is the point.
Access requires the 256-bit token and the client pins the agent's self-signed
certificate. Keep it on a trusted LAN or VPN (Tailscale/WireGuard); don't port-forward it.
`connection.json` is a credential.

## Game files

Current targets are Xbox, GameCube and PS2 recomps. Extracted game files are
copyrighted. They are never stored in git and are moved separately from builds,
using a content-addressed store on each agent that transfers each dataset once
per machine. See "Builds vs. game files" in [docs/PLAN.md](docs/PLAN.md).

See [docs/PLAN.md](docs/PLAN.md) for the roadmap.
