# Configuration store design

Agreed requirements from the design interview. Ozoku confirmed the design and authorized implementation in the sibling checkout on 2026-11-10. Host migration and real credential enrollment remain separate actions.

## Hosts and application

- Manage physical machines, VMs, and WSL instances individually as hosts.
- The intended fleet currently has seven environments.
- Manage one primary user's environment per host. On owned hosts, system management covers explicitly selected settings, not other users' environments.
- Share configuration across selected hosts without requiring identical setups.
- Apply changes to selected hosts explicitly and capture local changes explicitly.
- Agent authority follows the requested task and named hosts. System changes, removals, service interruptions, and reboots require explicit authorization.
- Fresh-install setup assumes an installed OS, working networking, and an accessible user account. OS installation, partitioning, personal-file restoration, and application account logins are outside the initial scope.

## Programs and configuration

- Hosts explicitly select tools and settings, individually or through optional reusable bundles. Bundles do not contain other bundles.
- Configuration combines shared defaults, platform-specific settings, then host-specific overrides, with the more specific level winning. Prefer application-native includes or generated configuration over a universal deep-merge mechanism. Git settings differing between Windows and Linux are a required case.
- Conflicting selections require an explicit host choice rather than implicit bundle ordering. Multiple desktop sessions may be installed side by side; coexistence alone is not a conflict.
- Tools have shared identities across platforms, mapped to platform-default installation methods with explicit exceptions. Unsupported selections are reported before changes.
- Selecting a program normally selects its configuration.
- Allow configuration alone for programs installed through other means.
- Separate repository-managed settings from application-owned state.
- Flag conflicting local edits before overwriting them. Allow keeping them locally, capturing them into shared configuration, or restoring the repository setting.
- Keeping a local edit creates an explicit host exception for that file until management is re-enabled. Other files for the tool remain managed; status reports identify the exception.
- Captured edits default to host-specific configuration. Promoting them to platform or shared configuration requires an explicit choice.
- Keep caches, history, session state, and credentials outside managed configuration.
- Removing a program from a selection stops requesting installation. Previously managed programs and configuration become explicit cleanup candidates, without automatic removal.
- Installation, configuration changes, and software upgrades are separate operations. Setup installs missing programs using an available supported version; existing programs upgrade only when requested. Specific tools may use pinned versions.
- Plans disclose required dependency changes during installation. Stop when installation requires a separate system upgrade; do not silently perform full upgrades or use unsupported Arch partial-upgrade workarounds.
- Preserve progress on partial failure and support safe reruns. Independent work may continue; dependent configuration waits for failed prerequisites. Back up replaced configuration without promising automatic rollback of package upgrades or arbitrary system changes.

## Repository-driven operation

- Repository commands are the interface for both manual management and agent-driven tasks. Do not require the user to operate an underlying configuration engine directly. Use chezmoi as an internal detail; repository commands remain the interface.
- Initial setup supports standalone `curl | bash` and `irm | iex` entry points, obtaining the repository without a manual clone and preserving interactive prompts. Matching existing checkouts are reused without resetting work.
- Initial setup is always human-started: collect required enrollment details, secret-unlock inputs, and credentials, then complete the authorized setup autonomously. Later work is primarily agent-driven, with manual repository commands also supported.
- Initial setup collects host choices, authentication, secret-unlock details, and privilege authorization, then presents one plan for approval. Complete that plan without routine per-item prompts; report failures and genuinely manual steps.
- An agent can manage selected reachable hosts from an authorized checkout. There is no central management server.
- Each host must be able to set itself up using the configuration and secrets repositories with minimal intervention after initial authorization, without depending on another managed host being online. Ansible's native Windows controller limitation conflicts with this local-autonomy requirement; use the accepted native-local architecture below.
- Hosts independently check for outdated configuration.
- Enroll hosts explicitly with an address and authenticated management connection. Prefer private connectivity and existing authenticated access; the exact Linux and Windows transports still need verification.
- Guided setup offers an existing host definition or creation of a new one from available selections, then previews proposed changes. Explicit arguments support unattended operation with the same underlying behavior.
- Hosts normally follow `main`, with optional commit pinning. Remote application uses a known committed revision. Uncommitted changes may be previewed and tested locally; fleet application requires a commit.
- One server is not owned by Ozoku, but Ozoku has sudo access. Management boundaries for that host require explicit design; sudo availability is not blanket authorization for host-wide changes.
- Default the non-owned server to user-only management. Prefer user-local installation and report system-change requirements. Exclude SSH, networking, services, other users, and system-wide defaults unless the specific changes are individually authorized. Enforce the restriction even when sudo is available.

## Secrets

