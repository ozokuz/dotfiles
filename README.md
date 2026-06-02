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
./setup.sh --host titan --session hyprland --groups desktop-common,apps,dev,hyprland --dry-run
```

Install only specific packages from the selected package categories:

```sh
./setup.sh --host titan --packages ghostty,neovim,bitwarden --dry-run
./setup.sh --host saturn --categories apps,dev --packages obsidian,mise --dry-run
./setup.sh --host titan --distro cachyos --packages ghostty --dry-run
```

When run interactively, package categories use the selected host and distro
defaults without an extra prompt. Package selection opens directly with preset
packages preselected; pass `--packages` to install only specific packages
without opening the selector.

## Model

- `setup.sh` is the main entrypoint.
- `packages/common` contains packages shared by all machines.
- `packages/groups` contains selectable package categories such as `dev`, `gaming`, `virtualization`, `hyprland`, `niri`, and `flatpak-gaming`.
- `packages/hosts` contains host presets such as `saturn` and `titan`.
  Host presets choose default categories and package selections; package
  definitions live in common, group, and distro lists. Use `PACKAGES` for
  host packages that apply to every distro preset, or distro-specific keys
  such as `ARCH_PACKAGES` for packages that should only be selected on one
  distro.
- `packages/distros` contains distro presets and overlays such as `arch` and `cachyos`.
- `dots` is managed with GNU Stow and currently owns curated shell dotfiles.
- `host-overlays/<host>` contains machine-specific dotfiles that should not be
  part of the generic Stow tree.
- Compositor configs are shared by default. Host-specific Hyprland and Niri
  settings live in `host-overlays/<host>/.config/{hypr,niri}/overlay.*`; setup
  links them into `~/.config/{hypr,niri}/overlays/current.*` after stowing.
- DankMaterialShell-generated compositor files are host-specific. Setup links
  `~/.config/{hypr,niri}/dms` to
  `host-overlays/<host>/.config/{hypr,niri}/dms`.
- DankMaterialShell settings are host-specific. Setup links
  `~/.config/DankMaterialShell/settings.json` to
  `host-overlays/<host>/.config/DankMaterialShell/settings.json`.

The default `saturn` setup selects:

```text
desktop-common,apps,dev,gaming,virtualization,flatpak-gaming,hyprland
```

The default `titan` setup selects:

```text
desktop-common,apps,dev,niri
```

`titan` is the laptop profile. It stays lean by default and can opt into larger
workstation sets when needed, for example `hyprland`, `gaming`, or
`virtualization`.

## Safety

- Use `--dry-run` to preview actions.
- Existing dotfile conflicts are moved to `~/.dotfiles-backups/<timestamp>/`.
- Secrets are not stored in this repo. After setup, authenticate tools manually, for example `gh auth login`, `tailscale up`, Bitwarden, and SSH keys.
- `~/.local/bin/screenshot-upload` expects a local `~/.local/upload_url.txt`; keep that file out of the repo.
