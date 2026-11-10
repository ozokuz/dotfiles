"""Remote invocation and notification-only checks reuse the host-local workflow."""

from __future__ import annotations

import base64
import io
import os
import re
import shlex
import tarfile
import tempfile
from pathlib import Path

from .core import Context, StoreError, load, resolve, run, write_json


def check(ctx: Context, fetch: bool, notify: bool) -> dict:
    tools, data, intended = resolve(ctx)
    if fetch:
        track = ctx.host.get("track", "main")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", track) or ".." in track:
            raise StoreError("Invalid tracking reference")
        environment = dict(
            os.environ,
            GIT_TERMINAL_PROMPT="0",
            GCM_INTERACTIVE="Never",
            GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5",
        )
        run(
            ["git", "-C", str(ctx.repo), "fetch", "--quiet", "origin", track],
            env=environment,
            timeout=15,
        )
        revision = run(["git", "-C", str(ctx.repo), "rev-parse", "FETCH_HEAD"]).decode().strip()
        archive = run(["git", "-C", str(ctx.repo), "archive", revision])
        with tempfile.TemporaryDirectory(prefix="envstore-check-") as directory:
            root = Path(directory)
            with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
                for member in stream.getmembers():
                    if not member.isfile() and not member.isdir():
                        raise StoreError("Tracking archive contains unsupported links")
                    if not (root / member.name).resolve().is_relative_to(root):
                        raise StoreError("Tracking archive escapes temporary checkout")
                for member in stream.getmembers():
                    target = root / member.name
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        content = stream.extractfile(member)
                        if content is not None:
                            target.write_bytes(content.read())
            candidate = Context(
                root,
                ctx.home,
                ctx.state,
                ctx.host_id,
                load(root / "hosts" / f"{ctx.host_id}.json"),
                ctx.platform,
            )
            _, _, intended = resolve(candidate)
    record = ctx.record()
    outdated = record.get("applied") != intended
    from .files import fingerprint

    local_changes = []
    for target, entry in record["files"].items():
        if target in record["exceptions"]:
            continue
        from .core import inside

        if (
            fingerprint(ctx, inside(ctx.home, target), entry.get("secret", False))
            != entry["fingerprint"]
        ):
            local_changes.append(target)
    result = {
        "local_changes": local_changes,
        "host": ctx.host_id,
        "outdated": outdated,
        "intended": intended,
        "applied": record.get("applied"),
        "exceptions": record["exceptions"],
    }
    notice_path = ctx.state / "hosts" / f"{ctx.host_id}.notice.json"
    previous = load(notice_path) if notice_path.exists() else {}
    if notify and outdated and previous.get("digest") != intended:
        message = f"{ctx.host_id}: environment configuration is out of date. Run env plan."
        if ctx.platform == "windows":
            try:
                run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
                        "$n = New-Object System.Windows.Forms.NotifyIcon; "
                        "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                        '$n.ShowBalloonTip(8000, "Environment configuration", "Configuration is out of date. Run env plan.", '
                        "[System.Windows.Forms.ToolTipIcon]::Info); Start-Sleep -Seconds 9; $n.Dispose()",
                    ]
                )
            except StoreError:
                print(message)
        elif os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            try:
                run(["notify-send", "Environment configuration", message])
            except StoreError:
                print(message)
        else:
            print(message)
        write_json(notice_path, {"digest": intended})
    if not outdated and notice_path.exists():
        notice_path.unlink()
    return result


def remote(ctx: Context, operation: str, allow_system: bool, yes: bool) -> bytes:
    if operation not in {"status", "plan", "apply", "install", "upgrade", "check", "sync"}:
        raise StoreError("Unsupported remote operation")
    if run(["git", "-C", str(ctx.repo), "status", "--porcelain"]):
        raise StoreError("Remote operations require a clean, committed configuration checkout")
    revision = run(["git", "-C", str(ctx.repo), "rev-parse", "HEAD"]).decode().strip()
    settings = ctx.host.get("remote", {})
    address = settings.get("address", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", address):
        raise StoreError("Set remote.address to an enrolled SSH destination")
    checkout = settings.get("checkout")
    if not isinstance(checkout, str) or not checkout:
        raise StoreError("Set remote.checkout to the enrolled checkout path")
    args = ["--host", ctx.host_id, "--expected-revision", revision, operation]
    if allow_system:
        args.append("--allow-system")
    if yes:
        args.append("--yes")
    for item in sorted(ctx.system_items):
        args.extend(["--allow-system-item", item])
    if operation == "sync" and not yes:
        raise StoreError("Remote checkout updates require explicit --yes")
    if ctx.platform == "windows":
        # SSH interprets a command string: encode PowerShell rather than concatenate user paths.
        def literal(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        script = (
            "& "
            + literal(str(Path(checkout) / "env.ps1"))
            + " "
            + " ".join(literal(v) for v in args)
            + "; exit $LASTEXITCODE"
        )
        if operation == "sync":
            root = literal(checkout)
            script = (
                "$ErrorActionPreference = 'Stop'; "
                f"$changes = & git -C {root} status --porcelain; "
                "if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Remote checkout must be clean' }; "
                f"& git -C {root} fetch origin {revision}; if ($LASTEXITCODE) {{ exit $LASTEXITCODE }}; "
                f"& git -C {root} checkout --detach {revision}; exit $LASTEXITCODE"
            )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand " + encoded
    else:
        command = shlex.join(["python3", str(Path(checkout) / "env.py"), *args])
        if operation == "sync":
            root = shlex.quote(checkout)
            command = (
                f'envstore_changes=$(git -C {root} status --porcelain) && test -z "$envstore_changes" && '
                f"git -C {root} fetch origin {revision} && "
                f"git -C {root} checkout --detach {revision}"
            )
    return run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=8",
            address,
            command,
        ]
    )
