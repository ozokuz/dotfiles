#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$ROOT_DIR/packages"
DOTS_DIR="$ROOT_DIR/dots"

DRY_RUN=0
ASSUME_YES=0
HOST=""
SESSION=""
SELECTED_GROUPS=""
PROFILE="workstation"
BACKUP_DIR=""

DEFAULT_SATURN_GROUPS="desktop-common,apps,dev,gaming,virtualization,flatpak-gaming"
DEFAULT_TITAN_GROUPS="desktop-common,apps,dev"

usage() {
  cat <<'EOF'
Usage: ./setup.sh [options]

Options:
  --dry-run                 Print actions without applying them.
  --yes                     Do not prompt for confirmation.
  --host NAME               Host profile: saturn, titan, or custom.
  --session NAME            Desktop session: hyprland or niri.
  --groups LIST             Comma-separated groups to install.
  --profile NAME            Profile label for display only. Default: workstation.
  -h, --help                Show this help.

Examples:
  ./setup.sh --dry-run
  ./setup.sh --host saturn --session hyprland --groups desktop-common,apps,dev,gaming,virtualization,flatpak-gaming
  ./setup.sh --host titan --session niri --dry-run
EOF
}

log() {
  printf '%s\n' "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

run() {
  if (( DRY_RUN )); then
    printf '[dry-run] %q' "$1"
    shift || true
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

run_shell() {
  if (( DRY_RUN )); then
    printf '[dry-run] %s\n' "$*"
  else
    bash -c "$*"
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
      --host)
        HOST="${2:-}"
        shift
        ;;
      --session)
        SESSION="${2:-}"
        shift
        ;;
      --groups)
        SELECTED_GROUPS="${2:-}"
        shift
        ;;
      --profile)
        PROFILE="${2:-}"
        shift
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
}

distro_id() {
  local id=""
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    id="${ID:-}"
  fi
  printf '%s\n' "$id"
}

host_name() {
  if command -v hostname >/dev/null 2>&1; then
    hostname
  elif [[ -r /etc/hostname ]]; then
    tr -d '[:space:]' </etc/hostname
  else
    printf 'custom\n'
  fi
}

prompt_default() {
  local var_name="$1"
  local prompt="$2"
  local default="$3"
  local value

  read -r -p "$prompt [$default]: " value
  printf -v "$var_name" '%s' "${value:-$default}"
}

normalize_group_list() {
  local raw="$1"
  raw="${raw// /}"
  raw="${raw//;/,}"
  printf '%s\n' "$raw"
}

contains_group() {
  local needle="$1"
  local item
  IFS=',' read -r -a items <<< "$SELECTED_GROUPS"
  for item in "${items[@]}"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

append_group_once() {
  local group="$1"
  contains_group "$group" && return 0
  if [[ -z "$SELECTED_GROUPS" ]]; then
    SELECTED_GROUPS="$group"
  else
    SELECTED_GROUPS="$SELECTED_GROUPS,$group"
  fi
}

resolve_defaults() {
  local detected_host
  detected_host="$(host_name)"

  if [[ -z "$HOST" ]]; then
    if (( ASSUME_YES )); then
      HOST="$detected_host"
    else
      prompt_default HOST "Host profile" "$detected_host"
    fi
  fi

  case "$HOST" in
    saturn)
      [[ -n "$SESSION" ]] || SESSION="hyprland"
      [[ -n "$SELECTED_GROUPS" ]] || SELECTED_GROUPS="$DEFAULT_SATURN_GROUPS"
      ;;
    titan)
      [[ -n "$SESSION" ]] || SESSION="niri"
      [[ -n "$SELECTED_GROUPS" ]] || SELECTED_GROUPS="$DEFAULT_TITAN_GROUPS"
      ;;
    *)
      [[ -n "$SESSION" ]] || SESSION="hyprland"
      [[ -n "$SELECTED_GROUPS" ]] || SELECTED_GROUPS="desktop-common,apps,dev"
      ;;
  esac

  if (( ! ASSUME_YES )); then
    prompt_default SESSION "Desktop session (hyprland/niri)" "$SESSION"
    prompt_default SELECTED_GROUPS "Package groups" "$SELECTED_GROUPS"
  fi

  SELECTED_GROUPS="$(normalize_group_list "$SELECTED_GROUPS")"

  case "$SESSION" in
    hyprland|niri)
      append_group_once "$SESSION"
      ;;
    none|"")
      ;;
    *)
      die "unsupported session: $SESSION"
      ;;
  esac
}

clean_manifest() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  sed -E '
    s/[[:space:]]+#.*$//;
    /^#{1,6}[[:space:]]*/d;
    /^[[:space:]]*$/d;
    s/^[[:space:]]*[-*][[:space:]]+//;
    s/^[[:space:]]+//;
    s/[[:space:]]+$//;
  ' "$file" | awk 'NF'
}

