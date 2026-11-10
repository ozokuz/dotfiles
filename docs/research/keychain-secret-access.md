# OS protection for centralized-secret access

Research date: 2026-11-10. Official sources only; documentation and source inspection, not runtime validation. No credentials accessed, software installed, or implementation performed. Bitwarden Secrets Manager remains a candidate, not a selection.

## Conclusion and scope

Human enrollment followed by OS-protected bootstrap credentials is feasible, but needs platform-specific retrieval code. `bws` does **not** itself enroll an access token in Windows Credential Manager or Linux Secret Service. Its encrypted session cache is a separate mechanism. An OS store protects the bootstrap token while stored; retrieving centralized secrets still exposes plaintext to the authorized process.

Hosted storage is now permitted in [configuration-design.md](../configuration-design.md). This note supplements [centralized-secrets.md](centralized-secrets.md); its earlier hosted-service question is resolved. The proposed policies preserve explicit application and checkout-driven management in ADRs [0001](../adr/0001-explicit-host-configuration-application.md) and [0002](../adr/0002-repository-driven-management.md). Automatic availability of credentials would not authorize automatic configuration changes.

## What `bws` actually stores

The documented authentication inputs are `BWS_ACCESS_TOKEN` and `--access-token`. Encrypted state files under `~/.config/bws/state` cache authentication tokens and associated session data to reduce repeated authentication and rate limiting. They are not documented as an offline secrets database. [Bitwarden CLI authentication and state](https://bitwarden.com/help/secrets-manager-cli/)

Source inspection confirms the distinction: the CLI parses a token from the flag/environment, rejects authenticated operations if it is missing, then passes that token and the optional state-file path to SDK authentication. There is no OS-keychain lookup in this flow. The configuration schema has server/profile/state settings, not a saved bootstrap-token field. Inspected revision: `ba3e6a09d52a12954ef39c06b93587afb657b020` (package declares 2.1.0). This is source evidence, not a guarantee about every distributed release. [CLI entry point](https://github.com/bitwarden/sdk-sm/blob/ba3e6a09d52a12954ef39c06b93587afb657b020/crates/bws/src/main.rs), [input schema](https://github.com/bitwarden/sdk-sm/blob/ba3e6a09d52a12954ef39c06b93587afb657b020/crates/bws/src/cli.rs), [package](https://github.com/bitwarden/sdk-sm/blob/ba3e6a09d52a12954ef39c06b93587afb657b020/crates/bws/Cargo.toml)

Therefore keep two concepts separate: **bootstrap credential storage** in an OS facility, and **cached authenticated state** managed by `bws`. Encryption of the latter does not establish OS-keychain integration or remove the former. This conclusion follows from the inspected authentication path; this research does not audit the SDK cache cryptography.

Enrollment would have a human authenticate to the provider, authorize a narrowly scoped machine account, and securely enroll its token locally. Losing OS-protected material requires retained provider administration to issue a replacement. Revocation prevents new authentication, but existing Bitwarden sessions may retrieve/decrypt for up to one hour. Clearing one local cache cannot revoke copies elsewhere. [Access-token lifecycle](https://bitwarden.com/help/access-tokens/)

## Platform mechanisms and availability

### Windows desktops

Recommended candidate: a named **generic credential**, written/read by a small Windows helper through `CredWrite`/`CredRead`. Use `CRED_PERSIST_LOCAL_MACHINE` for persistence across this user's logons on this computer. Despite its name, that persistence option does not expose the credential to every local user; avoid enterprise roaming unless wanted. [CredWrite](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew), [credential types and persistence](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)

Alternative: an ACL-restricted blob encrypted with **user-scoped DPAPI**. This supplies encryption rather than credential naming/storage management. Normally decryption requires the same logon credentials and computer, with documented roaming exceptions. Avoid `CRYPTPROTECT_LOCAL_MACHINE`: that DPAPI flag lets any user on the computer decrypt a blob they can read. It is distinct from Credential Manager's similarly named persistence option. [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)

After reboot, persistence preserves the credential, but retrieval still requires a suitable user logon context. After normal user login, a helper in that context can retrieve without a separate provider login. `CredRead` uses the current token's logon-session credential set; network logons do not have one. Do not promise Windows SSH, remote execution, or scheduled tasks will see the desktop credential set until their specific identity/logon/profile behavior is validated. [CredRead](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw)

Security implication: ordinary generic credentials/user DPAPI are user-context protection, not an application allowlist or mandatory Windows Hello prompt. Code running with the relevant user access can request plaintext. A locked screen is not evidence that the stored token becomes unavailable to already running user processes. These are boundaries inferred from the cited APIs, not a tested desktop policy.

### Arch/CachyOS desktops with multiple Wayland sessions

Use one selected Secret Service provider per user bus for this purpose, with an encrypted, password-protected collection. Secret Service runs in the user's login session and may need unlocking; it is not provided by Wayland itself. The API does not mandate per-application access control or even a particular unlock mechanism. [Secret Service introduction](https://specifications.freedesktop.org/secret-service/latest/ch01.html), [API exclusions](https://specifications.freedesktop.org/secret-service/latest/ch10.html)

GNOME Keyring is a feasible baseline even outside GNOME: its documented startup separates PAM login handling from session initialization. KDE also provides Secret Service support, but its implementation/version must be checked rather than assuming every installed KWallet behaves identically. [GNOME daemon startup](https://wiki.gnome.org/Projects/GnomeKeyring/RunningDaemon), [KDE framework documentation](https://github.com/KDE/kwallet)

PAM can unlock GNOME's login keyring with the supplied login password. This requires appropriate PAM integration and a matching keyring password. With passwordless authentication, an additional manual keyring unlock may be necessary. After boot before unlock, retrieval is blocked. Key-only unattended SSH does not supply that password, so cannot be assumed to unlock the keyring. [GNOME PAM behavior](https://wiki.gnome.org/Projects/GnomeKeyring/Pam), [PAM module manual](https://wiki.gnome.org/Projects/GnomeKeyring/Pam/Manual)

Recommended design inference: share the chosen provider across selected compositors, instead of creating a separate bootstrap-token copy per desktop. Validate provider ownership/activation, user-bus reachability, prompt support, login/unlock, and logout behavior for each actual session. Simultaneous sessions need explicit validation; switching compositors does not prove the bus or keyring lifecycle is correct. An SSH process might reach an already unlocked user service, but this is conditional availability, not a reliable unattended contract. Never solve it by removing the keyring password.

An unlocked keyring is not a boundary against malicious processes under the same user. GNOME explicitly documents this limitation. Its archived security FAQ is useful for that threat model, not for promises about current algorithms or compositor lock/suspend behavior. [GNOME security FAQ](https://wiki.gnome.org/Projects/GnomeKeyring/SecurityFAQ)

### Debian/Ubuntu headless servers

For unattended retrieval, prefer a narrowly scoped system service using `LoadCredentialEncrypted=`. systemd decrypts the stored bootstrap token at service activation and exposes a read-only plaintext credential file to the service user and root, preferably in non-swappable memory. The helper must read that file; `bws` does not consume it automatically. `LoadCredential=` alone provides delivery isolation but does not encrypt its source file at rest. [systemd execution credentials](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#Credentials)

Encryption can use a root-only host key, TPM2, or both. Host-key-only encryption does not resist an attacker who obtains the disk containing both blob and host key. TPM2 binding adds hardware dependence; combined protection needs the TPM and OS host key. Explicitly choose the mode rather than silently promising TPM protection everywhere. A TPM without a boot-state policy does not establish trusted-boot integrity: the documented direct PCR default is no PCR binding. PCR policies can block legitimate boot updates, so recovery/re-enrollment must be planned. [systemd-creds encryption and PCR options](https://www.freedesktop.org/software/systemd/man/latest/systemd-creds.html)

This can operate after boot without a graphical login or SSH password once the OS/storage and decryption policy permit service activation. An authorized SSH operation could invoke the designated service; a normal shell does not automatically receive its credentials. Restrict invocation and service identity, and retain explicit host/application authorization. This is a proposed execution policy based on systemd's service-scoped credential lifecycle. [System and service credentials](https://systemd.io/CREDENTIALS/)

Check installed versions and TPM access per host, including VMs. `systemd-creds` encryption arrived in v250; user-scoped encryption arrived in v256, so do not substitute a user-service design indiscriminately. For example, Debian 12 documents systemd 252 and Ubuntu 24.04 documents 255. Latest upstream documentation contains newer features these releases lack. [Debian package](https://packages.debian.org/bookworm/systemd), [Ubuntu 24.04 manual](https://manpages.ubuntu.com/manpages/noble/man1/systemd-creds.1.html), [upstream version annotations](https://www.freedesktop.org/software/systemd/man/latest/systemd-creds.html)

Root or compromise of the retrieving service can obtain the token in use. TPM sealing protects stored material under its chosen policy; it does not keep plaintext secret from the running service. Full unattended boot also depends on disk-unlock policy, outside this secrets-store decision.

### WSL

A Linux `bws` process does not automatically use Windows Credential Manager. A Linux Secret Service requires its own provider, reachable user bus, encrypted collection, and unlock lifecycle. Starting a distro or having WSLg is not evidence those exist. WSL supports systemd, but availability depends on WSL/distro configuration; systemd alone does not create a desktop keyring. [Microsoft systemd guidance](https://learn.microsoft.com/en-us/windows/wsl/systemd), [Secret Service prerequisites](https://specifications.freedesktop.org/secret-service/latest/ch01.html)

For attended WSL usage, prefer an explicit Windows helper using the logged-in Windows user's protected store. Microsoft supports invoking Windows executables from WSL as the active Windows user, including pipes. This makes a bridge feasible, not already implemented: either run retrieval in the Windows helper and pass only requested application secrets, or transfer the bootstrap token transiently to Linux `bws`. Prefer the former to reduce bootstrap-token propagation. Keep a separate scope for each WSL host. [Windows interoperability](https://learn.microsoft.com/en-us/windows/wsl/filesystems#run-windows-tools-from-linux)

This does not provide strong isolation from that Windows user or other processes able to invoke the helper. Remote/headless WSL must validate Windows logon context and interop availability. If it needs independent unattended operation, evaluate the Linux system-service policy with actual systemd/hardware capabilities; do not assume the Windows TPM is exposed to the distro. Until that choice is made, report retrieval blocked rather than persist a plaintext fallback.

## Plaintext handoff and proposed policy

The proposed helper reads protected storage and launches `bws` with a **child-process-only** `BWS_ACCESS_TOKEN`, never a persistent user environment variable, shell profile, checked-in file, or token-bearing command argument. The current CLI exposes no token-file/stdin input in its inspected schema. A systemd credential file or pipe is therefore not a direct substitute for the CLI token input. An SDK integration could avoid an environment handoff but would add implementation and still hold plaintext in process memory. [CLI inputs](https://github.com/bitwarden/sdk-sm/blob/ba3e6a09d52a12954ef39c06b93587afb657b020/crates/bws/src/cli.rs)

A private child environment reduces persistence and inheritance; it does not prevent privileged inspection, permitted same-user inspection, crashes, logging mistakes, or theft by the recipient. Avoid global exports, shell tracing, token logging, and indiscriminate child inheritance. systemd explicitly warns against putting secrets in unit environment settings; injecting a private environment inside the helper avoids storing the token in those settings but still exposes it to `bws`. Retrieved application secrets also need controlled output/delivery. [systemd environment warning](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#Environment=)

Proposed first-release defaults, subject to interview decisions:

- **Windows:** local persistent generic credential under the enrolled user; retrieve during that user's usable logon context.
- **Linux desktop:** one selected Secret Service provider, password-backed unlock at login or first use; block secret-dependent work while locked.
- **Headless server:** system-service encrypted credential for explicitly required unattended retrieval; TPM plus host key where supported and recoverable, otherwise acknowledge host-key-only limits or use attended delivery.
- **WSL:** attended Windows-helper retrieval with separate host scope; no claim of native Linux keychain integration.
- **All hosts:** initial human enrollment, narrow provider permissions, protected state outside managed configuration, retained provider recovery access, and no plaintext-storage fallback. Availability of credentials does not grant permission to apply changes.

These are implementation proposals, not integrations already present in this repository. For hosts needing secrets only during attended application, delivery from an authorized management checkout remains simpler than enrolling a store token on every target.

## Decisions for the interview

1. Which hosts need independent retrieval before any human login, and which only during explicit attended application or SSH management?
2. Is the same-user compromise boundary acceptable, including an unlocked desktop or WSL process reaching a Windows helper? If not, what operations must require fresh human approval?
3. Which desktop provider and login methods must work across the actual Wayland sessions? Must unattended desktop SSH work after a cold boot?
4. For servers without usable TPM2, is host-key-only protection plus existing disk protection acceptable, or should retrieval require attended delivery? What boot-update and hardware-loss recovery is acceptable?
5. Should WSL retrieval run in Windows and deliver selected values, or must Linux retrieve independently? Must it work without a usable Windows user logon context?
6. If Bitwarden is selected, what machine-account/project boundaries, token expiry, replacement procedure, and recovery authority are required? Enrollment should not depend on the sole recovery credential being inside the store it unlocks.
