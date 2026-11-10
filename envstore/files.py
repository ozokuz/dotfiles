"""Use chezmoi for rendering/application with explicit local-edit protection."""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

from . import secrets
from .core import Context, StoreError, digest, inside, mkdir_private, private, run


def fingerprint(ctx: Context, path: Path, secret: bool = False) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        return "unsupported-path"
    content = path.read_bytes()
    if secret:
        salt = ctx.state / "comparison.key"
        if not salt.exists():
            salt.write_bytes(os.urandom(32))
            private(salt)
        checksum = hmac.new(salt.read_bytes(), content, "sha256").hexdigest()
    else:
        checksum = digest(content)
    mode = stat.S_IMODE(path.stat().st_mode) if os.name != "nt" else 0
    return f"{checksum}:{mode}"


def source_name(target: str, executable: bool = False) -> Path:
    parts = Path(target).parts
    encoded = ["dot_" + part[1:] if part.startswith(".") else "literal_" + part for part in parts]
    # Escape every filename: a skill's run_*.sh or *.tmpl must never become code.
    encoded[-1] = (
        "private_empty_" + ("executable_" if executable else "") + encoded[-1] + ".literal"
    )
    return Path(*encoded)


@contextlib.contextmanager
def staged(
    ctx: Context,
    deps: dict[str, str],
    data: dict,
    file: dict,
    tool: str,
    *,
    secret_root: Path | None = None,
):
    target = file["target"]
    destination = inside(ctx.home, target)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=ctx.state) as temporary:
        root = Path(temporary)
        private(root, directory=True)
        source = root / "source"
        source.mkdir()
        source_file = source / source_name(target, file.get("executable", False))
        source_file.parent.mkdir(parents=True, exist_ok=True)
        override = ctx.host.get("overrides", {}).get(target)
        if file.get("secret"):
            if secret_root is None:
                raise StoreError("Secret snapshot is unavailable")
            reference = file["secret"]
            content = secrets.decrypt(
                ctx, deps, secret_root, reference["file"].replace("{host}", ctx.host_id)
            )
            if "key" in reference:
                value = json.loads(content)
                for part in reference["key"].split("."):
                    value = value[part]
                if not isinstance(value, str):
                    raise StoreError("Secret reference must resolve to a string")
                content = value.encode()
        elif override:
            content = inside(ctx.repo, override).read_bytes()
        else:
            content = (
                Path(file["_source"]).read_bytes()
                if file.get("_source")
                else inside(ctx.repo, file["source"]).read_bytes()
            )
            if file.get("template", True):
                source_file = source_file.with_name(source_file.name + ".tmpl")
        source_file.write_bytes(content)
        private(source_file)
        config = root / "config.json"
        config.write_text(json.dumps({"data": data}), encoding="utf-8")
        private(config)
        command = [
            deps["chezmoi"],
            "--config",
            str(config),
            "--source",
            str(source),
            "--destination",
            str(ctx.home),
            "--persistent-state",
            str(root / "state.boltdb"),
            "--cache",
            str(root / "cache"),
        ]
        # Rendering must not require or create destination directories during planning.
        rendered = (
            run([*command, "execute-template", "--file", str(source_file)])
            if source_file.name.endswith(".tmpl")
            else content
        )
        yield [*command, "apply", "--force", str(destination)], rendered, destination


def file_plan(ctx: Context, deps: dict[str, str], tools: list[dict], data: dict) -> list[dict]:
    record = ctx.record()
    result = []
    for tool in tools:
        for file in tool.get("files", []):
            target = file["target"]
            item = {"kind": "file", "tool": tool["id"], "target": target}
            if target in record["exceptions"]:
                result.append({**item, "status": "local-exception"})
                continue
            if file.get("secret"):
                # Do not decrypt, unlock, or expose values during planning.
                available = (
                    bool(ctx.host.get("secrets"))
                    and (ctx.state / "keys" / f"{ctx.host_id}.json").exists()
                )
                result.append(
                    {
                        **item,
                        "status": "protected-apply" if available else "blocked-enrollment",
                        "reference": file["secret"]["file"].replace("{host}", ctx.host_id),
                    }
                )
                continue
            with staged(ctx, deps, data, file, tool["id"]) as (_, desired, path):
                current = fingerprint(ctx, path)
                expected = digest(desired) + (
                    f":{0o700 if file.get('executable') else 0o600}" if os.name != "nt" else ":0"
                )
                baseline = record["files"].get(target, {}).get("fingerprint")
                status = (
                    "unchanged"
                    if current == expected
                    else "create"
                    if current is None
                    else "update"
                )
                if current is not None and current != expected and current != baseline:
                    status = "conflict"
                result.append({**item, "status": status})
    selected = {file["target"] for tool in tools for file in tool.get("files", [])}
    result.extend(
        {"kind": "file", "target": target, "status": "cleanup-candidate"}
        for target in record["files"]
        if target not in selected
    )
    return result


