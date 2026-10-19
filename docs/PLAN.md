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

## Target platforms

The current recomps target 6th-gen consoles: **Xbox, GameCube and PS2**. Xbox 360 and PS3 come later.

**First projects:** *SSX 3* and *Amped 2*, both Xbox versions. Integration details are in [First projects](#first-projects-ssx-3-and-amped-2).

| Graphics API | Linux | Windows |
|---|---|---|
| CPU (software renderer) | ✅ now | ✅ now |
| Vulkan | ✅ now | ✅ now |
| OpenGL | – | ✅ now |
| D3D11 / D3D12 | – | later |

The **CPU (software) renderer** is where every project starts before a GPU backend exists, and it stays as the compatibility fallback. It also matters for profiling: rendering cost appears in the CPU profile instead of on the GPU, so its frame times come from `recomp_probe.h` frame markers (MangoHud and PresentMon only see presents, if the window presents at all). It gets its own line in the system requirements, since it is mostly CPU-bound. It is also the realistic path for the retro Windows targets.

Each GPU API needs its own capture path. MangoHud covers Vulkan and OpenGL on Linux. PresentMon covers every API on Windows. RenderDoc handles Vulkan, OpenGL, D3D11 and D3D12 frame captures. Benchmarks record which API was used, so results stay comparable.

## Configuration TUI

Everything that can be configured is configured through one TUI (`recomp-profiler tui`, built with Textual; it works in Linux terminals, Windows Terminal and over SSH). Settings live in `config.toml` in the config directory, and secrets (SMB passwords) in a separate `secrets.toml` readable only by the user.

* **Install scripts are bootstrappers:** `install.sh` / `install.ps1` without arguments install only Python and the venv, then open the TUI. With arguments (`--all`, `--only <step>`, …) they run headless, which CI and `deploy-agent.sh` need. The TUI's setup actions call the same scripts with `--only <step>`, so there's a single implementation of each step.
* **Tabs:**
  * **Overview:** agent status, version, connection info and IP addresses
  * **Agent:** name, bind address, port, advertised address, client IP allowlist, log level; rotate token/certificate; show `connection.json`
  * **System setup:** install/reinstall packages, perf/ptrace tuning, firewall, autostart service, uninstall
  * **ROM sources:** NFS/SMB/local/HTTP shares (e.g. a NAS share), with a connection test
  * **Games:** per game: platform, recomp project folder, ROM source, path in the source, whether it's **extracted or a disc image** (plus the extractor command for images), supported and default render backend
  * **Hosts:** registered target machines, trust level (own/external), ping, remove
  * **Storage & profiling:** game-data store location and size limit, captures directory and retention, benchmark defaults (warm-up, duration)

## Builds vs. game files

These two are handled separately because they behave very differently:

| | Build (recomp executable + runtime) | Game files (extracted from your own discs) |
|---|---|---|
| Size | tens to hundreds of MB | GameCube ≈1.4 GB, Xbox/PS2 up to ≈8.5 GB, 360/PS3 16+ GB |
| Changes | every iteration | almost never |
| Legal | ours | copyrighted, never in git and never sent to anyone else's machine |

**Content-addressed store on each agent.** Every machine keeps
`~/.local/share/recomp-profiler/gamedata/<game-id>/<manifest-hash>/`.
A *manifest* lists every file with its size and hash, plus hashes of 4 MB chunks. A test run references `game-id@manifest-hash`, and the agent links that data into the run directory or passes its path via an environment variable. Each dataset is transferred **once per machine**. After that, only the files or chunks that changed are sent. Builds use the same mechanism, with small manifests.

There are three ways to fill the store, and all of them are verified against the manifest:

1. **Push from the dev machine (LAN default).** The agent compares manifests and only the missing chunks are streamed. They go over a dedicated binary channel on the same TLS port, using parallel streams that can resume after interruption, and each chunk is verified on arrival. Optional zstd compression is turned off automatically for data that doesn't shrink, since disc data mostly doesn't. On gigabit LAN, a full 8.5 GB DVD takes about 80 s and 16 GB about 2.5 min.
2. **Pull from a LAN share.** You configure an SMB/NFS/HTTP share, and the agent copies from it directly, so the data never passes through the dev machine. The first target is a NAS that exports the same share over NFS and SMB, with extracted games in per-platform folders (`Xbox/<Title>/`). Linux agents use NFS, Windows agents use SMB. The concrete server, share and mount point live only in each machine's `config.toml`.
3. **Extract on the target.** The tester points the agent at their *own* disc image, and the agent runs the recomp's extractor locally. The result is checked against the expected manifest and the known dump hashes (Redump). This is the **only** mode allowed for hosts marked `trust: external` (remote testers over Tailscale), so game data is never distributed to other people.

## First projects: SSX 3 and Amped 2

Surveyed read-only on 2026-10-19. The projects themselves are not changed by this repo while they're being worked on.

| | SSX 3 | Amped 2 |
|---|---|---|
| Repo | [bertibertig/SSX3-Recomp](https://github.com/bertibertig/SSX3-Recomp) | [bertibertig/Amped2-Recomp](https://github.com/bertibertig/Amped2-Recomp) |
| Version | PAL, title ID 0x4541003C | PAL, title ID 0x4D530041 |
| Game files | extracted into `game_files/` (≈2.2 GB) | extracted into `game_files/` (≈4.0 GB) |
| Renderers | Vulkan (Linux, 55–60 fps in races) and CPU (reference) | Vulkan (≈55 fps riding) and CPU (≈6 fps, reference) |
| Renderer switch | `SSX3_RENDERER=vulkan\|cpu` | `AMPED2_RENDERER=vulkan\|cpu` |
| Windows | experimental, CPU renderer only, tested under Wine/Proton | Windows build scripts exist |
| Launch | `scripts/run.sh` (start-up menu only on a TTY; `SSX3_MENU=0` forces it off) | `scripts/run.sh` |
| Releases | `scripts/package_release.sh` → binary + scripts + `game_files/` side by side | – |

**What this means for the profiler:**
- **No shared runtime library.** Both pin the same toolkit, xboxrecomp v0.14.0 (git submodule). Amped 2's host and input code was copied from SSX 3. So a future `recomp_probe.h` belongs in xboxrecomp itself, or in a small shared host module both projects include. Until then, profiling must be **non-invasive**.
- **Non-invasive measurement available today:**
  - Vulkan: MangoHud (it's a Vulkan layer, so no code change is needed)
  - Both renderers: the once-per-second window title `FPS: x (game y) | draws: n`, read via X11/XWayland window properties (presented fps and the game's own fps)
  - CPU renderer: the SDL2 framebuffer window. Forcing `SDL_RENDER_DRIVER=opengl` should make it visible to MangoHud's OpenGL hook (to verify)
- **Deterministic input for benchmarks already exists:** `RECOMP_PAD_SCRIPT=<ms>:<button>[:hold],…` or `@file` (xboxrecomp `usb_gamepad.c`). A benchmark spec can be a pad script that boots to a fixed race and rides it. Add `RECOMP_WATCHDOG_SECS` for hangs.
- **`game_files/` holds more than the disc contents:** the projects add patched XBEs (`default.xbe` next to `default.xbe_orig`, `default_ffp.xbe`). A share mirror must include those, so it can serve as the source of truth for test machines. Manifests must **exclude generated files**: `default_analysis.json`, `README.md`, `CACHE/`.
- **Couch co-op:** SSX 3 split screen already works with `RECOMP_USB_PADS=2` (≈27 fps; the game caps split screen at 30). Test it with two scripted pads.
- **LAN multiplayer:** SSX 3 is planning it on the branch `feature/lan-multiplayer`, see `docs/lan-multiplayer.md`. It uses ENet over UDP with state sync at 30 Hz, a host-owned session, and **UDP broadcast** for LAN discovery plus direct IP. This is the "two machines" case from Phase 4b: test it with multi-host start, packet capture on the ENet port, and added latency and loss. Discovery needs broadcast, so over Tailscale only direct IP will work.
- **Logs to collect after every run:** stderr, `xbox_kernel.log`, `logs/`, and BMP frame dumps (`SSX3_VK_DUMP` / `AMPED2_VK_DUMP` / `RECOMP_FB_DUMP`) for renderer comparisons across machines.

**TODOs from this:**
- [ ] Game settings: add `exclude` patterns, a launch command (default `scripts/run.sh` or the release's `run.sh`), a renderer environment variable name, and a required-file check (`default.xbe`), all editable in the TUI
- [ ] Deploy unit for test machines = the release package layout (`package_release.sh`), with `game_files/` filled from the agent's game-data store
- [ ] Window-title FPS reader and MangoHud log parser as the first frame-time backends
- [ ] Benchmark spec built on `RECOMP_PAD_SCRIPT`: boot, enter a fixed race, ride N seconds, quit
- [ ] Split-screen benchmark preset (`RECOMP_USB_PADS=2`, two pad scripts)

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

### Phase 1: remote control MVP + game-file transfer (see "Builds vs. game files")
- [ ] Binary streaming channel for file transfer (base64 currently costs 33% extra): parallel, resumable, chunk-verified, with progress reporting
- [ ] Manifest format and a tool that generates one from an extracted game directory or a build output (`recomp-profiler manifest <dir>`)
- [ ] Content-addressed store on the agent, with `gamedata.status/sync/link/gc` RPCs; MCP tools `sync_gamedata` and `deploy_build` that send only deltas
- [ ] Source: pull from an SMB/NFS/HTTP share configured on the agent (first target: a NAS share over NFS on Linux and SMB on Windows; server, share and credentials stay in each machine's local config, never in this repo)
- [ ] Source: push from game files that sit in the dev machine's local recomp project folders (the current setup for SSX 3 and Amped 2)
- [ ] Source: extract on the target from the tester's own disc image using the recomp's extractor, checked against Redump hashes
- [ ] Host `trust: own|external` flag, and refuse to push game data to external hosts
- [ ] Disk space checks and garbage collection of unused datasets and builds
- [ ] Pass the display/session environment through correctly (Wayland vs X11, `XDG_RUNTIME_DIR`), and import it into the systemd user service
- [ ] Screenshot tool (grim/spectacle/gnome-screenshot/`xwd` on Linux, GDI/DXGI on Windows) so Claude can see what's on screen
- [ ] Optional input injection (uinput / SendInput) for menu navigation in tests
- [ ] Push-based log streaming (server→client notifications) instead of polling
- [ ] Reconnect and handshake version checks; `agent.update` for self-update from the dev machine
- [ ] Per-host locking, so two sessions don't benchmark the same machine at once

### Phase 1b: configuration TUI
- [x] `config.toml` model (agent, storage, profiling, ROM sources, games) with separate secrets
- [x] TUI skeleton with tabs: Overview, Agent, System setup, ROM sources, Games, Hosts, Storage & profiling
- [x] Install scripts: bootstrap mode → TUI; headless `--all` / `--only <step>`
- [ ] ROM source "test connection" (`showmount -e` / `smbclient -L` on Linux, `Test-NetConnection` + `net view` on Windows) and mounting: fstab/autofs entry or userspace SMB/NFS access, so the agent doesn't need root at runtime
- [ ] Browse the share inside the TUI to pick a game's path, and auto-detect image vs. extracted
- [ ] Apply agent changes live (restart the service from the TUI) and validate settings before saving
- [ ] Windows parity for the System setup actions (`install.ps1 -Only <step>`)

### Phase 2: profiling backends (`profile.start/stop` → capture file → pull → summarize)
- [ ] **Frame times:** MangoHud CSV log on Linux (Vulkan/GL) and PresentMon on Windows. Report avg, 1% low, 0.1% low, a stutter histogram and a frame-time graph. For the CPU renderer, frame times come from `recomp_probe.h` frame markers
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

### Phase 4b: multiplayer, couch co-op and networking (TODO only; depends on how the recomps implement these)
- [ ] **Local couch co-op:** virtual controllers per player (uinput on Linux, ViGEmBus or a successor on Windows) driven by scripted input per player. Check that each player's input is routed to the right player, and profile split-screen separately, since it often doubles rendering cost and gets its own requirements line
- [ ] **"Pseudo" couch co-op across two machines:** run one session across two hosts. Start both at the same time, inject input on each, and measure input-to-remote latency and desync (compare state checksums if the runtime exposes them)
- [ ] **Multi-host orchestration primitives:** `session_create(hosts, roles)`, synchronized start, and collecting logs and captures from all participants together
- [ ] **Xbox System Link / Xbox Live** (Insignia-style revival services): multi-host LAN sessions, plus checks of the broadcast/UDP traffic (port 3074)
- [ ] **GameCube Broadband Adapter LAN play** (e.g. Mario Kart: Double Dash!!, Phantasy Star Online): test whichever BBA backend the recomps implement (tap, UDP tunnel, XLink Kai-style)
- [ ] **Network test tools:** packet capture on agents (tcpdump on Linux, pktmon on Windows, pulled to the dev machine as pcap) and network impairment (latency, jitter, loss via `tc netem` on Linux or clumsy on Windows) to test bad connections
- [ ] **VPN caveat:** Tailscale/WireGuard don't forward LAN broadcasts, which System Link and BBA discovery rely on. Remote testing needs a broadcast relay or tunnel, and the tool should detect and report when that's missing
- [ ] Optionally, the PS2 network adapter for the few PS2 online/LAN titles

### Phase 5: installers, CI, distribution
- [ ] Container CI matrix for `install.sh`: debian:12, ubuntu:22.04/24.04, fedora:latest, rockylinux:8/9, archlinux, opensuse/tumbleweed and leap
- [ ] Windows CI job for `install.ps1`, with shellcheck + PSScriptAnalyzer + pytest
- [ ] `install.ps1` must install **everything** without manual steps: Python via winget, plus WinDbg, WPR/WPA and Sysinternals via winget, and PresentMon from its GitHub release (it has no winget id)
- [ ] More distros: Gentoo, Void, Alpine (musl), NixOS (flake), Bazzite/Fedora Atomic (rpm-ostree / toolbox)
- [ ] Steam Deck / SteamOS: user-space only, Flatpak MangoHud
- [ ] Optional single-file agent binary (PyInstaller or Nuitka) for machines that shouldn't get a Python install

### Phase 5b: retro Windows targets (minor goal, much later)
- [ ] Run and profile recomps on **Windows XP and Windows 98** machines. Python can't run there (XP's last supported version is 3.4; 98 has none), so this needs a small native agent written in C (Winsock + a subset of the RPC) built with an old toolchain (e.g. MinGW / VC6-compatible)
- [ ] Start with the CPU (software) renderer there; it avoids old-driver problems
- [ ] Measure frame times with in-process `recomp_probe.h` timing, since PresentMon/ETW don't exist there; D3D8/D3D9 or OpenGL 1.x/2.x backends would come from the recomp side
- [ ] TLS on 98 is impractical: use a plain token over a trusted LAN only, or tunnel through a modern relay host

### Phase 6: security hardening
- [ ] Token rotation command; client IP allowlist
- [ ] Audit log on the agent of every command executed
- [ ] Read-only/observe-only mode for machines owned by other people (metrics and captures, no exec)
- [ ] mDNS discovery (`_recomp-agent._tcp`) so hosts can be found without typing IPs (the token is still required)

## Decisions
- Platforms: Xbox, GameCube and PS2 first; 360 and PS3 later.
- First projects: SSX 3 and Amped 2 (Xbox). CPU (software) renderer on both; Vulkan on Linux; Vulkan + OpenGL on Windows; D3D11/D3D12 later.
- All configuration (installs, reinstalls, ROM shares, game locations, agent settings) goes through the TUI.
- Game files: extracted (not images), in each project's `game_files/` and mirrored on a NAS share (NFS + SMB). Setup-specific values (servers, paths, game entries) stay in local `config.toml` / `local/`, never in git.
- The recomp repos are read-only for this project while they're being worked on.
- Retro Windows (XP/98): minor goal, much later.
- Windows: Python is fine, but `install.ps1` must install it (and every other tool) through winget.
- Network: LAN first; Tailscale or another VPN later for remote testers.
- License: MIT.

## Open questions
1. Should `recomp_probe.h` (frame markers, zones, counters) eventually go upstream into xboxrecomp, or into a host module shared by your projects?
2. Should test machines get release packages (binary + scripts) or full source builds? Release packages are smaller and match what players get.
