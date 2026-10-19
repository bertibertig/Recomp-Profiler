#!/usr/bin/env bash
# Install / configure the recomp-profiler agent on a Linux test machine.
#
#   ./scripts/install/install.sh                 # bootstrap Python + agent, then open the TUI
#   ./scripts/install/install.sh --all [opts]    # full headless install (CI, scripted setups)
#   ./scripts/install/install.sh --only STEP     # one step: packages|venv|init|service|perf|firewall
#
#   --port N            agent port, saved to config.toml (default 47800)
#   --name NAME         host name shown to Claude (default: hostname)
#   --address IP        address the dev machine should use (default: auto-detect)
#   --source PATH|URL   pip source for the package (default: this checkout)
#   --no-packages       --all without distro packages
#   --no-service        --all without the systemd user service
#   --open-firewall     --all plus opening the port in ufw / firewalld
#   --perf-tuning       --all plus allowing perf + ptrace for normal users
#   --no-tui            bootstrap without opening the TUI
#
# Runs as your normal user (sudo only for packages/sysctl/firewall): the agent
# must live in your graphical session to launch games with a display.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODE="" ONLY="" PORT="" AGENT_NAME="" ADDRESS="" SOURCE=""
DO_PACKAGES=1 DO_SERVICE=1 DO_FIREWALL=0 DO_PERF=0 DO_TUI=1
PYTHON=python3 PKGS=() BOOTSTRAP_PKGS=()
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/recomp-profiler"
VENV="$PREFIX/venv"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all) MODE=all; shift ;;
        --only) MODE=only; ONLY="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --name) AGENT_NAME="$2"; shift 2 ;;
        --address) ADDRESS="$2"; shift 2 ;;
        --source) SOURCE="$2"; shift 2 ;;
        --no-packages) MODE="${MODE:-all}"; DO_PACKAGES=0; shift ;;
        --no-service) MODE="${MODE:-all}"; DO_SERVICE=0; shift ;;
        --open-firewall) MODE="${MODE:-all}"; DO_FIREWALL=1; shift ;;
        --perf-tuning) MODE="${MODE:-all}"; DO_PERF=1; shift ;;
        --no-tui) DO_TUI=0; shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) die "unknown option $1" ;;
    esac
done
MODE="${MODE:-bootstrap}"
[[ -t 0 ]] || DO_TUI=0

[[ $EUID -eq 0 ]] && die "run as your normal desktop user, not root"
SUDO=sudo; command -v sudo >/dev/null || SUDO=doas

# Default source: this checkout when run from one, else what the last install used.
if [[ -z "$SOURCE" ]]; then
    if [[ -f "$REPO_ROOT/pyproject.toml" ]]; then
        SOURCE="$REPO_ROOT"
    elif [[ -x "$VENV/bin/python" ]]; then
        SOURCE="$("$VENV/bin/python" -c 'from recomp_profiler import settings; print(settings.load().install.source)' 2>/dev/null || true)"
    fi
fi

# ---------------------------------------------------------------- distro detect
[[ -r /etc/os-release ]] || die "/etc/os-release missing; unsupported system"
# shellcheck disable=SC1091
. /etc/os-release
DISTRO_ID="${ID:-unknown}" DISTRO_LIKE="${ID_LIKE:-}"

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
if [[ -n "$family" ]]; then
    # shellcheck disable=SC1090
    . "$SCRIPT_DIR/distros/$family.sh"
fi
CAN_PACKAGE=1
if [[ "$DISTRO_ID" == steamos ]]; then
    warn "SteamOS has a read-only rootfs; system packages are skipped"
    CAN_PACKAGE=0
elif [[ -z "$family" ]]; then
    warn "no package recipe for '$DISTRO_ID' (ID_LIKE='$DISTRO_LIKE'); install python>=3.10 and tools manually"
    CAN_PACKAGE=0
fi

install_pkgs() {
    [[ $CAN_PACKAGE -eq 1 ]] || return 0
    info "refreshing package metadata ($family)"
    pkg_refresh
    info "installing: $*"
    if ! pkg_install "$@"; then
        # Package names drift between releases; don't let one missing tool abort setup.
        warn "batch install failed, retrying packages individually"
        for p in "$@"; do pkg_install "$p" >/dev/null 2>&1 || warn "skipped unavailable package: $p"; done
    fi
}

cfg() { "$VENV/bin/recomp-profiler" config-set "$@"; }

# ---------------------------------------------------------------- steps
step_packages() { info "detected ${PRETTY_NAME:-$DISTRO_ID}"; install_pkgs "${PKGS[@]}"; }

