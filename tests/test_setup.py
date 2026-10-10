"""Workspace setup against real temporary client files and an installed runtime."""
import importlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.vault = Vault.initialize(self.root / "vault")
        self.backups = self.root / "local state"

    def setup(self, harness="claude", **kwargs):
        try:
            module = importlib.import_module("remember_dammit.setup")
        except ModuleNotFoundError:
            self.fail("Workspace setup helper is not implemented")
        options = dict(vault_path=self.vault.root, project="demo", python_executable=sys.executable)
        options.update(kwargs)
        with patch.object(module, "_state_root", return_value=self.backups):
            return module.setup_workspace(self.workspace, harness, **options)

    def write(self, relative, data):
        target = self.workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_default_dry_run_does_not_write_anything(self):
        before = self.snapshot()
        result = self.setup()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(result["status"], "planned")
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["tested_live"])

    def test_json_clients_preserve_unrelated_settings_and_repeat_is_noop(self):
        for harness, config, skill in (
            ("claude", ".mcp.json", ".claude/skills/remember-dammit/SKILL.md"),
            ("cursor", ".cursor/mcp.json", ".cursor/skills/remember-dammit/SKILL.md"),
            ("antigravity", ".agents/mcp_config.json", ".agents/skills/remember-dammit/SKILL.md"),
        ):
            with self.subTest(harness=harness):
                old = b'{"custom":{"enabled":true},"mcpServers":{"other":{"command":"other"}}}\n'
                target = self.write(config, old)
                agents = self.write("AGENTS.md", b"owner instructions")
                result = self.setup(harness, dry_run=False)
                value = json.loads(target.read_bytes())
                self.assertEqual(value["custom"], {"enabled": True})
                self.assertEqual(value["mcpServers"]["other"], {"command": "other"})
                server = value["mcpServers"]["remember-dammit"]
                self.assertEqual(server["args"], ["-m", "remember_dammit", "--vault", str(self.vault.root), "mcp", "--project", "demo"])
                self.assertTrue((self.workspace / skill).is_file())
                self.assertEqual(agents.read_bytes(), b"owner instructions")
                changed = next(c for c in result["changes"] if c["path"] == str(target))
                backup = Path(changed["backup"])
                self.assertEqual(backup.read_bytes(), old)
                self.assertTrue(backup.is_relative_to(self.backups))
                self.assertTrue(changed["readback_verified"])
                before = self.snapshot()
                repeated = self.setup(harness, dry_run=False)
                self.assertEqual(repeated["status"], "unchanged")
                self.assertEqual(self.snapshot(), before)

    def test_toml_appends_own_table_and_keeps_original_bytes(self):
        old = b'# owner comment\r\nmodel = "owner-model"\r\n[mcp_servers.other]\r\ncommand = "other"\r\n'
        target = self.write(".codex/config.toml", old)
        self.setup("codex", dry_run=False)
        self.assertTrue(target.read_bytes().startswith(old))
        parsed = tomllib.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(parsed["model"], "owner-model")
        self.assertEqual(parsed["mcp_servers"]["other"], {"command": "other"})
        self.assertEqual(parsed["mcp_servers"]["remember-dammit"]["command"], sys.executable)
        before = self.snapshot()
        self.assertEqual(self.setup("codex", dry_run=False)["status"], "unchanged")
        self.assertEqual(self.snapshot(), before)

    def test_conflicting_config_or_skill_refuses_all_writes(self):
        for config in (b'{"mcpServers":{"remember-dammit":{"command":"custom"}}}', b'{"mcpServers":[]}', b'invalid json'):
            self.write(".mcp.json", config)
            before = self.snapshot()
            with self.assertRaises(VaultError):
                self.setup(dry_run=False)
            self.assertEqual(self.snapshot(), before)
        (self.workspace / ".mcp.json").unlink()
        self.write(".claude/skills/remember-dammit/SKILL.md", b"custom skill")
        before = self.snapshot()
        with self.assertRaises(VaultError):
            self.setup(dry_run=False)
        self.assertEqual(self.snapshot(), before)

    def test_custom_skill_directory_without_skill_file_is_not_adopted(self):
        self.write(".claude/skills/remember-dammit/custom.txt", b"custom owner skill asset")
        before = self.snapshot()
        with self.assertRaises(VaultError):
            self.setup(dry_run=False)
        self.assertEqual(self.snapshot(), before)

    def test_bad_paths_selection_or_missing_runtime_refuse_changes(self):
        for options in (
            {"vault_path": "relative-vault"}, {"python_executable": "python"},
            {"python_executable": self.root / "missing.exe"},
            {"vault_path": self.root / "missing-vault"}, {"vault_path": self.workspace},
            {"project": None}, {"project": "bad/id"}, {"personal": True},
            {"advisor": "unknown"}, {"dry_run": "yes"},
        ):
            with self.subTest(options=options):
                before = self.snapshot()
                with self.assertRaises(VaultError):
                    self.setup(**({"dry_run": False} | options))
                self.assertEqual(self.snapshot(), before)

    def test_advisors_offer_shadow_connector_without_enabling_it(self):
        for choice in ("none", "jev", "laya"):
            result = self.setup(project=None, personal=True, advisor=choice)
            self.assertEqual(result["advisor"], {"choice": choice, "choice_confirmed": False, "enabled": False, "connector_available": choice != "none", "setup_status": "disabled" if choice == "none" else "not_configured"})

    def test_late_write_failure_rolls_back_earlier_file_with_receipt(self):
        module = importlib.import_module("remember_dammit.setup")
        old = b'{"custom":"keep"}'
        target = self.write(".mcp.json", old)
        original = module._atomic_write
        skill = self.workspace / ".claude/skills/remember-dammit/SKILL.md"
        def fail_skill(path, data, *args, **kwargs):
            if path == skill:
                raise OSError("controlled disk failure")
            return original(path, data, *args, **kwargs)
        with patch.object(module, "_atomic_write", side_effect=fail_skill), self.assertRaises(VaultError) as raised:
            self.setup(dry_run=False)
        self.assertEqual(target.read_bytes(), old)
        self.assertFalse(skill.exists())
        self.assertTrue(raised.exception.evidence["rolled_back"])
        receipt = Path(raised.exception.evidence["receipt"])
        self.assertEqual(json.loads(receipt.read_text())["status"], "rolled_back")

    def test_config_changed_after_planning_is_not_overwritten(self):
        module = importlib.import_module("remember_dammit.setup")
        target = self.write(".mcp.json", b'{}')
        original = module._runtime_check
        def concurrent_change(*args):
            original(*args)
            target.write_bytes(b'{"new-owner-setting":true}')
        with patch.object(module, "_runtime_check", side_effect=concurrent_change), self.assertRaises(VaultError) as raised:
            self.setup(dry_run=False)
        self.assertEqual(raised.exception.code, "concurrent_change")
        self.assertEqual(target.read_bytes(), b'{"new-owner-setting":true}')
        self.assertFalse((self.workspace / ".claude/skills/remember-dammit/SKILL.md").exists())

    def test_failure_after_atomic_publication_restores_original(self):
        module = importlib.import_module("remember_dammit.setup")
        target = self.write(".mcp.json", b'{"preserve":true}')
        original = module._atomic_write
        failed = False
        def fail_after_publish(path, data, *args, **kwargs):
            nonlocal failed
            original(path, data, *args, **kwargs)
            if path == target and not failed:
                failed = True
                raise OSError("controlled failure after publication")
        with patch.object(module, "_atomic_write", side_effect=fail_after_publish), self.assertRaises(VaultError) as raised:
            self.setup(dry_run=False)
        self.assertEqual(target.read_bytes(), b'{"preserve":true}')
        self.assertTrue(raised.exception.evidence["rolled_back"])

    def test_linked_config_parent_is_rejected_without_external_write(self):
        external = self.root / "external"
        external.mkdir()
        link = self.workspace / ".cursor"
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)], capture_output=True)
            if result.returncode:
                self.skipTest("Junction creation unavailable")
        else:
            link.symlink_to(external, target_is_directory=True)
        try:
            with self.assertRaises(VaultError):
                self.setup("cursor", dry_run=False)
            self.assertEqual(list(external.iterdir()), [])
        finally:
            if os.name == "nt":
                link.rmdir()
            else:
                link.unlink()

    def test_missing_mcp_in_selected_interpreter_refuses_writes(self):
        # A real dedicated venv with no site packages: executable exists, but
        # imports must fail. This catches merely checking file existence.
        runtime = self.root / "empty runtime"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", "--copies", str(runtime)], check=True, capture_output=True)
        executable = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        before = self.snapshot()
        with self.assertRaises(VaultError) as raised:
            self.setup(python_executable=executable, dry_run=False)
        self.assertEqual(raised.exception.code, "missing_runtime")
        self.assertEqual(self.snapshot(), before)

    def test_backup_state_inside_workspace_is_rejected(self):
        module = importlib.import_module("remember_dammit.setup")
        before = self.snapshot()
        with patch.object(module, "_state_root", return_value=self.workspace / "backups"), self.assertRaises(VaultError):
            module.setup_workspace(self.workspace, "claude", vault_path=self.vault.root, project="demo", dry_run=False)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == "nt", "POSIX virtual environments use interpreter symlinks")
    def test_interpreter_symlink_preserves_lexical_virtualenv_command(self):
        executable = self.root / "venv-python"
        executable.symlink_to(Path(sys.executable))
        self.setup(python_executable=executable, dry_run=False)
        server = json.loads((self.workspace / ".mcp.json").read_bytes())["mcpServers"]["remember-dammit"]
        self.assertEqual(server["command"], str(executable))


if __name__ == "__main__":
    unittest.main()
