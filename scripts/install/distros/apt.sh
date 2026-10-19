# Debian, Ubuntu, Mint, Pop!_OS, Zorin, elementary, Kali, ...
PKGS=(python3 python3-venv python3-pip git gdb strace ltrace valgrind binutils elfutils
      pciutils usbutils lshw dmidecode vulkan-tools mesa-utils sysstat lm-sensors
      mangohud bpftrace)
# perf lives in a kernel-versioned package on Ubuntu, a plain one on Debian.
if [[ "$DISTRO_ID" == ubuntu || "$DISTRO_LIKE" == *ubuntu* ]]; then
    PKGS+=(linux-tools-common "linux-tools-$(uname -r)")
else
    PKGS+=(linux-perf)
fi

pkg_refresh() { $SUDO apt-get update -y; }
pkg_install() { DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y --no-install-recommends "$@"; }
