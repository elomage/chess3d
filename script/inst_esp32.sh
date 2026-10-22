#!/usr/bin/env bash
# Install the tools for ESP32 firmware development of chess3d.
#
#   script/inst_esp32.sh [options]
#
# Installs, idempotently:
#   1. system packages: git, curl, python3 with venv, a C++ compiler (for the
#      firmware host tests)                                       [needs sudo]
#   2. PlatformIO Core in ~/.platformio (official installer), with `pio` linked
#      into ~/.local/bin
#   3. the ESP32 platform, toolchain and libraries pinned in
#      firmware/mover/platformio.ini
#   4. Linux only: PlatformIO udev rules and serial port group membership so
#      boards can be flashed without root                          [needs sudo]
# and then checks the result by building the firmware host test and,
# with --build, the firmware itself.
#
# Options:
#   --no-system   skip steps that need sudo (system packages, udev, groups)
#   --build       also build the firmware with `pio run`
#   --dry-run     print what would be done without doing it
#   -h, --help    show this help
#
# Works on Debian/Ubuntu (apt), Fedora (dnf), Arch (pacman), openSUSE (zypper)
# and macOS (Homebrew).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$ROOT/firmware/mover"
PIO_HOME="${PLATFORMIO_CORE_DIR:-$HOME/.platformio}"
PIO="$PIO_HOME/penv/bin/pio"
INSTALLER_URL="https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py"
UDEV_URL="https://raw.githubusercontent.com/platformio/platformio-core/develop/platformio/assets/system/99-platformio-udev.rules"

SYSTEM=1
BUILD=0
DRY=0

usage() { sed -n '2,/^$/{s/^# \{0,1\}//;p}' "$0"; }

for arg in "$@"; do
  case "$arg" in
    --no-system) SYSTEM=0 ;;
    --build) BUILD=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
run() {
  if [ "$DRY" = 1 ]; then
    printf '    [dry-run] %s\n' "$*"
  else
    "$@"
  fi
}
have() { command -v "$1" >/dev/null 2>&1; }

OS="$(uname -s)"
SUDO=""
if [ "$(id -u)" != 0 ] && have sudo; then SUDO="sudo"; fi

# -- 1. system packages ------------------------------------------------------

install_system_packages() {
  step "System packages"
  local missing=()
  have git || missing+=(git)
  have curl || missing+=(curl)
  have python3 || missing+=(python3)
  have g++ || have clang++ || missing+=(compiler)
  if have python3 && ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
    missing+=(python3-venv)
  fi
  if [ ${#missing[@]} = 0 ]; then
    info "all present"
    return
  fi
  info "missing: ${missing[*]}"
  if [ "$SYSTEM" = 0 ]; then
    info "skipped (--no-system); install them yourself"
    return
  fi
  if have apt-get; then
    run $SUDO apt-get update
    run $SUDO apt-get install -y git curl python3 python3-venv python3-pip build-essential
  elif have dnf; then
    run $SUDO dnf install -y git curl python3 python3-pip gcc-c++ make
  elif have pacman; then
    run $SUDO pacman -S --needed --noconfirm git curl python python-pip base-devel
  elif have zypper; then
    run $SUDO zypper install -y git curl python3 python3-pip gcc-c++ make
  elif [ "$OS" = Darwin ] && have brew; then
    have g++ || have clang++ || run xcode-select --install || true
    run brew install git curl python
  else
    echo "no supported package manager found; install: ${missing[*]}" >&2
    exit 1
  fi
}

# -- 2. PlatformIO Core --------------------------------------------------------

install_platformio() {
  step "PlatformIO Core"
  if [ -x "$PIO" ]; then
    info "found $("$PIO" --version)"
    info "upgrading"
    run "$PIO" upgrade || info "upgrade failed, keeping the installed version"
  else
    local tmp
    tmp="$(mktemp -d)"
    run curl -fsSL -o "$tmp/get-platformio.py" "$INSTALLER_URL"
    run python3 "$tmp/get-platformio.py"
    rm -rf "$tmp"
  fi
  run mkdir -p "$HOME/.local/bin"
  for tool in pio platformio piodebuggdb; do
    if [ -e "$PIO_HOME/penv/bin/$tool" ] || [ "$DRY" = 1 ]; then
      run ln -sf "$PIO_HOME/penv/bin/$tool" "$HOME/.local/bin/$tool"
    fi
  done
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) info "add ~/.local/bin to PATH, e.g.: echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc" ;;
  esac
}

# -- 3. ESP32 platform and project dependencies -------------------------------

install_project_packages() {
  step "ESP32 platform, toolchain and libraries for firmware/mover"
  info "pinned in $PROJECT/platformio.ini"
  run "$PIO" pkg install -d "$PROJECT"
}

# -- 4. serial port access (Linux) ---------------------------------------------

setup_serial_access() {
  [ "$OS" = Linux ] || return 0
  step "Serial port access"
  if [ "$SYSTEM" = 0 ]; then
    info "skipped (--no-system)"
    return
  fi
  local rules=/etc/udev/rules.d/99-platformio-udev.rules
  if [ -f "$rules" ]; then
    info "udev rules present"
  else
    local tmp
    tmp="$(mktemp)"
    run curl -fsSL -o "$tmp" "$UDEV_URL"
    run $SUDO install -m 0644 "$tmp" "$rules"
    rm -f "$tmp"
    if have udevadm; then
      run $SUDO udevadm control --reload-rules
      run $SUDO udevadm trigger
    fi
  fi
  local group=""
  for g in dialout uucp; do
    if getent group "$g" >/dev/null; then group="$g"; break; fi
  done
  if [ -z "$group" ]; then
    info "no dialout/uucp group on this system; nothing to join"
  elif id -nG "$USER" | tr ' ' '\n' | grep -qx "$group"; then
    info "$USER is in $group"
  else
    run $SUDO usermod -aG "$group" "$USER"
    info "added $USER to $group; log out and back in for it to take effect"
  fi
}

# -- checks --------------------------------------------------------------------

check() {
  step "Checks"
  local cxx
  cxx="$(command -v g++ || command -v clang++ || true)"
  if [ -z "$cxx" ]; then
    info "no C++ compiler: host test skipped"
  else
    local out
    out="$(mktemp)"
    (cd "$PROJECT/test/host" &&
      run "$cxx" -std=gnu++17 -I. -I../../include test_follow.cpp \
        ../../src/motion.cpp ../../src/hal.cpp -o "$out" &&
      if [ "$DRY" = 0 ]; then "$out" | tail -1; fi)
    rm -f "$out"
  fi
  if [ "$BUILD" = 1 ]; then
    run "$PIO" run -d "$PROJECT"
  fi
  [ "$DRY" = 1 ] || info "$("$PIO" --version)"
  info "build:  pio run -d firmware/mover"
  info "flash:  pio run -d firmware/mover -t upload"
  info "serial: pio device monitor -d firmware/mover"
}

install_system_packages
install_platformio
install_project_packages
setup_serial_access
check
step "Done"