def apply(
    ctx: Context,
    deps: dict[str, str],
    tools: list[dict],
    data: dict,
    failed_tools: set[str],
    restore: set[str],
) -> list[str]:
    record = ctx.record()
    failures = []
    secret_root = None
    for tool in tools:
        if tool["id"] in failed_tools:
            continue
        for file in tool.get("files", []):
            target = file["target"]
            if target in record["exceptions"]:
                continue
            protected = bool(file.get("secret"))
            try:
                if protected and secret_root is None:
                    secret_root = secrets.snapshot(ctx)
                with staged(ctx, deps, data, file, tool["id"], secret_root=secret_root) as (
                    command,
                    desired,
                    path,
                ):
                    before = fingerprint(ctx, path, protected)
                    baseline = record["files"].get(target, {}).get("fingerprint")
                    # Compare desired without persisting plaintext or a public secret hash.
                    equal = (
                        path.is_file() and not path.is_symlink() and path.read_bytes() == desired
                    )
                    mode_ok = os.name == "nt" or (
                        path.is_file()
                        and stat.S_IMODE(path.stat().st_mode)
                        == (0o700 if file.get("executable") else 0o600)
                    )
                    if (
                        not (equal and mode_ok)
                        and before is not None
                        and before != baseline
                        and target not in restore
                    ):
                        raise StoreError(
                            f"{target}: local edits conflict; capture, keep-local, or explicitly restore it"
                        )
                    if before == "unsupported-path":
                        raise StoreError(
                            f"{target}: replace a symlink/directory only through an explicit migration"
                        )
                    if not (equal and mode_ok):
                        # Recheck before backup/application; do not knowingly overwrite a concurrent edit.
                        if fingerprint(ctx, path, protected) != before:
                            raise StoreError(f"{target}: changed during application")
                        if path.exists():
                            backup = ctx.state / "backups" / str(time.time_ns()) / target
                            mkdir_private(backup.parent)
                            shutil.copy2(path, backup)
                            private(backup)
                        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        run(command, sensitive=protected)
                    private(path)
                    if os.name != "nt" and file.get("executable"):
                        path.chmod(0o700)
                    record["files"][target] = {
                        "fingerprint": fingerprint(ctx, path, protected),
                        "tool": tool["id"],
                        "secret": protected,
                    }
                    ctx.save(record)
            except (StoreError, OSError, ValueError, KeyError) as exc:
                failures.append(f"{target}: protected operation failed" if protected else str(exc))
    return failures


def capture(ctx: Context, target: str, layer: str) -> None:
    record = ctx.record()
    if target not in record["files"]:
        raise StoreError("Only a previously managed file can be captured")
    if record["files"][target].get("secret"):
        raise StoreError("Never capture plaintext secrets into the configuration repository")
    source = inside(ctx.home, target)
    if source.is_symlink() or not source.is_file():
        raise StoreError("Capture requires a regular file")
    if layer == "host":
        relative = f"overrides/{ctx.host_id}/{target}"
        output = inside(ctx.repo, relative)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        ctx.host.setdefault("overrides", {})[target] = relative
        from .core import write_json

        write_json(ctx.repo / "hosts" / f"{ctx.host_id}.json", ctx.host)
    else:
        raise StoreError(
            "Capture defaults to host overrides; promote a reviewed override by editing shared/platform inputs explicitly"
        )
    record["exceptions"] = [p for p in record["exceptions"] if p != target]
    ctx.save(record)


def exception(ctx: Context, target: str, enable: bool) -> None:
    record = ctx.record()
    if target not in record["files"]:
        raise StoreError("Path has not been managed by this host")
    values = set(record["exceptions"])
    if enable:
        values.add(target)
    else:
        values.discard(target)
    record["exceptions"] = sorted(values)
    ctx.save(record)
