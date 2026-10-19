#!/usr/bin/env bash
# From the dev machine: copy this checkout to a Linux target over SSH, run the
# installer there, and register the target locally. Works with a private repo
# because the target never needs GitHub access.
#
#   ./scripts/deploy-agent.sh user@target                 # bootstrap, then the setup TUI over SSH
#   ./scripts/deploy-agent.sh user@target --all [opts]    # headless full install
set -euo pipefail
target="${1:?usage: $0 user@host [install options]}"; shift
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
remote_dir='~/.cache/recomp-profiler-src'

echo "==> copying $(git -C "$repo" rev-parse --short HEAD) to $target"
git -C "$repo" archive --format=tar HEAD \
    | ssh "$target" "rm -rf $remote_dir && mkdir -p $remote_dir && tar -x -C $remote_dir"
echo "==> running installer on $target (may ask for sudo)"
ssh -t "$target" "$remote_dir/scripts/install/install.sh $*"

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
ssh "$target" 'cat "${XDG_CONFIG_HOME:-$HOME/.config}/recomp-profiler/agent/connection.json"' > "$tmp"
recomp-profiler add-host "$tmp"
