#!/usr/bin/env bash
# Install the recomp-profiler agent on a Linux test machine.
#
#   ./scripts/install/install.sh [options]
#
#   --port N            agent port (default 47800)
#   --name NAME         host name shown to Claude (default: hostname)
#   --address IP        address the dev machine should use (default: auto-detect)
#   --source PATH|URL   pip source for the package (default: this checkout)
#   --no-packages       skip distro package installation
#   --no-service        don't install/enable the systemd user service
#   --open-firewall     open the port in ufw / firewalld
#   --perf-tuning       allow perf + ptrace for normal users (writes /etc/sysctl.d)
#
# Runs as your normal user (sudo is used only for packages/sysctl/firewall):
# the agent must live in your graphical session to launch games with a display.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PORT=47800 NAME="" ADDRESS="" SOURCE="$REPO_ROOT"
DO_PACKAGES=1 DO_SERVICE=1 DO_FIREWALL=0 DO_PERF=0
PYTHON=python3
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/recomp-profiler"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --name) NAME="$2"; shift 2 ;;
        --address) ADDRESS="$2"; shift 2 ;;
        --source) SOURCE="$2"; shift 2 ;;
        --no-packages) DO_PACKAGES=0; shift ;;
        --no-service) DO_SERVICE=0; shift ;;
        --open-firewall) DO_FIREWALL=1; shift ;;
        --perf-tuning) DO_PERF=1; shift ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) die "unknown option $1" ;;
    esac
done

[[ $EUID -eq 0 ]] && die "run as your normal desktop user, not root"
SUDO=sudo; command -v sudo >/dev/null || SUDO=doas

# ---------------------------------------------------------------- distro detect
[[ -r /etc/os-release ]] || die "/etc/os-release missing; unsupported system"
# shellcheck disable=SC1091
. /etc/os-release
DISTRO_ID="${ID:-unknown}" DISTRO_LIKE="${ID_LIKE:-}"
info "detected ${PRETTY_NAME:-$DISTRO_ID}"

family=""
for id in $DISTRO_ID $DISTRO_LIKE; do
    case "$id" in
        debian|ubuntu) family=apt ;;
        fedora|rhel|centos) family=dnf ;;
        arch) family=pacman ;;
        suse|opensuse*|sles) family=zypper ;;
    esac
    [[ -n "$family" ]] && break
done

if [[ "$DISTRO_ID" == "steamos" ]]; then
    warn "SteamOS has a read-only rootfs; skipping system packages (use --no-packages to silence)"
    DO_PACKAGES=0
fi

# ---------------------------------------------------------------- packages
if [[ $DO_PACKAGES -eq 1 ]]; then
    [[ -n "$family" ]] || die "no package recipe for '$DISTRO_ID' (ID_LIKE='$DISTRO_LIKE'); rerun with --no-packages after installing python>=3.10 manually"
    # shellcheck disable=SC1090
    . "$SCRIPT_DIR/distros/$family.sh"
    info "refreshing package metadata ($family)"
    pkg_refresh
    info "installing: ${PKGS[*]}"
    if ! pkg_install "${PKGS[@]}"; then
        # Package names drift between releases; don't let one missing tool abort setup.
        warn "batch install failed, retrying packages individually"
        for p in "${PKGS[@]}"; do pkg_install "$p" >/dev/null 2>&1 || warn "skipped unavailable package: $p"; done
    fi
fi

# ---------------------------------------------------------------- python env
command -v "$PYTHON" >/dev/null || die "$PYTHON not found"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || die "$PYTHON is $("$PYTHON" -V); need >= 3.10"
info "creating venv in $PREFIX/venv"
mkdir -p "$PREFIX"
"$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q --upgrade pip
"$PREFIX/venv/bin/pip" install -q "$SOURCE"
mkdir -p "$HOME/.local/bin"
ln -sf "$PREFIX/venv/bin/recomp-agent" "$HOME/.local/bin/recomp-agent"

# ---------------------------------------------------------------- tuning
if [[ $DO_PERF -eq 1 ]]; then
    info "allowing unprivileged perf + ptrace attach (/etc/sysctl.d/90-recomp-profiler.conf)"
    printf 'kernel.perf_event_paranoid = 1\nkernel.kptr_restrict = 0\nkernel.yama.ptrace_scope = 0\n' \
        | $SUDO tee /etc/sysctl.d/90-recomp-profiler.conf >/dev/null
    $SUDO sysctl --system >/dev/null
fi

if [[ $DO_FIREWALL -eq 1 ]]; then
    if command -v ufw >/dev/null && $SUDO ufw status | grep -q active; then
        $SUDO ufw allow "$PORT/tcp" comment recomp-agent
    elif command -v firewall-cmd >/dev/null && $SUDO firewall-cmd --state >/dev/null 2>&1; then
        $SUDO firewall-cmd --permanent --add-port="$PORT/tcp" && $SUDO firewall-cmd --reload
    else
        warn "no active ufw/firewalld found; make sure TCP $PORT is reachable"
    fi
fi

# ---------------------------------------------------------------- identity
init_args=(--port "$PORT")
[[ -n "$NAME" ]] && init_args+=(--name "$NAME")
[[ -n "$ADDRESS" ]] && init_args+=(--host-address "$ADDRESS")
"$PREFIX/venv/bin/recomp-agent" init "${init_args[@]}" >/dev/null
CONN="${XDG_CONFIG_HOME:-$HOME/.config}/recomp-profiler/agent/connection.json"

# ---------------------------------------------------------------- service
if [[ $DO_SERVICE -eq 1 ]] && command -v systemctl >/dev/null; then
    unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unit_dir"
    sed -e "s|@AGENT@|$PREFIX/venv/bin/recomp-agent|" -e "s|@PORT@|$PORT|" \
        "$SCRIPT_DIR/recomp-agent.service.in" > "$unit_dir/recomp-agent.service"
    systemctl --user daemon-reload
    systemctl --user enable --now recomp-agent.service \
        || warn "could not start the user service (no graphical session?); start it later with: systemctl --user start recomp-agent"
fi

# ---------------------------------------------------------------- report
echo
info "agent installed. Connection info ($CONN):"
cat "$CONN"
echo
info "all addresses on this machine:"
ip -brief -4 addr show 2>/dev/null | awk '$1 != "lo" {print "    " $1 "  " $3}' || hostname -I
echo
info "on the dev machine, copy that JSON to a file and run:"
echo "    recomp-profiler add-host connection.json"
echo "(the file contains the access token; transfer it privately)"