manifest_files_for_source() {
  local source="$1"
  local group

  [[ -f "$PACKAGE_DIR/common/$source" ]] && printf '%s\n' "$PACKAGE_DIR/common/$source"

  IFS=',' read -r -a group_items <<< "$SELECTED_GROUPS"
  for group in "${group_items[@]}"; do
    [[ -f "$PACKAGE_DIR/groups/$group/$source" ]] && printf '%s\n' "$PACKAGE_DIR/groups/$group/$source"
  done

  [[ -f "$PACKAGE_DIR/hosts/$HOST/$source" ]] && printf '%s\n' "$PACKAGE_DIR/hosts/$HOST/$source"
}

collect_items() {
  local source="$1"
  local file
  while IFS= read -r file; do
    clean_manifest "$file"
  done < <(manifest_files_for_source "$source") | awk '!seen[$0]++'
}

install_pacman() {
  local label="$1"
  shift
  local pkgs=("$@")
  ((${#pkgs[@]})) || return 0

  log "Installing $label packages: ${pkgs[*]}"
  if (( DRY_RUN )); then
    printf '[dry-run] sudo pacman -S --needed'
    printf ' %q' "${pkgs[@]}"
    printf '\n'
  else
    sudo pacman -S --needed "${pkgs[@]}"
  fi
}

install_aur() {
  local pkgs=("$@")
  ((${#pkgs[@]})) || return 0

  local helper=""
  if command -v paru >/dev/null 2>&1; then
    helper="paru"
  elif command -v yay >/dev/null 2>&1; then
    helper="yay"
  elif (( DRY_RUN )); then
    helper="paru"
  else
    die "AUR packages requested but neither paru nor yay is installed"
  fi

  log "Installing AUR packages with $helper: ${pkgs[*]}"
  if (( DRY_RUN )); then
    printf '[dry-run] %q -S --needed' "$helper"
    printf ' %q' "${pkgs[@]}"
    printf '\n'
  else
    "$helper" -S --needed "${pkgs[@]}"
  fi
}

setup_chaotic_aur() {
  local chaotic_pkgs=("$@")
  ((${#chaotic_pkgs[@]})) || return 0

  if grep -Eq '^\[chaotic-aur\]' /etc/pacman.conf 2>/dev/null; then
    log "Chaotic-AUR repository is already configured."
    return 0
  fi

  log "Chaotic-AUR packages are selected, but the repository is not configured."
  log "This setup will install chaotic-keyring and chaotic-mirrorlist, then add the pacman repo block."

  if (( DRY_RUN )); then
    log "[dry-run] configure Chaotic-AUR repository in /etc/pacman.conf"
    return 0
  fi

  if confirm "Configure Chaotic-AUR now?"; then
    sudo pacman-key --recv-key 3056513887B78AEB --keyserver keyserver.ubuntu.com
    sudo pacman-key --lsign-key 3056513887B78AEB
    sudo pacman -U --needed 'https://cdn-mirror.chaotic.cx/chaotic-aur/chaotic-keyring.pkg.tar.zst' 'https://cdn-mirror.chaotic.cx/chaotic-aur/chaotic-mirrorlist.pkg.tar.zst'
    printf '\n[chaotic-aur]\nInclude = /etc/pacman.d/chaotic-mirrorlist\n' | sudo tee -a /etc/pacman.conf >/dev/null
    sudo pacman -Sy
  else
    die "Chaotic-AUR is required for selected packages"
  fi
}

setup_lizardbyte_repo() {
  local lizardbyte_pkgs=("$@")
  ((${#lizardbyte_pkgs[@]})) || return 0

  if grep -Eq '^\[lizardbyte\]' /etc/pacman.conf 2>/dev/null; then
    log "LizardByte repository is already configured."
    return 0
  fi

  log "LizardByte packages are selected, but the repository is not configured."
  log "This setup will add the LizardByte pacman repository for Sunshine."

  if (( DRY_RUN )); then
    log "[dry-run] configure LizardByte repository in /etc/pacman.conf"
    return 0
  fi

  if confirm "Configure LizardByte repository now?"; then
    printf '\n[lizardbyte]\nSigLevel = Optional\nServer = https://github.com/LizardByte/pacman-repo/releases/latest/download\n' | sudo tee -a /etc/pacman.conf >/dev/null
    sudo pacman -Sy
  else
    die "LizardByte repository is required for selected packages"
  fi
}

setup_flatpak() {
  local apps=("$@")
  ((${#apps[@]})) || return 0

  if ! command -v flatpak >/dev/null 2>&1 && (( ! DRY_RUN )); then
    sudo pacman -S --needed flatpak
  fi

  log "Ensuring Flathub remote exists."
  if (( DRY_RUN )); then
    log "[dry-run] flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo"
  else
    flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
  fi

  log "Installing Flatpak apps: ${apps[*]}"
  if (( DRY_RUN )); then
    printf '[dry-run] flatpak install -y --or-update flathub'
    printf ' %q' "${apps[@]}"
    printf '\n'
  else
    flatpak install -y --or-update flathub "${apps[@]}"
  fi
}

ensure_backup_dir() {
  [[ -n "$BACKUP_DIR" ]] || BACKUP_DIR="$HOME/.dotfiles-backups/$(date +%Y%m%d-%H%M%S)"
}

backup_path_for() {
  local target="$1"
  printf '%s/%s\n' "$BACKUP_DIR" "${target#$HOME/}"
}

prepare_stow_conflicts() {
  local source rel target backup

  [[ -d "$DOTS_DIR" ]] || return 0
  while IFS= read -r source; do
    rel="${source#$DOTS_DIR/}"
    target="$HOME/$rel"

    if [[ -e "$target" || -L "$target" ]]; then
      if [[ -L "$target" && "$(readlink -f "$target")" == "$(readlink -f "$source")" ]]; then
        continue
      fi

      ensure_backup_dir
      backup="$(backup_path_for "$target")"
      log "Backing up existing $target to $backup"
      if (( DRY_RUN )); then
        log "[dry-run] mkdir -p $(dirname "$backup")"
        log "[dry-run] mv $target $backup"
      else
        mkdir -p "$(dirname "$backup")"
        mv "$target" "$backup"
      fi
    fi
  done < <(find "$DOTS_DIR" -type f -o -type l)
}

stow_dotfiles() {
  command -v stow >/dev/null 2>&1 || (( DRY_RUN )) || sudo pacman -S --needed stow
  prepare_stow_conflicts
  log "Stowing dotfiles from $DOTS_DIR into $HOME"
  if (( DRY_RUN )); then
    log "[dry-run] stow -t $HOME -d $DOTS_DIR ."
  else
    stow -t "$HOME" -d "$DOTS_DIR" .
  fi
}

enable_services() {
  local services=(NetworkManager bluetooth tailscaled)

  contains_group hyprland && services+=(greetd)
  contains_group niri && services+=(greetd)
  contains_group virtualization && services+=(docker libvirtd)

  local service
  for service in "${services[@]}"; do
    log "Enabling service: $service"
    if (( DRY_RUN )); then
      log "[dry-run] sudo systemctl enable --now $service"
    else
      sudo systemctl enable --now "$service"
    fi
  done
}

configure_user() {
  local user="${USER:-$(id -un)}"
  local groups=()

  contains_group virtualization && groups+=(docker libvirt vboxusers)
  contains_group gaming && groups+=(input)

  if ((${#groups[@]})); then
    log "Adding $user to groups: ${groups[*]}"
    if (( DRY_RUN )); then
      printf '[dry-run] sudo usermod -aG %q %q\n' "$(IFS=,; printf '%s' "${groups[*]}")" "$user"
    else
      sudo usermod -aG "$(IFS=,; printf '%s' "${groups[*]}")" "$user"
    fi
  fi

  if command -v zsh >/dev/null 2>&1 || (( DRY_RUN )); then
    local zsh_path
    zsh_path="$(command -v zsh || printf '/usr/bin/zsh')"
    if [[ "${SHELL:-}" != "$zsh_path" ]]; then
      log "Setting default shell for $user to $zsh_path"
      if (( DRY_RUN )); then
        log "[dry-run] chsh -s $zsh_path $user"
      else
        chsh -s "$zsh_path" "$user"
      fi
    fi
  fi
}

install_selected_packages() {
  local official chaotic aur flatpaks
  local lizardbyte
  mapfile -t official < <(collect_items official.md)
  mapfile -t chaotic < <(collect_items chaotic-aur.md)
  mapfile -t lizardbyte < <(collect_items lizardbyte.md)
  mapfile -t aur < <(collect_items aur.md)
  mapfile -t flatpaks < <(collect_items flatpak.txt)

  setup_chaotic_aur "${chaotic[@]}"
  setup_lizardbyte_repo "${lizardbyte[@]}"
  install_pacman "official/native" "${official[@]}" "${chaotic[@]}" "${lizardbyte[@]}"
  install_aur "${aur[@]}"
  setup_flatpak "${flatpaks[@]}"
}

print_summary() {
  log "Bootstrap summary"
  log "  distro:  $(distro_id)"
  log "  host:    $HOST"
  log "  profile: $PROFILE"
  log "  session: ${SESSION:-none}"
  log "  groups:  $SELECTED_GROUPS"
  (( DRY_RUN )) && log "  mode:    dry-run"
}

main() {
  parse_args "$@"
  resolve_defaults

  case "$(distro_id)" in
    arch|cachyos|cachyos-lts)
      ;;
    *)
      die "unsupported distro: $(distro_id). Expected Arch Linux or CachyOS."
      ;;
  esac

  print_summary
  if (( ! ASSUME_YES && ! DRY_RUN )); then
    confirm "Apply this setup?" || die "aborted"
  fi

  (( DRY_RUN )) || sudo -v
  install_selected_packages
  stow_dotfiles
  configure_user
  enable_services

  log "Setup complete."
  log "Follow up manually for secrets/auth: gh auth login, tailscale up, Bitwarden login, SSH keys."
}

main "$@"
