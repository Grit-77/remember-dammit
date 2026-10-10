import hashlib
import tempfile
import unittest
import shutil
import os
import json
from unittest.mock import patch
from pathlib import Path

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.vault = Vault.initialize(self.root / 'target')

    def plan(self, **kwargs):
        from remember_dammit.importing import plan_import
        return plan_import(self.source, collection='notes', scope='project:atlas', **kwargs)

    def apply(self, plan):
        from remember_dammit.importing import apply_import
        return apply_import(self.vault, plan)

    def test_file_and_manifest_changes_refused_before_any_writes(self):
        (self.source / 'a.md').write_text('First', encoding='utf-8')
        (self.source / 'b.md').write_text('Second', encoding='utf-8')
        for mutation in ('content', 'new-file', 'delete'):
            plan = self.plan()
            if mutation == 'content':
                (self.source / 'b.md').write_text('Changed', encoding='utf-8')
            elif mutation == 'new-file':
                (self.source / 'c.md').write_text('Third', encoding='utf-8')
            else:
                (self.source / 'b.md').unlink()
            with self.assertRaises(VaultError) as caught:
                self.apply(plan)
            self.assertEqual(caught.exception.code, 'source_changed')
            self.assertEqual(self.vault.list_records(), [])

    def test_updates_correct_one_lineage_and_old_plan_cannot_overwrite_it(self):
        note = self.source / 'a.md'
        note.write_text('Original', encoding='utf-8')
        initial = self.plan()
        first_id = self.apply(initial)['completed'][0]['record_id']
        note.write_text('Second', encoding='utf-8')
        unbound = self.plan()
        with self.assertRaises(VaultError):
            self.apply(unbound)
        update = self.plan(vault=self.vault)
        self.assertEqual(update['files'][0]['action'], 'correct')
        self.assertEqual(update['files'][0]['expected']['id'], first_id)
        second_id = self.apply(update)['completed'][0]['record_id']
        self.apply(update)
        self.assertEqual(len(self.vault.history(first_id)), 2)
        self.assertEqual(self.vault.get(first_id)['state'], 'superseded')
        self.assertEqual(self.vault.get(second_id)['body'], 'Second')
        stale = self.plan(vault=self.vault)
        self.vault.correct(second_id, expected_revision=self.vault.get(second_id)['revision'],
                           title='Owner edit', body='New owner text')
        with self.assertRaises(VaultError) as caught:
            self.apply(stale)
        self.assertEqual(caught.exception.code, 'stale_revision')
        self.assertEqual(self.vault.history(first_id)[-1]['body'], 'New owner text')

    def test_root_move_preserves_ids_but_projects_and_collections_are_isolated(self):
        from remember_dammit.importing import plan_import
        (self.source / 'a.md').write_text('Content', encoding='utf-8')
        first = self.plan()
        moved = self.root / 'moved'
        shutil.copytree(self.source, moved)
        second = plan_import(moved, collection='notes', scope='project:atlas')
        self.assertEqual(first['files'][0]['record_id'], second['files'][0]['record_id'])
        self.apply(first)
        self.apply(second)
        for collection, scope in [('notes', 'project:beacon'), ('other', 'project:atlas')]:
            self.apply(plan_import(moved, collection=collection, scope=scope))
        self.assertEqual(len(self.vault.list_records()), 3)

    def test_partial_failure_reports_completed_index_and_retries_without_duplicates(self):
        (self.source / 'a.md').write_text('First', encoding='utf-8')
        (self.source / 'b.md').write_text('Second', encoding='utf-8')
        plan = self.plan()
        original = self.vault.put
        def interrupted(**kwargs):
            if kwargs['title'] == 'b.md':
                raise VaultError('storage_error', 'Injected interruption')
            return original(**kwargs)
        with patch.object(self.vault, 'put', side_effect=interrupted):
            partial = self.apply(plan)
        self.assertEqual(partial['status'], 'partial')
        self.assertEqual(partial['failed_index'], 1)
        self.assertEqual(len(partial['completed']), 1)
        self.assertTrue(partial['retry_same_plan'])
        complete = self.apply(plan)
        self.assertEqual(complete['status'], 'complete')
        self.assertEqual(len(self.vault.list_records()), 2)

    def test_acknowledged_commit_followed_by_error_is_retryable(self):
        (self.source / 'a.md').write_text('First', encoding='utf-8')
        plan = self.plan()
        original = self.vault.put
        def interrupted(**kwargs):
            original(**kwargs)
            raise OSError('injected after commit')
        with patch.object(self.vault, 'put', side_effect=interrupted):
            partial = self.apply(plan)
        self.assertEqual(partial['status'], 'partial')
        self.assertEqual(partial['failed_index'], 0)
        self.assertEqual(self.apply(plan)['status'], 'complete')
        self.assertEqual(len(self.vault.list_records()), 1)

    def test_excludes_hidden_cache_invalid_utf8_and_portable_paths(self):
        for directory in ('.obsidian', 'node_modules', '__pycache__'):
            (self.source / directory).mkdir()
            (self.source / directory / 'secret.md').write_text('Secret', encoding='utf-8')
        (self.source / 'visible.md').write_text('Visible', encoding='utf-8')
        (self.source / 'invalid.md').write_bytes(b'\xff')
        (self.source / 'empty.md').write_text(' \n', encoding='utf-8')
        (self.source / 'bad name .md').write_text('Bad filename', encoding='utf-8')
        plan = self.plan()
        self.assertEqual([f['path'] for f in plan['files']], ['bad name .md', 'visible.md'])
        reasons = {e['path']: e['reason'] for e in plan['excluded']}
        self.assertEqual(reasons['invalid.md'], 'invalid_utf8')
        self.assertEqual(reasons['empty.md'], 'empty')
        self.assertEqual(reasons['node_modules'], 'excluded_directory')

    def test_symlinks_and_junctions_are_excluded_without_reading_targets(self):
        (self.source / 'safe.md').write_text('Safe', encoding='utf-8')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'private.md').write_text('Private', encoding='utf-8')
        link = self.source / 'linked'
        if os.name == 'nt':
            import subprocess
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.addCleanup(lambda: os.rmdir(link))
        else:
            link.symlink_to(outside, target_is_directory=True)
        plan = self.plan()
        self.assertEqual([f['path'] for f in plan['files']], ['safe.md'])
        self.assertIn({'path': 'linked', 'reason': 'link'}, plan['excluded'])

    def test_case_collision_excludes_both_paths(self):
        (self.source / 'A.md').write_text('First', encoding='utf-8')
        (self.source / 'a.md').write_text('Second', encoding='utf-8')
        if len(list(self.source.iterdir())) != 2:
            self.skipTest('Filesystem is case insensitive')
        plan = self.plan()
        self.assertEqual(plan['files'], [])
        self.assertEqual({e['reason'] for e in plan['excluded']}, {'case_collision'})

    def test_absolute_root_valid_scope_and_plan_integrity_required(self):
        from remember_dammit.importing import plan_import
        for source, collection, scope in [('relative', 'notes', 'personal'), (self.source, '../bad', 'personal'),
                                           (self.source, 'notes', 'project:../bad')]:
            with self.assertRaises(VaultError):
                plan_import(source, collection=collection, scope=scope)
        (self.source / 'a.md').write_text('Text', encoding='utf-8')
        plan = self.plan()
        plan['files'][0]['path'] = '../outside.md'
        with self.assertRaises(VaultError):
            self.apply(plan)
        self.assertEqual(self.vault.list_records(), [])

    def test_bounded_file_size_and_scan_count(self):
        from remember_dammit import importing
        (self.source / 'large.md').write_bytes(b'x' * 20)
        with patch.object(importing, 'MAX_FILE_BYTES', 10):
            self.assertEqual(self.plan()['excluded'], [{'path': 'large.md', 'reason': 'too_large'}])
        for name in ('a.md', 'b.md'):
            (self.source / name).write_text('Text', encoding='utf-8')
        with patch.object(importing, 'MAX_ENTRIES', 2):
            with self.assertRaises(VaultError) as caught:
                self.plan()
            self.assertEqual(caught.exception.code, 'import_limit')

    def test_preview_cannot_exceed_the_plan_read_budget(self):
        from remember_dammit import importing
        (self.source / 'a.md').write_text('Text', encoding='utf-8')
        with patch.object(importing, 'MAX_PLAN_BYTES', 100):
            with self.assertRaises(VaultError) as caught:
                self.plan()
        self.assertEqual(caught.exception.code, 'import_limit')

    def test_canonical_target_cannot_be_inside_source(self):
        from remember_dammit.importing import plan_import
        nested = Vault.initialize(self.source / 'nested')
        with self.assertRaises(VaultError):
            plan_import(self.source, collection='notes', scope='personal', vault=nested)

    def test_target_lock_namespace_cannot_be_inside_source(self):
        from remember_dammit.importing import plan_import
        locks = self.vault.root.parent / '.remember-dammit-locks'
        with self.assertRaises(VaultError):
            plan_import(locks, collection='notes', scope='personal', vault=self.vault)

    def test_source_edit_during_target_preflight_is_refused_before_writes(self):
        note = self.source / 'a.md'
        note.write_text('Original', encoding='utf-8')
        plan = self.plan()
        original = self.vault.history
        def changed(identifier):
            note.write_text('Changed during target preflight', encoding='utf-8')
            return original(identifier)
        with patch.object(self.vault, 'history', side_effect=changed):
            with self.assertRaises(VaultError) as caught:
                self.apply(plan)
        self.assertEqual(caught.exception.code, 'source_changed')
        self.assertEqual(self.vault.list_records(), [])

    def test_modified_plan_cannot_claim_noop_for_different_source_body(self):
        # Local checksums are not authority; validate meaning as well as digest.
        def digest(value):
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        note = self.source / 'a.md'
        note.write_text('Original', encoding='utf-8')
        self.apply(self.plan())
        note.write_text('Changed', encoding='utf-8')
        plan = self.plan(vault=self.vault)
        item = plan['files'][0]
        item['action'] = 'noop'
        request = {key: value for key, value in item.items() if key != 'operation_id'}
        item['operation_id'] = 'import-' + digest({'collection': 'notes', 'scope': 'project:atlas', **request})
        plan['plan_id'] = digest({key: value for key, value in plan.items() if key != 'plan_id'})
        with self.assertRaises(VaultError) as caught:
            self.apply(plan)
        self.assertEqual(caught.exception.code, 'invalid_plan')
        self.assertEqual(self.vault.list_records()[0]['body'], 'Original')

    def test_rechecks_plan_shape_even_when_local_checksum_is_recomputed(self):
        def digest(value):
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        (self.source / 'a.md').write_text('Original', encoding='utf-8')
        plan = self.plan()
        item = plan['files'][0]
        del item['sha256']
        request = {key: value for key, value in item.items() if key != 'operation_id'}
        item['operation_id'] = 'import-' + digest({'collection': 'notes', 'scope': 'project:atlas', **request})
        plan['plan_id'] = digest({key: value for key, value in plan.items() if key != 'plan_id'})
        with self.assertRaises(VaultError) as caught:
            self.apply(plan)
        self.assertEqual(caught.exception.code, 'invalid_plan')
        self.assertEqual(self.vault.list_records(), [])

    def test_recursion_depth_plan_raises_structured_error_before_writes(self):
        (self.source / 'a.md').write_text('Original', encoding='utf-8')
        plan = self.plan()
        nested = []
        for _ in range(10000):
            nested = [nested]
        plan['files'] = nested
        with self.assertRaises(VaultError) as caught:
            self.apply(plan)
        self.assertEqual(caught.exception.code, 'invalid_plan')
        self.assertEqual(self.vault.list_records(), [])

    def test_target_preflight_refuses_late_conflict_before_writing_first_file(self):
        (self.source / 'a.md').write_text('First', encoding='utf-8')
        (self.source / 'b.md').write_text('Second', encoding='utf-8')
        plan = self.plan()
        self.vault.put(record_id=plan['files'][1]['record_id'], title='Collision', body='Owner text', scope='project:atlas')
        with self.assertRaises(VaultError) as caught:
            self.apply(plan)
        self.assertEqual(caught.exception.code, 'import_conflict')
        self.assertEqual(len(self.vault.list_records()), 1)

    def test_partial_update_retry_and_two_previews_do_not_fork_lineage(self):
        for name in ('a.md', 'b.md'):
            (self.source / name).write_text('Original ' + name, encoding='utf-8')
        initial = self.plan()
        self.apply(initial)
        for name in ('a.md', 'b.md'):
            (self.source / name).write_text('Changed ' + name, encoding='utf-8')
        update = self.plan(vault=self.vault)
        other_preview = self.plan(vault=self.vault)
        original = self.vault.correct
        def interrupted(record_id, **kwargs):
            if kwargs['title'] == 'b.md':
                raise VaultError('storage_error', 'Injected interruption')
            return original(record_id, **kwargs)
        with patch.object(self.vault, 'correct', side_effect=interrupted):
            partial = self.apply(update)
        self.assertEqual(partial['failed_index'], 1)
        self.assertEqual(self.apply(update)['status'], 'complete')
        self.assertEqual(self.apply(other_preview)['status'], 'complete')
        for item in initial['files']:
            self.assertEqual(len(self.vault.history(item['record_id'])), 2)

    def test_unadmitted_nonportable_filename_reported(self):
        if os.name == 'nt':
            self.skipTest('Windows cannot create this nonportable fixture')
        (self.source / 'bad:name.md').write_text('Content', encoding='utf-8')
        plan = self.plan()
        self.assertEqual(plan['files'], [])
        self.assertEqual(plan['excluded'], [{'path': 'bad:name.md', 'reason': 'nonportable_path'}])

    def test_raw_text_stays_private_and_source_tree_is_unchanged(self):
        from remember_dammit.importing import plan_import, apply_import
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'source'
            source.mkdir()
            (source / '.obsidian').mkdir()
            (source / '.obsidian' / 'settings.json').write_bytes(b'{"secret":true}')
            raw = '---\nscope: shared\ndisclosure: public\nremote_allowed: true\n---\n# Secret\nRaw text.\n'
            (source / 'Note.md').write_bytes(raw.encode())
            before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            plan = plan_import(source, collection='notes', scope='project:atlas')
            self.assertEqual([f['path'] for f in plan['files']], ['Note.md'])
            self.assertEqual(plan['files'][0]['sha256'], hashlib.sha256(raw.encode()).hexdigest())
            self.assertEqual(plan['excluded'][0]['path'], '.obsidian')
            vault = Vault.initialize(root / 'target')
            result = apply_import(vault, plan)
            self.assertEqual(result['status'], 'complete')
            record = vault.list_records()[0]
            self.assertEqual(record['body'], raw)
            self.assertEqual(record['scope'], 'project:atlas')
            self.assertEqual(record['evidence'], 'source-excerpt')
            self.assertEqual(record['disclosure'], 'private')
            self.assertFalse(record['remote_allowed'])
            apply_import(vault, plan)
            self.assertEqual(len(vault.list_records()), 1)
            self.assertEqual(before, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()
