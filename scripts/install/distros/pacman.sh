# Arch, Manjaro, EndeavourOS, Garuda, CachyOS, (SteamOS: see install.sh)
BOOTSTRAP_PKGS=(python python-pip)
PKGS=(python python-pip git gdb strace ltrace valgrind binutils elfutils
      pciutils usbutils lshw dmidecode vulkan-tools mesa-utils sysstat lm_sensors
      perf mangohud bpftrace)

pkg_refresh() { $SUDO pacman -Sy --noconfirm; }
pkg_install() { $SUDO pacman -S --needed --noconfirm "$@"; }
