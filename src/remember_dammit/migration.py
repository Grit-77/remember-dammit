"""Previewed, out-of-place v1 conversion with an untouched rollback source.

Plans and returned paths are owner-local authoring artifacts, not sync events.
Interrupted destinations and backups are retained. Recovery uses fresh paths
and a new preview; this module never deletes or overwrites previous attempts.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from .errors import VaultError
from .local_state import _is_link, reject_local_state_overlap
from .locking import writer_lock
from .storage import Vault, _canonical, _fsync_directory

_INCOMPLETE = '.migration-INCOMPLETE.json'
_BACKUP_INCOMPLETE = '.migration-backup-INCOMPLETE.json'


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _path(value):
    try:
        path = Path(value).absolute()
        for component in (path, *path.parents):
            if _is_link(component):
                raise VaultError('invalid_migration', 'Migration paths must not contain links.')
        return path.resolve()
    except (TypeError, ValueError, OSError):
        raise VaultError('invalid_migration', 'Select valid migration paths.') from None


def _paths(source, target, backup):
    paths = [_path(value) for value in (source, target, backup)]
    for index, left in enumerate(paths):
        for right in paths[index + 1:]:
            if left.is_relative_to(right) or right.is_relative_to(left):
                raise VaultError('invalid_migration', 'Source, target, and backup must be separate paths.')
    for path in paths:
        reject_local_state_overlap(paths[0], path)
    if any(path.exists() for path in paths[1:]):
        raise VaultError('migration_destination_exists', 'Migration requires new target and backup paths.')
    return paths


def _manifest(root, *, ignore=()):
    """Hash all bytes, including owner files and uncommitted/orphan payloads."""
    entries = []
    if not root.is_dir():
        raise VaultError('invalid_migration', 'The migration source must be an initialized directory.')
    def fail_walk(error):
        raise error

    for directory, names, files in os.walk(root, followlinks=False, onerror=fail_walk):
        for name in sorted(names + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative in ignore:
                continue
            _path(path)
            metadata = path.stat()
            if stat.S_ISDIR(metadata.st_mode):
                entry = {'path': relative, 'kind': 'directory', 'mode': stat.S_IMODE(metadata.st_mode)}
            elif stat.S_ISREG(metadata.st_mode):
                data = path.read_bytes()
                entry = {'path': relative, 'kind': 'file', 'mode': stat.S_IMODE(metadata.st_mode),
                         'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            else:
                raise VaultError('invalid_migration', 'Migration accepts only regular files and directories.')
            entries.append(entry)
    return sorted(entries, key=lambda entry: entry['path'])


def _legacy_view(source):
    config = json.loads((source / '.remember' / 'vault.json').read_bytes())
    if not isinstance(config, dict) or config.get('schema') != 1:
        raise VaultError('invalid_migration', 'Migration requires a validated format-v1 source.')
    vault = Vault(source)
    return vault, vault._load()


def preview_migration(source, target, backup):
    """Read-only exact preview; neither destinations nor lock state are made."""
    try:
        source, target, backup = _paths(source, target, backup)
        if any((source / name).exists() for name in (_INCOMPLETE, _BACKUP_INCOMPLETE)):
            raise VaultError('invalid_migration', 'An incomplete migration cannot be a source.')
        manifest = _manifest(source)
        vault, view = _legacy_view(source)
        if _manifest(source) != manifest:
            raise VaultError('stale_migration', 'The migration source changed during preview.')
        plan = {'schema': 1, 'source': str(source), 'target': str(target), 'backup': str(backup),
                'vault_id': vault.vault_id, 'source_snapshot': view['snapshot'],
                'source_fingerprint': _hash(manifest), 'manifest': manifest,
                'record_count': len(view['records']), 'operation_count': len(view['operations'])}
        return dict(plan, plan_id=_hash(plan))
    except VaultError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise VaultError('invalid_migration', 'The migration source cannot be validated.') from None


def _write_new(path, value):
    with path.open('xb') as handle:
        handle.write(_canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _copy_manifest(source, destination, manifest, *, managed=True):
    for entry in manifest:
        relative = entry['path']
        if not managed and (relative == '.remember' or relative.startswith('.remember/')):
            continue
        old, new = source / relative, destination / relative
        if entry['kind'] == 'directory':
            new.mkdir(exist_ok=True)
        else:
            with old.open('rb') as incoming, new.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            shutil.copystat(old, new)
    # Directory permissions are applied last, after children are persisted.
    for entry in reversed(manifest):
        relative = entry['path']
        if entry['kind'] == 'directory' and (managed or not (relative == '.remember' or relative.startswith('.remember/'))):
            shutil.copystat(source / relative, destination / relative)


def _semantic_readback(original, converted):
    """Verify conversion receipt evidence before publishing completion."""
    old, new = original._load(), converted._load()
    if original.vault_id != converted.vault_id or set(old['records']) != set(new['records']):
        raise VaultError('migration_verification', 'Migrated identities differ from the source.')
    for record_id, record in old['current'].items():
        migrated = new['current'][record_id]
        if any(migrated.get(key) != value for key, value in record.items() if key != 'path'):
            raise VaultError('migration_verification', 'Migrated record semantics differ from the source.')
        if (original.root / record['path']).read_bytes() != (converted.root / migrated['path']).read_bytes():
            raise VaultError('migration_verification', 'Migrated original revision bytes differ from the source.')
        if [r['id'] for r in original.history(record_id)] != [r['id'] for r in converted.history(record_id)]:
            raise VaultError('migration_verification', 'Migrated history differs from the source.')
    projects = old['grants'].keys() | new['grants'].keys()
    if (any(old['grants'].get(project, set()) != new['grants'].get(project, set()) for project in projects)
            or set(old['operations']) != set(new['operations'])):
        raise VaultError('migration_verification', 'Migrated policy or operation identities differ from the source.')
    for operation_id, operation in old['operations'].items():
        if new['operations'][operation_id]['request_digest'] != operation['request_digest']:
            raise VaultError('migration_verification', 'Migrated retry proof differs from the source.')
    mapping = {operation['digest']: new['operations'][operation_id]['digest']
               for operation_id, operation in old['operations'].items()}
    return new['snapshot'], mapping


def apply_migration(plan):
    """Apply exactly a preview, retaining source/backup/incomplete artifacts."""
    try:
        required = {'schema', 'source', 'target', 'backup', 'vault_id', 'source_snapshot',
                    'source_fingerprint', 'manifest', 'record_count', 'operation_count', 'plan_id'}
        if (not isinstance(plan, dict) or set(plan) != required or type(plan['schema']) is not int or plan['schema'] != 1
                or plan['plan_id'] != _hash({k: v for k, v in plan.items() if k != 'plan_id'})):
            raise VaultError('invalid_migration', 'The migration preview is invalid or changed.')
        source, target, backup = _paths(plan['source'], plan['target'], plan['backup'])
        with ExitStack() as stack:
            for path in sorted((source, target, backup), key=str):
                stack.enter_context(writer_lock(path))
            if _manifest(source) != plan['manifest']:
                raise VaultError('stale_migration', 'The source no longer matches this exact preview.')
            fresh = preview_migration(source, target, backup)
            if fresh != plan:
                raise VaultError('stale_migration', 'The source no longer matches this exact preview.')
            original, _ = _legacy_view(source)
            marker = {'schema': 1, 'vault_id': plan['vault_id'],
                      'source_fingerprint': plan['source_fingerprint'], 'state': 'incomplete'}
            backup.mkdir(parents=True, exist_ok=False)
            _write_new(backup / _BACKUP_INCOMPLETE, marker)
            _copy_manifest(source, backup, plan['manifest'])
            backup_manifest = _manifest(backup, ignore=(_BACKUP_INCOMPLETE,))
            if backup_manifest != plan['manifest']:
                raise VaultError('migration_verification', 'The backup did not preserve the source manifest.')
            backed_up, _ = _legacy_view(backup)
            if backed_up.snapshot_id() != plan['source_snapshot']:
                raise VaultError('migration_verification', 'The backup did not preserve the validated source.')
            (backup / _BACKUP_INCOMPLETE).unlink()
            _fsync_directory(backup)
            if _manifest(source) != plan['manifest']:
                raise VaultError('stale_migration', 'The source changed while creating its backup.')
            target.mkdir(parents=True, exist_ok=False)
            _write_new(target / _INCOMPLETE, marker)
            from .storage_v2 import convert_v1_to_v2
            converted = convert_v1_to_v2(source, target)
            _copy_manifest(source, target, plan['manifest'], managed=False)
            owner_entries = lambda entries: [entry for entry in entries if entry['path'] != _INCOMPLETE
                and entry['path'] != '.remember' and not entry['path'].startswith('.remember/')]
            if owner_entries(_manifest(target)) != owner_entries(plan['manifest']):
                raise VaultError('migration_verification', 'Migrated owner files differ from the source.')
            snapshot, operation_mapping = _semantic_readback(original, converted)
            if _manifest(source) != plan['manifest']:
                raise VaultError('stale_migration', 'The source changed during conversion.')
            (target / _INCOMPLETE).unlink()
            try:
                _fsync_directory(target)
                reopened = Vault(target)
                if reopened.snapshot_id() != snapshot:
                    raise VaultError('migration_verification', 'Completed target readback changed.')
                # Observe the backup again at completion, after conversion and
                # ordinary target readback; earlier verification is not current
                # evidence if an external editor changed it in the meantime.
                backup_manifest = _manifest(backup)
                if backup_manifest != plan['manifest']:
                    raise VaultError('migration_verification', 'The backup changed during migration.')
                backed_up, backup_view = _legacy_view(backup)
                if (backed_up.vault_id != plan['vault_id']
                        or backup_view['snapshot'] != plan['source_snapshot']
                        or _manifest(backup) != backup_manifest):
                    raise VaultError('migration_verification', 'Final backup validation differs from the source.')
            except (VaultError, OSError, ValueError, TypeError, KeyError):
                # Restore refusal if final ordinary-reader verification fails.
                # Never replace an existing marker or discard the target.
                if not (target / _INCOMPLETE).exists():
                    _write_new(target / _INCOMPLETE, marker)
                raise
            return {'plan_id': plan['plan_id'], 'vault_id': original.vault_id,
                    'legacy_operation_mapping': operation_mapping,
                    'backup_path': str(backup), 'backup_digest': _hash(backup_manifest),
                    'source_fingerprint': plan['source_fingerprint'], 'target_path': str(target),
                    'target_state': 'complete', 'target_snapshot': snapshot,
                    'rollback_source': str(source),
                    'rollback_instruction': 'Continue using the untouched source vault.',
                    'recovery_instruction': 'Retain incomplete artifacts; preview again with fresh target and backup paths.'}
    except VaultError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise VaultError('migration_incomplete', 'Migration stopped; retain artifacts and continue using the source.') from None


def inspect_migration(target):
    """Read-only recovery status; never resume, delete, or overwrite artifacts."""
    root = _path(target)
    for name in (_INCOMPLETE, _BACKUP_INCOMPLETE):
        marker = root / name
        if marker.exists():
            return {'state': 'incomplete', 'recovery_instruction':
                    'Retain these artifacts; continue using the source and choose fresh paths for a new preview.'}
    if not root.exists():
        return {'state': 'absent'}
    Vault(root).list_records()
    return {'state': 'complete'}
