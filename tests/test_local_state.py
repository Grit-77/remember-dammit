"""Machine-local authority must not follow portable cache or temp settings."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError
from remember_dammit.locking import writer_lock


class LocalStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Notes' / 'Brain'
        self.root.mkdir(parents=True)

    def state_module(self):
        try:
            return importlib.import_module('remember_dammit.local_state')
        except ModuleNotFoundError:
            self.fail('Machine-local state helper is required.')

    def test_lock_creates_no_sibling_artifacts(self):
        with writer_lock(self.root):
            self.assertFalse((self.root.parent / '.remember-dammit-locks').exists())
            self.assertEqual(list(self.root.parent.iterdir()), [self.root])

    def test_native_state_ignores_environment_and_canonicalizes_alias(self):
        state = self.state_module()
        first = state.local_state_directory(self.root, 'locks')
        with patch.dict(os.environ, {name: str(self.root / name) for name in
                        ('TEMP', 'TMP', 'TMPDIR', 'HOME', 'LOCALAPPDATA',
                         'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'REMEMBER_DAMMIT_STATE_HOME')}):
            second = state.local_state_directory(self.root / '..' / 'Brain', 'locks')
        self.assertEqual(first, second)
        self.assertFalse(first.is_relative_to(self.root.parent))

    def test_overlap_and_unsafe_purpose_are_refused(self):
        state = self.state_module()
        directory = state.local_state_directory(self.root, 'index')
        for path in (directory, directory.parent, directory / 'child'):
            with self.assertRaises(VaultError):
                state.reject_local_state_overlap(self.root, path)
        for purpose in ('../vault', '', 'a/b'):
            with self.assertRaises(VaultError):
                state.local_state_directory(self.root, purpose)

    def test_native_state_location_inside_synced_parent_is_refused(self):
        state = self.state_module()
        with patch.object(state, '_platform_state_root', return_value=self.root.parent / 'state'):
            with self.assertRaises(VaultError):
                state.local_state_directory(self.root, 'locks')

    def test_home_or_filesystem_root_parent_does_not_reject_native_state(self):
        state = self.state_module()
        home = state._platform_home()
        selected = home / 'synthetic-memory-root-no-writes'
        directory = state.local_state_directory(selected, 'locks')
        self.assertFalse(directory.is_relative_to(selected))
        selected = Path(home.anchor) / 'synthetic-memory-root-no-writes'
        directory = state.local_state_directory(selected, 'locks')
        self.assertFalse(directory.is_relative_to(selected))

    def test_state_symlink_is_refused(self):
        state = self.state_module()
        native = Path(self.temp.name) / 'native'
        elsewhere = Path(self.temp.name) / 'elsewhere'
        elsewhere.mkdir()
        try:
            native.symlink_to(elsewhere, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                self.skipTest('OS user cannot create symbolic links.')
            result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(native), str(elsewhere)],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode:
                self.skipTest('OS user cannot create symbolic links or junctions.')
        with patch.object(state, '_platform_state_root', return_value=native):
            with self.assertRaises(VaultError):
                state.local_state_directory(self.root, 'locks')
            if os.name == 'nt' and not native.is_symlink():
                # Python 3.11 lacks Path.is_junction; the native guard must
                # still recognize the real Windows reparse point.
                with patch.object(Path, 'is_junction', None, create=True):
                    with self.assertRaises(VaultError):
                        state.local_state_directory(self.root, 'locks')

    def test_two_processes_with_different_temp_and_cache_share_real_lock(self):
        self.state_module()
        script = '''
import sys
from remember_dammit.locking import writer_lock
from remember_dammit.errors import VaultError
try:
    with writer_lock(sys.argv[1], timeout=0.15):
        print('acquired')
except VaultError as error:
    print(error.code)
'''
        with writer_lock(self.root):
            for suffix in ('one', 'two'):
                environment = dict(os.environ)
                for name in ('TEMP', 'TMP', 'TMPDIR', 'REMEMBER_DAMMIT_STATE_HOME',
                             'LOCALAPPDATA', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'HOME'):
                    environment[name] = str(Path(self.temp.name) / suffix / name)
                result = subprocess.run([sys.executable, '-c', script, str(self.root)],
                                        env=environment, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'lock_timeout')
        result = subprocess.run([sys.executable, '-c', script, str(self.root)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.stdout.strip(), 'acquired', result.stderr)

    def test_same_thread_nested_writer_keeps_one_os_lock(self):
        with writer_lock(self.root):
            with writer_lock(self.root, timeout=0.1):
                self.assertFalse((self.root.parent / '.remember-dammit-locks').exists())


if __name__ == '__main__':
    unittest.main()