- The system must be free. Use SOPS + age with encrypted secrets stored in a separate private GitHub repository. Bitwarden Secrets Manager is not selected.
- Online account passwords currently live in Bitwarden; other secrets currently live separately on each host.
- Centralized machine-secret storage is required in the initial release to ease fresh-host setup. Use the selected SOPS + age design below.
- Research and official-source comparisons are recorded in [centralized-secrets.md](research/centralized-secrets.md).
- A hosted secrets service is acceptable; this does not authorize a central fleet-management server.
- Initial enrollment requires human authentication. After enrollment, prefer OS keychain protection for store-access credentials where supported. Protected-storage availability is verified per host; attended encrypted-key retrieval is an explicit alternative when no usable unattended mechanism exists.
- Separate machine-secret access from the personal password vault and restrict hosts to required secrets.
- Host identity credentials, such as SSH private keys, are normally unique per host. Shared application secrets may be distributed selectively.
- If secrets are unavailable, complete independent work and report blocked steps. Retain previously provisioned working credentials rather than erasing them.
- Include independent recovery instructions and a separately retained encrypted backup in initial setup. Recovery must not depend solely on credentials inside the store being recovered.
- Setup may provision application secrets into native credential stores or permission-restricted application files as needed. Keep values out of Git, logs, and previews; display references only.
- Locked or unavailable protected credential storage blocks secret-dependent operations until intervention; continue independent steps. Do not silently fall back to plaintext credential storage. Headless hosts may use encrypted systemd credentials where supported.
- Use separate decryption identities per host and a separately retained recovery identity. Automate identity generation and encryption-recipient maintenance so the human workflow is authorizing a host, not manually maintaining keys and rules. Do not introduce a custom key-management service.
- The configuration repository records the expected secrets-repository revision. One coordinated workflow updates secrets and that reference, with explicit failure reporting if only part succeeds. Applying configuration uses the recorded combination. Recovery covers both repositories.

## Agent skills

- Skills are selectable like other tools, with shared content deployed to supported agents' expected locations.
- Keep first-party skills in this repository. Track third-party skills by explicit source and pinned revision; update separately on request.
- Report incompatible agent requirements explicitly.

## Migration constraints

- Rebuild in the sibling checkout `/home/ozoku/src/github.com/ozokuz/dotfiles-rebuild` on branch `rebuild/configuration-store`. Leave the original checkout's live configuration intact.
- Rebuild all package lists from scratch. Do not carry over the existing package manifests or presets as the new selections.
- Existing configuration is input for selective evaluation only; wholesale reuse is not agreed.
- Do not remove or relocate existing configuration until live dependencies have been identified and a migration has been explicitly agreed.
- A read-only scan on the current host found `~/.zshenv` and `~/.zshrc` resolving into the original `../dotfiles/dots` tree. Scan scope: home top-level links, `~/.config`, and `~/.local/bin`; this does not establish the absence of other dependencies or other hosts using the checkout.
- Editing a symlink target in the original checkout can change the daily-driver shell configuration immediately, without running setup. The rebuild retains old files only as inactive `legacy/` references.
- Remove old implementation only after its live dependencies have been resolved through explicitly agreed host migrations. No host migration is authorized by the design interview.

## Outdated notifications

- Check at login or reconnect and periodically while online.
- Compare configuration relevant to the host; unrelated repository changes do not make it outdated.
- Notify through desktop notifications on graphical hosts and shell notices on servers and WSL.
- Deduplicate notifications until the intended configuration changes again.
- Start with local notifications; central notifications are deferred.
- Notification does not authorize application of changes.

## Initial platform support

- Arch/CachyOS desktops.
- Debian/Ubuntu servers.
- Windows desktops.
- WSL according to its Linux distribution.
- Additional distributions require an explicit addition.

## Deployment validation still required

- Real host names, selections, and individual configuration reuse need migration review. No old preset is adopted.
- Validate Windows native package, credential, scheduler, and SSH user-session behavior before using it on a daily-driver host.
- Configure private GitHub repository access and explicitly enroll real credentials.
- Validate each headless host's protected-storage and user-session scheduling capabilities. A WSL Windows-keychain bridge and TPM-sealed server keys are not implicit features.

## Accepted architecture

Implementation in the sibling checkout is authorized. Live host migrations and external credential provisioning are not implied.

- Expose repository-owned commands for setup, status, planning, installation, configuration application, upgrades, capture, enrollment, and explicit cleanup. Humans and agents use the same interface.
- Use chezmoi internally for home-file rendering and reconciliation, with focused native Bash/PowerShell adapters for package and system actions. Avoid an Ansible dependency, a generic custom configuration engine, or a permanent management daemon. Validate the integration against the agreed conflict and exception behavior in disposable environments.
- Native host-local setup on Linux and Windows is primary; do not require another host or WSL for Windows setup. Remote management invokes the same host-local workflow against a committed revision, using authenticated private connections. Prefer SSH where supported; report unsupported hosts instead of silently enabling a different management service.
- Store tool definitions, shared/platform/host settings, optional nonnested bundles, and explicit host selections in the configuration repository. Start package selections from scratch. Evaluate existing configuration individually before reuse.
- Fetch the separate private secrets repository at the recorded revision. Generate a decryption identity per host and automate recipient changes during explicitly authorized enrollment. Independent fresh-host enrollment uses separately available recovery material; an existing enrolled host may alternatively authorize it. GitHub authentication and decryption authorization are separate requirements.
- Prefer Windows user-protected credentials, Linux desktop Secret Service, or supported encrypted systemd credentials for stored decryption identities. WSL requires an explicit bridge or its own supported mechanism. Block dependent work if the required store is unavailable; never silently persist a raw key as fallback. Verify real OS versions and session contexts before enabling each adapter.
- Keep configuration and secret updates coordinated but do not claim cross-repository atomicity. Report partial updates and provide recovery; only publish the configuration reference after the corresponding secrets revision is available.
- Use lightweight login/reconnect/periodic checks for host-relevant changes. Checks only notify; they never apply configuration. Keep applied state local, marking partial application honestly.
- Stage and test implementation in the sibling checkout and disposable environments. Do not run setup on daily-driver hosts, migrate live symlinks, remove the old configuration, create the private repository, or enroll real credentials without the corresponding explicit authorization.
