"""CLI advisory assessment remains an explicit, provider-free default."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from remember_dammit.storage import Vault


class AdvisorCommandTests(unittest.TestCase):
    def test_default_assessment_preserves_local_recall(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            vault = Vault.initialize(root / 'vault')
            record = vault.put(title='Preferred style', body='Use concise answers.', scope='project:demo')
            before = vault.snapshot_id()
            result = subprocess.run(
                [sys.executable, '-m', 'remember_dammit', '--vault', str(vault.root),
                 'assess', 'concise', '--project', 'demo'], capture_output=True, cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['context']['records'][0]['id'], record['id'])
            self.assertEqual(report['advisor']['mode'], 'off')
            self.assertEqual(report['assessments'], [])
            self.assertEqual(vault.snapshot_id(), before)

    def test_template_is_disabled_and_requires_no_vault(self):
        result = subprocess.run(
            [sys.executable, '-m', 'remember_dammit', 'advisor-template', 'jev', '--model', 'jev-1.13.0'],
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = json.loads(result.stdout)
        self.assertEqual(config['schema'], 1)
        self.assertEqual(config['mode'], 'off')
        self.assertEqual(config['provider'], 'jev')
        self.assertEqual(config['endpoint'], 'https://api.typesafe.ai/v1/systemone')
        self.assertEqual(config['api_key_env'], 'TYPESAFE_API_KEY')


if __name__ == '__main__':
    unittest.main()
