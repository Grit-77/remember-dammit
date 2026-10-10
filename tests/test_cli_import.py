import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ImportCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'a.md').write_bytes(b'---\nscope: shared\n---\nOriginal\n')
        self.target = self.root / 'target'
        self.plan_file = self.root / 'plan.json'

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'remember_dammit', *args],
                              capture_output=True, timeout=30)

    def preview(self, *prefix):
        return self.run_cli(*prefix, 'import-plan', '--source', str(self.source),
                            '--collection', 'notes', '--scope', 'project:atlas')

    def apply(self):
        return self.run_cli('--vault', str(self.target), 'import-apply', '--plan', str(self.plan_file))

    def test_preview_before_init_apply_repeat_and_correct(self):
        preview = self.preview()
        self.assertEqual(preview.returncode, 0, preview.stdout.decode() + preview.stderr.decode())
        self.assertFalse(self.target.exists())
        plan = json.loads(preview.stdout)
        self.assertEqual(plan['scope'], 'project:atlas')
        self.plan_file.write_bytes(preview.stdout)
        self.assertNotEqual(self.apply().returncode, 0)
        self.assertEqual(self.run_cli('--vault', str(self.target), 'init').returncode, 0)
        applied = self.apply()
        self.assertEqual(applied.returncode, 0, applied.stdout.decode())
        first = json.loads(applied.stdout)['completed'][0]['record_id']
        self.assertEqual(self.apply().returncode, 0)
        (self.source / 'a.md').write_bytes(b'Updated\n')
        stale = self.apply()
        self.assertEqual(json.loads(stale.stdout)['error']['code'], 'source_changed')
        corrected = self.preview('--vault', str(self.target))
        self.assertEqual(corrected.returncode, 0, corrected.stdout.decode())
        self.plan_file.write_bytes(corrected.stdout)
        self.assertEqual(self.apply().returncode, 0)
        history = self.run_cli('--vault', str(self.target), 'history', first)
        self.assertEqual([r['body'] for r in json.loads(history.stdout)], ['---\nscope: shared\n---\nOriginal\n', 'Updated\n'])

    def test_json_arguments_and_malformed_plan_errors(self):
        for args in [('init',), ('import-apply', '--plan', str(self.plan_file)),
                     ('import-plan', '--source', str(self.source), '--collection', 'notes')]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_arguments')
        self.run_cli('--vault', str(self.target), 'init')
        for payload in (b'not json', b'[]', b'{"private":"do-not-echo-this"}', b'[' * 2000 + b']' * 2000):
            self.plan_file.write_bytes(payload)
            result = self.apply()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_plan')
            self.assertNotIn(b'do-not-echo-this', result.stdout + result.stderr)

    def test_relative_source_is_refused_without_touching_source(self):
        before = (self.source / 'a.md').read_bytes()
        result = self.run_cli('import-plan', '--source', 'relative', '--collection', 'notes', '--scope', 'personal')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_source')
        self.assertEqual((self.source / 'a.md').read_bytes(), before)

    def test_recursion_depth_plan_returns_json_without_traceback(self):
        self.assertEqual(self.run_cli('--vault', str(self.target), 'init').returncode, 0)
        self.plan_file.write_bytes(b'[' * 10000 + b']' * 10000)
        result = self.apply()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_plan')
        self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
