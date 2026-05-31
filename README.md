# Dotfiles

Post-install workstation bootstrap for Arch Linux and CachyOS machines.

## Quick Start

On a freshly installed minimal Arch/CachyOS system with shell and internet access,
first run:

```sh
scripts/bootstrap-minimal-arch.sh --user ozoku
```

To immediately continue into the workstation setup:

```sh
scripts/bootstrap-minimal-arch.sh --user ozoku --host saturn --run-setup
```

The minimal bootstrap intentionally stops before installing a desktop environment
or window manager. It prepares the base system with kernel/firmware basics,
NetworkManager, Bluetooth, PipeWire/WirePlumber audio, OpenSSH, firewalld, time
sync, fstrim, zram, sudo/wheel, and the tools needed to run the main setup.

Preview the setup for the current machine:

```sh
./setup.sh --dry-run
```

Run the interactive setup:

```sh
./setup.sh
```

Run with explicit host defaults:

```sh
./setup.sh --host saturn --session hyprland
./setup.sh --host titan --session niri --dry-run
```

## Model

- `setup.sh` is the main entrypoint.
- `packages/common` contains packages shared by all machines.
- `packages/groups` contains optional groups such as `dev`, `gaming`, `virtualization`, `hyprland`, `niri`, and `flatpak-gaming`.
- `packages/hosts` contains host overlays such as `saturn` and `titan`.
- `dots` is managed with GNU Stow and currently owns curated shell dotfiles.

The default `saturn` setup selects:

```text
desktop-common,apps,dev,gaming,virtualization,flatpak-gaming,hyprland
```

The default `titan` setup selects:

```text
desktop-common,apps,dev,niri
```

## Safety

- Use `--dry-run` to preview actions.
- Existing dotfile conflicts are moved to `~/.dotfiles-backups/<timestamp>/`.
- Secrets are not stored in this repo. After setup, authenticate tools manually, for example `gh auth login`, `tailscale up`, Bitwarden, and SSH keys.
- `~/.local/bin/niri-screenshot` expects a local `~/.local/upload_url.txt`; keep that file out of the repo.
