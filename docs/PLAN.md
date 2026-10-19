# Recomp Profiler: plan

## Goal

Make recomps run well on hardware we don't own, and publish system
requirements based on measured runs. Claude needs to be able to deploy,
run, debug and profile a build on a remote bare-metal Linux or Windows machine
just like it does locally, then compare the results across machines.

## Architecture decision

**Client/server with a custom agent**, rather than SSH alone.

| Option | Verdict |
|---|---|
| SSH only | Fine for Linux shell access. On Windows, OpenSSH runs in session 0, so it **can't launch a game on the desktop**. There's also no structured API for metrics or captures. We still use it for bootstrapping (`deploy-agent.sh`). |
| Ansible/Salt | Overkill for provisioning a handful of machines, and it doesn't help with runtime debugging or profiling. |
| **Agent in the user's desktop session + MCP bridge** ✅ | Works the same way on both OSes, can launch games with a display, has a structured RPC that can grow, and lets one MCP server drive many machines. |
| Existing remote tools | These plug into the agent as backends rather than replacing it: Tracy (in-process zones, network capture), RenderDoc remote server (GPU frame captures), PresentMon, WPR/ETW, perf, MangoHud. |

* **Transport:** JSON-RPC 2.0 over WebSocket with TLS. The agent's certificate is self-signed and the client pins its SHA-256 fingerprint. Authentication is a 256-bit bearer token.
* **Agent:** Python ≥3.10 using `websockets`, `psutil` and `cryptography`, which is available on every target distro. It runs as a systemd **user** service on Linux and as a logon scheduled task on Windows, so it lives in the graphical session.
* **Dev side:** an MCP server (`mcp` 2.x, stdio), a CLI, and the Claude skill in `skills/recomp-profiler/`.
* **Pairing:** `recomp-agent init` writes `connection.json` (address, port, token, fingerprint). Running `recomp-profiler add-host` on the dev machine registers it there.

## Status: phase 0 (skeleton) ✅

- [x] Agent: auth, TLS, concurrent RPC dispatch
- [x] `system.ping/info/metrics/methods`: hardware inventory including GPUs (nvidia-smi, lspci, WMI)
- [x] `process.exec/spawn/output/list/kill`: launch the recomp, read its output from a ring buffer with a cursor
- [x] `fs.stat/list/read/write/sha256/mkdir/remove`: chunked file transfer
- [x] `profile.*` and `debug.*` stubs that return NOT_IMPLEMENTED
- [x] Client with fingerprint pinning, CLI, and an MCP server with 12 tools
- [x] Install scripts: apt, dnf (with EPEL/EL8 Python), pacman, zypper, SteamOS (no packages), Windows (winget)
- [x] `deploy-agent.sh`: push over SSH and register, so targets never need access to the private repo
- [x] End-to-end tests over real TLS (5 passing)

## TODOs

### Phase 1: remote control MVP (make it pleasant)
- [ ] Binary WebSocket frames for file transfer (base64 currently costs 33% extra), with progress reporting
- [ ] Directory sync with per-file hashes, so redeploying a 2 GB build after a one-file change only sends the delta (`deploy_build` MCP tool)
- [ ] Pass the display/session environment through correctly (Wayland vs X11, `XDG_RUNTIME_DIR`), and import it into the systemd user service
- [ ] Screenshot tool (grim/spectacle/gnome-screenshot/`xwd` on Linux, GDI/DXGI on Windows) so Claude can see what's on screen
- [ ] Optional input injection (uinput / SendInput) for menu navigation in tests
- [ ] Push-based log streaming (server→client notifications) instead of polling
- [ ] Reconnect and handshake version checks; `agent.update` for self-update from the dev machine
- [ ] Per-host locking, so two sessions don't benchmark the same machine at once

