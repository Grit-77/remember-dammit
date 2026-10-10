"""User-facing vault navigation and Markdown edit commands."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from remember_dammit.storage import Vault


class VaultCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = Vault.initialize(self.root / 'vault')

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'remember_dammit', '--vault', str(self.vault.root),
                               *args], cwd=self.root, capture_output=True)

    def test_overview_reports_tasks_without_foreign_records(self):
        source = self.vault.put(title='My goal', body='Ship the documentation.', kind='source', scope='project:demo')
        task = self.vault.put(title='Write examples', body='Add a first example.', kind='task',
                              scope='project:demo', sources=[source['id']])
        hidden = self.vault.put(title='Private elsewhere', body='A private sentinel.', scope='project:other')
        result = self.run_cli('overview', '--project', 'demo')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['total_count'], 2)
        self.assertEqual(report['summary']['by_kind']['task'], 1)
        self.assertNotIn(hidden['id'], result.stdout.decode())
        items = {item['id']: item for item in report['records']}
        self.assertEqual(items[source['id']]['backlinks'][0]['id'], task['id'])

    def test_edit_open_plan_apply_and_replay_preserve_history(self):
        note = self.vault.put(title='Writing style', body='Use short sentences.', scope='project:demo')
        workspace = self.root / 'Working notes'
        result = self.run_cli('edit-open', '--destination', str(workspace), '--project', 'demo')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((workspace / 'manifest.json').read_bytes())
        entry = next(item for item in manifest['notes'] if item['id'] == note['id'])
        path = workspace / entry['path']
        path.write_bytes(path.read_bytes().replace(b'Use short sentences.', b'Use concise Turkish sentences.'))
        preview = self.run_cli('edit-plan', '--workspace', str(workspace), '--project', 'demo')
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        self.assertEqual(json.loads(preview.stdout)['status'], 'ready')
        plan_file = self.root / 'reviewed-plan.json'
        plan_file.write_bytes(preview.stdout)
        arguments = ('edit-apply', '--workspace', str(workspace), '--plan', str(plan_file), '--project', 'demo')
        applied = self.run_cli(*arguments)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        report = json.loads(applied.stdout)
        successor = report['successors'][note['id']]
        self.assertEqual(self.vault.get(successor)['body'], 'Use concise Turkish sentences.')
        retried = self.run_cli(*arguments)
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertEqual(json.loads(retried.stdout)['successors'][note['id']], successor)
        self.assertEqual(len(self.vault.history(note['id'])), 2)

    def test_stale_edit_plan_returns_nonzero_conflict_without_overwrite(self):
        note = self.vault.put(title='Decision', body='Original choice.', scope='project:demo')
        workspace = self.root / 'Working notes'
        opened = self.run_cli('edit-open', '--destination', str(workspace), '--project', 'demo')
        self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)
        entry = json.loads((workspace / 'manifest.json').read_bytes())['notes'][0]
        path = workspace / entry['path']
        path.write_bytes(path.read_bytes().replace(b'Original choice.', b'Edited choice.'))
        preview = self.run_cli('edit-plan', '--workspace', str(workspace), '--project', 'demo')
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        plan = self.root / 'plan.json'
        plan.write_bytes(preview.stdout)
        agent = self.vault.correct(note['id'], expected_revision=note['revision'],
                                   title='Agent change', body='Concurrent agent choice.')
        result = self.run_cli('edit-apply', '--workspace', str(workspace), '--plan', str(plan), '--project', 'demo')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'conflict')
        self.assertEqual(self.vault.get(agent['id'])['body'], 'Concurrent agent choice.')
        self.assertEqual(len(self.vault.history(note['id'])), 2)

    def test_deep_plan_returns_structured_error_before_any_write(self):
        plan = self.root / 'deep-plan.json'
        plan.write_bytes(b'[' * 10000 + b']' * 10000)
        before = self.vault.snapshot_id()
        result = self.run_cli('edit-apply', '--workspace', str(self.root / 'unused'),
                              '--plan', str(plan), '--project', 'demo')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_plan')
        self.assertEqual(result.stderr, b'')
        self.assertEqual(self.vault.snapshot_id(), before)


if __name__ == '__main__':
    unittest.main()
