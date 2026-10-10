"""Bounded explicit offline bundles of immutable format-2 objects.

This is a file transport, not a sync-client integration or a consensus protocol.
COMPLETE binds an advertised inventory; it cannot detect an unadvertised branch.
All validation and merge staging happens in disposable OS-local state. Admission
only adds validated immutable bytes; interrupted admission can be retried.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

from .errors import VaultError
from .local_state import local_state_directory
from .locking import writer_lock
from .storage import Vault

MAX_FILES = 100_000
MAX_BYTES = 1024 * 1024 * 1024
_HASH = re.compile(r'[a-f0-9]{64}\Z')
_OBJECT = re.compile(r'\.remember/(revisions/[a-f0-9]{64}\.md|'
                     r'operations/[a-f0-9]{64}\.json|acks/[a-f0-9]{64}\.json|vault\.json)\Z')


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _fail(code, message):
    raise VaultError(code, message)


def _safe_root(root):
    try:
        path = Path(root).absolute()
        for part in (path, *path.parents):
            junction = getattr(part, 'is_junction', None)
            if part.is_symlink() or (callable(junction) and junction()):
                _fail('invalid_bundle', 'Transfer paths must not contain links.')
        return path.resolve()
    except (OSError, TypeError, ValueError):
        _fail('invalid_bundle', 'Select a regular transfer directory.')


def _safe_relative(value):
    if not isinstance(value, str) or not _OBJECT.fullmatch(value):
        _fail('invalid_bundle', 'The inventory contains an unsupported or unsafe object path.')
    if str(PurePosixPath(value)) != value:
        _fail('invalid_bundle', 'Object paths must be canonical relative paths.')
    return value


def _limits(max_files, max_bytes):
    if type(max_files) is not int or max_files < 1 or type(max_bytes) is not int or max_bytes < 1:
        _fail('invalid_bundle', 'Transfer limits must be positive integers.')


def _read(path, remaining, *, missing='incomplete_transfer'):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            _fail('invalid_bundle', 'Every transfer object must be a regular file.')
        if info.st_size > remaining:
            _fail('transfer_limit', 'The transfer exceeds its byte limit.')
        with path.open('rb') as handle:
            chunks, length = [], 0
            while length <= remaining:
                chunk = handle.read(min(64 * 1024, remaining + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
            data = b''.join(chunks)
        if len(data) > remaining:
            _fail('transfer_limit', 'The transfer exceeds its byte limit.')
        return data
    except FileNotFoundError:
        _fail(missing, 'An advertised transfer object is missing.')


def _walk(root, allowed_directories):
    """Reject links including linked directories before traversing them."""
    if not root.is_dir():
        _fail('incomplete_transfer', 'The transfer directory is missing.')
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            junction = getattr(path, 'is_junction', None)
            if path.is_symlink() or (callable(junction) and junction()):
                _fail('invalid_bundle', 'Transfer directories must not contain links.')
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                if path.relative_to(root).as_posix() not in allowed_directories:
                    _fail('invalid_bundle', 'The transfer contains an unsupported object directory.')
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                yield path
            else:
                _fail('invalid_bundle', 'Transfer directories contain an unsupported file type.')


def _objects(root, max_files, max_bytes, *, bundle=False):
    _limits(max_files, max_bytes)
    objects = {}
    total = 0
    scan = root if bundle else root / '.remember'
    _safe_root(scan)
    allowed = {'revisions', 'operations', 'acks'}
    if bundle:
        allowed = {'.remember', *(f'.remember/{name}' for name in allowed)}
    for path in _walk(scan, allowed):
        relative = path.relative_to(root).as_posix()
        if bundle and relative == 'COMPLETE.json':
            continue
        if not bundle and path.name.startswith('.pending-'):
            continue  # Uncommitted files remain untouched and unadvertised.
        _safe_relative(relative)
        if len(objects) >= max_files:
            _fail('transfer_limit', 'The transfer exceeds its file limit.')
        data = _read(path, max_bytes - total)
        total += len(data)
        if '/revisions/' in relative and _digest(data) != path.stem:
            _fail('integrity_error', 'A digest-named revision contains different bytes.')
        objects[relative] = data
    return objects


def _config(objects):
    try:
        config = json.loads(objects['.remember/vault.json'])
        if config['schema'] != 2:
            _fail('unsupported_format', 'Explicit offline transfer requires vault format 2.')
        if not isinstance(config['vault_id'], str):
            raise ValueError
        return config
    except (KeyError, TypeError, ValueError, UnicodeError):
        _fail('integrity_error', 'The immutable vault configuration is invalid.')


def _input_digest(objects):
    return _digest(_canonical(_entries(objects)))


def _entries(objects):
    return [{'path': path, 'size': len(data), 'sha256': _digest(data)}
            for path, data in sorted(objects.items())]


def _stage(vault, objects, label):
    # Preserve candidates and sound payloads on failure; local staging is never
    # portable authority and is excluded from exports.
    directory = local_state_directory(vault.root, 'transfers') / (label + '-' + uuid.uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    for kind in ('revisions', 'operations', 'acks'):
        (directory / '.remember' / kind).mkdir(parents=True, exist_ok=True)
    for relative, data in sorted(objects.items()):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle:
            handle.write(data)
    candidate = Vault(directory)
    state = candidate._load()
    return candidate, state


def _publish_object(path, data):
    """Publish atomically and exclusively, comparing exact bytes on retry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_root(path)
    if path.exists():
        if path.stat().st_size != len(data) or _read(path, max(len(data), 1)) != data:
            _fail('integrity_error', 'Immutable publication would overwrite different bytes.')
        return False
    temporary = path.parent / ('.pending-' + uuid.uuid4().hex)
    with temporary.open('xb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        # link is an atomic create-if-absent on the destination volume. Unlike
        # replace/rename it cannot overwrite a concurrently arriving object.
        os.link(temporary, path)
    except FileExistsError:
        if path.stat().st_size != len(data) or _read(path, max(len(data), 1)) != data:
            _fail('integrity_error', 'Immutable publication found different existing bytes.')
        temporary.unlink()
        return False
    temporary.unlink()
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return True


def _manifest(objects, state, config):
    result = {'schema': 1, 'vault_schema': 2, 'vault_id': config['vault_id'],
              'snapshot': state['snapshot'], 'operation_heads': sorted(state['heads']),
              'entries': _entries(objects)}
    result['digest'] = _digest(_canonical(result))
    return result


def _bundle(vault, root, max_files, max_bytes):
    root = _safe_root(root)
    marker = _read(root / 'COMPLETE.json', min(max_bytes, 32 * 1024 * 1024))
    try:
        manifest = json.loads(marker)
        if set(manifest) != {'schema', 'vault_schema', 'vault_id', 'snapshot',
                             'operation_heads', 'entries', 'digest'}:
            raise ValueError
        if (type(manifest['schema']) is not int or manifest['schema'] != 1
                or type(manifest['vault_schema']) is not int or manifest['vault_schema'] != 2):
            raise ValueError
        digest = manifest['digest']
        unsigned = {k: v for k, v in manifest.items() if k != 'digest'}
        if not isinstance(digest, str) or not _HASH.fullmatch(digest) or _digest(_canonical(unsigned)) != digest:
            _fail('integrity_error', 'The bundle completion marker hash is invalid.')
        entries = manifest['entries']
        if not isinstance(entries, list):
            raise ValueError
        _limits(max_files, max_bytes)
        if len(entries) > max_files:
            _fail('transfer_limit', 'The advertised inventory exceeds its file limit.')
        seen, total, objects = set(), 0, {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'path', 'size', 'sha256'}:
                raise ValueError
            relative = _safe_relative(entry['path'])
            if relative.casefold() in seen:
                _fail('invalid_bundle', 'The inventory contains duplicate or colliding paths.')
            seen.add(relative.casefold())
            size, expected = entry['size'], entry['sha256']
            if type(size) is not int or size < 0 or not isinstance(expected, str) or not _HASH.fullmatch(expected):
                raise ValueError
            total += size
            if total > max_bytes:
                _fail('transfer_limit', 'The advertised inventory exceeds its byte limit.')
            # Validate link components before opening any advertised path.
            _safe_root(root / relative)
            data = _read(root / relative, max_bytes)
            if len(data) != size or _digest(data) != expected:
                _fail('integrity_error', 'Advertised transfer object bytes do not match their hash.')
            objects[relative] = data
        if list(objects) != sorted(objects):
            _fail('invalid_bundle', 'The advertised inventory must be sorted.')
        actual = _objects(root, max_files, max_bytes, bundle=True)
        if set(actual) != set(objects):
            _fail('invalid_bundle', 'The bundle contains unadvertised objects.')
        if actual != objects:
            _fail('stale_merge', 'The bundle changed during validation.')
        config = _config(objects)
        target_config = vault._config()
        if config['vault_id'] != target_config['vault_id'] or target_config['schema'] != 2:
            _fail('vault_mismatch', 'Source and destination vault identities or formats differ.')
        if manifest['vault_id'] != config['vault_id']:
            _fail('vault_mismatch', 'The completion marker identifies a different vault.')
        candidate, state = _stage(vault, objects, 'source')
        if _manifest(objects, state, config) != manifest:
            _fail('integrity_error', 'The completion marker does not describe the validated source graph.')
        return manifest, objects, state
    except (KeyError, TypeError, ValueError, UnicodeError):
        _fail('invalid_bundle', 'The bundle completion marker is malformed.')


def export_bundle(vault, destination, *, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    """Create a new completed bundle, publishing COMPLETE only after rechecks."""
    destination = _safe_root(destination)
    source_root = _safe_root(vault.root)
    if destination.is_relative_to(source_root) or source_root.is_relative_to(destination):
        _fail('invalid_destination', 'The bundle destination overlaps the vault.')
    if destination.exists():
        _fail('invalid_destination', 'Export requires a new destination directory.')
    with writer_lock(vault.root):
        objects = _objects(vault.root, max_files, max_bytes)
        config = _config(objects)
        candidate, state = _stage(vault, objects, 'export')
        manifest = _manifest(objects, state, config)
        destination.mkdir(parents=True, exist_ok=False)
        for relative, data in sorted(objects.items()):
            _publish_object(destination / relative, data)
        if _objects(vault.root, max_files, max_bytes) != objects:
            _fail('stale_merge', 'The source changed during export; no completion marker was published.')
        if _objects(destination, max_files, max_bytes, bundle=True) != objects:
            _fail('integrity_error', 'Exported bytes do not match the validated inventory.')
        _publish_object(destination / 'COMPLETE.json', _canonical(manifest))
        return {'complete': True, 'snapshot': state['snapshot'],
                'manifest_digest': manifest['digest'], 'objects': len(objects)}


def _merged(vault, existing, incoming, *, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    merged = dict(existing)
    for path, data in incoming.items():
        if path in merged and merged[path] != data:
            _fail('integrity_error', 'The union contains different bytes at one immutable object path.')
        merged[path] = data
    if len(merged) > max_files or sum(map(len, merged.values())) > max_bytes:
        _fail('transfer_limit', 'The merged inventory exceeds its transfer limits.')
    candidate, state = _stage(vault, merged, 'merged')
    # These deterministic witnesses name validated immutable operations, not a
    # machine-local transfer intent. Missing acknowledged nodes make readers
    # fail closed while any part of the reviewed graph has yet to arrive.
    witnessed = False
    for digest, node in state['operation_nodes'].items():
        path = f'.remember/acks/{digest}.json'
        data = _canonical({'schema': 2, 'vault_id': node['vault_id'], 'operation': digest})
        if path in merged and merged[path] != data:
            _fail('integrity_error', 'An operation witness contains different immutable bytes.')
        if path not in merged:
            merged[path] = data
            witnessed = True
    if len(merged) > max_files or sum(map(len, merged.values())) > max_bytes:
        _fail('transfer_limit', 'The witnessed merged inventory exceeds its transfer limits.')
    if witnessed:
        candidate, state = _stage(vault, merged, 'witnessed')
    return merged, state


def _logical_state(vault):
    try:
        return vault._load()
    except VaultError as error:
        if error.code == 'incomplete_transfer':
            return None  # A complete union may repair a previously partial copy.
        raise


def _plan_details(vault, source, max_files, max_bytes):
    source = _safe_root(source)
    manifest, incoming, source_state = _bundle(vault, source, max_files, max_bytes)
    existing = _objects(vault.root, max_files, max_bytes)
    target_state = _logical_state(vault)
    target_snapshot = target_state['snapshot'] if target_state is not None else None
    merged, state = _merged(vault, existing, incoming, max_files=max_files, max_bytes=max_bytes)
    policy_changes = None
    if target_state is not None:
        policy_changes = {}
        for project in sorted(set(target_state['grants']) | set(state['grants'])):
            before = target_state['grants'].get(project, set())
            after = state['grants'].get(project, set())
            if before != after:
                policy_changes[project] = {'added': sorted(after - before), 'removed': sorted(before - after)}
    result = {'schema': 1, 'source': str(source), 'vault_id': manifest['vault_id'],
              'manifest_digest': manifest['digest'], 'source_snapshot': source_state['snapshot'],
              'target_snapshot': target_snapshot, 'target_input_digest': _input_digest(existing),
              'target_inventory': _entries(existing), 'merged_inventory': _entries(merged),
              'merged_snapshot': state['snapshot'],
              'added': sorted(set(merged) - set(existing)),
              'identical': sorted(set(merged) & set(existing)),
              'conflicts': sorted(state.get('operation_conflicts', {})),
              'operation_conflicts': state.get('operation_conflicts', {}),
              'record_conflicts': {root: heads for root, heads in sorted(state['lineage_heads'].items())
                                   if len(heads) > 1},
              'policy_changes': policy_changes,
              'grants': {project: sorted(ids) for project, ids in sorted(state['grants'].items())},
              'max_files': max_files, 'max_bytes': max_bytes}
    result['digest'] = _digest(_canonical(result))
    return result, incoming, existing, merged, state


def plan_merge(vault, source, *, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    """Validate the advertised source and full candidate before any admission."""
    return _plan_details(vault, source, max_files, max_bytes)[0]


def _publication_order(objects, state):
    # Publish every witness before any new operation. A partial graph may
    # otherwise temporarily enable a grant whose advertised revoke is missing.
    # Until all witnessed nodes arrive, the core refuses every content read.
    revisions = sorted(p for p in objects if '/revisions/' in p)
    nodes = state['operation_nodes']
    pending = {digest: set(node['parents']) for digest, node in nodes.items()}
    operations, published = [], set()
    while pending:
        ready = sorted(d for d, parents in pending.items() if parents <= published)
        if not ready:
            _fail('integrity_error', 'The merged operation graph has no causal publication order.')
        for digest in ready:
            operations.append(f'.remember/operations/{digest}.json')
            published.add(digest)
            del pending[digest]
    acks = sorted(p for p in objects if '/acks/' in p)
    return acks + revisions + operations


def _resume_details(vault, plan):
    manifest, incoming, source_state = _bundle(
        vault, plan['source'], plan['max_files'], plan['max_bytes'])
    if (manifest['digest'] != plan['manifest_digest']
            or manifest['vault_id'] != plan['vault_id']
            or source_state['snapshot'] != plan['source_snapshot']):
        _fail('stale_merge', 'The source changed since the merge preview.')
    existing = _objects(vault.root, plan['max_files'], plan['max_bytes'])
    current_entries = {entry['path']: entry for entry in _entries(existing)}
    initial_entries = {entry['path']: entry for entry in plan['target_inventory']}
    reviewed_entries = {entry['path']: entry for entry in plan['merged_inventory']}
    if (len(initial_entries) != len(plan['target_inventory'])
            or len(reviewed_entries) != len(plan['merged_inventory'])):
        _fail('invalid_bundle', 'The merge plan inventory contains duplicate paths.')
    # Retrying is allowed only for monotonic progress inside the reviewed union.
    # Deletions/changes to initial bytes and every unreviewed addition require a
    # fresh preview, including independent changes with valid causal history.
    if (any(current_entries.get(path) != entry for path, entry in initial_entries.items())
            or any(reviewed_entries.get(path) != entry for path, entry in current_entries.items())):
        _fail('stale_merge', 'The destination contains changes outside the reviewed merge inventory.')
    initial = {path: existing[path] for path in initial_entries}
    if (_entries(initial) != plan['target_inventory']
            or _input_digest(initial) != plan['target_input_digest']):
        _fail('invalid_bundle', 'The merge plan initial inventory binding is invalid.')
    merged, state = _merged(vault, initial, incoming,
                           max_files=plan['max_files'], max_bytes=plan['max_bytes'])
    if (_entries(merged) != plan['merged_inventory']
            or state['snapshot'] != plan['merged_snapshot']):
        _fail('stale_merge', 'The reconstructed union differs from the reviewed candidate.')
    return incoming, existing, merged, state


def apply_merge(vault, plan):
    """Revalidate a bound preview under the local writer lock, then only add."""
    try:
        plan = deepcopy(plan)
        digest = plan.pop('digest')
        if (_digest(_canonical(plan)) != digest or type(plan['schema']) is not int
                or plan['schema'] != 1):
            _fail('invalid_bundle', 'The merge plan binding is invalid.')
        with writer_lock(vault.root):
            incoming, existing, merged, state = _resume_details(vault, plan)
            # External file arrival does not take the local writer lock.
            if _input_digest(_objects(vault.root, plan['max_files'], plan['max_bytes'])) != _input_digest(existing):
                _fail('stale_merge', 'The destination changed during candidate validation.')
            added = 0
            try:
                for relative in _publication_order(merged, state):
                    added += bool(_publish_object(vault.root / relative, merged[relative]))
            except OSError:
                return {'complete': False, 'code': 'transfer_interrupted', 'added': added,
                        'manifest_digest': plan['manifest_digest'], 'retry_required': True}
            actual = _objects(vault.root, plan['max_files'], plan['max_bytes'])
            if actual != merged:
                _fail('stale_merge', 'External file arrival changed the destination during publication; retry the bundle.')
            snapshot = vault.snapshot_id()
            if snapshot != state['snapshot']:
                _fail('integrity_error', 'The admitted union differs from its validated snapshot.')
            return {'complete': True, 'added': added, 'identical': len(merged) - added,
                    'snapshot': snapshot, 'manifest_digest': plan['manifest_digest']}
    except (KeyError, TypeError, ValueError, UnicodeError):
        _fail('invalid_bundle', 'The merge plan is malformed.')


def import_bundle(vault, bundle, *, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    """Import a completed bundle; retrying after interruption resumes safely."""
    return apply_merge(vault, plan_merge(vault, bundle, max_files=max_files, max_bytes=max_bytes))
