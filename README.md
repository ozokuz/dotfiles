# Environment store

Local-first setup and configuration for Linux, Windows, and WSL. You and an agent
use the same repository commands. No controller server or paid service is required.

The rebuild lives on `rebuild/configuration-store`. **Do not point your existing
live symlinks here.** The original `../dotfiles` checkout remains intact.

## First setup

Start with an installed OS, networking, and your user account. No pre-clone is
required. Once this rebuild is published to `main`, run:

```sh
curl -fsSL https://raw.githubusercontent.com/ozokuz/dotfiles/main/setup.sh | bash
```

On Windows, from PowerShell:

```powershell
irm https://raw.githubusercontent.com/ozokuz/dotfiles/main/setup.ps1 | iex
```

**These rebuilt entry points have not been published yet.** The current `main`
bootstrap is still the old implementation; wait for publication before using
these URLs.

The standalone bootstrap installs missing prerequisites with your authorization,
clones the configuration repository, and starts the same guided local setup.
Linux defaults to `~/.local/share/envstore/repository`; Windows defaults to
`%LOCALAPPDATA%\envstore\repository`. Bash reconnects stdin to the terminal so
passwords and prompts still work through a pipe. PowerShell returns to your
existing session after setup instead of exiting it.

Set `DOTFILES_DIRECTORY`, `DOTFILES_REPOSITORY`, or `DOTFILES_REF` before running
the command to choose a destination, repository, or branch/tag. An existing
matching checkout is reused without resetting local work. Other existing paths
or mismatched origins/refs are rejected. Bootstrap never silently pulls or
switches an existing checkout.

From an existing checkout, these entry points still work:

```sh
./setup.sh --host my-host
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -HostName my-host
```

For owned Windows hosts needing machine-wide changes, add `-AllowSystem`; setup
requests UAC elevation once and verifies that it is still the same user account.
User-only setup does not elevate.

