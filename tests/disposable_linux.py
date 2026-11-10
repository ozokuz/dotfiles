"""Run only inside a disposable Linux container; installs real packages there."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if os.environ.get("ENVSTORE_DISPOSABLE") != "1":
    raise SystemExit(
        "This integration test requires ENVSTORE_DISPOSABLE=1 in a disposable container"
    )
root = Path("/tmp/envstore-integration")
shutil.copytree("/workspace", root / "repo", ignore=shutil.ignore_patterns(".git", "__pycache__"))
repo = root / "repo"
sys.path.insert(0, str(repo))
core = __import__("envstore.core", fromlist=["native_platform"])

platform = core.native_platform()
host = {
    "platform": platform,
    "scope": "owned",
    "tools": {"git": "install", "jq": "install"},
    "settings": {"git_name": "Disposable Test", "git_email": "test@example.invalid"},
}
(repo / "hosts/integration.json").write_text(json.dumps(host))
home, state = root / "home", root / "state"
home.mkdir()
command = [
    sys.executable,
    str(repo / "env.py"),
    "--host",
    "integration",
    "--home",
    str(home),
    "--state",
    str(state),
]
for _ in range(2):
    subprocess.run([*command, "setup", "--yes", "--allow-system", "--no-notifications"], check=True)
subprocess.run(["git", "--version"], check=True)
subprocess.run(["jq", "--version"], check=True)
assert "Disposable Test" in (home / ".gitconfig").read_text()
record = json.loads((state / "hosts/integration.json").read_text())
assert record["applied"]
(home / ".gitconfig").write_text("[user]\n name = local edit\n")
assert subprocess.run([*command, "apply", "--yes"]).returncode != 0
subprocess.run([*command, "capture", ".gitconfig", "--yes"], check=True)
subprocess.run([*command, "apply", "--yes"], check=True)
assert "local edit" in (home / ".gitconfig").read_text()
print(f"Disposable {platform} package/configuration integration passed")
