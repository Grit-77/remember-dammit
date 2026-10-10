"""Exercise the public setup command on disposable user workspaces."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from remember_dammit.storage import Vault


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Setup requires the optional MCP extra')
class SetupCommandTests(unittest.TestCase):
    def test_deep_existing_json_returns_structured_error_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / 'workspace'
            workspace.mkdir()
            config = workspace / '.mcp.json'
            original = b'{"custom":' + b'[' * 10000 + b']' * 10000 + b'}'
            config.write_bytes(original)
            vault = Vault.initialize(root / 'vault')
            result = subprocess.run(
                [sys.executable, '-m', 'remember_dammit', '--vault', str(vault.root),
                 'setup', 'claude', '--workspace', str(workspace), '--project', 'demo', '--apply'],
                cwd=root, capture_output=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_config')
            self.assertEqual(result.stderr, b'')
            self.assertEqual(config.read_bytes(), original)
            self.assertFalse((workspace / '.claude').exists())

    def test_preview_apply_and_repeat_preserve_existing_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / 'workspace'
            workspace.mkdir()
            rules = workspace / 'AGENTS.md'
            rules.write_text('My existing instructions', encoding='utf-8')
            vault = Vault.initialize(root / 'vault')
            command = [sys.executable, '-m', 'remember_dammit', '--vault', str(vault.root),
                       'setup', 'codex', '--workspace', str(workspace), '--project', 'demo',
                       '--advisor', 'laya']

            def run(*extra):
                result = subprocess.run([*command, *extra], cwd=root, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return json.loads(result.stdout)

            preview = run()
            self.assertTrue(preview['dry_run'])
            self.assertFalse((workspace / '.codex/config.toml').exists())
            installed = run('--apply')
            self.assertFalse(installed['dry_run'])
            self.assertEqual(installed['advisor']['choice'], 'laya')
            self.assertIs(installed['advisor']['enabled'], False)
            self.assertIs(installed['tested_live'], False)
            self.assertTrue((workspace / '.codex/config.toml').is_file())
            self.assertTrue((workspace / '.agents/skills/remember-dammit/SKILL.md').is_file())
            before = {str(p.relative_to(workspace)): p.read_bytes()
                      for p in workspace.rglob('*') if p.is_file()}
            run('--apply')
            after = {str(p.relative_to(workspace)): p.read_bytes()
                     for p in workspace.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(rules.read_text(encoding='utf-8'), 'My existing instructions')


if __name__ == '__main__':
    unittest.main()
