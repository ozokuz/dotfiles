"""Encrypted repository snapshots and host identities; plaintext never enters Git."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .core import (
    Context,
    StoreError,
    inside,
    load,
    mkdir_private,
    private,
    run,
    write_json,
)


def git_revision(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise StoreError("Secrets revision must be a full Git commit SHA")
    return value


def snapshot(ctx: Context) -> Path:
    settings = ctx.host.get("secrets")
    if not settings:
        raise StoreError("This host has no secrets repository configured")
    revision = git_revision(settings["revision"])
    url = settings["repository"]
    if not (url.startswith("git@github.com:") or url.startswith("https://github.com/")):
        raise StoreError(
            "Use a credential-free GitHub repository URL; authentication belongs in Git's credential helper"
        )
    if "@" in url.removeprefix("git@") or "?" in url or "#" in url:
        raise StoreError("Secrets repository URL must not contain credentials or query parameters")
    directory = ctx.state / "secrets" / ctx.host_id
    fresh = not (directory / ".git").exists()
    if fresh:
        mkdir_private(directory.parent)
        run(["git", "clone", "--no-checkout", "--", url, str(directory)], sensitive=True)
        private(directory, directory=True)
    origin = (
        run(["git", "-C", str(directory), "config", "--get", "remote.origin.url"]).decode().strip()
    )
    if origin != url:
        raise StoreError("Secrets checkout belongs to a different repository")
    if not fresh and run(["git", "-C", str(directory), "status", "--porcelain"]):
        raise StoreError(
            "Secrets checkout has pending changes; finish or recover enrollment before fetching"
        )
    import subprocess

    available = subprocess.run(
        ["git", "-C", str(directory), "cat-file", "-e", revision + "^{commit}"],
        capture_output=True,
        check=False,
    )
    if available.returncode:
        run(["git", "-C", str(directory), "fetch", "--quiet", "origin", revision], sensitive=True)
    run(["git", "-C", str(directory), "checkout", "--detach", "--force", revision], sensitive=True)
    return directory


def key_info(ctx: Context) -> dict:
    return load(ctx.state / "keys" / f"{ctx.host_id}.json")


def key(ctx: Context, deps: dict[str, str]) -> bytes:
    info = key_info(ctx)
    backend = info["backend"]
    if backend == "secret-service":
        return run(
            ["secret-tool", "lookup", "application", "envstore", "host", ctx.host_id],
            sensitive=True,
        ).strip()
    if backend == "dpapi":
        return run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ctx.repo / "adapters" / "key-store.ps1"),
                "-Action",
                "get",
                "-Path",
                info["path"],
            ],
            sensitive=True,
        ).strip()
    if backend == "systemd":
        if ctx.host.get("scope") != "owned":
            raise StoreError("System credential access is excluded on user-only hosts")
        return run(
            ["sudo", "-n", "systemd-creds", "decrypt", "--name=" + ctx.host_id, info["path"], "-"],
            sensitive=True,
        ).strip()
    if backend == "passphrase":
        return run([deps["age"], "--decrypt", info["path"]], sensitive=True).strip()
    raise StoreError("Unsupported protected-key backend")


def store_key(ctx: Context, deps: dict[str, str], identity: bytes, backend: str) -> dict:
    identities = [line for line in identity.splitlines() if line.startswith(b"AGE-SECRET-KEY-")]
    if len(identities) != 1:
        raise StoreError("Expected one generated age identity")
    identity = identities[0]
    directory = ctx.state / "keys"
    mkdir_private(directory)
    if backend == "secret-service":
        run(
            [
                "secret-tool",
                "store",
                "--label",
                f"Environment store: {ctx.host_id}",
                "application",
                "envstore",
                "host",
                ctx.host_id,
            ],
            data=identity,
            sensitive=True,
        )
        info = {"backend": backend}
    elif backend == "dpapi":
        if os.name != "nt":
            raise StoreError("DPAPI requires Windows")
        path = directory / f"{ctx.host_id}.dpapi"
        run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ctx.repo / "adapters" / "key-store.ps1"),
                "-Action",
                "set",
                "-Path",
                str(path),
            ],
            data=identity,
            sensitive=True,
        )
        private(path)
        info = {"backend": backend, "path": str(path)}
    elif backend == "systemd":
        if ctx.host.get("scope") != "owned":
            raise StoreError("System credential enrollment is excluded on user-only hosts")
        path = directory / f"{ctx.host_id}.cred"
        # Explicit host-key-only encryption; never claim this is TPM sealed.
        content = run(
            [
                "sudo",
                "-n",
                "systemd-creds",
                "encrypt",
                "--with-key=host",
                "--name=" + ctx.host_id,
                "-",
                "-",
            ],
            data=identity,
            sensitive=True,
        )
        path.write_bytes(content)
        private(path)
        info = {"backend": backend, "path": str(path)}
    elif backend == "passphrase":
        path = directory / f"{ctx.host_id}.age"
        # age obtains the passphrase from the controlling terminal, not argv or env.
        content = run([deps["age"], "--passphrase", "--encrypt"], data=identity, sensitive=True)
        path.write_bytes(content)
        private(path)
        info = {"backend": backend, "path": str(path)}
    else:
        raise StoreError("Choose secret-service, dpapi, systemd, or passphrase")
    public = run([deps["age-keygen"], "-y"], data=identity, sensitive=True).decode().strip()
    info["recipient"] = public
    write_json(directory / f"{ctx.host_id}.json", info)
    return info


def decrypt(ctx: Context, deps: dict[str, str], root: Path, relative: str) -> bytes:
    path = inside(root, relative)
    if not path.is_file() or path.is_symlink():
        raise StoreError("Secret reference is missing or is a symbolic link")
    environment = dict(os.environ)
    for name in ["SOPS_AGE_KEY_FILE", "SOPS_AGE_KEY_CMD"]:
        environment.pop(name, None)
    environment["SOPS_AGE_KEY_FILE"] = os.devnull
    environment["SOPS_AGE_KEY"] = key(ctx, deps).decode()
    return run([deps["sops"], "--decrypt", str(path)], env=environment, sensitive=True)


def recovery_identity(path: Path, deps: dict[str, str]) -> bytes:
    content = path.read_bytes()
    if content.startswith(b"age-encryption.org/v1") or content.startswith(
        b"-----BEGIN AGE ENCRYPTED FILE-----"
    ):
        return run([deps["age"], "--decrypt", str(path)], sensitive=True)
    return content


def initialize(ctx: Context, deps: dict[str, str], directory: Path, backup: Path) -> str:
    directory, backup = directory.resolve(), backup.resolve()
    if directory.exists() or backup.exists():
        raise StoreError("Secrets directory and recovery backup must not already exist")
    if (
        directory.is_relative_to(ctx.repo)
        or ctx.repo.is_relative_to(directory)
        or backup.is_relative_to(ctx.repo)
        or backup.is_relative_to(directory)
    ):
        raise StoreError(
            "Keep secrets checkout and independent recovery backup outside the configuration repository and separate from each other"
        )
    identity = run([deps["age-keygen"]], sensitive=True)
    recipient = run([deps["age-keygen"], "-y"], data=identity, sensitive=True).decode().strip()
    encrypted = run([deps["age"], "--passphrase", "--encrypt"], data=identity, sensitive=True)
    mkdir_private(backup.parent)
    backup.write_bytes(encrypted)
    private(backup)
    mkdir_private(directory)
    run(["git", "init", "--initial-branch=main", str(directory)])
    (directory / ".sops.yaml").write_text(
        "creation_rules:\n  - path_regex: .*\\.json$\n    age: " + recipient + "\n"
    )
    (directory / "shared").mkdir()
    content = run(
        [deps["sops"], "encrypt", "--age", recipient, "--filename-override", "bootstrap.json"],
        data=b'{"setup":"Replace with your machine secrets"}',
        sensitive=True,
    )
    (directory / "shared" / "bootstrap.json").write_bytes(content)
    (directory / "README.md").write_text(
        "# Encrypted machine secrets\n\nOnly SOPS-encrypted values belong here. Keep recovery identities and passwords outside both repositories.\n"
    )
    return recipient


def enroll(
    ctx: Context,
    deps: dict[str, str],
    backend: str,
    recovery_file: Path | None,
    checkout: Path | None,
    files: list[str],
    recovery_recipient: str | None,
) -> str:
    metadata = ctx.state / "keys" / f"{ctx.host_id}.json"
    if recovery_file and not recovery_file.is_file():
        raise StoreError("Recovery identity file is missing")
    if metadata.exists():
        info = key_info(ctx)
    else:
        identity = run([deps["age-keygen"]], sensitive=True)
        info = store_key(ctx, deps, identity, backend)
    public = info["recipient"]
    # Only encrypted files in a separate, clean checkout can be re-keyed.
    if checkout:
        checkout = checkout.resolve()
        if checkout.is_relative_to(ctx.repo) or ctx.repo.is_relative_to(checkout):
            raise StoreError("Secrets checkout must be separate from the configuration repository")
        if run(["git", "-C", str(checkout), "status", "--porcelain"]):
            raise StoreError("Secrets checkout must be clean before enrollment")
        if not recovery_file or not files:
            raise StoreError(
                "Recipient enrollment requires recovery identity, public recovery recipient, and explicit secret files"
            )
        environment = dict(os.environ)
        recovery = recovery_identity(recovery_file, deps)
        if not recovery_recipient:
            recovery_recipient = (
                run([deps["age-keygen"], "-y"], data=recovery, sensitive=True).decode().strip()
            )
        environment["SOPS_AGE_KEY_FILE"] = os.devnull
        environment.pop("SOPS_AGE_KEY_CMD", None)
        environment["SOPS_AGE_KEY"] = recovery.decode()
        for relative in files:
            path = inside(checkout, relative)
            if path.is_symlink():
                raise StoreError("Refuse to re-key symbolic links")
            # Add only this host and recovery recipient; preserve all existing recipients.
            run(
                [
                    deps["sops"],
                    "--rotate",
                    "--in-place",
                    "--add-age",
                    f"{public},{recovery_recipient}",
                    str(path),
                ],
                env=environment,
                sensitive=True,
            )
    return public


def publish(ctx: Context, checkout: Path, deps: dict[str, str]) -> str:
    """Push ciphertext first, then update the host reference; never stage user work."""
    settings = ctx.host.get("secrets", {})
    checkout = checkout.resolve()
    if checkout.is_relative_to(ctx.repo) or ctx.repo.is_relative_to(checkout):
        raise StoreError("Secrets checkout must be separate")
    if run(["git", "-C", str(checkout), "status", "--porcelain"]):
        raise StoreError(
            "Commit the reviewed encrypted changes in the secrets checkout before publishing"
        )
    origin = (
        run(["git", "-C", str(checkout), "config", "--get", "remote.origin.url"]).decode().strip()
    )
    if origin != settings.get("repository"):
        raise StoreError("Secrets repository does not match this host definition")
    revision = run(["git", "-C", str(checkout), "rev-parse", "HEAD"]).decode().strip()
    branch = settings.get("branch", "main")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_/-]*", branch) or ".." in branch:
        raise StoreError("Invalid secrets branch")
    paths = run(["git", "-C", str(checkout), "ls-files", "-z"]).decode().split("\0")
    for relative in filter(None, paths):
        if relative in {"README.md", ".sops.yaml", ".gitignore"}:
            continue
        import json

        status = json.loads(
            run([deps["sops"], "filestatus", str(inside(checkout, relative))], sensitive=True)
        )
        if not status.get("encrypted"):
            raise StoreError(
                "Secrets publication blocked: a tracked data file is not SOPS encrypted"
            )
    run(["git", "-C", str(checkout), "push", "origin", "HEAD:refs/heads/" + branch], sensitive=True)
    ctx.host["secrets"]["revision"] = git_revision(revision)
    write_json(ctx.repo / "hosts" / f"{ctx.host_id}.json", ctx.host)
    return revision
