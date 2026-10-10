"""Offline lifecycle through actual owner CLI subprocesses."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from remember_dammit.storage import Vault
from test_causal_interfaces import union_into
import shutil


class CausalCliTests(unittest.TestCase):
    def run_portable_cli(self, root, vault, *args, expected_code=0):
        result = subprocess.run(
            [sys.executable, '-I', '-m', 'remember_dammit', '--vault', str(vault), *args],
            cwd=root, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, b'')
        return json.loads(result.stdout)

    @staticmethod
    def file_bytes(root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def legacy_with_examples(self, root):
        legacy = Vault.initialize(root / 'legacy', format_version=1)
        private = legacy.put(title='Synthetic evidence', body='Invented personal evidence.',
                             scope='personal', record_id='private-evidence')
        legacy.grant('atlas', private['id'])
        decision = legacy.put(title='Synthetic decision', body='Original synthetic choice.',
                              scope='project:atlas', sources=[private['id']],
                              record_id='seed-decision', kind='decision')
        legacy.correct(decision['id'], expected_revision=decision['revision'],
                       title='Corrected synthetic decision', body='Retain earlier synthetic choice.')
        legacy.revoke('atlas', private['id'])
        selected = root / 'selected-markdown'
        examples = Path(__file__).resolve().parents[1] / 'examples' / 'vault'
        for relative in ('Sources/Atlas-Brief.md', 'Projects/Atlas/Decisions/Email-Provider.md',
                         'Archive/Atlas/Email-Provider-v1.md'):
            destination = selected / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(examples / relative, destination)
        copied_bytes = self.file_bytes(selected)
        import_plan = self.run_portable_cli(root, legacy.root, 'import-plan', '--source',
                                           str(selected), '--collection', 'portable-examples',
                                           '--scope', 'project:atlas')
        plan_path = root / 'example-import-plan.json'
        plan_path.write_text(json.dumps(import_plan), encoding='utf-8')
        receipt = self.run_portable_cli(root, legacy.root, 'import-apply', '--plan', str(plan_path))
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(len(receipt['completed']), 3)
        self.assertEqual(self.file_bytes(selected), copied_bytes)
        for entry in receipt['completed']:
            self.assertIn(legacy.get(entry['record_id'])['body'].encode('utf-8'), copied_bytes.values())
        # Migration must preserve owner Markdown alongside managed authority too.
        shutil.copytree(selected, legacy.root / 'owner-examples')
        (legacy.root / 'owner-sentinel.txt').write_bytes(b'Keep these owner bytes\r\n')
        return legacy, selected, copied_bytes

    def migrate_through_cli(self, root, legacy):
        target, backup = root / 'migrated', root / 'backup'
        self.assertEqual(self.run_portable_cli(root, target, 'migrate-status', expected_code=1),
                         {'state': 'absent'})
        original_bytes = self.file_bytes(legacy.root)
        plan = self.run_portable_cli(root, legacy.root, 'migrate-plan', '--destination',
                                     str(target), '--backup', str(backup))
        self.assertEqual(self.file_bytes(legacy.root), original_bytes)
        self.assertFalse(target.exists())
        self.assertFalse(backup.exists())
        plan_path = root / 'migration-plan.json'
        plan_path.write_text(json.dumps(plan), encoding='utf-8')
        receipt = self.run_portable_cli(root, legacy.root, 'migrate-apply', '--plan', str(plan_path))
        self.assertEqual(receipt['target_state'], 'complete')
        self.assertEqual(receipt['rollback_source'], str(legacy.root))
        self.assertEqual(receipt['backup_path'], str(backup))
        self.assertEqual(self.run_portable_cli(root, target, 'migrate-status'), {'state': 'complete'})
        self.assertEqual(self.run_portable_cli(root, backup, 'migrate-status'), {'state': 'complete'})
        self.assertEqual(self.file_bytes(legacy.root), original_bytes)
        self.assertEqual(self.file_bytes(backup), original_bytes)
        return Vault(target), backup, original_bytes

    def test_cli_migration_status_absent_and_incomplete_are_nonzero_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name, marker_name, expected_state in (
                    ('absent', None, 'absent'),
                    ('incomplete-target', '.migration-INCOMPLETE.json', 'incomplete'),
                    ('incomplete-backup', '.migration-backup-INCOMPLETE.json', 'incomplete')):
                with self.subTest(state=name):
                    target = root / name
                    if marker_name is not None:
                        target.mkdir()
                        (target / marker_name).write_bytes(b'{}\n')
                        (target / 'retain-owner-bytes').write_bytes(b'Preserve incomplete artifacts.')
                    before = self.file_bytes(target)
                    exists_before = target.exists()
                    status = self.run_portable_cli(root, target, 'migrate-status', expected_code=1)
                    self.assertEqual(status['state'], expected_state)
                    self.assertEqual(self.file_bytes(target), before)
                    self.assertEqual(target.exists(), exists_before)

    def test_cli_legacy_resolve_and_retract_return_json_migration_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            legacy = Vault.initialize(root / 'legacy', format_version=1)
            record = legacy.put(title='Legacy note', body='Retain legacy authority.',
                                scope='project:demo', record_id='legacy-note')
            before = self.file_bytes(legacy.root)
            heads = self.run_portable_cli(root, legacy.root, 'heads', record['id'])
            self.assertEqual([h['id'] for h in heads['heads']], [record['id']])
            observed_path = root / 'legacy-heads.json'
            observed_path.write_text(json.dumps(heads), encoding='utf-8')
            for command, extra in (('resolve', ('--title', 'Requires migration', '--body', 'Not applied.')),
                                   ('retract', ())):
                with self.subTest(command=command):
                    rejected = self.run_portable_cli(root, legacy.root, command, record['id'],
                                                     '--expected-heads', str(observed_path),
                                                     *extra, expected_code=1)
                    self.assertEqual(rejected['error']['code'], 'migration_required')
                    self.assertEqual(self.file_bytes(legacy.root), before)

    def test_cli_migration_plan_apply_status_preserve_legacy_examples_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            legacy, selected, copied_bytes = self.legacy_with_examples(root)
            old_records = legacy.list_records()
            old_history = legacy.history('seed-decision')
            migrated, backup, original_bytes = self.migrate_through_cli(root, legacy)
            self.assertEqual(migrated.vault_id, legacy.vault_id)
            self.assertEqual(json.loads((migrated.root / '.remember/vault.json').read_bytes())['schema'], 2)
            self.assertEqual({r['id'] for r in migrated.list_records()}, {r['id'] for r in old_records})
            for old in old_records:
                new = migrated.get(old['id'])
                self.assertEqual({k: new[k] for k in old if k != 'path'},
                                 {k: v for k, v in old.items() if k != 'path'})
                self.assertEqual((migrated.root / new['path']).read_bytes(),
                                 (legacy.root / old['path']).read_bytes())
            self.assertEqual([r['id'] for r in migrated.history('seed-decision')],
                             [r['id'] for r in old_history])
            self.assertEqual(migrated.grants_for('atlas'), set())
            self.assertEqual(self.file_bytes(selected), copied_bytes)
            self.assertEqual(self.file_bytes(backup), original_bytes)

    def test_cli_sync_export_plan_apply_replay_and_import_preserve_both_branches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            legacy, selected, copied_bytes = self.legacy_with_examples(root)
            migrated, backup, original_bytes = self.migrate_through_cli(root, legacy)
            branches = {}
            for name in ('windows', 'mac'):
                destination = root / name
                shutil.copytree(migrated.root / '.remember', destination / '.remember')
                branches[name] = Vault(destination)
                self.run_portable_cli(root, destination, 'remember', '--title', name,
                                      '--body', f'Independent {name} capture.', '--scope',
                                      f'project:{name}', '--record-id', f'{name}-capture')
            bundle = root / 'windows-bundle'
            exported = self.run_portable_cli(root, branches['windows'].root, 'sync-export',
                                             '--destination', str(bundle))
            self.assertTrue(exported['complete'])
            self.assertTrue((bundle / 'COMPLETE.json').is_file())
            source_before = self.file_bytes(branches['windows'].root)
            target_before = self.file_bytes(branches['mac'].root)
            plan = self.run_portable_cli(root, branches['mac'].root, 'sync-plan', '--source', str(bundle))
            self.assertEqual(self.file_bytes(branches['windows'].root), source_before)
            self.assertEqual(self.file_bytes(branches['mac'].root), target_before)
            plan_path = root / 'sync-plan.json'
            plan_path.write_text(json.dumps(plan), encoding='utf-8')
            applied = self.run_portable_cli(root, branches['mac'].root, 'sync-apply', '--plan', str(plan_path))
            self.assertTrue(applied['complete'])
            self.assertGreater(applied['added'], 0)
            self.assertEqual(applied['snapshot'], plan['merged_snapshot'])
            merged_before_replay = self.file_bytes(branches['mac'].root)
            replay = self.run_portable_cli(root, branches['mac'].root, 'sync-apply', '--plan', str(plan_path))
            self.assertTrue(replay['complete'])
            self.assertEqual(replay['added'], 0)
            self.assertEqual(replay['snapshot'], applied['snapshot'])
            self.assertEqual(self.file_bytes(branches['mac'].root), merged_before_replay)
            merged_bundle = root / 'merged-bundle'
            self.run_portable_cli(root, branches['mac'].root, 'sync-export', '--destination', str(merged_bundle))
            imported = self.run_portable_cli(root, branches['windows'].root, 'sync-import',
                                             '--bundle', str(merged_bundle))
            self.assertTrue(imported['complete'])
            self.assertEqual(imported['snapshot'], applied['snapshot'])
            self.assertEqual(branches['windows'].list_records(), branches['mac'].list_records())
            for branch in branches.values():
                for name in branches:
                    capture = branch.get(f'{name}-capture')
                    self.assertEqual(capture['scope'], f'project:{name}')
                    self.assertEqual(capture['body'], f'Independent {name} capture.')
            again = self.run_portable_cli(root, branches['windows'].root, 'sync-import',
                                         '--bundle', str(merged_bundle))
            self.assertEqual(again['added'], 0)
            self.assertEqual(self.file_bytes(legacy.root), original_bytes)
            self.assertEqual(self.file_bytes(backup), original_bytes)
            self.assertEqual(self.file_bytes(selected), copied_bytes)

    def test_cli_sync_rejects_invalid_and_partial_bundles_without_destination_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            legacy, selected, copied_bytes = self.legacy_with_examples(root)
            migrated, backup, original_bytes = self.migrate_through_cli(root, legacy)
            destination = root / 'destination'
            shutil.copytree(migrated.root / '.remember', destination / '.remember')
            added = self.run_portable_cli(root, migrated.root, 'remember', '--title', 'Bundle tail',
                                         '--body', 'Synthetic tail bytes.', '--scope', 'project:atlas',
                                         '--record-id', 'bundle-tail')
            bundle = root / 'bundle'
            self.run_portable_cli(root, migrated.root, 'sync-export', '--destination', str(bundle))
            before = self.file_bytes(destination)
            marker = bundle / 'COMPLETE.json'
            marker_bytes = marker.read_bytes()
            marker.write_bytes(b'{}')
            for command, flag in (('sync-import', '--bundle'), ('sync-plan', '--source')):
                rejected = self.run_portable_cli(root, destination, command, flag, str(bundle), expected_code=1)
                self.assertEqual(rejected['error']['code'], 'invalid_bundle')
                self.assertEqual(self.file_bytes(destination), before)
            marker.write_bytes(marker_bytes)
            payload = bundle / added['path']
            payload_bytes = payload.read_bytes()
            payload.unlink()
            for command, flag in (('sync-import', '--bundle'), ('sync-plan', '--source')):
                rejected = self.run_portable_cli(root, destination, command, flag, str(bundle), expected_code=1)
                self.assertEqual(rejected['error']['code'], 'incomplete_transfer')
                self.assertEqual(self.file_bytes(destination), before)
            payload.write_bytes(payload_bytes)
            accepted = self.run_portable_cli(root, destination, 'sync-import', '--bundle', str(bundle))
            self.assertTrue(accepted['complete'])
            self.assertEqual(Vault(destination).get('bundle-tail')['body'], 'Synthetic tail bytes.')
            self.assertEqual(self.file_bytes(legacy.root), original_bytes)
            self.assertEqual(self.file_bytes(backup), original_bytes)
            self.assertEqual(self.file_bytes(selected), copied_bytes)

    def test_heads_resolve_stale_and_retract_through_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            vault = Vault.initialize(root / 'vault')
            original = vault.put(title='Plan', body='Original.', scope='project:demo')
            shutil.copytree(vault.root, root / 'mac')
            a = vault.correct(original['id'], expected_revision=original['revision'], title='Windows choice', body='First choice.')
            other = Vault(root / 'mac')
            other.correct(original['id'], expected_revision=original['revision'], title='Mac choice', body='Second choice.')
            union_into(vault.root, other.root)
            def cli(*args):
                return subprocess.run([sys.executable, '-m', 'remember_dammit', '--vault', str(vault.root), *args],
                                      cwd=root, capture_output=True)
            result = cli('heads', original['id'])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            heads = json.loads(result.stdout)
            self.assertEqual(len(heads['heads']), 2)
            path = root / 'heads.json'
            path.write_bytes(result.stdout)
            resolved = cli('resolve', original['id'], '--expected-heads', str(path),
                           '--title', 'Agreed plan', '--body', 'Reviewed both choices.', '--operation-id', 'resolve-cli')
            self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
            record = json.loads(resolved.stdout)
            stale = cli('resolve', original['id'], '--expected-heads', str(path), '--title', 'Stale plan', '--body', 'Old observations.')
            self.assertEqual(stale.returncode, 1)
            current = cli('heads', original['id'])
            path.write_bytes(current.stdout)
            deleted = cli('retract', original['id'], '--expected-heads', str(path), '--operation-id', 'delete-cli')
            self.assertEqual(deleted.returncode, 0, deleted.stdout + deleted.stderr)
            deleted_heads = json.loads(cli('heads', original['id']).stdout)['heads']
            self.assertTrue(deleted_heads)
            self.assertTrue(all(head['state'] == 'retracted' for head in deleted_heads))
            self.assertEqual(json.loads(cli('recall', 'Reviewed', '--project', 'demo').stdout)['records'], [])
            self.assertEqual(vault.get(record['id'])['state'], 'retracted')


if __name__ == '__main__':
    unittest.main()
