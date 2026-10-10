"""Bind an externally checked policy snapshot to an atomic correction."""
from pathlib import Path
import tempfile
import unittest

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


class CorrectionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Vault.initialize(Path(self.temp.name) / 'vault')
        self.source = self.vault.put(title='Owner choice', body='Use concise answers.', scope='personal')
        self.vault.grant('demo', self.source['id'])
        self.note = self.vault.put(title='Project style', body='Concise project answers.',
                                   scope='project:demo', sources=[self.source['id']])

    def correction(self, **extra):
        return self.vault.correct(self.note['id'], expected_revision=self.note['revision'],
                                  title='Project style', body='Brief project answers.',
                                  operation_id='guarded-edit', **extra)

    def test_revoked_policy_after_preflight_prevents_new_correction(self):
        observed = self.vault.snapshot_id()
        self.vault.revoke('demo', self.source['id'])
        before = self.vault.snapshot_id()
        with self.assertRaises(VaultError) as raised:
            self.correction(expected_snapshot=observed)
        self.assertEqual(raised.exception.code, 'source_changed')
        self.assertEqual(self.vault.snapshot_id(), before)
        self.assertEqual(len(self.vault.history(self.note['id'])), 1)

    def test_current_snapshot_allows_write_and_exact_retry_keeps_original_receipt(self):
        observed = self.vault.snapshot_id()
        result = self.correction(expected_snapshot=observed)
        self.vault.correct(result['id'], expected_revision=result['revision'],
                           title='Later owner edit', body='Detailed answers this time.')
        before = self.vault.snapshot_id()
        replay = self.correction(expected_snapshot=observed)
        self.assertEqual(replay['id'], result['id'])
        self.assertEqual(replay['body'], 'Brief project answers.')
        self.assertEqual(self.vault.snapshot_id(), before)
        self.assertEqual(len(self.vault.history(self.note['id'])), 3)

    def test_snapshot_is_checked_after_acquiring_writer_lock(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        import remember_dammit.storage as storage
        original = storage.writer_lock
        observed = self.vault.snapshot_id()

        @contextmanager
        def change_before_lock(root):
            with patch.object(storage, 'writer_lock', original):
                self.vault.revoke('demo', self.source['id'])
            with original(root):
                yield

        with patch.object(storage, 'writer_lock', change_before_lock):
            with self.assertRaises(VaultError) as raised:
                self.correction(expected_snapshot=observed)
        self.assertEqual(raised.exception.code, 'source_changed')
        self.assertEqual(len(self.vault.history(self.note['id'])), 1)


if __name__ == '__main__':
    unittest.main()
