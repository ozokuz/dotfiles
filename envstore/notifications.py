"""User-session notification scheduling; never applies configuration."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from .core import Context, StoreError, mkdir_private, private, run


def install(ctx: Context) -> None:
    if ctx.home != Path.home().resolve():
        raise StoreError(
            "Notification activation requires the actual user home; use --no-notifications in a sandbox"
        )
    if os.name == "nt":
        run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ctx.repo / "adapters" / "install-notifications.ps1"),
                "-Repo",
                str(ctx.repo),
                "-HostName",
                ctx.host_id,
                "-State",
                str(ctx.state),
            ]
        )
        return
    directory = ctx.home / ".config" / "systemd" / "user"
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(ctx.repo / "env.py"),
        "--host",
        ctx.host_id,
        "--state",
        str(ctx.state),
        "check",
        "--fetch",
        "--notify",
    ]
    # systemd performs specifier expansion independently of shell quoting.
    quoted = " ".join(
        '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"' for v in command
    )
    service = directory / "envstore-check.service"
    timer = directory / "envstore-check.timer"
    contents = {
        service: "[Unit]\nDescription=Check intended environment configuration\n[Service]\nType=oneshot\nExecStart="
        + quoted
        + "\n",
        timer: "[Unit]\nDescription=Check environment at login and periodically\n[Timer]\nOnStartupSec=30s\nOnUnitActiveSec=30min\nPersistent=true\n[Install]\nWantedBy=timers.target\n",
    }
    for path, content in contents.items():
        if path.exists() and path.read_text() != content:
            raise StoreError(f"{path}: existing notification unit differs; review before replacing")
        path.write_text(content)
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", "--now", "envstore-check.timer"])
    login = ctx.home / ".config" / "envstore" / "login.sh"
    mkdir_private(login.parent)
    text = (
        "# Source from your shell login file to get immediate reconnect notices.\n"
        + shlex.join(command)
        + "\n"
    )
    if login.exists() and login.read_text() != text:
        raise StoreError("Existing login notification hook differs; review before replacing")
    login.write_text(text)
    private(login)