### Phase 2: profiling backends (`profile.start/stop` → capture file → pull → summarize)
- [ ] **Frame times:** MangoHud CSV log on Linux (Vulkan/GL) and PresentMon on Windows. Report avg, 1% low, 0.1% low, a stutter histogram and a frame-time graph
- [ ] **CPU:** `perf stat` counters (IPC, cache misses, context switches) and `perf record`. Fold stacks into a text summary Claude can read (top functions, hottest recompiled blocks). WPR/ETW on Windows via `wpaexporter`
- [ ] **GPU:** nvidia-smi dmon, the amdgpu sysfs `gpu_busy_percent`, intel_gpu_top. RenderDoc remote capture of individual frames
- [ ] **Tracy:** headless `tracy-capture` on the agent when the recomp runtime is built with Tracy
- [ ] **`recomp_probe.h`:** a tiny header-only C/C++ API that recomp runtimes can include (frame markers, named zones, counters such as "recompiled function calls/frame" and "interpreter fallbacks"). Sends over shared memory or a local socket to the agent, with zero cost when compiled out
- [ ] Bottleneck classification per run (CPU-bound, GPU-bound, shader compilation stutter, I/O, thermal throttling from sensor data)
- [ ] Probe for actually usable backends (`perf_event_paranoid`, tools installed) in `profile.backends`

### Phase 3: debugging
- [ ] DAP relay: `gdb -i dap` / `lldb-dap` on Linux, `cdb` or lldb on Windows, exposed as breakpoint, backtrace, registers and memory tools
- [ ] Crash collection: `coredumpctl` and core_pattern on Linux, WER LocalDumps on Windows. Pull dumps automatically when a spawned process dies on a signal or exception
- [ ] Symbolize on the dev machine (symbols stay local, so release builds can be stripped), with a mapping from recompiled function back to the original guest address
- [ ] Optional sanitizer/debug build variants in the benchmark matrix

### Phase 4: benchmarks and system requirements (the main deliverable)
- [ ] `recomp-bench.toml` spec: build, args, scene/savestate, **deterministic input replay**, warm-up, duration, resolution, and quality presets
- [ ] Run matrix: hosts × presets × builds, executed sequentially per host and in parallel across hosts
- [ ] Results store (SQLite) keyed by build SHA + hardware fingerprint (CPU, GPU, driver, RAM, OS, kernel)
- [ ] Regression detection between builds on the same host
- [ ] **Requirements derivation:** for each target (e.g. 60 fps with 1% low ≥ 55 at preset X), the weakest passing hardware becomes the minimum and the comfortable-margin hardware becomes the recommended. Normalize CPUs and GPUs into performance tiers so the results extrapolate to hardware we didn't test, and mark extrapolated entries as estimates
- [ ] Generate a markdown/HTML spec sheet and per-hardware report, including known driver issues (Mesa version, NVIDIA proprietary vs nouveau/NVK, etc.)

### Phase 5: installers, CI, distribution
- [ ] Container CI matrix for `install.sh`: debian:12, ubuntu:22.04/24.04, fedora:latest, rockylinux:8/9, archlinux, opensuse/tumbleweed and leap
- [ ] Windows CI job for `install.ps1`, with shellcheck + PSScriptAnalyzer + pytest
- [ ] Fetch PresentMon from GitHub releases (it has no winget id)
- [ ] More distros: Gentoo, Void, Alpine (musl), NixOS (flake), Bazzite/Fedora Atomic (rpm-ostree / toolbox)
- [ ] Steam Deck / SteamOS: user-space only, Flatpak MangoHud
- [ ] Optional single-file agent binary (PyInstaller or Nuitka) for machines that shouldn't get a Python install

### Phase 6: security hardening
- [ ] Token rotation command; client IP allowlist
- [ ] Audit log on the agent of every command executed
- [ ] Read-only/observe-only mode for machines owned by other people (metrics and captures, no exec)
- [ ] mDNS discovery (`_recomp-agent._tcp`) so hosts can be found without typing IPs (the token is still required)

## Open questions
1. Which recomp(s) come first (N64Recomp/RT64, XenonRecomp/Unleashed, ps2recomp, …)? This decides the graphics APIs and where `recomp_probe.h` hooks in.
2. Is a Python install acceptable on Windows targets, or should a single-file agent binary be prioritized?
3. Are the targets on the same LAN, or remote (friends/testers) over Tailscale or WireGuard?
4. Is MIT the right license?