Setup creates a host definition if needed, asks which available tools to select,
collects Git identity and optional private secrets repository details, and
presents a plan. Approve once to apply that plan. Missing Python 3.11+ or Git must
be bootstrapped before the full plan can be computed; the script separately asks
before installing those prerequisites. Windows can register or bootstrap missing
WinGet for the current user using [Microsoft's bootstrap tooling](https://learn.microsoft.com/en-us/windows/package-manager/winget/#install-winget-on-windows-sandbox). An owned Windows
host that authorizes machine-wide setup continues through one UAC prompt after
the checkout is available; you do not need to rerun the download command.

Choose `scope: "user"` for a server you do not own. It excludes system packages
and services even with `--allow-system`. A specifically requested exception uses
`--allow-system-item TOOL`; it authorizes only that tool, not the whole host. `scope: "owned"` still requires explicit
`--allow-system` to change system state. Setup can collect that authorization and
sudo authentication interactively. Never run the whole tool with sudo.

An existing file that differs from the desired config is a conflict, including
on first adoption. Setup leaves it intact and reports it. Resolve conflicts
explicitly rather than forcing an entire home directory into management.

Only example hosts are included. Your seven real hosts have not been enrolled or
migrated, and no private GitHub repository has been created.

## Daily commands

`./env` on Linux and `.\env.cmd` (or `python env.py`) on Windows expose the same commands.
The Windows wrapper invokes the PowerShell entry point without requiring a
persistent execution-policy change.
The bootstrap invocation above uses a process-only execution-policy setting; it
does not change the machine or user policy. Flags such as
`--host` can go before or after the command. Output is JSON; errors return a
nonzero exit status.

```sh
./env --host my-host plan
./env --host my-host install --allow-system
./env --host my-host apply
./env --host my-host status
./env --host my-host upgrade --allow-system
./env --host my-host system-upgrade --allow-system
```

- `install` installs missing selected programs; `apply` configures them. `setup`
  performs both. A `config` selection configures without installing.
- `upgrade` explicitly upgrades selected programs. Arch requires the separate
  host-wide `system-upgrade` operation. Installation never refreshes Arch's
  repositories or silently upgrades the OS.
- `plan` shows package transactions where the provider supports them, file
  conflicts, system actions, and blocked work. Installer/runtime effects that
  cannot be simulated are not guaranteed by the preview.
- `status` reports intended/applied configuration, local changes, and exceptions.
- `--yes` approves the named operation noninteractively. It does not grant system
  access or override file conflicts. `--allow-system` does not override user-only
  host policy.

Local edits:

```sh
./env --host my-host capture .gitconfig
./env --host my-host keep-local .gitconfig
./env --host my-host manage .gitconfig
./env --host my-host apply --restore .gitconfig
```

Capture writes a literal host-specific override. Promote changes into shared or
platform settings through a reviewed repository edit. `keep-local` excludes that
file until `manage` re-enables management. Explicit restoration backs up the
previous file in private local state. Symlinks require an explicit migration;
setup never follows them into the old repository.

Removing a selection never uninstalls it. Review cleanup candidates in `plan`,
then name each item to remove:

```sh
./env --host my-host cleanup --package jq --allow-system
./env --host my-host cleanup --file .gitconfig
```

Only packages installed by this tool and unchanged managed files are eligible.
Unrelated preinstalled programs and locally edited/excepted files are preserved.
No blanket autoremove is performed. Changing a package mapping preserves ownership
of the old package without adopting an already-installed replacement. Superseded
packages remain cleanup candidates; pass the candidate's `tool` value from `plan`
to `cleanup --package`, including any provider/ID/scope suffix.

## Repository structure

| Path | Purpose |
| --- | --- |
| `hosts/*.json` | Explicit host selections, ownership scope, settings, overrides, secret and remote references |
| `catalog/*.json` | Tool definitions and platform package mappings |
| `bundles/*.json` | Optional sets of tools, without bundle inheritance |
| `settings/shared.json` | Shared template data |
| `settings/platform/*.json` | Platform-specific data |
| `templates/` | New, selectively managed configuration |
| `overrides/<host>/` | Captured literal configuration for one host |
| `examples/` | Secret and skill tool definitions to adapt |
| `dependencies.json` | Pinned engine binaries and publisher SHA-256 digests |
| `envstore/`, `adapters/` | Repository interface and native platform operations |
| `legacy/` | Inactive old implementation, retained for selective migration review |

Settings resolve **shared → platform → host**, one level at a time. There is no
universal recursive merge. Use application-native includes or explicit templates.
A tool's `settings_keys` declares the template inputs it uses, so unrelated tool
settings do not trigger notifications. `host` and `platform` are always available.
An explicit host tool choice overrides its bundles: `install`, `config`, or `off`.
Multiple desktop sessions are allowed; only overlapping managed paths or declared
exclusive resources conflict.

Package lists are newly authored. The small starting catalog covers Git, shell,
prompt, terminal, CLI/editor tools, Firefox, and Arch desktop sessions where
available. It is not a copy of either old workstation preset. Unsupported
platform/tool combinations fail before configuration writes.

Package mappings can be replaced through `package_overrides` in a host definition.
Providers are `apt`, `pacman`, `winget`, and user-scoped `flatpak`. Flatpak requires
its runtime to be installed first; a mapping may explicitly name a remote and
HTTPS `remote_url`. The runtime is not installed through an implicit system change.
AUR helpers and arbitrary installer scripts are intentionally not automatic.
Application packages follow their native sources; the configuration engine and
third-party skills are pinned. Application-specific version pinning is not yet a
supported catalog option.

System adapters currently support explicit service startup state, without
starting, stopping, or restarting a running service. Additional system settings
need focused, reviewed adapters rather than arbitrary privileged template scripts.

## Secrets

See [secrets and recovery](docs/secrets.md). Secret values belong in a **separate
private GitHub repository**, encrypted with SOPS + age. This repository records
its URL and an immutable revision. Initial enrollment needs GitHub access plus an
authorized identity; GitHub authentication alone does not decrypt secrets.

Private identities are stored in Windows user DPAPI, Linux Secret Service,
explicitly chosen systemd encrypted credentials, or an explicitly chosen
passphrase-encrypted file. There is no automatic raw-key fallback. Plans never
unlock secrets, show decrypted values, or print secret-bearing diffs.

## Agent skills

A tool can declare a local skill directory or a GitHub source at a full commit
SHA, plus explicit compatible destination directories. See
[examples/skill-tool.json](examples/skill-tool.json). Third-party sources also need
`repository` and `revision`; `source` is relative to that checkout. A skill source
must contain `SKILL.md`; symbolic links and special archive entries are rejected.
Files are deployed through the same conflict guard as other configuration.

Keep your own skill sources in this repository. Third-party updates are explicit
revision changes; no skill is pulled from a moving branch during setup. Target
compatibility is expressed in the tool's platform/target mapping, not inferred
from a skill's name.

## Remote operation

Enroll SSH independently, using private connectivity where practical. Configure
`remote.address` and `remote.checkout` in the host definition. Native Windows SSH
must run commands in a usable user context with Python and Git available.

```sh
./env --host my-host remote sync --yes
./env --host my-host remote plan
./env --host my-host remote apply --yes
./env fleet plan --targets workstation laptop server
```

Remote operations require a clean committed local checkout. `remote sync` fetches
that commit into a clean existing remote checkout; publish it to Git first.
`remote apply` refuses a different or dirty remote revision. SSH host-key checking
stays enabled. Fleet operations report unreachable/failed hosts and continue with
other explicitly named hosts. They never discover targets by scanning a network.

Remote access may not unlock an interactive desktop credential store. In that
case secret-dependent work remains blocked; there is no weakening of credentials
to make SSH work.

## Outdated notifications

Successful setup installs a user-session check: a Linux user-systemd timer or a
Windows interactive scheduled task. It checks at session start and every 30
minutes, fetching the tracked ref without checking out or applying changes.
New connectivity is picked up by the next check. Linux shell profiles managed by
the new catalog also source a login check for SSH/reconnect notices.

```sh
./env --host my-host check --fetch --notify
```

Checks compare host-relevant resolved inputs, including selected templates and
pinned secret/skill revisions. Unrelated host edits do not trigger a notification.
Notices are deduplicated until the intended configuration changes. Offline or
locked credentials can prevent fetching; reruns retry. No changes are queued for
automatic application. Graphical Linux needs `notify-send`; otherwise notices go
to stdout. Headless hosts without a usable user-systemd session need the shell
hook or an explicitly configured user scheduler. Setup reports registration
failures instead of marking the entire host current.

## Validation and boundaries

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary homes, state, fixture secrets, and pinned real engine binaries.
Disposable Debian and Arch container tests install actual packages and exercise
setup, repeatability, conflict detection, and capture. CI includes Windows tests
and a native DPAPI round-trip. No test enrolls real credentials or modifies a
real user's configuration. Engine binaries are downloaded into private state,
verified against pinned digests, and kept off system PATH.

Native Windows package, scheduled-task, and remote-session behavior still needs
validation on Windows; Linux PowerShell syntax checks do not establish that.
Recovery protects keys at rest, not plaintext used by an authorized application or
process under the same user. Bootstrapping disks, installing the OS, restoring
personal data, and completing application account logins remain outside scope.
