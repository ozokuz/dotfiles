"""Install pinned upstream tools into private application state, never system PATH."""

from __future__ import annotations

import hashlib
import io
import os
import platform
import tarfile
import urllib.request
import zipfile

from .core import Context, StoreError, load, mkdir_private


def ensure(ctx: Context) -> dict[str, str]:
    manifest = load(ctx.repo / "dependencies.json")
    system = "windows" if os.name == "nt" else "linux"
    architecture = {"x86_64": "amd64", "AMD64": "amd64", "aarch64": "arm64", "ARM64": "arm64"}.get(
        platform.machine()
    )
    if architecture is None:
        raise StoreError("Unsupported CPU architecture")
    result = {}
    for name, versions in manifest.items():
        version = versions["version"]
        asset = versions["assets"].get(f"{system}-{architecture}")
        if asset is None:
            raise StoreError(f"No pinned {name} binary for {system}/{architecture}")
        directory = ctx.state / "bin" / f"{name}-{version}"
        binary = directory / (name + (".exe" if system == "windows" else ""))
        if not binary.exists():
            mkdir_private(directory)
            try:
                with urllib.request.urlopen(asset["url"], timeout=60) as response:
                    content = response.read()
                if hashlib.sha256(content).hexdigest() != asset["sha256"]:
                    raise StoreError(f"Checksum mismatch for {name}")
                member = asset.get("member")
                if member and asset["url"].endswith(".zip"):
                    content = zipfile.ZipFile(io.BytesIO(content)).read(member)
                elif member:
                    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                        stream = archive.extractfile(member)
                        if stream is None:
                            raise StoreError(f"Missing {name} archive member")
                        content = stream.read()
                temporary = binary.with_suffix(".download")
                temporary.write_bytes(content)
                temporary.chmod(0o700)
                os.replace(temporary, binary)
            except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
                raise StoreError(f"Cannot install pinned {name}: {exc}") from None
        result[name] = str(binary)
    return result
