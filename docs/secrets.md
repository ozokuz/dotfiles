# Secrets and recovery

The private repository is a separate ciphertext store, not a management server.
Each host has its own age identity. SOPS recipient access is at file granularity:
put secrets with different authorized hosts in different files. An extra JSON key
inside the same file is not a separate access boundary.

## Create the store once

Create a host definition first, using setup or one of the examples. Initialize a
local secrets checkout and an encrypted recovery identity outside both repositories:

```sh
./env --host my-host secrets-init \
  --directory ../dotfiles-secrets \
  --backup /path/to/separate-backup/recovery.age
```

Age asks for the backup passphrase through the terminal. The private identity is
never printed or written as a raw file by this command. Keep the encrypted backup,
its password, and GitHub account recovery access independently available. Do not
keep the only copy on a managed host. This is a key backup; also retain separately
protected copies of the private ciphertext repository and configuration repository.

Create a **private** repository on GitHub explicitly. Review the generated local
store, commit only encrypted data and nonsecret metadata, set its remote, and push.
These external actions are not performed by `secrets-init`.

Configure the host's `secrets.repository` with a credential-free GitHub URL. Use
`secrets-publish` to record a committed, published secrets revision rather than
editing commit hashes manually:

```sh
./env --host my-host secrets-publish ../dotfiles-secrets
```

The command rejects tracked unencrypted data files, pushes the ciphertext commit
first, then updates the host reference. Commit the changed host definition in the
configuration repository. If the push fails, its reference is unchanged. If the
configuration update fails after the push, rerun publication; the ciphertext is
already available. This is coordinated ordering, not an atomic transaction across
two repositories.

## Add secret references

Copy and adapt `examples/secret-tool.json` into the catalog. Select it as `config`
or attach secret files to an installed tool. A reference names a SOPS-encrypted
file and optionally a dot-separated string key. `{host}` in the encrypted filename
is replaced with the selected host identifier. Without `key`, the decrypted file
is provisioned as bytes. Do not interpolate secrets into ordinary templates.

Store the corresponding encrypted data in the private repository. SOPS can edit
using an authorized identity, including a recovery identity retrieved through
`SOPS_AGE_KEY_CMD`. Do not decrypt it into the configuration checkout or paste
values into terminal commands. Add authorized recipients when creating new files;
existing enrollment only grants access to the explicitly named files.

## Enroll a host

Interactive setup enrolls an identity when selected configuration requires secrets.
It asks for the independent recovery identity, including an age-encrypted backup.
Passwords are read by age from the terminal. For an explicit enrollment:

```sh
./env --host my-host enroll --backend secret-service \
  --recovery-file /path/to/recovery.age \
  --secrets-checkout ../dotfiles-secrets \
  --secret-file hosts/my-host.json \
  --secret-file shared/application.json
```

The checkout must be separate and clean. This creates a host identity if needed,
then rotates the named files' data keys while adding that host and retaining the
existing recipients. Interrupted enrollment preserves the generated identity;
rerun with the same state after resolving the reported issue. Review and commit
the encrypted changes, then run `secrets-publish`. Interactive setup performs this
recipient commit/publication automatically as part of the explicitly started
human enrollment. It never stages unrelated source-repository work.

Backend choices:

- `dpapi`: Windows user-scoped protection. Remote or scheduled logon contexts must
  be verified; this does not promise access from every SSH session.
- `secret-service`: Linux `secret-tool` and an unlocked Secret Service provider.
  Use one provider across desktop sessions. Locked/unavailable keyrings block
  retrieval. The tool does not modify PAM or remove keyring passwords.
- `systemd`: explicitly chosen on owned Linux hosts. Uses `systemd-creds` with the
  host key and requires authorized sudo for encryption/decryption. This is **not
  TPM sealing**, and does not promise unattended retrieval after sudo expires.
  A machine with no usable unattended store can use attended retrieval instead.
- `passphrase`: explicitly chosen age-encrypted identity with terminal unlock.
  Useful for headless/user-only hosts; no plaintext fallback or persistent global
  environment variable is used.

WSL is a separate Linux host. It uses its own configured mechanism; it does not
silently inherit the Windows identity or credential store. A Windows bridge can
be added explicitly later. The encrypted/passphrase backend is available without
assuming a graphical keyring exists.

GitHub authentication is separate. Use your established protected Git credential
helper or a repository-scoped SSH/deploy key. This tool does not store GitHub
passwords. Public age recipients are safe to track; private identities are not.

## Recovery and rotation

1. Obtain the independently retained configuration/ciphertext backups and GitHub
   recovery access. Recover repository access first.
2. Use the encrypted recovery identity and its password to authorize a replacement
   host identity. You do not need any previous host to be online.
3. Re-enroll selected secret files, publish their new revision, and commit the
   configuration reference. Run setup on the replacement host.
4. For a compromised host, remove its age recipient using SOPS, rotate the affected
   files' data keys, and rotate actual application credentials at their issuers.
   Revoke its GitHub/SSH access separately. Apply the new revision explicitly to
   remaining hosts; offline hosts notify when they can check again.

Removing an age recipient cannot retract old plaintext or old encrypted Git
history that a formerly authorized identity can decrypt. Rotating ciphertext alone
does not rotate an API token at its issuer. Do not erase known-working local
credentials merely because a store is unavailable.

Protected local state contains engine caches, identity metadata/encrypted blobs,
file fingerprints, and configuration backups. Unix permissions and Windows ACLs
restrict it to the current user. Plaintext application files and backups remain
restricted local files when the application requires them; key protection is not
isolation from an already authorized or compromised same-user process.
