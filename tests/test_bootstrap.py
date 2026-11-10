"""Exercise downloaded scripts using a local Git fixture, never the real store."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="envstore-bootstrap-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.log = self.root / "invocation.json"
        (self.source / "env.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "reply = None\n"
            "if os.environ.get('BOOTSTRAP_PROMPT'):\n"
            "    reply = input('BOOTSTRAP-READY: ')\n"
            "Path(os.environ['BOOTSTRAP_LOG']).write_text(json.dumps({'args':sys.argv[1:], 'tty':sys.stdin.isatty(), 'reply':reply}))\n"
        )
        shutil.copy(ROOT / "setup.sh", self.source / "setup.sh")
        shutil.copy(ROOT / "setup.ps1", self.source / "setup.ps1")
        for arguments in [
            ["init", "--initial-branch=main", str(self.source)],
            ["-C", str(self.source), "add", "."],
            [
                "-C",
                str(self.source),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-m",
                "Fixture",
            ],
        ]:
            subprocess.run(["git", *arguments], check=True, capture_output=True)
        self.destination = self.root / "fresh checkout"
        self.environment = dict(
            os.environ,
            DOTFILES_REPOSITORY=self.source.as_posix(),
            DOTFILES_DIRECTORY=str(self.destination),
            DOTFILES_REF="main",
            BOOTSTRAP_LOG=str(self.log),
            LOCALAPPDATA=str(self.root / "local"),
        )
        (self.root / "local").mkdir()

    def bash_pipe(self, environment=None):
        return subprocess.run(
            ["bash", "-c", 'cat "$1" | bash', "bootstrap-test", str(ROOT / "setup.sh")],
            cwd=self.root,
            env=environment or self.environment,
            capture_output=True,
            timeout=30,
        )

    @unittest.skipIf(os.name == "nt", "Bash bootstrap runs on Linux")
    def test_bash_pipe_clones_and_preserves_existing_work(self):
        result = self.bash_pipe()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(json.loads(self.log.read_text())["args"], ["setup"])
        (self.destination / "local-edit").write_text("preserve me")
        self.log.unlink()
        result = self.bash_pipe()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual((self.destination / "local-edit").read_text(), "preserve me")
        self.assertTrue(self.log.exists())

    @unittest.skipIf(os.name == "nt", "Bash bootstrap runs on Linux")
    def test_bash_pipe_refuses_unrelated_existing_directory(self):
        self.destination.mkdir()
        (self.destination / "keep").write_text("keep")
        result = self.bash_pipe()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertEqual((self.destination / "keep").read_text(), "keep")

    def assert_terminal_setup(self, command):
        environment = {**self.environment, "BOOTSTRAP_PROMPT": "1"}
        import pty

        pid, terminal = pty.fork()
        if pid == 0:
            os.chdir(self.root)
            os.execvpe(command[0], command, environment)
        output = b""
        status = None
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if select.select([terminal], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(terminal, 4096)
                    except OSError:
                        break
                    output += chunk
                    if b"BOOTSTRAP-READY:" in output:
                        os.write(terminal, b"authorized\n")
                        output = b""
                ended, value = os.waitpid(pid, os.WNOHANG)
                if ended:
                    status = value
                    break
            if status is None:
                ended, value = os.waitpid(pid, os.WNOHANG)
                if ended:
                    status = value
                else:
                    os.kill(pid, 9)
                    _, status = os.waitpid(pid, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0, output.decode(errors="replace"))
            invocation = json.loads(self.log.read_text())
            self.assertTrue(invocation["tty"])
            self.assertEqual(invocation["reply"], "authorized")
        finally:
            os.close(terminal)

    @unittest.skipIf(os.name == "nt", "Terminal harness uses a Unix PTY")
    def test_bash_pipe_returns_prompts_to_controlling_terminal(self):
        self.assert_terminal_setup(
            ["bash", "-c", 'cat "$1" | bash', "test", str(ROOT / "setup.sh")]
        )

    @unittest.skipIf(os.name == "nt", "Terminal harness uses a Unix PTY")
    def test_powershell_pipe_preserves_interactive_setup_input(self):
        executable = shutil.which("pwsh")
        if not executable:
            self.skipTest("PowerShell is not available")
        self.environment["BOOTSTRAP_SCRIPT"] = str(ROOT / "setup.ps1")
        self.assert_terminal_setup(
            [
                executable,
                "-NoProfile",
                "-Command",
                "function winget {}; Get-Content -Raw -LiteralPath $env:BOOTSTRAP_SCRIPT | Invoke-Expression",
            ]
        )

    @unittest.skipIf(os.name == "nt", "Bash bootstrap runs on Linux")
    def test_bash_bootstraps_missing_runtimes_without_touching_system(self):
        binaries = self.root / "bootstrap-bin"
        binaries.mkdir()
        for command in ["bash", "cat", "dirname", "mkdir"]:
            (binaries / command).symlink_to(shutil.which(command, path="/usr/bin:/bin"))
        python = shutil.which("python3", path="/usr/bin:/bin")
        installer = binaries / "apt-get"
        installer.write_text(
            "#!" + python + "\n"
            "import pathlib, sys\n"
            "if 'install' in sys.argv:\n"
            + f"    pathlib.Path({str(binaries / 'python3')!r}).symlink_to({python!r})\n"
            + f"    pathlib.Path({str(binaries / 'git')!r}).symlink_to({shutil.which('git')!r})\n"
        )
        installer.chmod(0o700)
        sudo = binaries / "sudo"
        sudo.write_text('#!/bin/sh\nexec "$@"\n')
        sudo.chmod(0o700)
        result = self.bash_pipe(
            {**self.environment, "PATH": str(binaries), "DOTFILES_BOOTSTRAP_YES": "1"}
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue(self.log.exists())

    @unittest.skipIf(os.name == "nt", "Bash bootstrap runs on Linux")
    def test_local_bash_entry_preserves_arguments_without_cloning(self):
        result = subprocess.run(
            ["bash", str(self.source / "setup.sh"), "--host", "fixture", "--yes"],
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(
            json.loads(self.log.read_text())["args"], ["setup", "--host", "fixture", "--yes"]
        )
        self.assertFalse(self.destination.exists())

    def powershell_pipe(self):
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if not executable:
            self.skipTest("PowerShell is not available")
        # Read from an environment path so shell quoting cannot substitute data.
        environment = dict(self.environment, BOOTSTRAP_SCRIPT=str(ROOT / "setup.ps1"))
        return subprocess.run(
            [
                executable,
                "-NoProfile",
                "-Command",
                "function winget {} ; try { Get-Content -Raw -LiteralPath $env:BOOTSTRAP_SCRIPT | Invoke-Expression; Write-Output 'SESSION-ALIVE' } catch { Write-Error $_; exit 1 }",
            ],
            cwd=self.root,
            env=environment,
            capture_output=True,
            timeout=30,
        )

    def test_powershell_iex_clones_without_local_dependencies_or_exiting_session(self):
        result = self.powershell_pipe()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(b"SESSION-ALIVE", result.stdout)
        invocation = json.loads(self.log.read_text())
        self.assertIn("setup", invocation["args"])
        self.assertTrue((self.destination / ".git").is_dir())
        (self.destination / "local-edit").write_text("preserve me")
        result = self.powershell_pipe()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual((self.destination / "local-edit").read_text(), "preserve me")

    def test_powershell_iex_refuses_unrelated_existing_directory(self):
        self.destination.mkdir()
        (self.destination / "keep").write_text("keep")
        result = self.powershell_pipe()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertEqual((self.destination / "keep").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
