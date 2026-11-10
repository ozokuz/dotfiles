from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envstore import cli, deps, files, operations, packages, secrets, skills
from envstore.core import Context, StoreError, load, resolve, run, write_json

ROOT = Path(__file__).resolve().parents[1]


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = tempfile.TemporaryDirectory(prefix="envstore-tools-")
        ctx = Context(
            ROOT,
            Path(cls.cache.name) / "home",
            Path(cls.cache.name) / "state",
            "test",
            {},
            "debian",
        )
        cls.binaries = deps.ensure(ctx)

    @classmethod
    def tearDownClass(cls):
        cls.cache.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="envstore-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for directory in ["catalog", "bundles", "settings", "templates", "envstore"]:
            shutil.copytree(
                ROOT / directory,
                self.repo / directory,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        shutil.copy(ROOT / "dependencies.json", self.repo / "dependencies.json")
        (self.repo / "hosts").mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.host = {
            "platform": "debian",
            "scope": "user",
            "tools": {"git": "config"},
            "settings": {"git_name": "Test User", "git_email": "test@example.invalid"},
        }
        self.ctx = Context(self.repo, self.home, self.root / "state", "test", self.host, "debian")
        self.ctx.state.mkdir(mode=0o700)
        self.save_host()

    def save_host(self):
        write_json(self.repo / "hosts/test.json", self.host)

    def resolved(self):
        return resolve(self.ctx)

    def apply(self, restore=frozenset()):
        tools, data, _ = self.resolved()
        return files.apply(self.ctx, self.binaries, tools, data, set(), set(restore))

    def test_render_apply_conflict_capture_and_exception(self):
        tools, data, _ = self.resolved()
        self.assertEqual(
            files.file_plan(self.ctx, self.binaries, tools, data)[0]["status"], "create"
        )
        self.assertEqual(self.apply(), [])
        target = self.home / ".gitconfig"
        self.assertIn("Test User", target.read_text())
        target.write_text("[user]\n name = local\n")
        self.assertEqual(
            files.file_plan(self.ctx, self.binaries, tools, data)[0]["status"], "conflict"
        )
        self.assertTrue(self.apply())
        self.assertIn("local", target.read_text())
        files.exception(self.ctx, ".gitconfig", True)
        self.assertEqual(self.apply(), [])
        self.assertIn("local", target.read_text())
        files.capture(self.ctx, ".gitconfig", "host")
        self.assertEqual(self.apply(), [])
        self.assertIn("local", target.read_text())
        self.assertEqual(self.ctx.record()["exceptions"], [])
        self.assertTrue((self.repo / "overrides/test/.gitconfig").is_file())

    def test_first_adoption_conflicts_and_explicit_restore_backs_up(self):
        (self.home / ".gitconfig").write_text("previous config")
        self.assertTrue(self.apply())
        self.assertEqual(self.apply({".gitconfig"}), [])
        backups = list((self.ctx.state / "backups").rglob(".gitconfig"))
        self.assertEqual(backups[0].read_text(), "previous config")

    def test_relevant_digest_ignores_other_hosts_but_tracks_templates(self):
        first = self.resolved()[2]
        write_json(self.repo / "hosts/other.json", {"settings": {"git_name": "Other"}})
        self.assertEqual(first, self.resolved()[2])
        settings = load(self.repo / "settings/shared.json")
        settings["unrelated_tool_setting"] = "irrelevant"
        write_json(self.repo / "settings/shared.json", settings)
        self.assertEqual(first, self.resolved()[2])
        with (self.repo / "templates/git.tmpl").open("a") as stream:
            stream.write("# new shared setting\n")
        self.assertNotEqual(first, self.resolved()[2])

    def test_platform_and_host_precedence(self):
        ctx = Context(
            self.repo,
            self.home,
            self.ctx.state,
            "test",
            {**self.host, "platform": "windows"},
            "windows",
        )
        self.assertEqual(resolve(ctx)[1]["git_credential_helper"], "manager")
        ctx.host["settings"]["git_credential_helper"] = "custom"
        self.assertEqual(resolve(ctx)[1]["git_credential_helper"], "custom")

    def test_explicit_selection_overrides_bundle_and_nested_bundles_fail(self):
        self.host["bundles"] = ["cli"]
        self.host["tools"]["jq"] = "off"
        self.assertEqual([t["id"] for t in self.resolved()[0]], ["git", "ripgrep"])
        write_json(self.repo / "bundles/cli.json", {"bundles": ["other"]})
        with self.assertRaises(StoreError):
            self.resolved()

    def test_duplicate_file_ownership_and_unsupported_tools_fail(self):
        write_json(self.repo / "catalog/duplicate.json", load(self.repo / "catalog/git.json"))
        self.host["tools"]["duplicate"] = "config"
        with self.assertRaises(StoreError):
            self.resolved()
        self.host["tools"] = {"missing": "install"}
        with self.assertRaises(StoreError):
            self.resolved()

    def test_shared_server_never_uses_sudo_for_packages(self):
        self.host["tools"]["git"] = "install"
        with (
            patch("envstore.packages.installed", return_value=False),
            patch("envstore.packages.run") as command,
        ):
            failed, errors = packages.install(self.ctx, self.resolved()[0], True)
        self.assertEqual(failed, {"git"})
        self.assertTrue(errors)
        command.assert_not_called()

    def test_cleanup_does_not_remove_unselected_dependents(self):
        self.ctx.system_items = frozenset({"git"})
        record = self.ctx.record()
        record["packages"]["git"] = {"provider": "apt", "id": "git"}
        self.ctx.save(record)
        with patch(
            "envstore.packages.run", return_value=b"Remv git [1]\nRemv unrelated-app [1]\n"
        ) as command:
            with self.assertRaises(StoreError):
                packages.cleanup(self.ctx, [], ["git"], False)
        self.assertEqual(command.call_count, 1)
        self.assertIn("git", self.ctx.record()["packages"])

    def test_named_system_exception_does_not_grant_other_tools(self):
        self.ctx.system_items = frozenset({"git"})
        system = {"provider": "apt", "id": "git"}
        self.assertTrue(packages.allowed(self.ctx, system, False, "git"))
        self.assertFalse(packages.allowed(self.ctx, system, True, "other"))

    def test_symlink_escape_does_not_write(self):
        outside = self.root / "outside"
        outside.write_text("keep")
        try:
            (self.home / ".gitconfig").symlink_to(outside)
        except OSError:
            self.skipTest("Symlinks unavailable in this Windows logon context")
        with self.assertRaises(StoreError):
            self.resolved()
        self.assertEqual(outside.read_text(), "keep")

    def test_fetch_check_compares_new_revision_without_checkout_or_apply(self):
        remote = self.root / "remote.git"
        run(["git", "init", "--bare", str(remote)])
        run(["git", "init", "--initial-branch=main", str(self.repo)])
        run(["git", "-C", str(self.repo), "config", "user.name", "Fixture"])
        run(["git", "-C", str(self.repo), "config", "user.email", "fixture@example.invalid"])
        run(["git", "-C", str(self.repo), "remote", "add", "origin", str(remote)])
        run(["git", "-C", str(self.repo), "add", "."])
        run(["git", "-C", str(self.repo), "commit", "-m", "Initial"])
        first = run(["git", "-C", str(self.repo), "rev-parse", "HEAD"]).decode().strip()
        record = self.ctx.record()
        record["applied"] = self.resolved()[2]
        self.ctx.save(record)
        original = (self.repo / "templates/git.tmpl").read_bytes()
        (self.repo / "templates/git.tmpl").write_bytes(original + b"# changed upstream\n")
        run(["git", "-C", str(self.repo), "add", "."])
        run(["git", "-C", str(self.repo), "commit", "-m", "Update"])
        run(["git", "-C", str(self.repo), "push", "origin", "main"])
        run(["git", "-C", str(self.repo), "checkout", "--detach", first])
        self.assertTrue(operations.check(self.ctx, True, False)["outdated"])
        self.assertEqual((self.repo / "templates/git.tmpl").read_bytes(), original)
        self.assertFalse((self.home / ".gitconfig").exists())

    def test_notification_deduplicates_without_apply(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            first = operations.check(self.ctx, False, True)
            operations.check(self.ctx, False, True)
        self.assertTrue(first["outdated"])
        self.assertEqual(output.getvalue().count("out of date"), 1)
        self.assertFalse((self.home / ".gitconfig").exists())

    def test_secret_plan_never_decrypts_and_apply_never_leaks(self):
        write_json(
            self.repo / "catalog/secret.json",
            {
                "platforms": {"debian": {}},
                "files": [
                    {
                        "target": ".private-token",
                        "secret": {"file": "hosts/test.json", "key": "token"},
                    }
                ],
            },
        )
        self.host["tools"] = {"secret": "config"}
        self.host["secrets"] = {
            "repository": "git@github.com:example/private.git",
            "revision": "a" * 40,
        }
        tools, data, _ = self.resolved()
        with patch("envstore.secrets.decrypt") as decrypt:
            plan = files.file_plan(self.ctx, self.binaries, tools, data)
        decrypt.assert_not_called()
        self.assertEqual(plan[0]["status"], "blocked-enrollment")
        encrypted = self.root / "encrypted"
        encrypted.mkdir()
        with (
            patch("envstore.secrets.snapshot", return_value=encrypted),
            patch("envstore.secrets.decrypt", return_value=b'{"token":"never-print-this"}'),
        ):
            self.assertEqual(self.apply(), [])
        self.assertEqual((self.home / ".private-token").read_text(), "never-print-this")
        self.assertNotIn("never-print-this", self.ctx.record_path.read_text())
        with self.assertRaises(StoreError):
            files.capture(self.ctx, ".private-token", "host")

    def test_partial_apply_preserves_independent_progress(self):
        git = load(self.repo / "catalog/git.json")
        git["files"].append({"target": ".missing", "source": "templates/nonexistent.tmpl"})
        write_json(self.repo / "catalog/git.json", git)
        # Detect missing source before any mutation.
        with self.assertRaises(FileNotFoundError):
            self.resolved()
        git["files"].pop()
        git["files"].append({"target": ".conflict", "source": "templates/git.tmpl"})
        write_json(self.repo / "catalog/git.json", git)
        (self.home / ".conflict").write_text("local")
        self.assertTrue(self.apply())
        self.assertTrue((self.home / ".gitconfig").exists())
        self.assertIn(".gitconfig", self.ctx.record()["files"])
        self.assertNotIn("applied", self.ctx.record())

    def test_cli_configuration_only_setup_and_safe_cleanup(self):
        args = [
            "--repo",
            str(self.repo),
            "--host",
            "test",
            "--home",
            str(self.home),
            "--state",
            str(self.ctx.state),
        ]
        with (
            patch("envstore.cli.native_platform", return_value="debian"),
            patch("envstore.deps.ensure", return_value=self.binaries),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main([*args, "setup", "--yes", "--no-notifications"]), 0)
            self.assertFalse(operations.check(self.ctx, False, False)["outdated"])
            self.host["tools"] = {}
            self.save_host()
            self.assertEqual(cli.main([*args, "cleanup", "--file", ".gitconfig", "--yes"]), 0)
            self.assertFalse((self.home / ".gitconfig").exists())

    def test_remote_uses_committed_revision_and_safe_command(self):
        self.host["remote"] = {
            "address": "test@example.invalid",
            "checkout": "/home/test/config store",
        }
        outputs = [b"", b"a" * 40, b"ok"]
        with patch("envstore.operations.run", side_effect=outputs) as command:
            self.assertEqual(operations.remote(self.ctx, "plan", False, False), b"ok")
        invoked = command.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", invoked)
        self.assertIn("'/home/test/config store/env.py'", invoked[-1])
        self.assertIn("--expected-revision", invoked[-1])

    def test_literal_filenames_and_empty_files_are_not_engine_actions(self):
        source = self.repo / "templates" / "literal.txt"
        source.write_text("{{ this must remain literal }}")
        tool = load(self.repo / "catalog" / "git.json")
        tool["files"] = [
            {"target": "run_payload.sh", "source": "templates/literal.txt", "template": False},
            {
                "target": "nested/private_directory/secret.tmpl",
                "source": "templates/literal.txt",
                "template": False,
            },
        ]
        write_json(self.repo / "catalog" / "git.json", tool)
        self.assertEqual(self.apply(), [])
        self.assertEqual((self.home / "run_payload.sh").read_text(), source.read_text())
        self.assertEqual(
            (self.home / "nested/private_directory/secret.tmpl").read_text(), source.read_text()
        )
        source.write_bytes(b"")
        self.assertEqual(self.apply(), [])
        self.assertTrue((self.home / "run_payload.sh").is_file())
        self.assertEqual((self.home / "run_payload.sh").read_bytes(), b"")

    def test_local_skill_deployment_and_source_change_detection(self):
        source = self.repo / "agent-skills" / "example"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("---\nname: example\n---\nTest fixture only.\n")
        (source / "helper.sh").write_text("#!/bin/sh\nexit 0\n")
        (source / "helper.sh").chmod(0o700)
        write_json(
            self.repo / "catalog" / "example-skill.json",
            {
                "platforms": {"debian": {}},
                "skill": {"source": "agent-skills/example", "targets": [".agents/skills/example"]},
            },
        )
        self.host["tools"] = {"example-skill": "config"}
        tools, data, initial = self.resolved()
        expanded = skills.materialize(self.ctx, tools)
        self.assertEqual(files.apply(self.ctx, self.binaries, expanded, data, set(), set()), [])
        self.assertEqual(
            (self.home / ".agents/skills/example/SKILL.md").read_bytes(),
            (source / "SKILL.md").read_bytes(),
        )
        if os.name != "nt":
            self.assertTrue(os.access(self.home / ".agents/skills/example/helper.sh", os.X_OK))
        (source / "SKILL.md").write_text("Changed fixture")
        self.assertNotEqual(initial, self.resolved()[2])

    def test_secret_recipient_enrollment_is_scoped_and_resumable(self):
        checkout = self.root / "private-secrets"
        run(["git", "init", "--initial-branch=main", str(checkout)])
        recovery = run([self.binaries["age-keygen"]], sensitive=True)
        public = (
            run([self.binaries["age-keygen"], "-y"], data=recovery, sensitive=True).decode().strip()
        )
        recovery_path = self.root / "fixture-recovery.txt"
        recovery_path.write_bytes(recovery)
        ciphertext = run(
            [self.binaries["sops"], "encrypt", "--age", public, "--filename-override", "host.json"],
            data=b'{"token":"scoped-fixture"}',
            sensitive=True,
        )
        (checkout / "allowed.json").write_bytes(ciphertext)
        (checkout / "other.json").write_bytes(ciphertext)
        run(["git", "-C", str(checkout), "add", "."])
        run(
            [
                "git",
                "-C",
                str(checkout),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-m",
                "Fixture",
            ]
        )
        saved = {}

        def store(ctx, binaries, identity, backend):
            saved["identity"] = identity
            recipient = (
                run([binaries["age-keygen"], "-y"], data=identity, sensitive=True).decode().strip()
            )
            info = {"backend": "fixture", "recipient": recipient}
            write_json(ctx.state / "keys" / f"{ctx.host_id}.json", info)
            return info

        with patch("envstore.secrets.store_key", side_effect=store):
            enrolled = secrets.enroll(
                self.ctx, self.binaries, "fixture", recovery_path, checkout, ["allowed.json"], None
            )
        self.assertIn(enrolled, (checkout / "allowed.json").read_text())
        self.assertNotIn(enrolled, (checkout / "other.json").read_text())
        environment = dict(
            os.environ, SOPS_AGE_KEY=saved["identity"].decode(), SOPS_AGE_KEY_FILE=os.devnull
        )
        result = run(
            [self.binaries["sops"], "--decrypt", str(checkout / "allowed.json")],
            env=environment,
            sensitive=True,
        )
        self.assertEqual(json.loads(result)["token"], "scoped-fixture")
        with self.assertRaises(StoreError):
            run(
                [self.binaries["sops"], "--decrypt", str(checkout / "other.json")],
                env=environment,
                sensitive=True,
            )

    def test_publish_pushes_secrets_before_updating_reference(self):
        checkout = self.root / "ciphertext"
        checkout.mkdir()
        self.host["secrets"] = {
            "repository": "git@github.com:fixture/private.git",
            "revision": "a" * 40,
        }
        responses = [
            b"",
            b"git@github.com:fixture/private.git\n",
            b"b" * 40,
            b"allowed.json\0",
            b'{"encrypted":true}',
            b"",
        ]
        with patch("envstore.secrets.run", side_effect=responses) as command:
            self.assertEqual(secrets.publish(self.ctx, checkout, self.binaries), "b" * 40)
        self.assertEqual(self.host["secrets"]["revision"], "b" * 40)
        self.assertIn("HEAD:refs/heads/main", command.call_args.args[0])
        self.host["secrets"]["revision"] = "a" * 40
        with patch(
            "envstore.secrets.run", side_effect=[*responses[:-1], StoreError("push failed")]
        ):
            with self.assertRaises(StoreError):
                secrets.publish(self.ctx, checkout, self.binaries)
        self.assertEqual(self.host["secrets"]["revision"], "a" * 40)

    def test_remote_windows_does_not_require_local_platform_match(self):
        self.host["platform"] = "windows"
        self.save_host()
        with (
            patch("envstore.operations.remote", return_value=b"ok") as remote,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                cli.main(["--repo", str(self.repo), "--host", "test", "remote", "plan"]), 0
            )
        self.assertEqual(remote.call_args.args[0].platform, "windows")

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI requires Windows")
    def test_windows_dpapi_roundtrip(self):
        shutil.copytree(ROOT / "adapters", self.repo / "adapters")
        identity = run([self.binaries["age-keygen"]], sensitive=True)
        secrets.store_key(self.ctx, self.binaries, identity, "dpapi")
        expected = next(
            line for line in identity.splitlines() if line.startswith(b"AGE-SECRET-KEY-")
        )
        self.assertEqual(secrets.key(self.ctx, self.binaries).strip(), expected)
        self.assertNotIn(identity.strip(), (self.ctx.state / "keys/test.dpapi").read_bytes())

    def test_age_identity_and_real_sops_roundtrip(self):
        identity = run([self.binaries["age-keygen"]], sensitive=True)
        recipient = (
            run([self.binaries["age-keygen"], "-y"], data=identity, sensitive=True).decode().strip()
        )
        plain = self.root / "test.json"
        plain.write_text('{"token":"test-fixture-value"}')
        ciphertext = run(
            [self.binaries["sops"], "--encrypt", "--age", recipient, str(plain)], sensitive=True
        )
        self.assertNotIn(b"test-fixture-value", ciphertext)
        encrypted = self.root / "test.enc.json"
        encrypted.write_bytes(ciphertext)
        environment = dict(os.environ, SOPS_AGE_KEY=identity.decode())
        value = run(
            [self.binaries["sops"], "--decrypt", str(encrypted)], env=environment, sensitive=True
        )
        self.assertEqual(json.loads(value)["token"], "test-fixture-value")


if __name__ == "__main__":
    unittest.main()
