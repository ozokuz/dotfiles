#!/usr/bin/env bash
# Standalone bootstrap: usable from a checkout or through curl | bash.
set -euo pipefail

bootstrap() {
    local source_file=${BASH_SOURCE[0]:-} repo='' answer
    local repository=${DOTFILES_REPOSITORY:-https://github.com/ozokuz/dotfiles.git}
    local ref=${DOTFILES_REF:-main}
    local destination=${DOTFILES_DIRECTORY:-$HOME/.local/share/envstore/repository}
    local -a privileged=()
    if (( EUID != 0 )); then privileged=(sudo); fi

    if ! command -v git >/dev/null || ! command -v python3 >/dev/null ||
       ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        printf '%s\n' 'Setup needs Git and Python 3.11+ before it can compute the configuration plan.'
        if [[ ${DOTFILES_BOOTSTRAP_YES:-0} != 1 ]]; then
            read -r -p 'Install these prerequisites? [y/N] ' answer
            [[ "$answer" == y || "$answer" == Y ]] || return 1
        fi
        if command -v apt-get >/dev/null; then
            "${privileged[@]}" apt-get update
            "${privileged[@]}" apt-get install -y python3 git ca-certificates
        elif command -v pacman >/dev/null; then
            "${privileged[@]}" pacman -S --needed --noconfirm python git ca-certificates
        else
            printf '%s\n' 'Install Git and Python 3.11+ manually on this distribution.' >&2
            return 1
        fi
    fi
    python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'

    if [[ -n "$source_file" && "$source_file" != "${BASH:-}" && -f "$source_file" ]]; then
        repo=$(CDPATH= cd -- "$(dirname -- "$source_file")" && pwd)
        [[ -f "$repo/env.py" ]] || repo=''
    fi
    if [[ -z "$repo" ]]; then
        repo=$destination
        if [[ -e "$repo" ]]; then
            if [[ ! -e "$repo/.git" || ! -f "$repo/env.py" ]]; then
                printf 'Refusing to overwrite existing path: %s\n' "$repo" >&2
                return 1
            fi
            local origin current
            origin=$(git -C "$repo" config --get remote.origin.url)
            current=$(git -C "$repo" symbolic-ref --quiet --short HEAD || git -C "$repo" rev-parse HEAD)
            if [[ "$origin" != "$repository" || "$current" != "$ref" ]]; then
                printf '%s\n' 'Existing checkout has a different origin or ref; review it before rerunning bootstrap.' >&2
                return 1
            fi
            printf 'Using existing checkout without changing it: %s\n' "$repo"
        else
            mkdir -p -- "$(dirname -- "$repo")"
            git clone --branch "$ref" --single-branch -- "$repository" "$repo"
        fi
    fi
    [[ -f "$repo/env.py" ]] || { printf '%s\n' 'The selected repository ref does not contain the environment store.' >&2; return 1; }
    exec python3 "$repo/env.py" setup "$@"
}

# Bash must finish parsing the function before stdin is redirected. Never let
# prompts or the child setup process consume the remaining downloaded script.
if [[ -t 0 ]]; then
    bootstrap "$@"
elif { true </dev/tty; } 2>/dev/null; then
    bootstrap "$@" </dev/tty
else
    bootstrap "$@" </dev/null
fi
