"""Repository data, selection resolution, and private per-host state."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class StoreError(Exception):
    pass


def run(
    args: list[str],
    *,
    data: bytes | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    sensitive: bool = False,
    timeout: float | None = None,
) -> bytes:
    try:
        result = subprocess.run(
            args,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise StoreError(f"{Path(args[0]).name} timed out") from None
    except OSError as exc:
        raise StoreError(f"Cannot run {args[0]}: {exc.strerror}") from None
    if result.returncode:
        detail = (
            "protected operation failed; check authentication and unlock state"
            if sensitive
            else result.stderr.decode(errors="replace").strip()
        )
        raise StoreError(f"{Path(args[0]).name} failed ({result.returncode}): {detail}")
    return result.stdout


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreError(f"Cannot read {path}: {exc}") from None
    if not isinstance(value, dict):
        raise StoreError(f"Expected an object in {path}")
    return value


def private(path: Path, directory: bool = False) -> None:
    if os.name == "nt":
        sid = (
            run(["whoami", "/user", "/fo", "csv", "/nh"]).decode().strip().split(",")[-1].strip('"')
        )
        grant = f"{sid}:{'(OI)(CI)' if directory else ''}F"
        run(["icacls", str(path), "/inheritance:r", "/grant:r", grant], sensitive=True)
    else:
        path.chmod(0o700 if directory else 0o600)


def mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    private(path, directory=True)


def write_json(path: Path, value: dict) -> None:
    mkdir_private(path.parent)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        private(Path(name))
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", value):
        raise StoreError(f"Invalid identifier: {value!r}")
    return value


def inside(root: Path, relative: str) -> Path:
    path = Path(relative)
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in relative
        or ":" in relative
    ):
        raise StoreError(f"Expected a relative path: {relative!r}")
    destination = root / path
    if not destination.resolve().is_relative_to(root.resolve()):
        raise StoreError(f"Path escapes its root: {relative}")
    return destination


def native_platform() -> str:
    if os.name == "nt":
        return "windows"
    if platform.system() != "Linux":
        raise StoreError("Supported systems: Linux and Windows")
    info = platform.freedesktop_os_release()
    names = {info.get("ID", ""), *info.get("ID_LIKE", "").split()}
    if names & {"arch", "cachyos"}:
        return "arch"
    if names & {"debian", "ubuntu"}:
        return "debian"
    raise StoreError("This Linux distribution is not supported")


@dataclass
class Context:
    repo: Path
    home: Path
    state: Path
    host_id: str
    host: dict
    platform: str
    system_items: frozenset[str] = frozenset()

    def system_authorized(self, tool: str, allow_system: bool) -> bool:
        return tool in self.system_items or (self.host.get("scope") == "owned" and allow_system)

    @property
    def record_path(self) -> Path:
        return self.state / "hosts" / f"{self.host_id}.json"

    def record(self) -> dict:
        if not self.record_path.exists():
            return {"files": {}, "packages": {}, "exceptions": []}
        result = load(self.record_path)
        if result.get("home", str(self.home)) != str(self.home):
            raise StoreError("State belongs to a different home directory")
        return result

    def save(self, value: dict) -> None:
        value["home"] = str(self.home)
        write_json(self.record_path, value)

    @contextlib.contextmanager
    def lock(self):
        mkdir_private(self.state)
        path = self.state / "operation.lock"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise StoreError(
                f"Another operation holds {path}; remove only after confirming it has exited"
            ) from None
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(str(os.getpid()))
            yield
        finally:
            path.unlink(missing_ok=True)


def resolve(ctx: Context) -> tuple[list[dict], dict, str]:
    host = ctx.host
    if host.get("scope", "user") not in {"user", "owned"}:
        raise StoreError("Host scope must be user or owned")
    if host.get("platform") != ctx.platform:
        raise StoreError("Host platform does not match the selected platform")
    selected: dict[str, str] = {}
    for bundle_id in host.get("bundles", []):
        bundle = load(ctx.repo / "bundles" / f"{identifier(bundle_id)}.json")
        if "bundles" in bundle:
            raise StoreError("Bundles cannot contain other bundles")
        for name in bundle.get("tools", []):
            selected[identifier(name)] = "install"
    for name, mode in host.get("tools", {}).items():
        if mode not in {"install", "config", "off"}:
            raise StoreError(f"Invalid selection for {name}: {mode}")
        selected[identifier(name)] = mode
    tools = []
    owners: dict[str, str] = {}
    resources: dict[str, str] = {}
    for name, mode in sorted(selected.items()):
        if mode == "off":
            continue
        tool = load(ctx.repo / "catalog" / f"{name}.json")
        variant = tool.get("platforms", {}).get(ctx.platform)
        if variant is None:
            raise StoreError(f"{name} is unsupported on {ctx.platform}")
        tool = {**tool, **variant, "id": name, "mode": mode}
        if name in host.get("package_overrides", {}):
            tool["package"] = host["package_overrides"][name]
        for resource in tool.get("exclusive", []):
            if resource in resources:
                raise StoreError(f"{name} and {resources[resource]} conflict on {resource}")
            resources[resource] = name
        configs = tool.get("files", [])
        for file in configs:
            target = file["target"]
            if Path(target).as_posix() != target or target in {".", ""}:
                raise StoreError("Managed file paths must be normalized relative paths")
            inside(ctx.home, target)
            ownership = target.casefold() if ctx.platform == "windows" else target
            if ownership in owners:
                raise StoreError(f"{name} and {owners[ownership]} both manage {target}")
            owners[ownership] = name
        if tool.get("skill") and not tool["skill"].get("repository"):
            from .skills import local_files

            skill_root = inside(ctx.repo, tool["skill"]["source"])
            tool["_skill_hashes"] = {
                str(p.relative_to(skill_root)): digest(p.read_bytes())
                for p in local_files(skill_root)
            }
        tools.append(tool)
    data = load(ctx.repo / "settings" / "shared.json")
    data.update(load(ctx.repo / "settings" / "platform" / f"{ctx.platform}.json"))
    data.update(host.get("settings", {}))
    data.update({"host": ctx.host_id, "platform": ctx.platform})
    setting_keys = {"host", "platform"}
    for tool in tools:
        setting_keys.update(tool.get("settings_keys", []))
    data = {key: value for key, value in data.items() if key in setting_keys}
    # Hash resolved inputs, not the repository HEAD, so unrelated changes do not notify.
    relevant = {"host": host, "tools": tools, "data": data, "secrets": host.get("secrets", {})}
    sources = {}
    for tool in tools:
        for file in tool.get("files", []):
            source = host.get("overrides", {}).get(file["target"], file.get("source"))
            if source:
                sources[source] = digest(inside(ctx.repo, source).read_bytes())
        for action in tool.get("actions", []):
            if action.get("kind") not in {"service"}:
                raise StoreError(f"Unsupported system action in {tool['id']}")
    relevant["sources"] = sources
    relevant["runtime"] = {
        str(p.relative_to(ctx.repo)): digest(p.read_bytes())
        for p in sorted((ctx.repo / "envstore").glob("*.py"))
    }
    system = "windows" if ctx.platform == "windows" else "linux"
    architecture = {"x86_64": "amd64", "AMD64": "amd64", "aarch64": "arm64", "ARM64": "arm64"}.get(
        platform.machine(), platform.machine()
    )
    relevant["dependencies"] = {
        name: {
            "version": entry["version"],
            "asset": entry["assets"].get(f"{system}-{architecture}"),
        }
        for name, entry in load(ctx.repo / "dependencies.json").items()
    }
    return tools, data, digest(json.dumps(relevant, sort_keys=True).encode())
