# openSUSE Tumbleweed / Leap, SLES
PKGS=(python3 python3-pip git gdb strace ltrace valgrind binutils elfutils
      pciutils usbutils lshw dmidecode vulkan-tools Mesa-demo-x sysstat sensors
      perf mangohud bpftrace)
# Leap's default python3 is 3.6; use the newest packaged one.
if [[ "$DISTRO_ID" == opensuse-leap || "$DISTRO_ID" == sles ]]; then
    PKGS+=(python311 python311-pip); PYTHON=python3.11
fi

pkg_refresh() { $SUDO zypper --non-interactive refresh; }
pkg_install() { $SUDO zypper --non-interactive install --no-recommends "$@"; }
