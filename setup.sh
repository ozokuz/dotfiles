#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$ROOT_DIR/packages"
DOTS_DIR="$ROOT_DIR/dots"
HOST_OVERLAY_DIR="$ROOT_DIR/host-overlays"

DRY_RUN=0
ASSUME_YES=0
HOST=""
DISTRO=""
DISTRO_SET=0
SESSION=""
SELECTED_CATEGORIES=""
SELECTED_PACKAGES=""
EXCLUDED_PACKAGES=""
PRESET_PACKAGES=""
PROFILE="workstation"
BACKUP_DIR=""

usage() {
  cat <<'EOF'
Usage: ./setup.sh [options]

Options:
  --dry-run                 Print actions without applying them.
  --yes                     Do not prompt for confirmation.
  --host NAME               Host profile: saturn, titan, or custom.
  --distro NAME             Distro preset: arch or cachyos. Default: detected.
  --session NAME            Desktop session: hyprland or niri.
  --categories LIST         Comma-separated package categories to install.
  --groups LIST             Alias for --categories.
  --packages LIST           Comma-separated package names to install from selected categories.
  --exclude-packages LIST   Comma-separated package names to skip.
  --profile NAME            Profile label for display only. Default: workstation.
  -h, --help                Show this help.

Examples:
  ./setup.sh --dry-run
  ./setup.sh --host saturn --session hyprland --categories desktop-common,apps,dev,gaming,virtualization,gaming/flatpak,hardware/nvidia-gpu
  ./setup.sh --host titan --session niri --dry-run
  ./setup.sh --host titan --packages ghostty,neovim,bitwarden --dry-run
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
      --distro)
        DISTRO="${2:-}"
        DISTRO_SET=1
        shift
        ;;
      --session)
        SESSION="${2:-}"
        shift
        ;;
      --categories|--groups)
        SELECTED_CATEGORIES="${2:-}"
        shift
        ;;
      --packages)
        SELECTED_PACKAGES="${2:-}"
        shift
        ;;
      --exclude-packages)
        EXCLUDED_PACKAGES="${2:-}"
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

