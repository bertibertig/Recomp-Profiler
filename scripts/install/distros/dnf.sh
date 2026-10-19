# Fedora, Nobara, RHEL, CentOS Stream, Rocky, Alma, Oracle Linux
BOOTSTRAP_PKGS=(python3 python3-pip)
PKGS=(python3 python3-pip git gdb strace ltrace valgrind binutils elfutils
      pciutils usbutils lshw dmidecode vulkan-tools mesa-demos sysstat lm_sensors
      perf mangohud bpftrace)
# EL8 ships Python 3.6; the agent needs >= 3.10.
if [[ "$DISTRO_ID" != fedora && "$DISTRO_ID" != nobara && "${VERSION_ID%%.*}" == 8 ]]; then
    BOOTSTRAP_PKGS=(python3.11 python3.11-pip); PKGS+=(python3.11 python3.11-pip); PYTHON=python3.11
fi

pkg_refresh() {
    # Enterprise distros need EPEL for lshw/mangohud and friends.
    if [[ "$DISTRO_ID" != "fedora" && "$DISTRO_ID" != "nobara" ]]; then
        $SUDO dnf install -y epel-release || warn "could not enable EPEL; some tools will be skipped"
    fi
    $SUDO dnf makecache -y
}
pkg_install() { $SUDO dnf install -y "$@"; }
