"""Bounded native package/service actions, separate from configuration writes."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from .core import Context, StoreError, run


def validate(package: dict) -> None:
    if package.get("provider") not in {"apt", "pacman", "winget", "flatpak"}:
        raise StoreError("Supported providers: apt, pacman, winget, flatpak")
    if "version" in package:
        raise StoreError("Application version pins are not a supported catalog option yet")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", package["id"]):
        raise StoreError("Invalid package identifier")


def installed(package: dict) -> bool:
    validate(package)
    provider, name = package["provider"], package["id"]
    if provider == "apt":
        result = subprocess.run(["dpkg-query", "-W", "-f=${Status}", name], capture_output=True)
        if result.returncode not in {0, 1}:
            raise StoreError("Cannot query dpkg state")
        return result.returncode == 0 and result.stdout == b"install ok installed"
    if provider == "pacman":
        result = subprocess.run(["pacman", "-Q", name], capture_output=True)
        if result.returncode not in {0, 1}:
            raise StoreError("Cannot query pacman state")
        return result.returncode == 0
    if provider == "flatpak":
        result = subprocess.run(
            ["flatpak", "info", "--user", name], capture_output=True, check=False
        )
        if result.returncode not in {0, 1}:
            raise StoreError("Cannot query user Flatpak state")
        return result.returncode == 0
    result = subprocess.run(
        ["winget", "list", "--id", name, "--exact", "--disable-interactivity"], capture_output=True
    )
    if result.returncode == 0:
        return True
    if result.returncode & 0xFFFFFFFF == 0x8A150014:
        return False
    raise StoreError(
        "WinGet cannot query installed packages; initialize its sources in the enrolled user session"
    )


def identity(package: dict) -> tuple[str, str, str]:
    return package["provider"], package["id"], package.get("scope", "user")


def allowed(ctx: Context, package: dict, allow_system: bool, tool: str) -> bool:
    system = package["provider"] in {"apt", "pacman"} or package.get("scope", "user") != "user"
    return not system or ctx.system_authorized(tool, allow_system)


def elevation(args: list[str]) -> list[str]:
    return args if os.name != "nt" and os.geteuid() == 0 else ["sudo", "-n", *args]


def plan(ctx: Context, tools: list[dict], allow_system: bool) -> list[dict]:
    result = []
    for tool in sorted(tools, key=lambda t: t.get("package", {}).get("provider") == "flatpak"):
        package = tool.get("package")
        if tool["mode"] == "config" or not package:
            continue
        validate(package)
        if package["provider"] == "flatpak" and not shutil.which("flatpak"):
            result.append(
                {"kind": "package", "tool": tool["id"], "status": "requires-flatpak-provider"}
            )
            continue
        status = "installed" if installed(package) else "install"
        if status == "install" and not allowed(ctx, package, allow_system, tool["id"]):
            status = "blocked-system-authorization"
        entry = {"kind": "package", "tool": tool["id"], "package": package["id"], "status": status}
        if status == "install" and package["provider"] == "apt":
            simulation = run(
                [
                    "apt-get",
                    "--simulate",
                    "--no-install-recommends",
                    "--no-remove",
                    "--no-upgrade",
                    "install",
                    "--",
                    package["id"],
                ]
            ).decode()
            entry["transaction"] = [
                line for line in simulation.splitlines() if line.startswith(("Inst ", "Remv "))
            ]
        if status == "install" and package["provider"] == "pacman":
            entry["transaction"] = (
                run(["pacman", "-Sp", "--print-format", "%n %v", "--", package["id"]])
                .decode()
                .splitlines()
            )
            entry["notice"] = (
                "Uses current synchronized databases; no refresh or system upgrade. Stale databases can block installation."
            )
        result.append(entry)
    record = ctx.record()
    selected = {identity(t["package"]) for t in tools if t["mode"] == "install" and t.get("package")}
    result.extend(
        {"kind": "package", "tool": name, "package": value["id"], "status": "cleanup-candidate"}
        for name, value in record["packages"].items()
        if identity(value) not in selected
    )
    return result


def install(
    ctx: Context, tools: list[dict], allow_system: bool, *, upgrade: bool = False
) -> tuple[set[str], list[str]]:
    failed, failures = set(), []
    record = ctx.record()
    for tool in sorted(tools, key=lambda t: t.get("package", {}).get("provider") == "flatpak"):
        package = tool.get("package")
        if tool["mode"] == "config" or not package:
            continue
        try:
            validate(package)
            present = installed(package)
            if not present or upgrade:
                if not allowed(ctx, package, allow_system, tool["id"]):
                    raise StoreError("system package changes are not authorized for this host")
                provider, name = package["provider"], package["id"]
                if provider == "winget" and package.get("scope", "user") == "machine":
                    import ctypes

                    if not ctypes.windll.shell32.IsUserAnAdmin():
                        raise StoreError(
                            "Machine installation requires the enrolled user elevated once; run setup.ps1 -AllowSystem"
                        )
                if provider == "apt":
                    flags = [] if upgrade else ["--no-upgrade"]
                    run(
                        elevation(
                            [
                                "apt-get",
                                "install",
                                "-y",
                                "--no-install-recommends",
                                "--no-remove",
                                *flags,
                                "--",
                                name,
                            ]
                        )
                    )
                elif provider == "pacman":
                    if upgrade:
                        raise StoreError(
                            "Arch upgrades are host-wide; use the explicit system-upgrade operation"
                        )
                    run(elevation(["pacman", "-S", "--needed", "--noconfirm", "--", name]))
                elif provider == "flatpak":
                    remote = package.get("remote", "flathub")
                    if not re.fullmatch(r"[A-Za-z0-9_-]+", remote):
                        raise StoreError("Invalid Flatpak remote")
                    if package.get("remote_url"):
                        url = package["remote_url"]
                        if not url.startswith("https://") or "@" in url:
                            raise StoreError("Flatpak remote must use credential-free HTTPS")
                        run(["flatpak", "remote-add", "--user", "--if-not-exists", remote, url])
                    command = (
                        ["flatpak", "update", "--user", "-y", name]
                        if upgrade
                        else [
                            "flatpak",
                            "install",
                            "--user",
                            "--noninteractive",
                            "-y",
                            remote,
                            name,
                        ]
                    )
                    run(command)
                else:
                    command = [
                        "winget",
                        "upgrade" if upgrade else "install",
                        "--id",
                        name,
                        "--exact",
                        "--scope",
                        package.get("scope", "user"),
                        "--silent",
                        "--disable-interactivity",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ]
                    run(command)
            if not present:
                # Keep superseded packages available for explicit cleanup. Ownership
                # follows package identity, never an unrelated preinstalled mapping.
                previous = record["packages"].get(tool["id"])
                if previous and identity(previous) != identity(package):
                    archived = tool["id"] + ":" + ":".join(identity(previous))
                    record["packages"][archived] = {**previous, "tool": tool["id"]}
                record["packages"][tool["id"]] = package
                ctx.save(record)
        except (StoreError, OSError) as exc:
            failed.add(tool["id"])
            failures.append(f"{tool['id']}: {exc}")
    return failed, failures


def system_actions(
    ctx: Context, tools: list[dict], failed: set[str], allow_system: bool
) -> list[str]:
    failures = []
    for tool in tools:
        if tool["id"] in failed:
            continue
        for action in tool.get("actions", []):
            try:
                if not ctx.system_authorized(tool["id"], allow_system):
                    raise StoreError("system actions are not authorized")
                name = action["name"]
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", name):
                    raise StoreError("Invalid service name")
                state = action.get("state", "enabled")
                if state not in {"enabled", "disabled"}:
                    raise StoreError("Supported service states: enabled, disabled")
                if ctx.platform == "windows":
                    run(
                        [
                            "powershell.exe",
                            "-NoProfile",
                            "-Command",
                            f"Set-Service -Name '{name}' -StartupType {'Automatic' if state == 'enabled' else 'Disabled'}",
                        ]
                    )
                else:
                    run(
                        elevation(
                            ["systemctl", "enable" if state == "enabled" else "disable", name]
                        )
                    )
            except StoreError as exc:
                failures.append(f"{tool['id']} service: {exc}")
    return failures


def cleanup(ctx: Context, tools: list[dict], names: list[str], allow_system: bool) -> None:
    selected = {identity(t["package"]) for t in tools if t["mode"] == "install" and t.get("package")}
    record = ctx.record()
    for name in names:
        if name not in record["packages"] or identity(record["packages"][name]) in selected:
            raise StoreError(f"{name} is not a package cleanup candidate")
        package = record["packages"][name]
        if not allowed(ctx, package, allow_system, package.get("tool", name)):
            raise StoreError("Package removal is not authorized")
        provider, package_id = package["provider"], package["id"]
        if provider == "apt":
            simulation = run(["apt-get", "--simulate", "remove", "--", package_id]).decode()
            removed = {
                line.split()[1].split(":")[0]
                for line in simulation.splitlines()
                if line.startswith("Remv ")
            }
            if removed - {package_id}:
                raise StoreError(
                    "Removal would also remove other installed programs; review a separate removal plan"
                )
            command = elevation(["apt-get", "remove", "-y", "--", package_id])
        elif provider == "pacman":
            command = elevation(["pacman", "-R", "--noconfirm", "--", package_id])
        elif provider == "flatpak":
            command = ["flatpak", "uninstall", "--user", "-y", package_id]
        else:
            command = [
                "winget",
                "uninstall",
                "--id",
                package_id,
                "--exact",
                "--silent",
                "--disable-interactivity",
            ]
        run(command)
        del record["packages"][name]
        ctx.save(record)