prompt_package_selection() {
  local entries=()
  local preset=()
  local selected selected_csv

  mapfile -t entries < <(all_package_entries)
  mapfile -t preset < <(available_package_items)
  ((${#entries[@]})) || return 0

  selected="$(printf '%s\n' "${preset[@]}")"
  selected_csv="$(package_selector_tui entries "$selected")"
  SELECTED_PACKAGES="$selected_csv"
}

normalize_group_list() {
  local raw="$1"
  raw="${raw// /}"
  raw="${raw//;/,}"
  raw="${raw//\/\//\/}"
  printf '%s\n' "$raw"
}

uppercase() {
  local value="$1"
  printf '%s\n' "${value^^}"
}

contains_group() {
  local needle="$1"
  local item
  IFS=',' read -r -a items <<< "$SELECTED_CATEGORIES"
  for item in "${items[@]}"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

validate_group_name() {
  local group="$1"
  [[ -n "$group" ]] || return 0
  [[ "$group" != /* ]] || die "invalid category '$group': absolute paths are not allowed"
  [[ "$group" != */ ]] || die "invalid category '$group': trailing slashes are not allowed"
  [[ "$group" != *"/../"* && "$group" != "../"* && "$group" != *"/.." && "$group" != ".." ]] ||
    die "invalid category '$group': parent directory references are not allowed"
}

validate_group_list() {
  local list="$1"
  local group
  [[ -n "$list" ]] || return 0
  IFS=',' read -r -a items <<< "$list"
  for group in "${items[@]}"; do
    validate_group_name "$group"
  done
}

append_group_once() {
  local group="$1"
  validate_group_name "$group"
  contains_group "$group" && return 0
  if [[ -z "$SELECTED_CATEGORIES" ]]; then
    SELECTED_CATEGORIES="$group"
  else
    SELECTED_CATEGORIES="$SELECTED_CATEGORIES,$group"
  fi
}

load_preset_value() {
  local file="$1"
  local key="$2"
  [[ -f "$file" ]] || return 0
  awk -F= -v key="$key" '$1 == key { print substr($0, length(key) + 2); exit }' "$file"
}

resolve_defaults() {
  local detected_host
  local host_preset distro_preset preset_session preset_categories preset_packages distro_preset_packages distro_categories distro_package_key distro_host_packages
  detected_host="$(host_name)"
  [[ -n "$DISTRO" ]] || DISTRO="$(distro_id)"

  if [[ -z "$HOST" ]]; then
    if (( ASSUME_YES )); then
      HOST="$detected_host"
    else
      prompt_default HOST "Host profile" "$detected_host"
    fi
  fi

  if (( ! ASSUME_YES && ! DISTRO_SET )); then
    prompt_default DISTRO "Distro preset (arch/cachyos)" "$(distro_id)"
  fi

  case "$DISTRO" in
    arch|cachyos)
      ;;
    *)
      die "unsupported distro preset: $DISTRO. Expected arch or cachyos."
      ;;
  esac

  host_preset="$PACKAGE_DIR/hosts/$HOST/preset.conf"
  distro_preset="$PACKAGE_DIR/distros/$DISTRO/preset.conf"
  preset_session="$(load_preset_value "$host_preset" SESSION)"
  preset_categories="$(load_preset_value "$host_preset" CATEGORIES)"
  preset_packages="$(load_preset_value "$host_preset" PACKAGES)"
  distro_package_key="$(uppercase "$DISTRO")_PACKAGES"
  distro_host_packages="$(load_preset_value "$host_preset" "$distro_package_key")"
  distro_categories="$(load_preset_value "$distro_preset" CATEGORIES)"
  distro_preset_packages="$(load_preset_value "$distro_preset" PACKAGES)"
  PRESET_PACKAGES="$(normalize_group_list "$preset_packages,$distro_preset_packages,$distro_host_packages")"

  [[ -n "$SESSION" ]] || SESSION="${preset_session:-hyprland}"
  [[ -n "$SELECTED_CATEGORIES" ]] || SELECTED_CATEGORIES="${preset_categories:-desktop-common,apps,dev}"
  if [[ -n "$distro_categories" ]]; then
    SELECTED_CATEGORIES="$(normalize_group_list "$SELECTED_CATEGORIES,$distro_categories")"
  fi

  if (( ! ASSUME_YES )); then
    prompt_default SESSION "Desktop session (hyprland/niri)" "$SESSION"
  fi

  SELECTED_CATEGORIES="$(normalize_group_list "$SELECTED_CATEGORIES")"
  SELECTED_PACKAGES="$(normalize_group_list "$SELECTED_PACKAGES")"
  EXCLUDED_PACKAGES="$(normalize_group_list "$EXCLUDED_PACKAGES")"
  validate_group_list "$SELECTED_CATEGORIES"

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

  if (( ! ASSUME_YES )) && [[ -z "$SELECTED_PACKAGES" ]]; then
    prompt_package_selection
    SELECTED_PACKAGES="$(normalize_group_list "$SELECTED_PACKAGES")"
  fi
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
  [[ -f "$PACKAGE_DIR/distros/$DISTRO/$source" ]] && printf '%s\n' "$PACKAGE_DIR/distros/$DISTRO/$source"

  IFS=',' read -r -a group_items <<< "$SELECTED_CATEGORIES"
  for group in "${group_items[@]}"; do
    validate_group_name "$group"
    [[ -d "$PACKAGE_DIR/groups/$group" ]] || continue
    find "$PACKAGE_DIR/groups/$group" -mindepth 1 -maxdepth 4 -type f -name "$source" -print 2>/dev/null | sort
  done

}

collect_items() {
  local source="$1"
  local file
  while IFS= read -r file; do
    clean_manifest "$file"
  done < <(manifest_files_for_source "$source") | awk '!seen[$0]++'
}

collect_install_items() {
  local source="$1"
  local file

  if [[ -n "$SELECTED_PACKAGES" ]]; then
    collect_all_items "$source"
    return 0
  fi

  {
    collect_items "$source"
    collect_preset_items "$source"
  } | awk '!seen[$0]++'
}

available_package_items() {
  local source
  {
    for source in official.md chaotic-aur.md lizardbyte.md aur.md flatpak.txt; do
      collect_items "$source"
    done
    csv_to_lines "$PRESET_PACKAGES"
  } | awk '!seen[$0]++' | sort
}

csv_to_lines() {
  local list="$1"
  local item
  [[ -n "$list" ]] || return 0
  IFS=',' read -r -a items <<< "$list"
  for item in "${items[@]}"; do
    [[ -n "$item" ]] && printf '%s\n' "$item"
  done
}

collect_preset_items() {
  local source="$1"
  local item
  [[ -n "$PRESET_PACKAGES" ]] || return 0

  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    if collect_all_items "$source" | grep -Fxq "$item"; then
      printf '%s\n' "$item"
    fi
  done < <(csv_to_lines "$PRESET_PACKAGES")
}

collect_all_items() {
  local source="$1"
  local file
  find "$PACKAGE_DIR/common" "$PACKAGE_DIR/groups" "$PACKAGE_DIR/distros" -mindepth 1 -maxdepth 4 -type f -name "$source" -print0 2>/dev/null |
    while IFS= read -r -d '' file; do
      clean_manifest "$file"
    done | awk '!seen[$0]++'
}

available_category_items() {
  local source
  for source in official.md chaotic-aur.md lizardbyte.md aur.md flatpak.txt; do
    collect_items "$source"
  done | awk '!seen[$0]++' | sort
}

all_package_items() {
  local source
  for source in official.md chaotic-aur.md lizardbyte.md aur.md flatpak.txt; do
    collect_all_items "$source"
  done | awk '!seen[$0]++' | sort
}

package_category_for_file() {
  local file="$1"
  local rel="${file#$PACKAGE_DIR/}"
  local dir="${rel%/*}"

  case "$dir" in
    groups/*) dir="${dir#groups/}" ;;
  esac

  printf '%s\n' "$dir"
}

package_source_for_file() {
  local file="$1"
  local rel="${file#$PACKAGE_DIR/}"
  local source="${rel##*/}"

  case "$source" in
    official.md) source="official" ;;
    chaotic-aur.md) source="chaotic" ;;
    lizardbyte.md) source="lizardbyte" ;;
    aur.md) source="aur" ;;
    flatpak.txt) source="flatpak" ;;
  esac

  printf '%s\n' "$source"
}

