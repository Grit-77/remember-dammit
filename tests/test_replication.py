"""Synthetic, offline transport acceptance; no sync client or live vault."""
import hashlib
import importlib
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


def inventory(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in (root / '.remember').rglob('*') if p.is_file()}


class OfflineTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Resolve the OS temporary-directory alias for positive fixtures only;
        # deliberate links created by rejection tests remain unresolved.
        self.base = Path(self.temp.name).resolve()
        try:
            self.transfer = importlib.import_module('remember_dammit.replication')
        except ModuleNotFoundError:
            self.transfer = None
        self.assertIsNotNone(self.transfer, 'Explicit offline transfer must be implemented.')
        self.seed = Vault.initialize(self.base / 'seed')
        self.root = self.seed.put(title='Seed', body='Common seed.', scope='shared',
                                  record_id='seed', operation_id='seed-put')

    def fork(self, name):
        path = self.base / name
        shutil.copytree(self.seed.root, path)
        return Vault(path)

    def exchange(self, source, target, name):
        bundle = self.base / name
        self.transfer.export_bundle(source, bundle)
        return self.transfer.import_bundle(target, bundle)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(VaultError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_independent_adds_merge_in_both_orders_and_idempotently(self):
        a, b = self.fork('a'), self.fork('b')
        a.put(title='A', body='A project bytes.', scope='project:a', record_id='a')
        b.put(title='B', body='B project bytes.', scope='project:b', record_id='b')
        snapshots = []
        for order in ((a, b), (b, a)):
            target = self.fork('merged-' + str(len(snapshots)))
            for index, source in enumerate(order):
                receipt = self.exchange(source, target, f'adds-{len(snapshots)}-{index}')
                self.assertTrue(receipt['complete'])
            snapshot = target.snapshot_id()
            self.exchange(order[0], target, f'repeat-{len(snapshots)}')
            self.assertEqual(target.snapshot_id(), snapshot)
            self.assertEqual({r['id']: (r['scope'], r['body']) for r in target.list_records()},
                             {'seed': ('shared', 'Common seed.'),
                              'a': ('project:a', 'A project bytes.'),
                              'b': ('project:b', 'B project bytes.')})
            snapshots.append(snapshot)
        self.assertEqual(*snapshots)

    def test_correction_heads_and_stale_resolution_after_third_arrival(self):
        a, b, c = [self.fork(n) for n in ('a', 'b', 'c')]
        branches = []
        for name, branch in zip(('A', 'B', 'C'), (a, b, c)):
            branches.append(branch.correct('seed', expected_revision=self.root['revision'], title=name,
                                           body=f'{name} correction.'))
        self.exchange(a, b, 'a-to-b')
        expected = [{'id': r['id'], 'revision': r['revision']} for r in b.heads('seed')]
        self.assertEqual({r['id'] for r in b.heads('seed')}, {r['id'] for r in branches[:2]})
        self.exchange(c, b, 'c-to-b')
        before = inventory(b.root)
        self.assert_code('stale_heads', b.resolve, 'seed', expected_heads=expected,
                         title='Merged', body='Resolution.')
        self.assertEqual(inventory(b.root), before)
        resolved = b.resolve('seed', expected_heads=[{'id': r['id'], 'revision': r['revision']}
                                                    for r in b.heads('seed')],
                             title='Merged', body='Resolution.')
        self.assertEqual([r['id'] for r in b.heads('seed')], [resolved['id']])
        self.assertEqual(len(b.history('seed')), 5)

    def test_three_copies_permuted_repeated_transfers_converge(self):
        copies = [self.fork(name) for name in ('a', 'b', 'c')]
        for index, copy in enumerate(copies):
            copy.put(title=f'Branch {index}', body=f'Independent bytes {index}.',
                     scope='shared', record_id=f'branch-{index}')
        expected = None
        for number, permutation in enumerate(itertools.permutations(range(3))):
            target = self.fork(f'target-{number}')
            for iteration, index in enumerate(permutation + permutation):
                self.exchange(copies[index], target, f'permutation-{number}-{iteration}')
            actual = (target.snapshot_id(), target.list_records())
            if expected is None:
                expected = actual
            self.assertEqual(actual, expected)

    def test_both_correction_merge_orders_and_unseen_head_after_resolution(self):
        a, b, c = [self.fork(name) for name in ('a', 'b', 'c')]
        corrected = [v.correct('seed', expected_revision=self.root['revision'], title=name,
                               body=f'{name} exact correction bytes.')
                     for v, name in zip((a, b, c), ('A', 'B', 'C'))]
        snapshots = []
        for index, order in enumerate(((a, b), (b, a))):
            target = self.fork(f'merged-{index}')
            for number, branch in enumerate(order):
                self.exchange(branch, target, f'corrected-{index}-{number}')
            self.assertEqual({r['id'] for r in target.heads('seed')},
                             {r['id'] for r in corrected[:2]})
            self.assertEqual({r['body'] for r in target.heads('seed')},
                             {r['body'] for r in corrected[:2]})
            snapshots.append(target.snapshot_id())
        self.assertEqual(*snapshots)
        resolved = target.resolve('seed', expected_heads=[{'id': r['id'], 'revision': r['revision']}
                                                          for r in target.heads('seed')],
                                  title='Resolved', body='Observed two heads.')
        self.exchange(c, target, 'unseen-after-resolution')
        self.assertEqual({r['id'] for r in target.heads('seed')}, {resolved['id'], corrected[2]['id']})
        self.assertEqual(len(target.history('seed')), 5)

    def test_operation_id_conflict_is_visible_and_identity_conflict_is_not_admitted(self):
        a, b = self.fork('a'), self.fork('b')
        a.put(title='A', body='A bytes.', scope='shared', record_id='a', operation_id='same-request')
        b.put(title='B', body='B bytes.', scope='shared', record_id='b', operation_id='same-request')
        self.exchange(a, b, 'request-collision')
        self.assertEqual({r['id'] for r in b.list_records()}, {'seed', 'a', 'b'})
        self.assertIn('same-request', b._load()['operation_conflicts'])
        self.assert_code('operation_conflict', b.put, title='B', body='B bytes.',
                         scope='shared', record_id='b', operation_id='same-request')
        c, d = self.fork('c'), self.fork('d')
        c.put(title='C', body='Different C bytes.', scope='shared', record_id='collision')
        d.put(title='D', body='Different D bytes.', scope='shared', record_id='collision')
        before = inventory(d.root)
        bundle = self.base / 'identity-collision'
        self.transfer.export_bundle(c, bundle)
        self.assert_code('identity_conflict', self.transfer.import_bundle, d, bundle)
        self.assertEqual(inventory(d.root), before)
        self.assertEqual(len(c.list_records()), 2)

    def test_export_snapshot_change_has_no_complete_marker(self):
        from unittest.mock import patch
        source = self.fork('source')
        destination = self.base / 'bundle'
        publish = self.transfer._publish_object
        changed = False
        def arrival(path, data):
            nonlocal changed
            result = publish(path, data)
            if not changed:
                changed = True
                source.put(title='External arrival', body='Arrived during export.', scope='shared')
            return result
        with patch.object(self.transfer, '_publish_object', side_effect=arrival):
            self.assert_code('stale_merge', self.transfer.export_bundle, source, destination)
        self.assertFalse((destination / 'COMPLETE.json').exists())
        self.assertEqual(len(source.list_records()), 2)

    def test_tombstone_and_revoke_survive_old_branch_and_later_explicit_grant(self):
        personal = self.seed.put(title='Private', body='Synthetic personal.', scope='personal')
        self.seed.grant('a', personal['id'])
        a, b = self.fork('a'), self.fork('b')
        a.delete('seed', expected_heads=[{'id': 'seed', 'revision': self.root['revision']}])
        a.revoke('a', personal['id'])
        corrected = b.correct('seed', expected_revision=self.root['revision'], title='Old branch', body='Retained.')
        b.grant('a', personal['id'])
        self.exchange(b, a, 'old-to-new')
        self.exchange(a, b, 'new-to-old')
        self.exchange(b, a, 'repeat-old')
        for vault in (a, b):
            self.assertTrue(all(r['state'] == 'retracted' for r in vault.history('seed')))
            self.assertNotIn(personal['id'], vault.grants_for('a'))
            self.assertTrue((vault.root / corrected['path']).exists())
        a.grant('a', personal['id'])
        self.exchange(a, b, 'regrant')
        self.assertIn(personal['id'], b.grants_for('a'))
        self.assertEqual(a.snapshot_id(), b.snapshot_id())

    def test_incomplete_and_corrupt_bundles_preserve_target(self):
        source, target = self.fork('source'), self.fork('target')
        added = source.put(title='Added', body='Immutable payload.', scope='shared')
        bundle = self.base / 'bundle'
        self.transfer.export_bundle(source, bundle)
        before = inventory(target.root)
        payload = bundle / added['path']
        sound = payload.read_bytes()
        payload.unlink()
        self.assert_code('incomplete_transfer', self.transfer.import_bundle, target, bundle)
        self.assertEqual(inventory(target.root), before)
        payload.write_bytes(sound + b'changed')
        self.assert_code('integrity_error', self.transfer.import_bundle, target, bundle)
        self.assertEqual(inventory(target.root), before)
        payload.write_bytes(sound)
        self.assertTrue(self.transfer.import_bundle(target, bundle)['complete'])

    def test_manifest_safety_identity_limits_and_stale_plan(self):
        source, target = self.fork('source'), self.fork('target')
        source.put(title='Added', body='Immutable payload.', scope='shared')
        bundle = self.base / 'bundle'
        self.transfer.export_bundle(source, bundle)
        complete = bundle / 'COMPLETE.json'
        original = complete.read_bytes()
        manifest = json.loads(original)
        manifest['entries'][0]['path'] = '../outside'
        unsigned = {k: v for k, v in manifest.items() if k != 'digest'}
        manifest['digest'] = hashlib.sha256(json.dumps(unsigned, sort_keys=True,
            ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        complete.write_text(json.dumps(manifest), encoding='utf-8')
        self.assert_code('invalid_bundle', self.transfer.import_bundle, target, bundle)
        complete.write_bytes(original)
        foreign = Vault.initialize(self.base / 'foreign')
        self.assert_code('vault_mismatch', self.transfer.import_bundle, foreign, bundle)
        self.assert_code('transfer_limit', self.transfer.import_bundle, target, bundle, max_files=1)
        plan = self.transfer.plan_merge(target, bundle)
        target.put(title='Arrived', body='Changed snapshot.', scope='shared')
        self.assert_code('stale_merge', self.transfer.apply_merge, target, plan)

    def test_process_interruption_retry_keeps_sound_payloads(self):
        source, target = self.fork('source'), self.fork('target')
        source.put(title='Added', body='Immutable payload.', scope='shared')
        bundle = self.base / 'bundle'
        self.transfer.export_bundle(source, bundle)
        script = '''import os, sys
from remember_dammit.storage import Vault
import remember_dammit.replication as r
original = r._publish_object
count = 0
def interrupted(path, data):
    global count
    original(path, data)
    count += 1
    if count == 2: os._exit(73)
r._publish_object = interrupted
r.import_bundle(Vault(sys.argv[1]), sys.argv[2])
'''
        result = subprocess.run([sys.executable, '-I', '-c', script, str(target.root), str(bundle)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 73, result.stderr)
        preserved = inventory(target.root)
        self.assertTrue(self.transfer.import_bundle(target, bundle)['complete'])
        after = inventory(target.root)
        for path, data in preserved.items():
            self.assertEqual(after[path], data)
        self.assertEqual(source.snapshot_id(), target.snapshot_id())
        self.assertEqual(len(target.list_records()), 2)

    def test_empty_vault_and_acknowledged_half_copy_can_be_repaired(self):
        empty = Vault.initialize(self.base / 'empty')
        empty_bundle = self.base / 'empty-bundle'
        self.assertTrue(self.transfer.export_bundle(empty, empty_bundle)['complete'])
        source, target = self.fork('source'), self.fork('target')
        source.put(title='Tail', body='Known tail payload.', scope='shared')
        objects = inventory(source.root)
        seed_objects = inventory(self.seed.root)
        tail = next(path for path in objects if '/operations/' in path and path not in seed_objects)
        for path, data in objects.items():
            if path != tail:
                destination = target.root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    destination.write_bytes(data)
        self.assert_code('incomplete_transfer', target.list_records)
        self.exchange(source, target, 'repair-half')
        self.assertEqual(source.snapshot_id(), target.snapshot_id())

    def test_hash_named_orphan_is_validated_without_deletion(self):
        source = self.fork('source')
        orphan = source.root / '.remember/revisions' / ('0' * 64 + '.md')
        orphan.write_bytes(b'Sound preservation requires matching its claimed digest.')
        self.assert_code('integrity_error', self.transfer.export_bundle, source, self.base / 'bundle')
        self.assertEqual(orphan.read_bytes(), b'Sound preservation requires matching its claimed digest.')

    def test_reported_partial_publication_resumes(self):
        from unittest.mock import patch
        source, target = self.fork('source'), self.fork('target')
        source.put(title='Added', body='Immutable payload.', scope='shared')
        bundle = self.base / 'bundle'
        self.transfer.export_bundle(source, bundle)
        publish = self.transfer._publish_object
        calls = 0
        def interruption(path, data):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('Synthetic publication interruption')
            return publish(path, data)
        with patch.object(self.transfer, '_publish_object', side_effect=interruption):
            receipt = self.transfer.import_bundle(target, bundle)
        self.assertFalse(receipt['complete'])
        self.assertEqual(receipt['code'], 'transfer_interrupted')
        preserved = inventory(target.root)
        self.assertTrue(self.transfer.import_bundle(target, bundle)['complete'])
        for path, data in preserved.items():
            self.assertEqual((target.root / path).read_bytes(), data)

    def test_unadvertised_directory_is_rejected(self):
        source, target = self.fork('source'), self.fork('target')
        bundle = self.base / 'bundle'
        self.transfer.export_bundle(source, bundle)
        (bundle / 'unadvertised').mkdir()
        before = inventory(target.root)
        self.assert_code('invalid_bundle', self.transfer.import_bundle, target, bundle)
        self.assertEqual(inventory(target.root), before)

    def test_linked_object_directory_is_rejected(self):
        source, target = self.fork('source'), self.fork('target')
        bundle = self.base / 'bundle'
        self.transfer.export_bundle(source, bundle)
        revisions = bundle / '.remember/revisions'
        external = self.base / 'external-revisions'
        self.assertTrue(revisions.resolve().is_relative_to(self.base.resolve()))
        self.assertTrue(external.resolve().is_relative_to(self.base.resolve()))
        revisions.rename(external)
        if os.name == 'nt':
            linked = subprocess.run(['cmd', '/c', 'mklink', '/J', str(revisions), str(external)],
                                    capture_output=True, text=True)
            self.assertEqual(linked.returncode, 0, linked.stderr)
        else:
            revisions.symlink_to(external, target_is_directory=True)
        before = inventory(target.root)
        self.assert_code('invalid_bundle', self.transfer.import_bundle, target, bundle)
        self.assertEqual(inventory(target.root), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows junctions require native reparse detection')
    def test_junction_rejection_without_pathlib_is_junction(self):
        # Python 3.11 lacks Path.is_junction: keep real NTFS junctions and bytes,
        # disable only the optional convenience method on a 3.12 test host.
        with patch.object(Path, 'is_junction', None, create=True):
            self.test_linked_object_directory_is_rejected()

    @unittest.skipUnless(os.name == 'nt', 'Windows junctions require native reparse detection')
    def test_export_rejects_junction_without_pathlib_is_junction(self):
        source = self.fork('junction-source')
        revisions = source.root / '.remember/revisions'
        external = self.base / 'external-source-revisions'
        self.assertTrue(revisions.resolve().is_relative_to(self.base))
        self.assertTrue(external.resolve().is_relative_to(self.base))
        revisions.rename(external)
        linked = subprocess.run(['cmd', '/c', 'mklink', '/J', str(revisions), str(external)],
                                capture_output=True, text=True)
        self.assertEqual(linked.returncode, 0, linked.stderr)
        before = inventory(source.root)
        with patch.object(Path, 'is_junction', None, create=True):
            self.assert_code('invalid_bundle', self.transfer.export_bundle,
                             source, self.base / 'junction-export')
        self.assertEqual(inventory(source.root), before)
        self.assertFalse((self.base / 'junction-export' / 'COMPLETE.json').exists())

    def test_preview_reports_effective_policy_changes_without_admission(self):
        personal = self.seed.put(title='Personal', body='Private preview fixture.', scope='personal')
        self.seed.grant('a', personal['id'])
        source, target = self.fork('source'), self.fork('target')
        source.revoke('a', personal['id'])
        bundle = self.base / 'bundle'
        self.transfer.export_bundle(source, bundle)
        before = inventory(target.root)
        preview = self.transfer.plan_merge(target, bundle)
        self.assertEqual(preview['policy_changes'], {'a': {'added': [], 'removed': [personal['id']]}})
        self.assertEqual(inventory(target.root), before)

    def test_raw_union_is_idempotent_and_survives_renamed_root(self):
        a, b, target = [self.fork(name) for name in ('a', 'b', 'target')]
        for name, branch in (('a', a), ('b', b)):
            branch.put(title=name, body=f'Raw {name} bytes.', scope=f'project:{name}', record_id=name)
        for source in (a, b, b, a):
            for path, data in inventory(source.root).items():
                destination = target.root / path
                if destination.exists():
                    self.assertEqual(destination.read_bytes(), data)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
        before = inventory(target.root)
        snapshot, vault_id = target.snapshot_id(), target.vault_id
        renamed = self.base / 'renamed'
        self.assertTrue(target.root.resolve().is_relative_to(self.base.resolve()))
        self.assertTrue(renamed.resolve().is_relative_to(self.base.resolve()))
        target.root.rename(renamed)
        reopened = Vault(renamed)
        self.assertEqual(reopened.vault_id, vault_id)
        self.assertEqual(reopened.snapshot_id(), snapshot)
        self.assertEqual(inventory(reopened.root), before)
        self.assertEqual({r['id'] for r in reopened.list_records()}, {'seed', 'a', 'b'})
        for record in reopened.list_records():
            self.assertEqual(hashlib.sha256((reopened.root / record['path']).read_bytes()).hexdigest(),
                             record['revision'])

    def policy_transfer_fixture(self, *, unacknowledged=False):
        source = self.fork('policy-source')
        private = source.put(title='Private', body='Synthetic confidential phrase.',
                             scope='personal', record_id='private')
        baseline = self.base / 'policy-baseline'
        shutil.copytree(source.root, baseline)
        source.grant('one', private['id'], operation_id='grant-one')
        source.put(title='Derived', body='Synthetic confidential derivative.',
                   scope='project:one', sources=[private['id']], record_id='derived')
        source.revoke('one', private['id'], operation_id='terminal-revoke')
        revoke = source._load()['operations']['terminal-revoke']['digest']
        if unacknowledged:
            (source.root / '.remember/acks' / (revoke + '.json')).unlink()
        bundle = self.base / 'policy-bundle'
        self.transfer.export_bundle(source, bundle)
        return source, baseline, bundle, revoke

    def test_partial_revocation_transfer_blocks_private_and_derived_reads(self):
        from unittest.mock import patch
        from remember_dammit.retrieval import search
        source, baseline, bundle, revoke = self.policy_transfer_fixture()
        target_path = self.base / 'policy-target'
        shutil.copytree(baseline, target_path)
        target = Vault(target_path)
        plan = self.transfer.plan_merge(target, bundle)
        publish = self.transfer._publish_object
        def interrupted(path, data):
            if '/operations/' in path.as_posix() and json.loads(data)['action'] == 'revoke':
                raise OSError('Stop before terminal revoke')
            return publish(path, data)
        with patch.object(self.transfer, '_publish_object', side_effect=interrupted):
            receipt = self.transfer.apply_merge(target, plan)
        self.assertFalse(receipt['complete'])
        self.assertEqual(source.grants_for('one'), set())
        self.assert_code('incomplete_transfer', target.grants_for, 'one')
        self.assert_code('incomplete_transfer', search, target, 'confidential', project='one')
        self.assert_code('incomplete_transfer', target.list_records)

    def test_exact_plan_retry_accepts_only_its_reviewed_partial_inventory(self):
        from unittest.mock import patch
        source, target = self.fork('source'), self.fork('target')
        source.put(title='New', body='Reviewed bytes.', scope='shared')
        bundle = self.base / 'bundle'
        self.transfer.export_bundle(source, bundle)
        plan = self.transfer.plan_merge(target, bundle)
        publish, count = self.transfer._publish_object, 0
        def interrupted(path, data):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError('Partial reviewed transfer')
            return publish(path, data)
        with patch.object(self.transfer, '_publish_object', side_effect=interrupted):
            self.assertFalse(self.transfer.apply_merge(target, plan)['complete'])
        partial = inventory(target.root)
        self.assertTrue(self.transfer.apply_merge(target, plan)['complete'])
        self.assertTrue(self.transfer.apply_merge(target, plan)['complete'])
        for path, data in partial.items():
            self.assertEqual((target.root / path).read_bytes(), data)
        self.assertEqual(source.snapshot_id(), target.snapshot_id())
        target.put(title='Unreviewed', body='Arrived independently.', scope='shared')
        self.assert_code('stale_merge', self.transfer.apply_merge, target, plan)

    def test_unacknowledged_terminal_revoke_is_witnessed_before_new_operations(self):
        from unittest.mock import patch
        source, baseline, bundle, revoke = self.policy_transfer_fixture(unacknowledged=True)
        target_path = self.base / 'policy-target'
        shutil.copytree(baseline, target_path)
        target = Vault(target_path)
        plan = self.transfer.plan_merge(target, bundle)
        original_source, original_bundle = inventory(source.root), inventory(bundle)
        publish = self.transfer._publish_object
        def interrupted(path, data):
            if '/operations/' in path.as_posix() and json.loads(data)['action'] == 'revoke':
                raise OSError('Unacknowledged terminal revoke interrupted')
            return publish(path, data)
        with patch.object(self.transfer, '_publish_object', side_effect=interrupted):
            self.assertFalse(self.transfer.apply_merge(target, plan)['complete'])
        self.assertTrue((target.root / '.remember/acks' / (revoke + '.json')).is_file())
        self.assert_code('incomplete_transfer', target.grants_for, 'one')
        self.assertTrue(self.transfer.apply_merge(target, plan)['complete'])
        self.assertEqual(target.grants_for('one'), set())
        self.assertEqual(target.snapshot_id(), source.snapshot_id())
        self.assertEqual(inventory(source.root), original_source)
        self.assertEqual(inventory(bundle), original_bundle)

    def test_every_partial_write_boundary_never_exposes_new_grant(self):
        from unittest.mock import patch
        from remember_dammit.retrieval import search
        source, baseline, bundle, revoke = self.policy_transfer_fixture(unacknowledged=True)
        # Enough boundaries for every object, including synthesized witnesses.
        limit = len(inventory(source.root)) + len(source._load()['operation_nodes']) + 1
        for boundary in range(1, limit + 1):
            with self.subTest(boundary=boundary):
                target_path = self.base / f'boundary-{boundary}'
                shutil.copytree(baseline, target_path)
                target = Vault(target_path)
                plan = self.transfer.plan_merge(target, bundle)
                publish, count = self.transfer._publish_object, 0
                def interrupted(path, data):
                    nonlocal count
                    count += 1
                    if count == boundary:
                        raise OSError('Stop at real object publication boundary')
                    return publish(path, data)
                with patch.object(self.transfer, '_publish_object', side_effect=interrupted):
                    receipt = self.transfer.apply_merge(target, plan)
                try:
                    grants = target.grants_for('one')
                    packet = search(target, 'confidential', project='one')
                except VaultError as error:
                    self.assertEqual(error.code, 'incomplete_transfer')
                else:
                    self.assertEqual(grants, set())
                    self.assertEqual(packet['records'], [])
                self.assertTrue(self.transfer.apply_merge(target, plan)['complete'])
                self.assertEqual(target.snapshot_id(), source.snapshot_id())


if __name__ == '__main__':
    unittest.main()
