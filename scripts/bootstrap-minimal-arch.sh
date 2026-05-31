#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

DRY_RUN=0
ASSUME_YES=0
TARGET_USER="${SUDO_USER:-${USER:-ozoku}}"
HOST=""
SESSION=""
SETUP_GROUPS=""
RUN_SETUP=0
INSTALL_SYSTEM_BASE=1

BASE_PACKAGES=(
  alsa-utils
  avahi
  base
  base-devel
  bluez
  bluez-utils
  btrfs-progs
  ca-certificates
  curl
  dosfstools
  efibootmgr
  firewalld
  git
  grub
  linux
  linux-firmware
  man-db
  man-pages
  networkmanager
  openssh
  os-prober
  pacman-contrib
  pipewire
  pipewire-alsa
  pipewire-jack
  pipewire-pulse
  reflector
  rsync
  stow
  sudo
  wget
  wireplumber
  xdg-user-dirs
  xdg-utils
  zsh
  zram-generator
)

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap-minimal-arch.sh [options]

Prepare a freshly installed minimal Arch system so it can run this dotfiles repo.
Assumes the OS is already installed, booted, and has internet access.

Options:
  --dry-run                 Print actions without applying them.
  --yes                     Do not prompt for confirmation.
  --user NAME               User to create/configure. Default: current sudo user or current user.
  --host NAME               Pass host to setup.sh when --run-setup is used.
  --session NAME            Pass session to setup.sh when --run-setup is used.
  --groups LIST             Pass groups to setup.sh when --run-setup is used.
  --no-system-base          Only install repo bootstrap tools, not the full base-system set.
  --install-boot-packages   Compatibility alias; base-system packages are installed by default.
  --run-setup               Run ./setup.sh after minimal bootstrap.
  -h, --help                Show this help.

Examples:
  scripts/bootstrap-minimal-arch.sh --dry-run --user ozoku
  scripts/bootstrap-minimal-arch.sh --user ozoku
  scripts/bootstrap-minimal-arch.sh --user ozoku --host saturn --run-setup
EOF
}

log() {
  printf '%s\n' "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

as_root() {
  if (( DRY_RUN )); then
    if (( EUID == 0 )); then
      printf '[dry-run]'
    else
      printf '[dry-run] sudo'
    fi
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi

  if (( EUID == 0 )); then
    "$@"
  else
    sudo "$@"
  fi
}

confirm() {
  local prompt="$1"
  (( ASSUME_YES )) && return 0
  read -r -p "$prompt [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" || "$answer" == "yes" || "$answer" == "YES" ]]
}

parse_args() {
  while (($#)); do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        ;;
      --yes)
        ASSUME_YES=1
        ;;
      --user)
        TARGET_USER="${2:-}"
        shift
        ;;
      --host)
        HOST="${2:-}"
        shift
        ;;
      --session)
        SESSION="${2:-}"
        shift
        ;;
      --groups)
        SETUP_GROUPS="${2:-}"
        shift
        ;;
      --no-system-base)
        INSTALL_SYSTEM_BASE=0
        ;;
      --install-boot-packages)
        INSTALL_SYSTEM_BASE=1
        ;;
      --run-setup)
        RUN_SETUP=1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown option: $1"
        ;;
    esac
    shift
  done

  [[ -n "$TARGET_USER" ]] || die "--user cannot be empty"
}

require_arch() {
  [[ -r /etc/os-release ]] || die "/etc/os-release not found"
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    arch|cachyos|cachyos-lts)
      ;;
    *)
      die "unsupported distro: ${ID:-unknown}. Expected Arch Linux or CachyOS."
      ;;
  esac
}

require_privilege_path() {
  (( DRY_RUN )) && return 0

  if (( EUID == 0 )); then
    return 0
  fi

  command -v sudo >/dev/null 2>&1 || die "run as root, or install sudo first"
  sudo -v
}

refresh_pacman() {
  log "Refreshing pacman package databases."
  as_root pacman -Sy
}

install_packages() {
  local packages=("${BASE_PACKAGES[@]}")
  if (( ! INSTALL_SYSTEM_BASE )); then
    packages=(
      base-devel
      ca-certificates
      curl
      git
      openssh
      rsync
      stow
      sudo
      wget
      zsh
    )
  fi

  log "Installing minimal bootstrap packages: ${packages[*]}"
  as_root pacman -S --needed "${packages[@]}"
}

ensure_user() {
  if id "$TARGET_USER" >/dev/null 2>&1; then
    log "User exists: $TARGET_USER"
  else
    log "Creating user: $TARGET_USER"
    as_root useradd -m -G wheel -s /usr/bin/zsh "$TARGET_USER"
    if (( ! DRY_RUN )); then
      passwd "$TARGET_USER"
    else
      log "[dry-run] passwd $TARGET_USER"
    fi
  fi

  log "Ensuring $TARGET_USER is in wheel."
  as_root usermod -aG wheel "$TARGET_USER"
}

