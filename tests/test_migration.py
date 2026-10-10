"""Synthetic out-of-place migration acceptance; never selects a live vault."""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


def file_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.vault = Vault.initialize(self.source, format_version=1)
        self.target = Path(self.temp.name) / 'target'
        self.backup = Path(self.temp.name) / 'backup'
        self.first = self.vault.put(record_id='evidence', operation_id='first-operation',
                                    title='Owner statement', body='Keep exact original bytes.',
                                    scope='personal')
        self.vault.grant('alpha', 'evidence', operation_id='allow-alpha')
        self.dependent = self.vault.put(record_id='dependent', operation_id='decision-operation',
                                        title='Decision', body='Derived from source.',
                                        scope='project:alpha', sources=['evidence'])
        self.second = self.vault.correct('evidence', expected_revision=self.first['revision'],
                                         operation_id='correct-operation',
                                         title='Correction', body='Keep the superseded history.')
        self.vault.revoke('alpha', 'evidence', operation_id='deny-alpha')
        (self.source / 'owner-file.txt').write_bytes(b'Non-managed owner bytes\r\n')

    def module(self):
        try:
            return importlib.import_module('remember_dammit.migration')
        except ModuleNotFoundError:
            self.fail('Previewed out-of-place migration implementation is required.')

    def preview(self):
        return self.module().preview_migration(self.source, self.target, self.backup)

    def test_preview_is_read_only_and_binds_complete_source_manifest(self):
        before = file_bytes(self.source)
        siblings = set(self.source.parent.iterdir())
        plan = self.preview()
        self.assertEqual(file_bytes(self.source), before)
        self.assertEqual(set(self.source.parent.iterdir()), siblings)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.backup.exists())
        self.assertEqual(plan['vault_id'], self.vault.vault_id)
        self.assertEqual({entry['path'] for entry in plan['manifest'] if entry['kind'] == 'file'}, set(before))
        self.assertEqual(plan, self.preview())

    def test_apply_preserves_full_backup_revision_bytes_history_sources_and_policy(self):
        module = self.module()
        before = file_bytes(self.source)
        receipt = module.apply_migration(self.preview())
        self.assertEqual(file_bytes(self.source), before)
        self.assertEqual(file_bytes(self.backup), before)
        self.assertEqual(receipt['backup_path'], str(self.backup))
        self.assertEqual(receipt['target_state'], 'complete')
        self.assertEqual(receipt['rollback_source'], str(self.source))
        migrated = Vault(self.target)
        self.assertEqual(migrated.vault_id, self.vault.vault_id)
        self.assertEqual(json.loads((self.target / '.remember/vault.json').read_bytes())['schema'], 2)
        for old in self.vault.list_records():
            new = migrated.get(old['id'])
            for field in old:
                if field != 'path':
                    self.assertEqual(new[field], old[field], field)
            self.assertEqual((self.target / new['path']).read_bytes(), (self.source / old['path']).read_bytes())
        self.assertEqual([r['id'] for r in migrated.history(self.second['id'])], ['evidence', self.second['id']])
        self.assertEqual(migrated.grants_for('alpha'), set())
        self.assertEqual(set(migrated._load()['operations']), set(self.vault._load()['operations']))
        self.assertEqual(module.inspect_migration(self.target)['state'], 'complete')
        mapping = receipt['legacy_operation_mapping']
        old_ops, new_ops = self.vault._load()['operations'], migrated._load()['operations']
        self.assertEqual(mapping, {old['digest']: new_ops[operation_id]['digest']
                                   for operation_id, old in old_ops.items()})
        # Same request receipt still represents its original revision.
        retry = migrated.put(record_id='evidence', operation_id='first-operation',
                             title='Owner statement', body='Keep exact original bytes.', scope='personal')
        self.assertEqual(retry['revision'], self.first['revision'])

    def test_independent_migrations_of_common_history_produce_identical_events(self):
        module = self.module()
        module.apply_migration(self.preview())
        other = self.target.with_name('other-target')
        backup = self.backup.with_name('other-backup')
        module.apply_migration(module.preview_migration(self.source, other, backup))
        self.assertEqual(file_bytes(self.target / '.remember'), file_bytes(other / '.remember'))
        self.assertEqual(Vault(self.target).snapshot_id(), Vault(other).snapshot_id())

    def test_stale_preview_refuses_all_destination_writes(self):
        module = self.module()
        plan = self.preview()
        (self.source / 'owner-file.txt').write_bytes(b'changed source')
        with self.assertRaises(VaultError) as caught:
            module.apply_migration(plan)
        self.assertEqual(caught.exception.code, 'stale_migration')
        self.assertFalse(self.target.exists())
        self.assertFalse(self.backup.exists())

    def test_occupied_or_overlapping_destination_preserves_existing_bytes(self):
        module = self.module()
        plan = self.preview()
        self.target.mkdir()
        sentinel = self.target / 'important'
        sentinel.write_bytes(b'preserve')
        with self.assertRaises(VaultError):
            module.apply_migration(plan)
        self.assertEqual(sentinel.read_bytes(), b'preserve')
        self.assertFalse(self.backup.exists())
        with self.assertRaises(VaultError):
            module.preview_migration(self.source, self.source / 'new', self.backup)

    def test_corrupt_checkpoint_preview_rejects_without_writes(self):
        module = self.module()
        (self.source / '.remember/head.json').write_bytes(b'{invalid')
        before = file_bytes(self.source)
        with self.assertRaises(VaultError):
            self.preview()
        self.assertEqual(file_bytes(self.source), before)
        self.assertFalse(self.target.exists())

    def test_interrupted_conversion_retains_verified_backup_and_incomplete_target(self):
        module = self.module()
        plan = self.preview()
        before = file_bytes(self.source)
        with patch('remember_dammit.storage_v2.convert_v1_to_v2', side_effect=OSError('synthetic failure')):
            with self.assertRaises(VaultError):
                module.apply_migration(plan)
        self.assertEqual(file_bytes(self.source), before)
        self.assertEqual(file_bytes(self.backup), before)
        self.assertTrue((self.target / '.migration-INCOMPLETE.json').exists())
        self.assertEqual(module.inspect_migration(self.target)['state'], 'incomplete')
        with self.assertRaises(VaultError):
            Vault(self.target)
        with self.assertRaises(VaultError):
            module.apply_migration(plan)
        self.assertTrue((self.target / '.migration-INCOMPLETE.json').exists())

    def test_interrupted_backup_retains_partial_bytes_and_never_creates_target(self):
        module = self.module()
        plan = self.preview()
        before = file_bytes(self.source)
        actual = module._copy_manifest

        def interrupt_after_copy(source, destination, manifest, **kwargs):
            actual(source, destination, manifest[:2], **kwargs)
            raise OSError('synthetic interrupted copy')

        with patch.object(module, '_copy_manifest', side_effect=interrupt_after_copy):
            with self.assertRaises(VaultError):
                module.apply_migration(plan)
        self.assertEqual(file_bytes(self.source), before)
        self.assertFalse(self.target.exists())
        self.assertTrue((self.backup / '.migration-backup-INCOMPLETE.json').exists())
        self.assertEqual(module.inspect_migration(self.backup)['state'], 'incomplete')
        with self.assertRaises(VaultError):
            module.apply_migration(plan)

    def test_file_modes_and_owner_files_survive_backup_and_target(self):
        module = self.module()
        owner = self.source / 'owner-file.txt'
        owner.chmod(0o444)
        # Windows temporary-directory cleanup can clear a read-only flag.
        try:
            receipt = module.apply_migration(self.preview())
            for root in (self.backup, self.target):
                copied = root / owner.name
                self.assertEqual(copied.stat().st_mode, owner.stat().st_mode)
                self.assertEqual(copied.read_bytes(), owner.read_bytes())
                copied.chmod(0o666)
            self.assertEqual(receipt['target_state'], 'complete')
        finally:
            owner.chmod(0o666)

    def test_changed_preview_and_occupied_backup_are_refused(self):
        module = self.module()
        plan = self.preview()
        changed = dict(plan, target=str(self.target.with_name('unreviewed-target')))
        with self.assertRaises(VaultError) as caught:
            module.apply_migration(changed)
        self.assertEqual(caught.exception.code, 'invalid_migration')
        self.assertFalse(self.target.exists())
        self.backup.mkdir()
        sentinel = self.backup / 'sentinel'
        sentinel.write_bytes(b'old backup')
        with self.assertRaises(VaultError):
            module.apply_migration(plan)
        self.assertEqual(sentinel.read_bytes(), b'old backup')
        self.assertFalse(self.target.exists())

    def test_target_owner_file_readback_failure_retains_incomplete_marker(self):
        module = self.module()
        plan = self.preview()
        actual = module._copy_manifest

        def corrupt_target_copy(source, destination, manifest, **kwargs):
            actual(source, destination, manifest, **kwargs)
            if kwargs.get('managed') is False:
                (destination / 'owner-file.txt').write_bytes(b'wrong target bytes')

        with patch.object(module, '_copy_manifest', side_effect=corrupt_target_copy):
            with self.assertRaises(VaultError) as caught:
                module.apply_migration(plan)
        self.assertEqual(caught.exception.code, 'migration_verification')
        self.assertTrue((self.target / '.migration-INCOMPLETE.json').exists())

    def test_process_death_preserves_marker_backup_and_releases_writer_locks(self):
        module = self.module()
        before = file_bytes(self.source)
        plan = self.preview()
        code = '''
import json, os, sys
from remember_dammit import storage_v2
from remember_dammit.migration import apply_migration
storage_v2.convert_v1_to_v2 = lambda *args: os._exit(73)
apply_migration(json.loads(sys.argv[1]))
'''
        result = subprocess.run([sys.executable, '-c', code, json.dumps(plan)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(file_bytes(self.source), before)
        self.assertEqual(file_bytes(self.backup), before)
        self.assertEqual(module.inspect_migration(self.target)['state'], 'incomplete')
        next_target, next_backup = self.target.with_name('retry-target'), self.backup.with_name('retry-backup')
        receipt = module.apply_migration(module.preview_migration(self.source, next_target, next_backup))
        self.assertEqual(receipt['target_state'], 'complete')

    def test_failed_final_readback_restores_incomplete_marker(self):
        module = self.module()
        from remember_dammit.storage_v2 import CausalVault
        actual = CausalVault.snapshot_id

        def fail_completed_readback(vault):
            if vault.root == self.target and not (self.target / '.migration-INCOMPLETE.json').exists():
                raise OSError('synthetic completed read failure')
            return actual(vault)

        with patch.object(CausalVault, 'snapshot_id', fail_completed_readback):
            with self.assertRaises(VaultError):
                module.apply_migration(self.preview())
        self.assertTrue((self.target / '.migration-INCOMPLETE.json').exists())
        self.assertEqual(module.inspect_migration(self.target)['state'], 'incomplete')

    def test_backup_changed_during_conversion_refuses_success_and_retains_bytes(self):
        module = self.module()
        from remember_dammit import storage_v2
        convert = storage_v2.convert_v1_to_v2
        source_before = file_bytes(self.source)
        for selected in ('owner-file.txt', '.remember/vault.json'):
            with self.subTest(changed_file=selected):
                suffix = 'owner' if selected == 'owner-file.txt' else 'config'
                target = self.target.with_name('target-' + suffix)
                backup = self.backup.with_name('backup-' + suffix)
                plan = module.preview_migration(self.source, target, backup)
                altered = {}

                def convert_then_change_backup(source, destination):
                    converted = convert(source, destination)
                    (backup / selected).write_bytes(b'intentionally changed backup')
                    altered.update(file_bytes(backup))
                    return converted

                with patch.object(storage_v2, 'convert_v1_to_v2', side_effect=convert_then_change_backup):
                    with self.assertRaises(VaultError) as caught:
                        module.apply_migration(plan)
                self.assertEqual(caught.exception.code, 'migration_verification')
                self.assertEqual(file_bytes(self.source), source_before)
                self.assertEqual(file_bytes(backup), altered)
                self.assertEqual(module.inspect_migration(target)['state'], 'incomplete')
                self.assertTrue((target / '.migration-INCOMPLETE.json').exists())
                with self.assertRaises(VaultError):
                    Vault(target)


if __name__ == '__main__':
    unittest.main()
