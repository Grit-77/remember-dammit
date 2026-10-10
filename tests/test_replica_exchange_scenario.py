"""Run the artifact acceptance CLI; local producers are explicitly simulated."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HELPER = Path(__file__).with_name('replica_exchange_scenario.py')


class ReplicaExchangeScenarioTests(unittest.TestCase):
    def test_ci_producer_refuses_a_logical_os_label_on_the_wrong_host(self):
        wrong_replica = 'linux' if sys.platform == 'win32' else 'windows'
        with tempfile.TemporaryDirectory() as temporary:
            run = subprocess.run([sys.executable, str(HELPER), 'produce', '--mode', 'ci',
                                  '--replica', wrong_replica, '--seed', temporary,
                                  '--output', str(Path(temporary) / 'producer')],
                                 capture_output=True, text=True, timeout=30)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('requires actual platform', run.stderr)
            self.assertFalse((Path(temporary) / 'producer').exists())

    def test_simulation_runs_complete_exchange_and_reports_actual_host(self):
        # Missing contributions, lost conflict heads, revived deletes/revokes,
        # order-dependent merges, or reporting labels as hosts must fail here.
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'exchange'
            run = subprocess.run([sys.executable, str(HELPER), 'simulate',
                                  '--output', str(output)], capture_output=True,
                                 text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            report = json.loads((output / 'verification' / 'report.json').read_text())
            self.assertEqual(report['mode'], 'simulation')
            self.assertFalse(report['cross_os_proven'])
            self.assertEqual(report['permutation_count'], 6)
            self.assertEqual(report['unique_snapshots'], 1)
            self.assertEqual(report['contribution_count'], 3)
            self.assertEqual(report['decision_head_count'], 3)
            self.assertEqual(report['stale_resolution_code'], 'stale_heads')
            self.assertEqual(report['resolved_head_count'], 1)
            self.assertEqual({p['platform'] for p in report['producers']}, {sys.platform})
            self.assertTrue(all(p['python_version'] for p in report['producers']))
            self.assertTrue(all(p['reindex_unchanged'] for p in report['permutations']))
            marker = output / 'replicas' / 'exchange-replica-mac' / 'bundle' / 'COMPLETE.json'
            marker.unlink()
            broken = subprocess.run([sys.executable, str(HELPER), 'verify', '--mode',
                                     'simulation', '--seed', str(output / 'seed'),
                                     '--replicas', str(output / 'replicas'), '--output',
                                     str(output / 'missing-marker')], capture_output=True,
                                    text=True, timeout=30)
            self.assertNotEqual(broken.returncode, 0)
            self.assertIn('COMPLETE.json', broken.stderr)


if __name__ == '__main__':
    unittest.main()
