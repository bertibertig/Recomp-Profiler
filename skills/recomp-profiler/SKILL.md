---
name: recomp-profiler
description: Deploy, run, debug and profile a recomp build on remote bare-metal Linux/Windows test machines through the recomp-profiler MCP server, and turn the results into per-hardware performance findings and system requirements. Use when testing a recomp on another machine, comparing hardware, chasing a platform-specific crash or stutter, or writing minimum/recommended specs.
---

# Recomp Profiler

Targets are physical machines running `recomp-agent`. The `recomp-profiler` MCP
server (tools below) talks to them. Treat every target like the local machine:
deploy, run, read logs, measure, iterate.

## Workflow

1. **Pick targets** – `list_hosts`; skip unreachable ones and say so.
2. **Know the hardware** – `host_info` per target before measuring anything.
   Record CPU, cores, RAM, GPU + driver, distro/kernel, Wayland vs X11.
3. **Deploy** – `push_file` the build (`executable=true` for the binary) into
   `~/recomp-tests/<project>/<git-sha>/`. Push assets only if changed (`run_command`
   with `sha256sum` to compare).
4. **Run** – `launch_process` with the target's display env; poll
   `process_output` using the returned `next` cursor until it exits or you have
   enough. Always `kill_process` what you started.
5. **Measure** – `host_metrics` with the process pid for CPU/RAM/thermals.
   Frame-time capture (MangoHud/PresentMon) and perf are `profile_*` tools as
   they land; until then use `run_command` (e.g. `MANGOHUD_LOG=1`, `perf stat -p`).
6. **Collect** – `pull_file` logs, captures and core dumps; they land in the
   local captures dir per host.
7. **Report** – per target: hardware summary, avg/1%-low FPS or frame time,
   CPU-bound vs GPU-bound verdict, crashes with backtrace. Compare against the
   other targets and derive min/recommended requirements only from measured runs.

## Rules

- Never run destructive commands (`rm -rf`, package removal, reboot) on a target
  without asking the user first; these are real machines.
- Benchmarks must be comparable: same build sha, same scene/demo, same
  resolution, same duration, warm-up discarded.
- State which numbers were measured and which are inferred.
