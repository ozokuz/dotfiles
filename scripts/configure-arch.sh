#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"

clean_md() {
  sed -E '
    /^#{1,6}[[:space:]]*/d;  # remove markdown headings (#, ##, etc.)
    /^[[:space:]]*$/d;        # remove empty lines
    s/^[[:space:]]*-[[:space:]]+//  # strip "- " list markers only
  ' "$@" | tr '\n' ' ' | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//'
}

install_needed() {
  local pkg_string
  pkg_string="$(clean_md "$@")"

  [[ -n $pkg_string ]] || return 0

  read -r -a pkgs <<< "$pkg_string"
  sudo pacman -S --needed "${pkgs[@]}" 2>&1 | grep -v 'is up to date -- skipping'
}

install_needed_aur() {
  local pkg_string
  pkg_string="$(clean_md "$@")"

  [[ -n $pkg_string ]] || return 0

  read -r -a pkgs <<< "$pkg_string"
  paru -S --needed "${pkgs[@]}" 2>&1 | grep -v 'is up to date -- skipping'
}

sudo -v

install_needed $SCRIPT_DIR/../arch_manual.md
install_needed $SCRIPT_DIR/../official.md
install_needed $SCRIPT_DIR/../chaotic-aur.md
install_needed $SCRIPT_DIR/../unknown.md
#install_needed_aur $SCRIPT_DIR/../aur.md

stow -t $HOME -d $SCRIPT_DIR/../dots .