step_bootstrap_packages() {
    if command -v "$PYTHON" >/dev/null && "$PYTHON" -c 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        return 0
    fi
    install_pkgs "${BOOTSTRAP_PKGS[@]}"
}

step_venv() {
    [[ -n "$SOURCE" ]] || die "no agent source known; pass --source PATH|URL"
    command -v "$PYTHON" >/dev/null || die "$PYTHON not found"
    "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
        || die "$PYTHON is $("$PYTHON" -V); need >= 3.10"
    info "creating venv in $VENV"
    mkdir -p "$PREFIX"
    "$PYTHON" -m venv --clear "$VENV"
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q "$SOURCE"
    mkdir -p "$HOME/.local/bin"
    ln -sf "$VENV/bin/recomp-agent" "$HOME/.local/bin/recomp-agent"
    ln -sf "$VENV/bin/recomp-profiler" "$HOME/.local/bin/recomp-profiler"
    cfg install.source "$SOURCE"
}

step_init() {
    [[ -n "$PORT" ]] && cfg agent.port "$PORT"
    [[ -n "$AGENT_NAME" ]] && cfg agent.name "$AGENT_NAME"
    [[ -n "$ADDRESS" ]] && cfg agent.address "$ADDRESS"
    "$VENV/bin/recomp-agent" init >/dev/null
}

step_perf() {
    info "allowing unprivileged perf + ptrace attach (/etc/sysctl.d/90-recomp-profiler.conf)"
    printf 'kernel.perf_event_paranoid = 1\nkernel.kptr_restrict = 0\nkernel.yama.ptrace_scope = 0\n' \
        | $SUDO tee /etc/sysctl.d/90-recomp-profiler.conf >/dev/null
    $SUDO sysctl --system >/dev/null
}

agent_port() {
    "$VENV/bin/python" -c 'from recomp_profiler import settings; print(settings.load().agent.port)'
}

step_firewall() {
    local port; port="${PORT:-$(agent_port)}"
    if command -v ufw >/dev/null && $SUDO ufw status | grep -q active; then
        $SUDO ufw allow "$port/tcp" comment recomp-agent
    elif command -v firewall-cmd >/dev/null && $SUDO firewall-cmd --state >/dev/null 2>&1; then
        $SUDO firewall-cmd --permanent --add-port="$port/tcp" && $SUDO firewall-cmd --reload
    else
        warn "no active ufw/firewalld found; make sure TCP $port is reachable"
    fi
}

step_service() {
    command -v systemctl >/dev/null || { warn "no systemd; start 'recomp-agent serve' from your session autostart"; return 0; }
    local unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unit_dir"
    sed -e "s|@AGENT@|$VENV/bin/recomp-agent|" "$SCRIPT_DIR/recomp-agent.service.in" > "$unit_dir/recomp-agent.service"
    systemctl --user daemon-reload
    systemctl --user enable recomp-agent.service
    systemctl --user restart recomp-agent.service \
        || warn "could not start the user service (no graphical session?); start it later with: systemctl --user start recomp-agent"
}

report() {
    local conn="${XDG_CONFIG_HOME:-$HOME/.config}/recomp-profiler/agent/connection.json"
    echo
    info "connection info ($conn):"
    cat "$conn"
    echo
    info "all addresses on this machine:"
    ip -brief -4 addr show 2>/dev/null | awk '$1 != "lo" {print "    " $1 "  " $3}' || hostname -I
    echo
    info "on the dev machine: recomp-profiler add-host connection.json  (or the TUI's Hosts tab)"
    echo "(the file contains the access token; transfer it privately)"
}

# ---------------------------------------------------------------- run
case "$MODE" in
    only)
        case "$ONLY" in
            packages|venv|init|service|perf|firewall) "step_$ONLY" ;;
            *) die "unknown step '$ONLY' (packages|venv|init|service|perf|firewall)" ;;
        esac ;;
    all)
        [[ $DO_PACKAGES -eq 1 ]] && step_packages || step_bootstrap_packages
        step_venv
        step_init
        [[ $DO_PERF -eq 1 ]] && step_perf
        [[ $DO_FIREWALL -eq 1 ]] && step_firewall
        [[ $DO_SERVICE -eq 1 ]] && step_service
        report ;;
    bootstrap)
        step_bootstrap_packages
        step_venv
        step_init
        if [[ $DO_TUI -eq 1 ]]; then
            info "opening the setup TUI (System setup tab installs tools, service, firewall, …)"
            exec "$VENV/bin/recomp-profiler" tui --tab system
        fi
        report ;;
esac