all_package_entries() {
  local source file category package_source
  for source in official.md chaotic-aur.md lizardbyte.md aur.md flatpak.txt; do
    find "$PACKAGE_DIR/common" "$PACKAGE_DIR/groups" "$PACKAGE_DIR/distros" -mindepth 1 -maxdepth 4 -type f -name "$source" -print0 2>/dev/null |
      while IFS= read -r -d '' file; do
        category="$(package_category_for_file "$file")"
        package_source="$(package_source_for_file "$file")"
        clean_manifest "$file" | awk -v category="$category" -v package_source="$package_source" 'NF { print category "\t" package_source "\t" $0 }'
      done
  done | sort -t $'\t' -k1,1 -k3,3 -k2,2 |
    awk -F '\t' '
      $1 != current {
        current = $1
        print "H\t" current
      }
      { print "P\t" $1 "\t" $2 "\t" $3 }
    '
}

package_selector_tui() {
  local -n entries_ref="$1"
  local initial_selected="$2"
  local cursor=0 offset=0 page_size=18 key entry type label package_source item i marker selected_csv
  local term_lines
  declare -A selected_map=()

  while IFS= read -r item; do
    [[ -n "$item" ]] && selected_map["$item"]=1
  done <<< "$initial_selected"

  cleanup_selector() {
    stty sane 2>/dev/null || true
    printf '\033[?25h\033[?1049l' >/dev/tty
  }
  trap cleanup_selector RETURN

  term_lines="$(tput lines 2>/dev/null || printf '24')"
  page_size="$((term_lines - 6))"
  (( page_size < 8 )) && page_size=8

  while (( cursor < ${#entries_ref[@]} )) && [[ "${entries_ref[$cursor]%%$'\t'*}" != "P" ]]; do
    cursor="$((cursor + 1))"
  done

  printf '\033[?1049h\033[?25l' >/dev/tty
  stty -echo -icanon time 0 min 1
  while true; do
    if (( cursor < offset )); then
      offset="$cursor"
    elif (( cursor >= offset + page_size )); then
      offset="$((cursor - page_size + 1))"
    fi

    printf '\033[H\033[J' >/dev/tty
    printf 'Package selection: arrows move, Space toggles, Enter confirms, q cancels.\n' >/dev/tty
    printf 'Preset packages start selected. Headers group packages by category.\n\n' >/dev/tty

    for ((i = offset; i < ${#entries_ref[@]} && i < offset + page_size; i++)); do
      entry="${entries_ref[$i]}"
      type="${entry%%$'\t'*}"
      if [[ "$type" == "H" ]]; then
        label="${entry#*$'\t'}"
        printf '\033[1m%s\033[0m\n' "$label" >/dev/tty
        continue
      fi

      IFS=$'\t' read -r type label package_source item <<< "$entry"
      if [[ -n "${selected_map[$item]:-}" ]]; then
        marker='[x]'
      else
        marker='[ ]'
      fi
      if (( i == cursor )); then
        printf '\033[7m  %s %s (%s)\033[0m\n' "$marker" "$item" "$package_source" >/dev/tty
      else
        printf '  %s %s (%s)\n' "$marker" "$item" "$package_source" >/dev/tty
      fi
    done

    IFS= read -rsn1 key </dev/tty || key=""
    case "$key" in
      $'\x1b')
        IFS= read -rsn2 -t 0.01 key </dev/tty || key=""
        case "$key" in
          '[A')
            while (( cursor > 0 )); do
              cursor="$((cursor - 1))"
              [[ "${entries_ref[$cursor]%%$'\t'*}" == "P" ]] && break
            done
            ;;
          '[B')
            while (( cursor < ${#entries_ref[@]} - 1 )); do
              cursor="$((cursor + 1))"
              [[ "${entries_ref[$cursor]%%$'\t'*}" == "P" ]] && break
            done
            ;;
        esac
        ;;
      " ")
        entry="${entries_ref[$cursor]}"
        [[ "${entry%%$'\t'*}" == "P" ]] || continue
        item="${entry##*$'\t'}"
        if [[ -n "${selected_map[$item]:-}" ]]; then
          unset 'selected_map[$item]'
        else
          selected_map["$item"]=1
        fi
        ;;
      "")
        break
        ;;
      q|Q)
        return 1
        ;;
    esac
  done

  for entry in "${entries_ref[@]}"; do
    [[ "${entry%%$'\t'*}" == "P" ]] || continue
    item="${entry##*$'\t'}"
    if [[ -n "${selected_map[$item]:-}" ]] && ! list_contains_csv "$selected_csv" "$item"; then
      if [[ -z "$selected_csv" ]]; then
        selected_csv="$item"
      else
        selected_csv="$selected_csv,$item"
      fi
    fi
  done
  printf '%s\n' "$selected_csv"
}

list_contains_csv() {
  local list="$1"
  local needle="$2"
  local item
  [[ -n "$list" ]] || return 1
  IFS=',' read -r -a items <<< "$list"
  for item in "${items[@]}"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

filter_items() {
  local item
  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    if [[ -n "$SELECTED_PACKAGES" ]] && ! list_contains_csv "$SELECTED_PACKAGES" "$item"; then
      continue
    fi
    if list_contains_csv "$EXCLUDED_PACKAGES" "$item"; then
      continue
    fi
    printf '%s\n' "$item"
  done | awk '!seen[$0]++'
}

validate_package_filter() {
  [[ -n "$SELECTED_PACKAGES" ]] || return 0

  local source item all_items selected
  all_items="$(all_package_items)"

  IFS=',' read -r -a selected <<< "$SELECTED_PACKAGES"
  for item in "${selected[@]}"; do
    [[ -n "$item" ]] || continue
    if ! grep -Fxq "$item" <<< "$all_items"; then
      die "package '$item' is not in selected categories/host/distro manifests"
    fi
  done
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

link_host_file() {
  local label="$1"
  local source_file="$2"
  local target_file="$3"
  local link_target="$4"
  local backup

  [[ -e "$source_file" || -L "$source_file" ]] || return 0

  log "Selecting $label overlay: $HOST"
  if [[ -e "$target_file" || -L "$target_file" ]]; then
    if [[ -L "$target_file" && "$(readlink "$target_file")" == "$link_target" ]]; then
      return 0
    fi

    ensure_backup_dir
    backup="$(backup_path_for "$target_file")"
    log "Backing up existing $target_file to $backup"
    if (( DRY_RUN )); then
      log "[dry-run] mkdir -p $(dirname "$backup")"
      log "[dry-run] mv $target_file $backup"
    else
      mkdir -p "$(dirname "$backup")"
      mv "$target_file" "$backup"
    fi
  fi

  if (( DRY_RUN )); then
    log "[dry-run] mkdir -p $(dirname "$target_file")"
    log "[dry-run] ln -s $link_target $target_file"
  else
    mkdir -p "$(dirname "$target_file")"
    ln -s "$link_target" "$target_file"
  fi
}

configure_host_overlays() {
  local host_dir="$HOST_OVERLAY_DIR/$HOST"

  link_host_file "Hyprland" \
    "$host_dir/.config/hypr/overlay.conf" \
    "$HOME/.config/hypr/overlays/current.conf" \
    "$host_dir/.config/hypr/overlay.conf"

  link_host_file "Hyprland DMS" \
    "$host_dir/.config/hypr/dms" \
    "$HOME/.config/hypr/dms" \
    "$host_dir/.config/hypr/dms"

  link_host_file "Niri" \
    "$host_dir/.config/niri/overlay.kdl" \
    "$HOME/.config/niri/overlays/current.kdl" \
    "$host_dir/.config/niri/overlay.kdl"

  link_host_file "Niri DMS" \
    "$host_dir/.config/niri/dms" \
    "$HOME/.config/niri/dms" \
    "$host_dir/.config/niri/dms"

  link_host_file "DankMaterialShell" \
    "$host_dir/.config/DankMaterialShell/settings.json" \
    "$HOME/.config/DankMaterialShell/settings.json" \
    "$host_dir/.config/DankMaterialShell/settings.json"
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
  validate_package_filter
  mapfile -t official < <(collect_install_items official.md | filter_items)
  mapfile -t chaotic < <(collect_install_items chaotic-aur.md | filter_items)
  mapfile -t lizardbyte < <(collect_install_items lizardbyte.md | filter_items)
  mapfile -t aur < <(collect_install_items aur.md | filter_items)
  mapfile -t flatpaks < <(collect_install_items flatpak.txt | filter_items)

  setup_chaotic_aur "${chaotic[@]}"
  setup_lizardbyte_repo "${lizardbyte[@]}"
  install_pacman "official/native" "${official[@]}" "${chaotic[@]}" "${lizardbyte[@]}"
  install_aur "${aur[@]}"
  setup_flatpak "${flatpaks[@]}"
}

print_summary() {
  log "Bootstrap summary"
  log "  distro:  $(distro_id)"
  log "  preset:  $DISTRO"
  log "  host:    $HOST"
  log "  profile: $PROFILE"
  log "  session: ${SESSION:-none}"
  log "  categories: $SELECTED_CATEGORIES"
  [[ -n "$SELECTED_PACKAGES" ]] && log "  packages:   $SELECTED_PACKAGES"
  [[ -n "$EXCLUDED_PACKAGES" ]] && log "  excluded:   $EXCLUDED_PACKAGES"
  (( DRY_RUN )) && log "  mode:    dry-run"
}

main() {
  parse_args "$@"
  resolve_defaults

  case "$(distro_id)" in
    arch|cachyos)
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
  configure_host_overlays
  configure_user
  enable_services

  log "Setup complete."
  log "Follow up manually for secrets/auth: gh auth login, tailscale up, Bitwarden login, SSH keys."
}

main "$@"
