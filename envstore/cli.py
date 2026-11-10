"""Human and agent interface. Native actions are always explicit operations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from . import deps, files, notifications, operations, packages, secrets, skills
from .core import (
    Context,
    StoreError,
    identifier,
    inside,
    load,
    native_platform,
    resolve,
    run,
    write_json,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Repository-driven environment configuration")
    result.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    result.add_argument("--host", default=None)
    result.add_argument("--home", type=Path, default=Path.home())
    result.add_argument("--state", type=Path)
    result.add_argument(
        "--platform",
        choices=["arch", "debian", "windows"],
        help="Plan a different platform; never mutate it locally",
    )
    result.add_argument("--expected-revision", help=argparse.SUPPRESS)
    commands = result.add_subparsers(dest="command", required=True)
    for name in [
        "setup",
        "plan",
        "status",
        "apply",
        "install",
        "upgrade",
        "cleanup",
        "check",
        "enroll",
        "capture",
        "keep-local",
        "manage",
        "remote",
        "secrets-publish",
        "system-upgrade",
        "secrets-init",
        "fleet",
    ]:
        command = commands.add_parser(name)
        for flag, kind in [
            ("--repo", Path),
            ("--host", str),
            ("--home", Path),
            ("--state", Path),
            ("--platform", str),
        ]:
            command.add_argument(flag, type=kind, default=argparse.SUPPRESS)
        command.add_argument(
            "--yes", action="store_true", help="Approve this explicit operation without prompting"
        )
        command.add_argument(
            "--allow-system-item",
            action="append",
            default=[],
            metavar="TOOL",
            help="Explicitly authorize a named tool system action, including on a user-only host",
        )
        command.add_argument(
            "--allow-system", action="store_true", help="Authorize system changes on owned hosts"
        )
        if name == "setup":
            command.add_argument(
                "--no-notifications",
                action="store_true",
                help="Skip user-session scheduling, e.g. in a disposable test",
            )
        if name in {"setup", "apply"}:
            command.add_argument(
                "--restore",
                action="append",
                default=[],
                metavar="PATH",
                help="Explicitly restore a conflicting managed file",
            )
        if name in {"capture", "keep-local", "manage"}:
            command.add_argument("target")
        if name == "cleanup":
            command.add_argument("--package", action="append", default=[])
            command.add_argument("--file", action="append", default=[])
        if name == "enroll":
            command.add_argument(
                "--backend",
                choices=["secret-service", "dpapi", "systemd", "passphrase"],
                required=True,
            )
            command.add_argument("--recovery-file", type=Path)
            command.add_argument("--recovery-recipient")
            command.add_argument("--secrets-checkout", type=Path)
            command.add_argument("--secret-file", action="append", default=[])
        if name == "secrets-init":
            command.add_argument("--directory", type=Path, required=True)
            command.add_argument("--backup", type=Path, required=True)
        if name == "secrets-publish":
            command.add_argument("checkout", type=Path)
        if name == "check":
            command.add_argument("--fetch", action="store_true")
            command.add_argument("--notify", action="store_true")
        if name == "fleet":
            command.add_argument("--targets", nargs="+", required=True)
        if name in {"remote", "fleet"}:
            command.add_argument(
                "operation",
                choices=["plan", "status", "apply", "install", "upgrade", "check", "sync"],
            )
    return result


def approve(args, description: str) -> None:
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise StoreError("Noninteractive changes require --yes after reviewing env plan")
    if input(description + " [y/N] ").strip().lower() not in {"y", "yes"}:
        raise StoreError("Cancelled")


def create_host(args, platform: str) -> dict:
    if not sys.stdin.isatty():
        raise StoreError("Create a host definition before unattended setup")
    print("No host definition found. Create one; existing package lists are not used.")
    scope = (
        "owned"
        if input("Do you own this OS and want system management? [y/N] ").lower() in {"y", "yes"}
        else "user"
    )
    available = sorted(
        path.stem
        for path in (args.repo / "catalog").glob("*.json")
        if platform in load(path).get("platforms", {})
    )
    print("Available tools: " + ", ".join(available))
    selected = input("Tools (comma separated, e.g. git:config,jq:install; blank for none): ")
    tools = {}
    for choice in filter(None, (part.strip() for part in selected.split(","))):
        name, separator, mode = choice.partition(":")
        mode = mode if separator else "install"
        if mode not in {"install", "config", "off"}:
            raise StoreError("Tool mode must be install, config, or off")
        tools[identifier(name)] = mode
    host = {
        "platform": platform,
        "scope": scope,
        "bundles": [],
        "tools": tools,
        "settings": {},
        "overrides": {},
    }
    if "git" in tools:
        host["settings"] = {"git_name": input("Git name: "), "git_email": input("Git email: ")}
    secret_url = input("Private secrets repository URL (blank to configure later): ").strip()
    if secret_url:
        if not (
            secret_url.startswith("git@github.com:") or secret_url.startswith("https://github.com/")
        ):
            raise StoreError("Use a credential-free GitHub URL")
        revision = run(["git", "ls-remote", secret_url, "HEAD"], sensitive=True).decode().split()[0]
        host["secrets"] = {"repository": secret_url, "revision": secrets.git_revision(revision)}
    write_json(args.repo / "hosts" / f"{args.host}.json", host)
    return host


def show_plan(
    ctx: Context, binaries: dict[str, str], tools: list[dict], data: dict, allow_system: bool
) -> list[dict]:
    rows = (
        packages.plan(ctx, tools, allow_system)
        if ctx.platform == native_platform()
        else [
            {"kind": "package", "tool": tool["id"], "status": "requires-native-host"}
            for tool in tools
            if tool["mode"] == "install" and tool.get("package")
        ]
    )
    rows += files.file_plan(ctx, binaries, tools, data)
    for tool in tools:
        for action in tool.get("actions", []):
            rows.append(
                {
                    "kind": "system",
                    "tool": tool["id"],
                    "action": action,
                    "status": "apply"
                    if ctx.system_authorized(tool["id"], allow_system)
                    else "blocked-system-authorization",
                }
            )
    print(
        json.dumps(
            {"host": ctx.host_id, "scope": ctx.host.get("scope", "user"), "plan": rows}, indent=2
        )
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.repo = args.repo.resolve()
        if args.command == "fleet":
            failures = []
            for target in args.targets:
                invocation = [
                    "--repo",
                    str(args.repo),
                    "--host",
                    identifier(target),
                    "remote",
                    args.operation,
                ]
                if args.yes:
                    invocation.append("--yes")
                if args.allow_system:
                    invocation.append("--allow-system")
                for item in args.allow_system_item:
                    invocation.extend(["--allow-system-item", identifier(item)])
                if main(invocation):
                    failures.append(target)
            print(json.dumps({"failed_hosts": failures}, indent=2))
            return 1 if failures else 0
        args.home = args.home.resolve()
        if args.command == "setup" and not args.host and sys.stdin.isatty():
            known = ", ".join(sorted(path.stem for path in (args.repo / "hosts").glob("*.json")))
            print("Existing host definitions: " + known)
            args.host = input("Existing or new host name (blank uses this machine name): ").strip()
        args.host = identifier(args.host or socket.gethostname().split(".")[0])
        platform = args.platform or native_platform()
        host_path = args.repo / "hosts" / f"{args.host}.json"
        host = (
            load(host_path)
            if host_path.exists()
            else create_host(args, platform)
            if args.command == "setup"
            else None
        )
        if host is None:
            raise StoreError(
                f"Unknown host {args.host}; use setup or create hosts/{args.host}.json"
            )
        default_state = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            / "envstore"
            if os.name == "nt"
            else Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
            / "envstore"
        )
        state = (args.state or default_state).resolve()
        if state.is_relative_to(args.repo):
            raise StoreError("Private state must be outside the configuration repository")
        if args.command == "remote":
            platform = host["platform"]
        ctx = Context(
            args.repo,
            args.home,
            state,
            args.host,
            host,
            platform,
            frozenset(identifier(v) for v in args.allow_system_item),
        )
        if args.command == "remote":
            print(
                operations.remote(ctx, args.operation, args.allow_system, args.yes).decode(), end=""
            )
            return 0
        tools, data, intended = resolve(ctx)
        mutating = args.command not in {"plan", "status", "check", "remote"}
        if mutating and platform != native_platform():
            raise StoreError("Cannot mutate a host for a different platform")
        if args.expected_revision:
            revision = run(["git", "-C", str(ctx.repo), "rev-parse", "HEAD"]).decode().strip()
            if revision != args.expected_revision or run(
                ["git", "-C", str(ctx.repo), "status", "--porcelain"]
            ):
                raise StoreError(
                    "Remote checkout must be clean and match the requested committed revision"
                )
        if args.command in {"status", "check"}:
            with ctx.lock():
                status = operations.check(
                    ctx, getattr(args, "fetch", False), getattr(args, "notify", False)
                )
            if not getattr(args, "notify", False):
                print(json.dumps(status, indent=2))
            return 0
        with ctx.lock():
            binaries = deps.ensure(ctx)
            tools = skills.materialize(ctx, tools)
            if args.command == "plan":
                rows = show_plan(ctx, binaries, tools, data, args.allow_system)
                return (
                    2
                    if any(
                        row["status"]
                        in {"conflict", "blocked-enrollment", "blocked-system-authorization"}
                        for row in rows
                    )
                    else 0
                )
            if args.command == "setup":
                # Human enrollment precedes the final plan; do not ask for secrets through the CLI parser.
                if host.get("secrets") and not (state / "keys" / f"{args.host}.json").exists():
                    if not sys.stdin.isatty():
                        raise StoreError("Run enroll before unattended setup")
                    backend = (
                        "dpapi"
                        if os.name == "nt"
                        else "secret-service"
                        if shutil.which("secret-tool")
                        else "passphrase"
                    )
                    recovery = Path(
                        input(
                            "Path to independent recovery identity (encrypted backup is supported): "
                        )
                    ).expanduser()
                    root = secrets.snapshot(ctx)
                    selected_files = sorted(
                        {
                            f["secret"]["file"].replace("{host}", ctx.host_id)
                            for t in tools
                            for f in t.get("files", [])
                            if f.get("secret")
                        }
                    )
                    if selected_files:
                        secrets.enroll(ctx, binaries, backend, recovery, root, selected_files, None)
                        run(["git", "-C", str(root), "add", "--", *selected_files])
                        run(
                            [
                                "git",
                                "-C",
                                str(root),
                                "-c",
                                "user.name=Environment enrollment",
                                "-c",
                                "user.email=environment@localhost",
                                "commit",
                                "-m",
                                f"Enroll {ctx.host_id}",
                            ]
                        )
                        secrets.publish(ctx, root, binaries)
                        tools, data, intended = resolve(ctx)
                        tools = skills.materialize(ctx, tools)
                if host.get("scope") == "owned" and not args.allow_system and sys.stdin.isatty():
                    args.allow_system = input(
                        "Authorize system changes included in the setup plan? [y/N] "
                    ).lower() in {"y", "yes"}
                if os.name == "nt" and (args.allow_system or args.allow_system_item):
                    import ctypes

                    if not ctypes.windll.shell32.IsUserAnAdmin():
                        print("Continuing setup requires UAC authorization through setup.ps1.")
                        return 77
                if (
                    (args.allow_system or args.allow_system_item)
                    and os.name != "nt"
                    and os.geteuid() != 0
                ):
                    if subprocess.run(["sudo", "-v"], check=False).returncode:
                        raise StoreError("Administrator authentication was not completed")
                show_plan(ctx, binaries, tools, data, args.allow_system)
            if args.command in {"apply", "install", "upgrade"}:
                show_plan(ctx, binaries, tools, data, args.allow_system)
            approve(args, f"Proceed with {args.command} for {ctx.host_id}?")
            if args.command in {"setup", "apply", "install", "upgrade"}:
                failed, failures = (set(), [])
                if args.command in {"setup", "install", "upgrade"}:
                    failed, failures = packages.install(
                        ctx, tools, args.allow_system, upgrade=args.command == "upgrade"
                    )
                if args.command in {"setup", "apply"}:
                    # Config-only selections are intentionally independent of installation.
                    if args.command == "apply":
                        for tool in tools:
                            if (
                                tool["mode"] == "install"
                                and tool.get("package")
                                and not packages.installed(tool["package"])
                            ):
                                failed.add(tool["id"])
                                failures.append(f"{tool['id']}: install prerequisite is missing")
                    failures += files.apply(ctx, binaries, tools, data, failed, set(args.restore))
                    failures += packages.system_actions(ctx, tools, failed, args.allow_system)
                    if args.command == "setup" and not args.no_notifications:
                        try:
                            notifications.install(ctx)
                        except StoreError as exc:
                            failures.append(f"Notifications: {exc}")
                    if not failures:
                        record = ctx.record()
                        record["applied"] = intended
                        ctx.save(record)
                print(json.dumps({"host": args.host, "failures": failures}, indent=2))
                return 1 if failures else 0
            if args.command == "secrets-init":
                print(
                    "Recovery recipient: "
                    + secrets.initialize(ctx, binaries, args.directory, args.backup)
                )
                print(
                    "Commit only ciphertext; create/push the private GitHub repository explicitly. Keep the encrypted recovery backup separately."
                )
            elif args.command == "enroll":
                public = secrets.enroll(
                    ctx,
                    binaries,
                    args.backend,
                    args.recovery_file,
                    args.secrets_checkout,
                    args.secret_file,
                    args.recovery_recipient,
                )
                print(f"Enrolled public recipient: {public}")
            elif args.command == "secrets-publish":
                print(
                    "Published secrets revision: " + secrets.publish(ctx, args.checkout, binaries)
                )
            elif args.command == "capture":
                files.capture(ctx, args.target, "host")
            elif args.command in {"keep-local", "manage"}:
                files.exception(ctx, args.target, args.command == "keep-local")
            elif args.command == "system-upgrade":
                if host.get("scope") != "owned" or not args.allow_system:
                    raise StoreError("System upgrade requires an owned host and --allow-system")
                if platform == "arch":
                    run(packages.elevation(["pacman", "-Syu", "--noconfirm"]))
                elif platform == "debian":
                    run(packages.elevation(["apt-get", "update"]))
                    run(packages.elevation(["apt-get", "upgrade", "-y"]))
                else:
                    raise StoreError("Windows OS updates remain an explicit OS operation")
            elif args.command == "cleanup":
                record = ctx.record()
                selected = {f["target"] for t in tools for f in t.get("files", [])}
                for target in args.file:
                    if (
                        target in selected
                        or target not in record["files"]
                        or target in record["exceptions"]
                    ):
                        raise StoreError(f"{target} is not a file cleanup candidate")
                    path = inside(ctx.home, target)
                    entry = record["files"][target]
                    if (
                        files.fingerprint(ctx, path, entry.get("secret", False))
                        != entry["fingerprint"]
                    ):
                        raise StoreError(f"{target} changed locally; refusing cleanup")
                    path.unlink(missing_ok=True)
                    del record["files"][target]
                    ctx.save(record)
                packages.cleanup(ctx, tools, args.package, args.allow_system)
            return 0
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        return 130
    except (StoreError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
