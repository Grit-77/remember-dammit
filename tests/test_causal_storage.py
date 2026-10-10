"""Causal behavior tested with intact, independently writable disk copies."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


def union(source, target):
    for path in (source / '.remember').rglob('*'):
        if path.is_file():
            dest = target / path.relative_to(source)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                assert dest.read_bytes() == path.read_bytes()
            else:
                shutil.copyfile(path, dest)


class CausalStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.v = Vault.initialize(self.root / 'seed')

    def fork(self, name):
        shutil.copytree(self.v.root, self.root / name)
        return Vault(self.root / name)

    def note(self, vault=None, **kwargs):
        return (vault or self.v).put(title='Base', body='Original bytes', scope='shared',
                                     **kwargs)

    def assertCode(self, code, function, *args, **kwargs):
        with self.assertRaises(VaultError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def test_default_has_no_portable_mutable_checkpoint(self):
        self.note()
        self.assertEqual(json.loads((self.v.root / '.remember/vault.json').read_bytes())['schema'], 2)
        self.assertFalse((self.v.root / '.remember/head.json').exists())

    def test_raw_union_concurrent_corrections_and_resolution(self):
        base = self.note(record_id='base')
        a, b = self.fork('a'), self.fork('b')
        left = a.correct('base', expected_revision=base['revision'], title='Left', body='Left bytes')
        right = b.correct('base', expected_revision=base['revision'], title='Right', body='Right bytes')
        union(b.root, a.root)
        union(a.root, b.root)
        self.assertEqual(a.snapshot_id(), b.snapshot_id())
        self.assertEqual({r['id'] for r in a.heads('base')}, {left['id'], right['id']})
        self.assertEqual(a.get('base')['state'], 'superseded')
        self.assertCode('stale_revision', a.correct, left['id'], expected_revision=left['revision'], title='bad', body='bad')
        observed = [{k: r[k] for k in ('id', 'revision')} for r in a.heads('base')]
        result = a.resolve('base', expected_heads=observed, title='Resolved', body='Both checked')
        self.assertEqual([r['id'] for r in a.heads('base')], [result['id']])
        self.assertIsNone(result['supersedes'])
        self.assertEqual(set(result['supersedes_all']), {left['id'], right['id']})
        self.assertEqual({r['body'] for r in a.history(right['id'])},
                         {'Original bytes', 'Left bytes', 'Right bytes', 'Both checked'})
        for record in a.history('base'):
            self.assertEqual(record['lineage_id'], 'base')

    def test_late_branch_remains_a_head_and_stale_preview_rejected(self):
        base = self.note(record_id='base')
        a, b, c = self.fork('a'), self.fork('b'), self.fork('c')
        for vault, label in ((a, 'a'), (b, 'b'), (c, 'c')):
            vault.correct('base', expected_revision=base['revision'], title=label, body=label)
        union(b.root, a.root)
        preview = [{k: r[k] for k in ('id', 'revision')} for r in a.heads('base')]
        resolved = a.resolve('base', expected_heads=preview, title='ab', body='ab')
        union(c.root, a.root)
        self.assertEqual({r['title'] for r in a.heads('base')}, {'ab', 'c'})
        self.assertCode('stale_heads', a.resolve, 'base', expected_heads=preview, title='old', body='old')
        self.assertEqual(a.get(resolved['id'])['state'], 'active')

    def test_delete_wins_concurrent_correction_and_preserves_history(self):
        base = self.note(record_id='base')
        a, b = self.fork('a'), self.fork('b')
        a.retract('base', expected_heads=[{'id': 'base', 'revision': base['revision']}])
        descendant = b.correct('base', expected_revision=base['revision'], title='Offline', body='Preserved')
        union(b.root, a.root)
        union(a.root, b.root)
        for vault in (a, b):
            self.assertEqual({r['state'] for r in vault.history('base')}, {'retracted'})
            self.assertEqual(vault.get(descendant['id'])['body'], 'Preserved')
            self.assertCode('stale_revision', vault.correct, descendant['id'], expected_revision=descendant['revision'], title='revive', body='revive')

    def test_revoke_wins_concurrent_grant_and_causal_source_capture(self):
        personal = self.v.put(title='Personal', body='Private', scope='personal', record_id='p')
        self.v.grant('one', 'p')
        a, b = self.fork('a'), self.fork('b')
        a.revoke('one', 'p')
        b.grant('one', 'p')
        derived = b.put(title='Derived', body='Allowed when written', scope='project:one', sources=['p'])
        union(b.root, a.root)
        self.assertEqual(a.grants_for('one'), set())
        self.assertEqual(a.get(derived['id'])['body'], 'Allowed when written')
        self.assertCode('source_scope', a.put, title='Denied now', body='Denied', scope='project:one', sources=['p'])
        a.grant('one', 'p')
        self.assertEqual(a.grants_for('one'), {'p'})
        corrected = a.correct('p', expected_revision=personal['revision'], title='New personal', body='New private')
        self.assertNotIn(corrected['id'], a.grants_for('one'))

    def test_missing_acknowledged_leaf_parent_or_payload_is_incomplete(self):
        self.note(record_id='base')
        for what in ('leaf', 'payload'):
            branch = self.fork(what)
            directory = 'operations' if what == 'leaf' else 'revisions'
            next((branch.root / '.remember' / directory).iterdir()).unlink()
            self.assertCode('incomplete_transfer', branch.list_records)
        branch = self.fork('parent')
        branch.put(title='Child', body='Child', scope='shared')
        nodes = branch._load()['operation_nodes']
        parent = next(op['digest'] for op in nodes.values() if not op['parents'])
        (branch.root / '.remember/operations' / (parent + '.json')).unlink()
        self.assertCode('incomplete_transfer', branch.list_records)

    def test_same_operation_retry_receipt_and_ambiguous_offline_id(self):
        request = dict(title='First', body='First', scope='shared', operation_id='stable')
        receipt = self.v.put(**request)
        self.v.correct(receipt['id'], expected_revision=receipt['revision'], title='Later', body='Later')
        self.assertEqual(self.v.put(**request), receipt)
        self.assertCode('operation_conflict', self.v.put, **{**request, 'body': 'Different'})
        a, b = self.fork('a'), self.fork('b')
        a.put(title='A', body='A', scope='shared', operation_id='colliding')
        b.put(title='B', body='B', scope='shared', operation_id='colliding')
        union(b.root, a.root)
        self.assertEqual(len(a.list_records()), 4)
        self.assertIn('colliding', a._load()['operation_conflicts'])
        self.assertCode('operation_conflict', a.put, title='A', body='A', scope='shared', operation_id='colliding')
        self.assertFalse(a.doctor()['ok'])

    def test_marker_crash_retry_repairs_ack_and_preserves_exact_receipt(self):
        from remember_dammit import storage_v2
        original = storage_v2._publish
        def fail_ack(path, data):
            if path.parent.name == 'acks':
                raise OSError('simulated interruption after marker')
            return original(path, data)
        request = dict(title='Crash', body='Crash bytes', scope='shared', operation_id='crash')
        with patch.object(storage_v2, '_publish', fail_ack):
            self.assertCode('storage_error', self.v.put, **request)
        record = self.v.list_records()[0]
        self.assertEqual(self.v.put(**request), record)
        self.assertTrue(self.v.doctor()['ok'])
        self.assertTrue(list((self.v.root / '.remember/acks').glob('*.json')))

    def test_changed_bytes_fail_integrity_and_orphan_never_admitted(self):
        record = self.note()
        orphan = self.v.root / '.remember/revisions' / ('0' * 64 + '.md')
        orphan.write_bytes(b'orphan bytes')
        self.assertEqual(len(self.v.list_records()), 1)
        self.assertIn(orphan.relative_to(self.v.root).as_posix(), self.v.doctor()['orphan_payloads'])
        (self.v.root / record['path']).write_bytes(b'changed')
        self.assertCode('integrity_error', self.v.list_records)
        self.assertEqual(orphan.read_bytes(), b'orphan bytes')

    def test_explicit_v1_stays_read_write_compatible(self):
        old = Vault.initialize(self.root / 'v1', format_version=1)
        record = self.note(old)
        self.assertEqual(Vault(old.root).get(record['id']), record)
        self.assertEqual(json.loads((old.root / '.remember/vault.json').read_bytes())['schema'], 1)

    def test_deterministic_conversion_and_incomplete_marker_blocks_public_open(self):
        from remember_dammit.storage_v2 import convert_v1_to_v2
        old = Vault.initialize(self.root / 'old', format_version=1)
        personal = old.put(title='Private', body='Private bytes', scope='personal',
                           record_id='personal', operation_id='original-put')
        old.grant('one', 'personal', operation_id='original-grant')
        old.revoke('one', 'personal', operation_id='original-revoke')
        source_bytes = {p.relative_to(old.root).as_posix(): p.read_bytes()
                        for p in old.root.rglob('*') if p.is_file()}
        destination = self.root / 'converted'
        destination.mkdir()
        marker = destination / '.migration-INCOMPLETE.json'
        marker.write_text('{}', encoding='utf-8')
        converted = convert_v1_to_v2(old.root, destination)
        self.assertEqual(converted.get('personal')['revision'], personal['revision'])
        self.assertEqual(converted.grants_for('one'), set())
        self.assertCode('incomplete_transfer', Vault, destination)
        marker.unlink()
        reopened = Vault(destination)
        second = convert_v1_to_v2(old.root, self.root / 'converted-again')
        self.assertEqual(reopened.snapshot_id(), second.snapshot_id())
        self.assertEqual(reopened.vault_id, old.vault_id)
        self.assertEqual(source_bytes, {p.relative_to(old.root).as_posix(): p.read_bytes()
                        for p in old.root.rglob('*') if p.is_file()})

    def test_record_identity_collision_fails_closed_without_losing_bytes(self):
        a, b = self.fork('a'), self.fork('b')
        self.note(a, record_id='same')
        b.put(title='Different', body='Different bytes', scope='shared', record_id='same')
        union(b.root, a.root)
        self.assertCode('identity_conflict', a.list_records)
        self.assertEqual(len(list((a.root / '.remember/revisions').glob('*.md'))), 2)

    def test_exact_correct_retry_ignores_stale_snapshot_but_new_write_is_guarded(self):
        base = self.note(record_id='base')
        snapshot = self.v.snapshot_id()
        request = dict(expected_revision=base['revision'], title='Corrected', body='Corrected',
                       operation_id='correct-once', expected_snapshot=snapshot)
        corrected = self.v.correct('base', **request)
        self.note(record_id='unrelated')
        self.assertEqual(self.v.correct('base', **request), corrected)
        self.assertCode('source_changed', self.v.correct, corrected['id'],
                        expected_revision=corrected['revision'], title='Guarded', body='Guarded',
                        expected_snapshot=snapshot)

    def test_all_observed_operation_heads_are_parents_of_new_write(self):
        self.note(record_id='base')
        a, b = self.fork('a'), self.fork('b')
        self.note(a, record_id='left')
        self.note(b, record_id='right')
        union(b.root, a.root)
        frontier = a.operation_heads()
        self.assertEqual(len(frontier), 2)
        receipt = self.note(a, record_id='joins-observed')
        new = a._load()['operations'][next(opid for opid, op in a._load()['operations'].items()
                                       if op['result'].get('id') == receipt['id'])]
        self.assertEqual(new['parents'], frontier)

    def test_payload_stage_crash_leaves_orphan_and_retry_admits_once(self):
        request = dict(title='Crash', body='Crash bytes', scope='shared', operation_id='payload-crash')
        with patch.object(type(self.v), '_commit', side_effect=OSError('before publication')):
            self.assertCode('storage_error', self.v.put, **request)
        self.assertEqual(self.v.list_records(), [])
        orphans = self.v.doctor()['orphan_payloads']
        self.assertEqual(len(orphans), 1)
        receipt = self.v.put(**request)
        self.assertEqual(self.v.put(**request), receipt)
        self.assertEqual(len(self.v.list_records()), 1)
        self.assertTrue((self.v.root / orphans[0]).exists())

    def test_immutable_publication_refuses_arrival_at_atomic_boundary(self):
        from remember_dammit.storage_v2 import _publish
        destination = self.root / 'immutable-object'
        replace, link = os.replace, os.link
        def arrive_then_publish(original):
            def publish(source, target, *args, **kwargs):
                if Path(target) == destination and not destination.exists():
                    destination.write_bytes(b'external complete object')
                return original(source, target, *args, **kwargs)
            return publish
        with patch.object(os, 'replace', arrive_then_publish(replace)), patch.object(os, 'link', arrive_then_publish(link)):
            self.assertCode('integrity_error', _publish, destination, b'local complete object')
        self.assertEqual(destination.read_bytes(), b'external complete object')

    def test_incomplete_marker_before_config_refuses_public_open(self):
        destination = self.root / 'crashed-before-config'
        destination.mkdir()
        (destination / '.migration-INCOMPLETE.json').write_text('{}', encoding='utf-8')
        self.assertCode('incomplete_transfer', Vault, destination)

    def test_deep_malformed_committed_json_is_structured_integrity_error(self):
        self.note()
        operation = next((self.v.root / '.remember/operations').glob('*.json'))
        operation.write_bytes(b'[' * 2000 + b'0' + b']' * 2000)
        self.assertCode('integrity_error', self.v.list_records)

    def test_missing_terminal_revocation_cannot_restore_disclosure(self):
        personal = self.v.put(title='Private', body='Secret bytes', scope='personal')
        self.v.grant('one', personal['id'])
        self.v.revoke('one', personal['id'], operation_id='terminal-revoke')
        revoke = self.v._load()['operations']['terminal-revoke']['digest']
        (self.v.root / '.remember/operations' / (revoke + '.json')).unlink()
        self.assertCode('incomplete_transfer', self.v.grants_for, 'one')
        self.assertFalse(self.v.doctor()['ok'])

    def test_real_process_death_at_payload_marker_and_ack_boundaries(self):
        script = '''import os,stat,sys
from pathlib import Path
from remember_dammit.storage import Vault
root,stage=sys.argv[1:]
real_fsync,real_link=os.fsync,os.link
flushes=0
def fsync(fd):
 global flushes
 real_fsync(fd)
 if stat.S_ISREG(os.fstat(fd).st_mode):
  flushes+=1
  if stage=={1:'payload_flush',2:'marker_flush',3:'ack_flush'}.get(flushes):
   os._exit(73)
def link(source,target,*args,**kwargs):
 real_link(source,target,*args,**kwargs)
 if stage=={'revisions':'payload_publish','operations':'marker_publish','acks':'ack_publish'}.get(Path(target).parent.name):
  os._exit(73)
os.fsync,os.link=fsync,link
Vault(root).put(title='Crash',body='Original crashed bytes',scope='personal',record_id='crash-note',operation_id='crash')
'''
        for stage in ('payload_flush', 'payload_publish', 'marker_flush', 'marker_publish', 'ack_flush', 'ack_publish'):
            with self.subTest(stage=stage):
                vault = Vault.initialize(self.root / stage)
                process = subprocess.run([sys.executable, '-c', script, str(vault.root), stage],
                                         capture_output=True, text=True, timeout=15)
                self.assertEqual(process.returncode, 73, process.stderr)
                before = Vault(vault.root).list_records()
                self.assertEqual(len(before), 1 if stage in ('marker_publish', 'ack_flush', 'ack_publish') else 0)
                receipt = vault.put(title='Crash', body='Original crashed bytes', scope='personal',
                                    record_id='crash-note', operation_id='crash')
                self.assertEqual(len(vault.list_records()), 1)
                if before:
                    self.assertEqual(receipt, before[0])
                self.assertEqual(vault.doctor()['unacknowledged_operations'], [])
                self.assertTrue(vault.doctor()['uncommitted_files'])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction behavior')
    def test_python311_root_junction_is_rejected_without_following_alias(self):
        alias = self.root / 'junction-alias'
        process = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.v.root)],
                                 capture_output=True, text=True, timeout=10)
        if process.returncode:
            self.skipTest('Host cannot create junctions: ' + process.stderr)
        with patch.object(Path, 'is_junction', None, create=True):
            self.assertCode('invalid_vault', Vault, alias)
        self.assertTrue((self.v.root / '.remember/vault.json').exists())

    def test_partial_personal_grant_does_not_authorize_indirect_sources(self):
        deep = self.v.put(title='Private source', body='Private detail.', scope='personal')
        direct = self.v.put(title='Personal summary', body='Based on private detail.', scope='personal', sources=[deep['id']])
        self.v.grant('atlas', direct['id'])
        before = self.v.snapshot_id()
        with self.assertRaises(VaultError) as raised:
            self.v.put(title='Project note', body='Cannot cite an unreadable chain.', scope='project:atlas', sources=[direct['id']])
        self.assertEqual(raised.exception.code, 'source_scope')
        self.assertEqual(self.v.snapshot_id(), before)
        self.v.grant('atlas', deep['id'])
        admitted = self.v.put(title='Project note', body='Both sources were explicitly granted.', scope='project:atlas', sources=[direct['id']])
        self.assertEqual(admitted['sources'], [direct['id']])

    def test_new_writes_recheck_revoked_transitive_sources(self):
        self.v.put(title='Private', body='Private bytes', scope='personal', record_id='p')
        self.v.grant('one', 'p')
        direct = self.v.put(title='Direct', body='Direct capture', scope='project:one', sources=['p'])
        base = self.v.put(title='Indirect', body='Indirect capture', scope='project:one', sources=[direct['id']])
        a, b = self.fork('a'), self.fork('b')
        a.correct(base['id'], expected_revision=base['revision'], title='Left', body='Left')
        b.correct(base['id'], expected_revision=base['revision'], title='Right', body='Right')
        b.revoke('one', 'p')
        union(b.root, a.root)
        self.assertEqual({r['title'] for r in a.heads(base['id'])}, {'Left', 'Right'})
        observed = [{k: r[k] for k in ('id', 'revision')} for r in a.heads(base['id'])]
        self.assertCode('source_scope', a.put, title='New', body='New', scope='project:one', sources=[direct['id']])
        self.assertCode('source_scope', a.correct, direct['id'], expected_revision=direct['revision'], title='New', body='New')
        self.assertCode('source_scope', a.resolve, base['id'], expected_heads=observed, title='Resolve', body='Resolve')
        resolved = a.resolve(base['id'], expected_heads=observed, title='Explicit source choice',
                             body='Owner supplies a new independent statement', sources=[])
        self.assertEqual(resolved['sources'], [])

    def test_legacy_transitive_capture_remains_readable_after_explicit_conversion(self):
        from remember_dammit.storage_v2 import convert_v1_to_v2
        old = Vault.initialize(self.root / 'old', format_version=1)
        personal = old.put(title='Private', body='Private', scope='personal')
        old.grant('one', personal['id'])
        direct = old.put(title='Direct', body='Direct', scope='project:one', sources=[personal['id']])
        old.revoke('one', personal['id'])
        historical = old.put(title='Legacy capture', body='Preserved legacy capture', scope='project:one', sources=[direct['id']])
        converted = convert_v1_to_v2(old.root, self.root / 'converted')
        self.assertEqual(converted.get(historical['id'])['body'], 'Preserved legacy capture')
        self.assertCode('source_scope', converted.put, title='New', body='New', scope='project:one', sources=[historical['id']])


if __name__ == '__main__':
    unittest.main()