ensure_sudoers_wheel() {
  local sudoers_dropin="/etc/sudoers.d/10-wheel"
  log "Ensuring wheel group has sudo access via $sudoers_dropin."

  if (( DRY_RUN )); then
    log "[dry-run] install sudoers drop-in: %wheel ALL=(ALL:ALL) ALL"
    return 0
  fi

  printf '%%wheel ALL=(ALL:ALL) ALL\n' | as_root tee "$sudoers_dropin" >/dev/null
  as_root chmod 0440 "$sudoers_dropin"
  as_root visudo -cf "$sudoers_dropin" >/dev/null
}

set_user_shell() {
  log "Setting $TARGET_USER shell to zsh."
  as_root chsh -s /usr/bin/zsh "$TARGET_USER"
}

enable_core_services() {
  local services=(sshd)
  local service

  if (( INSTALL_SYSTEM_BASE )); then
    services=(NetworkManager bluetooth avahi-daemon firewalld sshd systemd-timesyncd)
  fi

  for service in "${services[@]}"; do
    log "Enabling service: $service"
    as_root systemctl enable --now "$service"
  done

  if (( INSTALL_SYSTEM_BASE )); then
    log "Enabling periodic SSD trim."
    as_root systemctl enable --now fstrim.timer
  fi
}

enable_audio_user_units() {
  (( INSTALL_SYSTEM_BASE )) || return 0

  local units=(pipewire.socket pipewire-pulse.socket wireplumber.service)
  log "Enabling PipeWire user units globally: ${units[*]}"
  as_root systemctl --global enable "${units[@]}"
}

configure_zram() {
  local config_path="/etc/systemd/zram-generator.conf"

  (( INSTALL_SYSTEM_BASE )) || return 0

  log "Configuring zram via $config_path."
  if (( DRY_RUN )); then
    log "[dry-run] write zram config with zram0 = min(ram / 2, 4096)"
    return 0
  fi

  as_root install -Dm0644 /dev/stdin "$config_path" <<'EOF'
[zram0]
zram-size = min(ram / 2, 4096)
compression-algorithm = zstd
EOF
}

configure_user_runtime() {
  (( INSTALL_SYSTEM_BASE )) || return 0

  if (( DRY_RUN )); then
    log "[dry-run] sudo -Hu $TARGET_USER xdg-user-dirs-update"
    return 0
  fi

  if command -v xdg-user-dirs-update >/dev/null 2>&1; then
    sudo -Hu "$TARGET_USER" xdg-user-dirs-update
  fi
}

run_workstation_setup() {
  (( RUN_SETUP )) || return 0

  local cmd=("$ROOT_DIR/setup.sh" --yes)
  [[ -n "$HOST" ]] && cmd+=(--host "$HOST")
  [[ -n "$SESSION" ]] && cmd+=(--session "$SESSION")
  [[ -n "$SETUP_GROUPS" ]] && cmd+=(--groups "$SETUP_GROUPS")
  (( DRY_RUN )) && cmd+=(--dry-run)

  log "Running workstation setup: ${cmd[*]}"
  if [[ "$TARGET_USER" == "${USER:-}" && $EUID -ne 0 ]]; then
    "${cmd[@]}"
  elif (( DRY_RUN )); then
    printf '[dry-run]'
    if (( EUID == 0 )); then
      printf ' sudo -Hu %q' "$TARGET_USER"
    else
      printf ' sudo sudo -Hu %q' "$TARGET_USER"
    fi
    printf ' %q' "${cmd[@]}"
    printf '\n'
  else
    sudo -Hu "$TARGET_USER" "${cmd[@]}"
  fi
}

print_summary() {
  log "Minimal Arch bootstrap summary"
  log "  user:                  $TARGET_USER"
  log "  install system base:   $INSTALL_SYSTEM_BASE"
  log "  run setup.sh:          $RUN_SETUP"
  [[ -n "$HOST" ]] && log "  setup host:            $HOST"
  [[ -n "$SESSION" ]] && log "  setup session:         $SESSION"
  [[ -n "$SETUP_GROUPS" ]] && log "  setup groups:          $SETUP_GROUPS"
  (( DRY_RUN )) && log "  mode:                  dry-run"
}

main() {
  parse_args "$@"
  require_arch
  print_summary

  if (( ! ASSUME_YES && ! DRY_RUN )); then
    confirm "Apply minimal Arch bootstrap?" || die "aborted"
  fi

  require_privilege_path
  refresh_pacman
  install_packages
  ensure_user
  ensure_sudoers_wheel
  set_user_shell
  configure_zram
  configure_user_runtime
  enable_audio_user_units
  enable_core_services
  run_workstation_setup

  log "Minimal Arch bootstrap complete."
  log "If this was a new login user, log out and back in before relying on group membership."
}

main "$@"
