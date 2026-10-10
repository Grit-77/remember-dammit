"""Read-only local installation inspection against real client files."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError
from remember_dammit.setup import setup_workspace
from remember_dammit.storage import Vault


PATHS = {
    "claude": (".mcp.json", ".claude/skills/remember-dammit/SKILL.md"),
    "codex": (".codex/config.toml", ".agents/skills/remember-dammit/SKILL.md"),
    "cursor": (".cursor/mcp.json", ".cursor/skills/remember-dammit/SKILL.md"),
    "antigravity": (".agents/mcp_config.json", ".agents/skills/remember-dammit/SKILL.md"),
}


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.vault = Vault.initialize(self.root / "vault")
        self.backups = self.root / "backups"

    def options(self, **kwargs):
        return dict(vault_path=self.vault.root, project="demo", python_executable=sys.executable) | kwargs

    def install(self, harness="claude", **kwargs):
        with patch("remember_dammit.setup._state_root", return_value=self.backups):
            return setup_workspace(self.workspace, harness, dry_run=False, **self.options(**kwargs))

    def inspect(self, harness="claude", **kwargs):
        try:
            module = importlib.import_module("remember_dammit.diagnostics")
        except ModuleNotFoundError:
            self.fail("Read-only diagnostics API is missing")
        return module.inspect_workspace(self.workspace, harness, **self.options(**kwargs))

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def check(self, result, name):
        return next(item for item in result["checks"] if item["name"] == name)

    def test_installed_harnesses_are_locally_ready_and_untouched(self):
        for harness in PATHS:
            with self.subTest(harness=harness):
                self.install(harness)
                before = self.snapshot()
                result = self.inspect(harness)
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(result["ready"])
                self.assertEqual(result["status"], "ready")
                self.assertFalse(result["tested_live"])
                self.assertEqual(result["native_approval"], "pending")
                self.assertEqual({c["name"] for c in result["checks"]}, {"config", "skill", "runtime", "vault"})
                self.assertTrue(all(c["status"] == "ready" for c in result["checks"]))

    def test_missing_files_are_independent_and_do_not_initialize_anything(self):
        before = self.snapshot()
        result = self.inspect(vault_path=self.root / "absent-vault")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "not_ready")
        for name in ("config", "skill", "vault"):
            self.assertEqual(self.check(result, name)["status"], "missing")
        self.assertEqual(self.check(result, "runtime")["status"], "ready")

    def test_missing_server_and_skill_conflict_are_reported_without_secrets(self):
        self.install()
        config, skill = (self.workspace / p for p in PATHS["claude"])
        config.write_text(json.dumps({"mcpServers": {"other": {"env": {"TOKEN": "private-credential"}}}}))
        skill.write_text("owner-custom-skill-private")
        before = self.snapshot()
        result = self.inspect()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.check(result, "config")["code"], "missing_server")
        self.assertEqual(self.check(result, "skill")["status"], "conflict")
        serialized = json.dumps(result)
        self.assertNotIn("private-credential", serialized)
        self.assertNotIn("owner-custom-skill-private", serialized)

    def test_differing_scoped_server_is_conflict(self):
        self.install()
        for options in ({"project": "other"}, {"project": None, "personal": True},
                        {"vault_path": self.root / "other-vault"}):
            with self.subTest(options=options):
                result = self.inspect(**options)
                self.assertFalse(result["ready"])
                self.assertEqual(self.check(result, "config")["status"], "conflict")
                self.assertEqual(self.check(result, "config")["code"], "server_conflict")

    def test_personal_install_is_checked_using_personal_scope(self):
        self.install(project=None, personal=True)
        result = self.inspect(project=None, personal=True)
        self.assertTrue(result["ready"])
        self.assertEqual(result["selection"], {"project": None, "personal": True})

    def test_invalid_config_does_not_echo_parser_input(self):
        for harness, content in (
            ("claude", b'{"private-credential": '),
            ("claude", b'{"mcpServers": []}'),
            ("claude", b'{"mcpServers":{},"mcpServers":{}}'),
            ("claude", b'{"unrelated": NaN}'),
            ("codex", b'private-credential = ['),
            ("codex", b'mcp_servers = []'),
        ):
            with self.subTest(harness=harness, content=content):
                target = self.workspace / PATHS[harness][0]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                before = self.snapshot()
                result = self.inspect(harness)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.check(result, "config")["code"], "invalid_config")
                self.assertEqual(self.check(result, "config")["status"], "error")
                self.assertNotIn("private-credential", json.dumps(result))

    def test_custom_skill_directory_is_conflict_even_when_skill_matches(self):
        self.install()
        skill = self.workspace / PATHS["claude"][1]
        (skill.parent / "private-owner-asset").write_text("private-credential")
        before = self.snapshot()
        result = self.inspect()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.check(result, "skill")["status"], "conflict")
        self.assertNotIn("private-owner-asset", json.dumps(result))

    def test_bad_runtime_is_reported_without_running_config_command(self):
        self.install()
        target = self.workspace / PATHS["claude"][0]
        data = json.loads(target.read_bytes())
        data["mcpServers"]["remember-dammit"]["command"] = "private-credential"
        target.write_text(json.dumps(data))
        before = self.snapshot()
        result = self.inspect(python_executable=self.root / "missing-python.exe")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(result["ready"])
        self.assertEqual(self.check(result, "runtime")["code"], "missing_runtime")
        self.assertEqual(self.check(result, "runtime")["status"], "missing")
        self.assertNotIn("private-credential", json.dumps(result))

    def test_existing_interpreter_without_package_and_mcp_is_not_ready(self):
        import subprocess
        environment = self.root / "empty-runtime"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(environment)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import os
        executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        before = self.snapshot()
        result = self.inspect(python_executable=executable)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.check(result, "runtime")["code"], "missing_runtime")

    def test_vault_doctor_detects_modified_committed_data_without_echoing_it(self):
        self.install()
        record = self.vault.put(title="private-title", body="private-credential", scope="project:demo")
        (self.vault.root / record["path"]).write_text("private-credential")
        before = self.snapshot()
        result = self.inspect()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(result["ready"])
        self.assertEqual(self.check(result, "vault")["code"], "integrity_error")
        self.assertEqual(self.check(result, "vault")["status"], "error")
        self.assertNotIn("private-credential", json.dumps(result))
        self.assertNotIn("private-title", json.dumps(result))

    def test_client_file_changed_during_runtime_probe_is_not_ready(self):
        self.install()
        module = importlib.import_module("remember_dammit.diagnostics")
        probe = module._runtime_check
        def owner_edit(*args):
            result = probe(*args)
            (self.workspace / PATHS["claude"][0]).write_text('{"owner-edit":true}')
            return result
        with patch.object(module, "_runtime_check", side_effect=owner_edit):
            result = self.inspect()
        self.assertFalse(result["ready"])
        self.assertEqual(self.check(result, "config")["code"], "concurrent_change")

    def test_skill_directory_changed_during_probe_is_not_ready(self):
        self.install()
        module = importlib.import_module("remember_dammit.diagnostics")
        probe = module._runtime_check
        def owner_edit(*args):
            result = probe(*args)
            skill = self.workspace / PATHS["claude"][1]
            (skill.parent / "owner-asset").write_text("preserve")
            return result
        with patch.object(module, "_runtime_check", side_effect=owner_edit):
            result = self.inspect()
        self.assertFalse(result["ready"])
        self.assertEqual(self.check(result, "skill")["code"], "concurrent_change")

    def test_runtime_probe_ignores_workspace_module_shadowing(self):
        self.install()
        local_module = self.workspace / "remember_dammit.py"
        local_module.write_text('raise RuntimeError("must never import workspace file")')
        before = self.snapshot()
        result = self.inspect()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(result["ready"])

    def test_invalid_selection_and_unsafe_arguments_are_refused_read_only(self):
        for harness, options in (("unknown", {}), ("claude", {"project": None}),
                                 ("claude", {"personal": True}), ("claude", {"project": "bad/id"}),
                                 ("claude", {"vault_path": "relative"}),
                                 ("claude", {"vault_path": self.workspace}),
                                 ("claude", {"python_executable": "python"})):
            with self.subTest(harness=harness, options=options):
                before = self.snapshot()
                with self.assertRaises(VaultError):
                    self.inspect(harness, **options)
                self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
