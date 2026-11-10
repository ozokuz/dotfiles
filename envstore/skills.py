"""Materialize explicitly selected local or commit-pinned skill files."""

from __future__ import annotations

import io
import re
import tarfile
from pathlib import Path

from .core import Context, StoreError, inside, mkdir_private, run


def local_files(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise StoreError("Skill sources must not contain symbolic links")
        if path.is_file():
            result.append(path)
    if not (root / "SKILL.md").is_file():
        raise StoreError("Skill source needs a SKILL.md")
    return result


def materialize(ctx: Context, tools: list[dict]) -> list[dict]:
    result = []
    for tool in tools:
        skill = tool.get("skill")
        if not skill:
            result.append(tool)
            continue
        if skill.get("repository"):
            revision = skill.get("revision", "")
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise StoreError("Third-party skills require a full pinned commit SHA")
            url = skill["repository"]
            if not url.startswith("https://github.com/") or "@" in url or "?" in url:
                raise StoreError("Use a credential-free GitHub HTTPS skill source")
            root = ctx.state / "skills" / tool["id"] / revision
            if not root.exists():
                mkdir_private(root.parent)
                checkout = root.parent / "git"
                if not (checkout / ".git").exists():
                    run(["git", "clone", "--no-checkout", "--", url, str(checkout)])
                if (
                    run(["git", "-C", str(checkout), "remote", "get-url", "origin"])
                    .decode()
                    .strip()
                    != url
                ):
                    raise StoreError(
                        "Skill cache belongs to a different source; remove its cache before switching"
                    )
                run(["git", "-C", str(checkout), "fetch", "--quiet", "origin", revision])
                content = run(["git", "-C", str(checkout), "archive", revision])
                # Create only regular files; never extract archives across trust boundaries.
                mkdir_private(root)
                try:
                    with tarfile.open(fileobj=io.BytesIO(content)) as archive:
                        for member in archive.getmembers():
                            target = inside(root, member.name)
                            if member.isdir():
                                target.mkdir(parents=True, exist_ok=True)
                            elif member.isfile():
                                target.parent.mkdir(parents=True, exist_ok=True)
                                stream = archive.extractfile(member)
                                if stream is not None:
                                    target.write_bytes(stream.read())
                                    target.chmod(0o700 if member.mode & 0o111 else 0o600)
                            else:
                                raise StoreError("Skill archive contains links or special files")
                except Exception:
                    import shutil

                    shutil.rmtree(root)
                    raise
            source = inside(root, skill.get("source", "."))
        else:
            source = inside(ctx.repo, skill["source"])
        generated = list(tool.get("files", []))
        for path in local_files(source):
            for target in skill["targets"]:
                relative = str(Path(target) / path.relative_to(source)).replace("\\", "/")
                inside(ctx.home, relative)
                generated.append(
                    {
                        "target": relative,
                        "_source": str(path),
                        "template": False,
                        "executable": bool(path.stat().st_mode & 0o111),
                    }
                )
        result.append({**tool, "files": generated})
    targets = [f["target"] for t in result for f in t.get("files", [])]
    if ctx.platform == "windows":
        targets = [target.casefold() for target in targets]
    if len(targets) != len(set(targets)):
        raise StoreError("Selected skills/configurations overlap target files")
    return result
