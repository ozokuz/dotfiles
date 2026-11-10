# Centralized secrets for repository-driven host setup

Research date: 2026-11-10. Official primary sources only. Documentation research, not an installation or runtime compatibility test. No secrets were accessed and no option was selected or provisioned.

## Fit with the current design

The glossary treats physical machines, VMs, and WSL instances as separate **hosts**. [ADR-0002](../adr/0002-repository-driven-management.md) rules out a fleet controller: an authorized repository checkout manages selected reachable hosts through direct authenticated connections. It does not explicitly forbid an optional hosted secrets dependency. Whether that dependency is acceptable remains a user decision. Self-hosting a secrets service would introduce a server to operate, even if it is not a configuration controller.

The interview now requires centralized machine secrets in the first release; [configuration-design.md](../configuration-design.md) still records the store as undecided. The parent owns updating that document. These findings do not change either ADR or authorize applying configuration.

Two deployment patterns are possible with any candidate: retrieve secrets at the authorized checkout and deliver only required values through the authenticated connection, or let each host retrieve its own secrets. The former avoids distributing store credentials to every host; the latter supports independent retrieval but needs a bootstrap credential on each participating host. This is an architectural inference, not a provider requirement. Applications still receive the plaintext they need.

## Comparison

| Option | Platform evidence | Dependency and authentication | Exposure boundary |
| --- | --- | --- | --- |
| Bitwarden Password Manager CLI (`bw`) | Official Windows and Linux support; native x64 binaries, npm installation for ARM64. [CLI](https://bitwarden.com/help/cli/#download-and-install) | Existing Bitwarden cloud account or configured self-hosted server. Human vault unlock; API-key login still requires unlock to read vault data. [CLI](https://bitwarden.com/help/cli/) | Unlock yields a vault decryption session, not a per-host secret token. Using Ozoku's personal account on every host would expose that account's accessible vault to those sessions. A filtered retrieval command is not an access-control boundary. [Unlock](https://bitwarden.com/help/cli/#unlock) |
| Bitwarden Secrets Manager (`bws`) | Official Windows and Linux CLI support. [CLI](https://bitwarden.com/help/secrets-manager-cli/#download-and-install) | Hosted US/EU service, or Enterprise self-hosting. Machine-account access token instead of personal vault unlock. [CLI configuration](https://bitwarden.com/help/secrets-manager-cli/#config), [self-hosting FAQ](https://bitwarden.com/en-gb/help/secrets-manager-faqs/) | Machine accounts receive projects with read or read/write permissions. Tokens inherit that scope; use separate read-only scopes where useful. Personal password-vault access is unnecessary. [Machine accounts](https://bitwarden.com/help/machine-accounts/) |
| SOPS + age encrypted files in Git | SOPS publishes Linux AMD64/ARM64 binaries, Debian packages, and Windows AMD64/ARM64 executables. age publishes Windows/Linux binaries and documents Arch, Debian, Ubuntu, and Windows installation. [SOPS release](https://github.com/getsops/sops/releases/tag/v3.13.3), [age installation](https://github.com/FiloSottile/age#installation) | No secrets service or cloud KMS required when using local age identities. Git distributes ciphertext; the private identity enables local decryption. [SOPS age documentation](https://raw.githubusercontent.com/getsops/docs/main/content/en/docs/usage/identities/age/_index.md) | A shared identity for all files creates a broad decrypt key. Separate identities and recipient sets per file can limit scope. A recipient decrypts the file, not merely one selected value. [Age recipients](https://raw.githubusercontent.com/getsops/docs/main/content/en/docs/usage/identities/age/_index.md) |

WSL should use the Linux build appropriate to its distribution and architecture, as a separate host. CachyOS should be evaluated through its Arch-compatible packaging or upstream Linux binaries. Those are platform-fit inferences; the cited upstream platform support is not a test of every distribution/version. No fourth product is necessary to distinguish the relevant policy choices.

## Lifecycle and offline behavior

### Password Manager CLI

Bootstrap needs account login and vault unlock. An API key does not remove the master-password unlock requirement. `BW_SESSION` carries the unlocked session; finish with `bw lock`. Recommendation: use this only from a trusted management checkout for attended setup, or use a dedicated machine-secrets account if host-side use is desired. Merely separating items into folders does not make the personal session narrowly scoped. [CLI authentication and unlock](https://bitwarden.com/help/cli/#unlock)

Bitwarden documents offline read-only use of unlocked apps. The CLI separately documents downloading an encrypted local vault with `sync`. Therefore a previously synchronized/unlocked CLI can serve cached reads, but fresh login/sync and current data require connectivity. Do not assume a logged-out fresh host can bootstrap offline, or that offline data reflects recent rotations. Verify the chosen CLI release's offline path before promising it in setup. [Offline operation](https://bitwarden.com/help/using-bitwarden-offline/), [CLI sync](https://bitwarden.com/help/cli/#sync)

Recovery should include an independently accessible backup. Password-protected encrypted exports can be imported into another account; account-restricted exports remain tied to the originating account and encryption key. Preserve the export password outside the failure being recovered from. [Encrypted exports](https://bitwarden.com/help/encrypted-export/)

Rotation must distinguish stored application credentials from vault/session credentials; neither updates the application's issuer automatically. Core Password Manager storage is free; premium features have separate entitlements. [Plans](https://bitwarden.com/help/password-manager-plans/)

### Secrets Manager

Bootstrap requires a human to create an organization/project, assign a machine account, generate a token, and transfer it through an already trusted channel. Tokens are displayed once and cannot be retrieved later; expiry is configurable and defaults to never. Losing a token calls for issuing a replacement using retained administrative access. Rotate by distributing a replacement and revoking the old token. Revocation blocks new authentication immediately, but existing sessions can retrieve/decrypt secrets for **up to one hour**. [Access tokens](https://bitwarden.com/help/access-tokens/)

The scope is enforced by the service, not by an independent cryptographic key for every project: Bitwarden describes tokens unlocking the organization symmetric key, followed by server authorization of requested data. Consequently machine scoping should not be described as cryptographic isolation of every project's ciphertext. Tokens also do not expose the separate personal password vault. [Secret decryption](https://bitwarden.com/help/secret-decryption/)

Treat CLI retrieval as online. The documented state files cache authentication state, not a promised offline secret database. Bitwarden discusses explicit caching through SDKs/integrations as a separate availability measure. Already installed application credentials can remain usable during an outage if the application permits; fetching new values cannot be assumed. [CLI state](https://bitwarden.com/help/secrets-manager-cli/#config), [availability guidance](https://bitwarden.com/tips/)

For recovery, owner/admin exports include projects and secrets but exclude machine accounts and tokens. The JSON export needs separate encryption and backup protection; recovery must recreate access assignments/tokens. Updating a value in the store does not itself rotate the credential at its issuing service or update an offline host. [Export data](https://bitwarden.com/en-gb/help/export-secrets-data/)

Current published limits: Free includes unlimited secrets, 2 users, 3 projects, and 3 machine accounts; Teams includes 20 machine accounts and Enterprise 50, with extra accounts billed separately. Self-hosting requires Enterprise. These are product limits, not a statement of the user's existing subscription. Recheck pricing before purchase; no paid price quote is needed to decide this design. [Plans](https://bitwarden.com/help/secrets-manager-plans/), [FAQ](https://bitwarden.com/en-gb/help/secrets-manager-faqs/)

Inference for this fleet: one isolated machine account per host would exhaust the free tier after three hosts, including separately scoped WSL instances. Multiple tokens for one account do not create different project permissions. Retrieving from one management checkout could reduce account count, at the cost of concentrating retrieval authority there. [Machine-account scope](https://bitwarden.com/help/machine-accounts/)

### SOPS + age

Proposed bootstrap: generate a host identity, send its public recipient to an authorized decryptor, and add it to required files using `updatekeys`. Alternatively, decrypt centrally and deliver values remotely. Keep a separate recovery recipient on every file and back up its identity independently. Losing all matching identities has no service reset path. [SOPS age identity handling](https://raw.githubusercontent.com/getsops/docs/main/content/en/docs/usage/identities/age/_index.md)

A local identity permits unattended decryption; a human could instead supply it when needed. SOPS accepts a key file, environment variable, or key-output command. Local decryption has no online expiry/revocation check. Ciphertext plus identity works offline; Git is needed for updates. [Identity inputs](https://raw.githubusercontent.com/getsops/docs/main/content/en/docs/usage/identities/age/_index.md)

After compromise, remove the recipient, run `updatekeys`, rotate the file data key, then rotate the actual passwords/API keys. Updating recipients alone does not renew the data key. Old Git revisions remain decryptable with a formerly authorized identity, so removing a recipient cannot retract old secrets. This history consequence follows from local decryption and versioned ciphertext. [SOPS key management and compromise procedure](https://getsops.io/docs/usage/key-management/)

SOPS supports structured encrypted files, including YAML, JSON and ENV. Keep ciphertext separate from ordinary rendered configuration, and account for visible structural metadata when choosing formats. SOPS is MPL-2.0 and age is BSD-3-Clause; local use needs no secrets-service subscription. Git hosting/backup costs remain separate. [SOPS formats/license](https://getsops.io/docs/), [age license](https://github.com/FiloSottile/age/blob/main/LICENSE)

## Conditional recommendations, not a selection

- **Hosted secrets dependency allowed; scoped unattended retrieval matters:** shortlist hosted Bitwarden Secrets Manager. It fits the existing provider relationship and separates machine access from personal passwords. Decide project/account boundaries and expected host count before relying on Free.
- **No secrets-service dependency; encrypted Git history acceptable:** shortlist SOPS + age. It fits checkout-driven operation and offline recovery, provided recipient enrollment, independent recovery keys, and compromise rotation are explicit first-release responsibilities.
- **Attended setup only; least new machinery:** consider Password Manager CLI on a trusted management checkout. Avoid making personal-vault unlock a prerequisite on every target host. A dedicated account is possible, but still has a human-vault authentication model.

In all cases, centralized retrieval does not eliminate the initial trust step: a human must unlock, deliver a token, or authorize a new recipient. Keep bootstrap/recovery material outside the managed configuration and avoid circular recovery, such as storing the only repository credential inside a store reachable only through that repository.

## Decisions still needed in the interview

1. Does the server ban permit a hosted secrets service? Would operating a self-hosted secrets server ever be acceptable?
2. Which actions require secrets: attended setup/application only, or independent host operation after reboot? Outdated-host checks should not acquire secrets unless their design actually needs them.
3. Must hosts retrieve directly, or may the authorized management checkout deliver required values? Which hosts may share access to the same secrets?
4. Are encrypted machine secrets and their historical versions permitted in Git, including a public repository?
5. What must work during provider/Git outages, and what recovery material will be available after loss of every current host?
6. How many independent scopes are needed, what recurring cost is acceptable, and how will revoked/rotated credentials reach offline hosts through explicit application?

No implementation, enrollment, migration, secret export, or credential changes were performed.
