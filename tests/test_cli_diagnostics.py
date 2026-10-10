"""Installation diagnostics are available through the owner CLI."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from remember_dammit.storage import Vault


class DiagnosticsCommandTests(unittest.TestCase):
    def test_missing_installation_returns_actionable_read_only_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / 'workspace'
            workspace.mkdir()
            vault = Vault.initialize(root / 'vault')
            result = subprocess.run(
                [sys.executable, '-m', 'remember_dammit', '--vault', str(vault.root),
                 'setup-check', 'codex', '--workspace', str(workspace), '--project', 'demo'],
                capture_output=True, cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['status'], 'not_ready')
            self.assertIs(report['tested_live'], False)
            self.assertEqual(list(workspace.iterdir()), [])
            self.assertTrue(any(check['name'] == 'config' and check['status'] == 'missing'
                                for check in report['checks']))


if __name__ == '__main__':
    unittest.main()
