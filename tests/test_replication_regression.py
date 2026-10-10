"""Offline copies must preserve and admit independent project captures."""
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


class OfflineForkRegressionTests(unittest.TestCase):
    def test_union_keeps_both_project_captures_regardless_of_local_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            seed = Vault.initialize(base / 'seed')
            records = [seed.put(title='Shared seed', body='Synthetic seed bytes.', scope='shared',
                                record_id='seed-note', operation_id='seed-put')]
            branches = {}
            for platform in ('windows', 'mac'):
                root = base / platform
                shutil.copytree(seed.root, root)
                branch = Vault(root)
                records.append(branch.put(
                    title=f'{platform} project note', body=f'Synthetic {platform} offline bytes.',
                    scope=f'project:{platform}-project', record_id=f'{platform}-note',
                    operation_id=f'{platform}-put', actor=platform))
                branches[platform] = root
                self.assertEqual(len(branch.list_records()), 2)

            for head_name, head_root in branches.items():
                with self.subTest(head_source=head_name):
                    merged = base / f'merged-{head_name}'
                    shutil.copytree(seed.root, merged)
                    # Transfer the complete immutable artifact set, including future
                    # acknowledgements. Shared identity and a legacy mutable checkpoint
                    # are handled separately; no merge or repair API is assumed.
                    other = next(root for name, root in branches.items() if name != head_name)
                    for source in (head_root, other):
                        for path in (source / '.remember').rglob('*'):
                            if not path.is_file() or path.relative_to(source).as_posix() in (
                                    '.remember/vault.json', '.remember/head.json'):
                                continue
                            target = merged / path.relative_to(source)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            if target.exists():
                                self.assertEqual(target.read_bytes(), path.read_bytes())
                            else:
                                shutil.copyfile(path, target)
                    checkpoint = head_root / '.remember/head.json'
                    if checkpoint.exists():
                        shutil.copyfile(checkpoint, merged / '.remember/head.json')
                    for record in records:
                        self.assertEqual(hashlib.sha256((merged / record['path']).read_bytes()).hexdigest(),
                                         record['revision'], 'Transport must preserve every payload byte.')
                    try:
                        reopened = Vault(merged)
                        admitted = {record['id']: record for record in reopened.list_records()}
                    except VaultError as exc:
                        self.fail(f'An offline file union with all payloads intact must admit both '
                                  f'project captures; got {exc.code}: {exc.message}')
                    self.assertEqual(set(admitted), {record['id'] for record in records})
                    for original in records:
                        self.assertEqual(admitted[original['id']]['body'], original['body'])
                        self.assertEqual(admitted[original['id']]['scope'], original['scope'])
                    self.assertTrue(reopened.doctor()['ok'])


if __name__ == '__main__':
    unittest.main()
