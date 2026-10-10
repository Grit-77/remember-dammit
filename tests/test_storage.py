"""Behavioral storage acceptance checks using disposable real vaults."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError

if importlib.util.find_spec('remember_dammit.storage'):
    from remember_dammit.storage import Vault
else:
    Vault = None


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Vault, 'The contract requires a storage.Vault implementation')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'vault'
        self.vault = Vault.initialize(self.root)

    def put(self, **kwargs):
        return self.vault.put(title='Original choice', body='Keep the original bytes.',
                              scope='personal', **kwargs)

    def assertCode(self, code, operation):
        with self.assertRaises(VaultError) as cm:
            operation()
        self.assertEqual(cm.exception.code, code)

    def test_initialize_is_explicit_and_preserves_existing_user_content(self):
        other = Path(self.temp.name) / 'other'
        self.assertCode('invalid_vault', lambda: Vault(other))
        other.mkdir()
        (other / 'important.md').write_text('human text', encoding='utf-8')
        self.assertCode('invalid_vault', lambda: Vault.initialize(other))
        self.assertEqual((other / 'important.md').read_text(), 'human text')
        self.assertEqual(Vault.initialize(self.root).vault_id, self.vault.vault_id)

    def test_put_survives_reopen_as_readable_markdown(self):
        record = self.put(record_id='first', operation_id='capture-1')
        reopened = Vault(self.root)
        self.assertEqual(reopened.get('first'), record)
        self.assertEqual(record['state'], 'active')
        self.assertIn('Keep the original bytes.', (self.root / record['path']).read_text())
        self.assertTrue(record['path'].endswith('.md'))
        self.assertEqual(len(reopened.list_records()), 1)

    def test_correction_uses_new_id_preserves_bytes_and_old_lookup_terms(self):
        first = self.put(aliases=['old provider'])
        original = (self.root / first['path']).read_bytes()
        second = self.vault.correct(first['id'], expected_revision=first['revision'],
                                    title='New choice', body='Use the new provider.')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(second['supersedes'], first['id'])
        self.assertEqual(second['scope'], 'personal')
        self.assertIn('Original choice', second['aliases'])
        self.assertIn('old provider', second['aliases'])
        self.assertEqual((self.root / first['path']).read_bytes(), original)
        self.assertEqual(self.vault.get(first['id'])['state'], 'superseded')
        self.assertEqual([r['id'] for r in self.vault.history(second['id'])],
                         [first['id'], second['id']])
        self.assertEqual(self.vault.history(first['id']), self.vault.history(second['id']))

    def test_stale_correction_refuses_a_second_successor(self):
        first = self.put()
        self.assertCode('stale_revision', lambda: self.vault.correct(
            first['id'], expected_revision='0'*64, title='x', body='x'))
        self.vault.correct(first['id'], expected_revision=first['revision'], title='new', body='new')
        self.assertCode('stale_revision', lambda: self.vault.correct(
            first['id'], expected_revision=first['revision'], title='other', body='other'))
        self.assertEqual(len(self.vault.list_records()), 2)

    def test_idempotent_capture_returns_original_result_after_correction(self):
        first = self.put(operation_id='capture')
        self.vault.correct(first['id'], expected_revision=first['revision'], title='new', body='new')
        self.assertEqual(self.put(operation_id='capture'), first)
        self.assertCode('operation_conflict', lambda: self.vault.put(
            title='changed', body='x', scope='personal', operation_id='capture'))
        self.assertEqual(len(self.vault.list_records()), 2)

    def test_idempotent_correction_returns_original_successor(self):
        first = self.put()
        args = dict(expected_revision=first['revision'], title='new', body='new', operation_id='fix')
        second = self.vault.correct(first['id'], **args)
        self.assertEqual(Vault(self.root).correct(first['id'], **args), second)
        self.assertCode('operation_conflict', lambda: self.vault.correct(
            first['id'], **dict(args, body='different')))

    def test_scope_and_metadata_are_validated_before_publication(self):
        invalid = [dict(scope='../secret'), dict(scope='project:'), dict(scope='project:a/b'),
                   dict(title=''), dict(body=42), dict(aliases='bad'), dict(sources='bad'),
                   dict(remote_allowed='false'), dict(evidence='magic'), dict(disclosure='magic'),
                   dict(state='magic'), dict(record_id='../outside'), dict(record_id='CON'),
                   dict(operation_id='../../op'), dict(actor='')]
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(VaultError):
                    self.vault.put(**{'title': 'valid', 'body': 'text', 'scope': 'personal', **values})
        self.assertEqual(self.vault.list_records(), [])

    def test_duplicate_ids_and_case_collisions_are_rejected(self):
        self.put(record_id='Abc')
        self.assertCode('invalid_record', lambda: self.put(record_id='abc'))
        self.assertCode('invalid_record', lambda: self.put(record_id='Abc'))

    def test_project_sources_require_matching_scope_or_explicit_grant(self):
        personal = self.put()
        foreign = self.vault.put(title='secret', body='foreign', scope='project:other')
        create = lambda source: self.vault.put(title='derived', body='x', scope='project:atlas', sources=[source])
        self.assertCode('source_scope', lambda: create(personal['id']))
        self.assertCode('source_scope', lambda: create(foreign['id']))
        self.assertCode('not_found', lambda: create('missing'))
        self.vault.grant('atlas', personal['id'])
        self.assertEqual(create(personal['id'])['sources'], [personal['id']])
        self.vault.revoke('atlas', personal['id'])
        self.assertCode('source_scope', lambda: create(personal['id']))

    def test_proposed_or_superseded_sources_cannot_be_current_evidence(self):
        proposal = self.put(state='proposed')
        self.assertCode('source_scope', lambda: self.put(sources=[proposal['id']]))
        original = self.put()
        self.vault.correct(original['id'], expected_revision=original['revision'], title='new', body='new')
        self.assertCode('source_scope', lambda: self.put(sources=[original['id']]))

    def test_grants_are_portable_revocable_and_not_inherited_by_successors(self):
        first = self.put()
        before = self.vault.snapshot_id()
        reply = self.vault.grant('atlas', first['id'], operation_id='grant')
        self.assertTrue(reply['granted'])
        self.assertNotEqual(before, self.vault.snapshot_id())
        second = self.vault.correct(first['id'], expected_revision=first['revision'], title='new', body='new')
        self.assertEqual(Vault(self.root).grants_for('atlas'), {first['id']})
        self.assertNotIn(second['id'], self.vault.grants_for('atlas'))
        self.vault.revoke('atlas', first['id'], operation_id='revoke')
        self.assertEqual(Vault(self.root).grants_for('atlas'), set())
        self.assertEqual(self.vault.grant('atlas', first['id'], operation_id='grant'), reply)
        self.assertEqual(self.vault.grants_for('atlas'), set())

    def test_grant_refuses_nonpersonal_records(self):
        record = self.vault.put(title='x', body='y', scope='project:atlas')
        self.assertCode('source_scope', lambda: self.vault.grant('other', record['id']))

    def test_changed_revision_is_exposed_without_overwriting_human_text(self):
        first = self.put()
        path = self.root / first['path']
        path.write_text('External edit that must survive.', encoding='utf-8')
        self.assertCode('integrity_error', lambda: self.vault.list_records())
        report = self.vault.doctor()
        self.assertFalse(report['ok'])
        self.assertTrue(report['issues'])
        self.assertEqual(path.read_text(), 'External edit that must survive.')
        self.assertCode('integrity_error', lambda: self.put())

    def test_uncommitted_orphan_payload_is_ignored_and_reported(self):
        record = self.put()
        orphan = self.root / '.remember/revisions/orphan.md'
        orphan.write_text('not a committed note', encoding='utf-8')
        self.assertEqual(self.vault.list_records(), [record])
        report = self.vault.doctor()
        self.assertTrue(report['ok'])
        self.assertIn('.remember/revisions/orphan.md', report['orphan_payloads'])

    def test_failed_commit_publication_is_invisible_and_retry_is_safe(self):
        import remember_dammit.storage as storage
        real_replace = os.replace
        def fail_marker(source, target):
            if Path(target).parent.name == 'operations':
                raise OSError('simulated disk failure at commit publication')
            return real_replace(source, target)
        with patch.object(storage.os, 'replace', side_effect=fail_marker):
            with self.assertRaises(VaultError):
                self.put(operation_id='interrupted')
        self.assertEqual(Vault(self.root).list_records(), [])
        self.assertTrue(self.vault.doctor()['orphan_payloads'])
        result = self.put(operation_id='interrupted')
        self.assertEqual(self.vault.list_records(), [result])

    def test_corrupt_or_missing_committed_payload_fails_closed(self):
        first = self.put()
        (self.root / first['path']).unlink()
        self.assertCode('integrity_error', lambda: self.vault.get(first['id']))
        self.assertFalse(self.vault.doctor()['ok'])

    def test_corrupted_manifest_is_not_treated_as_an_orphan(self):
        self.put()
        next((self.root / '.remember/operations').glob('*.json')).write_text('{}', encoding='utf-8')
        self.assertCode('integrity_error', lambda: self.vault.list_records())
        self.assertFalse(self.vault.doctor()['ok'])

    def test_process_writers_serialize_and_validate_base_after_lock(self):
        first = self.put()
        script = '''import json,sys
from remember_dammit.storage import Vault
from remember_dammit.errors import VaultError
try:
 r=Vault(sys.argv[1]).correct(sys.argv[2],expected_revision=sys.argv[3],title=sys.argv[4],body='new')
 print(json.dumps({'ok':True,'id':r['id']}))
except VaultError as e:
 print(json.dumps({'ok':False,'code':e.code}))
'''
        commands = [[sys.executable, '-c', script, str(self.root), first['id'], first['revision'], title]
                    for title in ['writer one', 'writer two']]
        processes = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for cmd in commands]
        results = []
        for proc in processes:
            stdout, stderr = proc.communicate(timeout=30)
            self.assertEqual(proc.returncode, 0, stderr)
            results.append(json.loads(stdout))
        self.assertEqual(sum(result['ok'] for result in results), 1)
        self.assertEqual([r['code'] for r in results if not r['ok']], ['stale_revision'])
        self.assertEqual(len(self.vault.list_records()), 2)

    def test_vault_works_without_python312_junction_helper(self):
        # Python 3.11 pathlib has no junction method. Keep all actual IO real.
        with patch.object(Path, 'is_junction', None, create=True):
            try:
                another = Vault.initialize(Path(self.temp.name) / 'python311')
                record = another.put(title='Portable', body='Real IO', scope='personal')
                self.assertEqual(Vault(another.root).get(record['id'])['body'], 'Real IO')
            except (VaultError, TypeError, AttributeError) as exc:
                self.fail(f'Portable vault operations failed without the 3.12 helper: {exc}')

    def test_doctor_reports_source_that_was_revoked_after_admission(self):
        source = self.put()
        self.vault.grant('atlas', source['id'])
        dependent = self.vault.put(title='Derived', body='x', scope='project:atlas', sources=[source['id']])
        self.vault.revoke('atlas', source['id'])
        report = self.vault.doctor()
        self.assertFalse(report['ok'])
        self.assertIn({'code': 'source_scope', 'record_id': dependent['id'], 'source_id': source['id']}, report['issues'])

    def test_process_death_at_publication_boundaries_preserves_retry_result(self):
        script = '''import os,stat,sys
from pathlib import Path
import remember_dammit.storage as storage
root,stage=sys.argv[1:]
real_fsync,real_replace=storage.os.fsync,storage.os.replace
flushes=0
def fsync(fd):
 global flushes
 real_fsync(fd)
 if stat.S_ISREG(os.fstat(fd).st_mode):
  flushes+=1
  if (stage=='payload_flush' and flushes==1) or (stage=='marker_flush' and flushes==2) or (stage=='checkpoint_flush' and flushes==3):
   os._exit(73)
def replace(src,dst):
 real_replace(src,dst)
 if (stage=='payload_publish' and Path(dst).parent.name=='revisions') or (stage=='marker_publish' and Path(dst).parent.name=='operations') or (stage=='checkpoint_publish' and Path(dst).name=='head.json'):
  os._exit(73)
storage.os.fsync,storage.os.replace=fsync,replace
storage.Vault(root).put(title='Crash record',body='Submitted text',scope='personal',operation_id='crash',record_id='crash-note')
'''
        for stage in ['payload_flush', 'payload_publish', 'marker_flush', 'marker_publish', 'checkpoint_flush', 'checkpoint_publish']:
            with self.subTest(stage=stage):
                vault = Vault.initialize(Path(self.temp.name) / stage)
                proc = subprocess.run([sys.executable, '-c', script, str(vault.root), stage],
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 73, proc.stderr)
                before = Vault(vault.root).list_records()
                self.assertEqual(len(before), 1 if stage in ('marker_publish', 'checkpoint_flush', 'checkpoint_publish') else 0)
                report = vault.doctor()
                if stage in ('payload_flush', 'marker_flush', 'checkpoint_flush'):
                    self.assertIn('uncommitted_files', report)
                    self.assertTrue(report['uncommitted_files'])
                result = vault.put(title='Crash record', body='Submitted text', scope='personal',
                                   operation_id='crash', record_id='crash-note')
                self.assertEqual(len(vault.list_records()), 1)
                if before:
                    self.assertEqual(result, before[0])
                # Retry must anchor a marker that survived an earlier crash.
                next((vault.root / '.remember/operations').glob('*.json')).unlink()
                self.assertCode('integrity_error', lambda: vault.list_records())

    def test_writer_lock_is_shared_when_process_temp_directories_differ(self):
        from remember_dammit.locking import writer_lock
        alternate_temp = Path(self.temp.name) / 'different-temp'
        alternate_temp.mkdir()
        script = '''import json,sys
from remember_dammit.locking import writer_lock
from remember_dammit.errors import VaultError
try:
 with writer_lock(sys.argv[1],timeout=0.25):
  print(json.dumps({'acquired':True}))
except VaultError as e:
 print(json.dumps({'code':e.code}))
'''
        env = dict(os.environ, TEMP=str(alternate_temp), TMP=str(alternate_temp), TMPDIR=str(alternate_temp))
        with writer_lock(self.root):
            proc = subprocess.run([sys.executable, '-c', script, str(self.root)], env=env,
                                  capture_output=True, text=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {'code': 'lock_timeout'})

    def test_deleting_checkpointed_revoke_marker_cannot_restore_a_grant(self):
        record = self.put()
        self.vault.grant('atlas', record['id'])
        self.vault.revoke('atlas', record['id'])
        last = sorted((self.root / '.remember/operations').glob('*.json'))[-1]
        last.unlink()
        self.assertCode('integrity_error', lambda: self.vault.grants_for('atlas'))
        self.assertFalse(self.vault.doctor()['ok'])

    def test_deleting_checkpointed_capture_is_exposed_as_journal_loss(self):
        self.put()
        next((self.root / '.remember/operations').glob('*.json')).unlink()
        self.assertCode('integrity_error', lambda: self.vault.list_records())
        self.assertFalse(self.vault.doctor()['ok'])

    def test_empty_or_whitespace_body_never_commits_a_record(self):
        for body in ['', ' ', '\n\t']:
            with self.subTest(body=body):
                self.assertCode('invalid_input', lambda: self.vault.put(title='Title', body=body, scope='personal'))
        self.assertEqual(self.vault.list_records(), [])


if __name__ == '__main__':
    unittest.main()
