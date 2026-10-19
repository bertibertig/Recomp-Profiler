#!/usr/bin/env bash
# Remove the agent, its service and its credentials. Distro packages are left alone.
set -euo pipefail
systemctl --user disable --now recomp-agent.service 2>/dev/null || true
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/recomp-agent.service"
systemctl --user daemon-reload 2>/dev/null || true
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/recomp-profiler"
rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/recomp-profiler/agent"
rm -f "$HOME/.local/bin/recomp-agent"
[[ -f /etc/sysctl.d/90-recomp-profiler.conf ]] && echo "note: remove /etc/sysctl.d/90-recomp-profiler.conf manually to undo --perf-tuning"
echo "recomp-agent removed"
