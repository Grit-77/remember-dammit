"""Stable per-OS-user authority outside portable and synced vault contents.

Environment-selected caches must never select an authority or writer lock.
Different OS users do not coordinate through this per-user namespace; a vault
shared by those users needs a separately agreed common protected lock service.
Canonical paths normalize symlink aliases; bind mounts/hardlink aliases are not
proven equivalent. Returned paths are local data and never portable identity.
"""
import hashlib
import os
from pathlib import Path
import re
import sys

from .errors import VaultError


def _windows_known_folder(folder_id):
    """Query the OS, including OS-managed account-folder redirection."""
    if os.name == 'nt':
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [('data1', wintypes.DWORD), ('data2', wintypes.WORD),
                        ('data3', wintypes.WORD), ('data4', ctypes.c_ubyte * 8)]

        identifier = GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
        pointer = ctypes.c_void_p()
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD,
                                              wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
        shell.SHGetKnownFolderPath.restype = ctypes.c_long
        result = shell.SHGetKnownFolderPath(ctypes.byref(identifier), 0, None,
                                            ctypes.byref(pointer))
        if result != 0 or not pointer.value:
            raise VaultError('local_state_unavailable', 'The OS user state directory is unavailable.')
        try:
            return Path(ctypes.wstring_at(pointer.value))
        finally:
            ole = ctypes.WinDLL('ole32')
            ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole.CoTaskMemFree(pointer)


def _platform_home():
    if os.name == 'nt':
        return _windows_known_folder('5e6c858f-0e22-4760-9afe-ea3317b67173')
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _platform_state_root():
    """Read persistent account location through OS identity, ignoring env."""
    if os.name == 'nt':
        return _windows_known_folder('f1b32785-6fba-4fcf-9d55-7b8e7f157091')
    home = _platform_home()
    if sys.platform == 'darwin':
        return home / 'Library' / 'Application Support'
    return home / '.local' / 'state'


def _is_link(path):
    if path.is_symlink():
        return True
    if os.name == 'nt':
        # All reparse points, including junctions on Python 3.11.
        import ctypes
        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return attributes != -1 and bool(attributes & 0x400)
    return False


def _reject_links(path):
    for component in (path, *path.parents):
        if _is_link(component):
            raise VaultError('invalid_local_state', 'Local state paths must not contain links.')


def _namespace(vault_root):
    try:
        root = Path(vault_root).resolve()
        native = Path(_platform_state_root()).absolute()
        _reject_links(native)
        identity = os.path.normcase(str(root))
        namespace = native / 'remember-dammit' / hashlib.sha256(identity.encode('utf-8')).hexdigest()
        _reject_links(namespace)
        resolved = namespace.resolve()
        # Home and filesystem roots are account/container boundaries rather
        # than selected content folders. Otherwise protect the complete parent
        # (e.g. Notes/Brain must not place managed state anywhere under Notes).
        container_parent = root.parent in (Path(root.anchor), _platform_home().resolve())
        if (resolved.is_relative_to(root) or root.is_relative_to(resolved)
                or (not container_parent and resolved.is_relative_to(root.parent))):
            raise VaultError('invalid_local_state', 'Local state must be outside the vault and its parent.')
        return resolved
    except VaultError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise VaultError('local_state_unavailable', 'The OS user state directory is unavailable.') from None


def local_state_directory(vault_root, purpose):
    """Return an uncreated stable local path; callers create it when needed."""
    if not isinstance(purpose, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', purpose):
        raise VaultError('invalid_local_state', 'Select a valid local state purpose.')
    result = _namespace(vault_root) / purpose
    _reject_links(result)
    return result


def reject_local_state_overlap(vault_root, path):
    """Refuse either direction of overlap with this vault's local namespace."""
    selected = Path(path).resolve()
    namespace = _namespace(vault_root)
    if selected.is_relative_to(namespace) or namespace.is_relative_to(selected):
        raise VaultError('invalid_destination', 'The selected path overlaps managed local state.')
