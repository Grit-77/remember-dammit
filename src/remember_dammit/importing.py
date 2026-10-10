"""Explicit, bounded Markdown source import; source trees are never written.

Plans are local owner previews, not signed capabilities. Apply preflights the
entire admitted manifest and target heads before writing. Individual storage
operations are atomic; batches are not. A partial result names the failed index
and completed records. Retry the identical plan after fixing a transient failure;
changed source bytes or target heads require a fresh preview. Removed source files
never delete canonical records. Frontmatter remains untrusted raw body text.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import unicodedata

from .errors import VaultError
from .validation import validate_identifier

MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 1000
MAX_ENTRIES = 10000
MAX_PLAN_BYTES = 4 * 1024 * 1024
_EXCLUDED_DIRS = {'node_modules', '__pycache__', 'cache', 'caches', 'system volume information', '$recycle.bin'}
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _is_link(path):
    # Any Windows reparse point is excluded, including junctions on Python 3.11.
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _guard(path):
    if any(_is_link(item) for item in (path, *path.parents)):
        raise VaultError('invalid_source', 'Source paths cannot contain links or junctions.')


def _root(source_root):
    try:
        path = Path(source_root)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError
        _guard(path)
        return path.resolve()
    except (TypeError, ValueError, OSError):
        raise VaultError('invalid_source', 'Specify an existing absolute source directory.') from None


def _scope(scope):
    if scope in ('personal', 'shared'):
        return scope
    if isinstance(scope, str) and ':' in scope:
        prefix, identifier = scope.split(':', 1)
        if prefix in ('project', 'session'):
            validate_identifier(identifier, 'Scope ID')
            return scope
    raise VaultError('invalid_scope', 'Select a valid explicit import scope.')


def _portable(relative):
    if not isinstance(relative, str) or len(relative) > 240 or '\\' in relative:
        return False
    parts = relative.split('/')
    if len(parts) > 32:
        return False
    return all(part not in ('', '.', '..') and len(part) <= 128
               and not part.endswith((' ', '.'))
               and not any(ord(c) < 32 or ord(c) == 127 or c in '<>:"|?*' for c in part)
               and part.split('.')[0].upper() not in _RESERVED for part in parts)


def _read(root, relative):
    if not _portable(relative):
        raise VaultError('invalid_plan', 'Import plan contains an unsafe source path.')
    path = root.joinpath(*PurePosixPath(relative).parts)
    _guard(path)
    if not path.resolve().is_relative_to(root):
        raise VaultError('invalid_source', 'Source file is outside the explicit root.')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise VaultError('invalid_source', 'Source must be a regular file.')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise VaultError('source_changed', 'Source file changed during preview.')
        payload = handle.read(MAX_FILE_BYTES + 1)
    _guard(path)
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise VaultError('source_changed', 'Source file changed during preview.')
    return payload


def _scan(root):
    files, excluded, bodies = [], [], {}
    count, total = 0, 0
    pending = [root]
    while pending:
        directory = pending.pop()
        _guard(directory)
        entries = []
        with os.scandir(directory) as scan:
            for entry in scan:
                count += 1
                if count > MAX_ENTRIES:
                    raise VaultError('import_limit', 'Source tree exceeds the bounded entry limit.')
                entries.append(entry)
        for entry in sorted(entries, key=lambda item: item.name):
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            reason = None
            if _is_link(path):
                reason = 'link'
            elif not _portable(relative):
                reason = 'nonportable_path'
            elif entry.name.startswith('.') or getattr(info, 'st_file_attributes', 0) & 0x6:
                reason = 'hidden_or_system'
            elif stat.S_ISDIR(info.st_mode):
                if entry.name.casefold() in _EXCLUDED_DIRS:
                    reason = 'excluded_directory'
                else:
                    pending.append(path)
                    continue
            elif not stat.S_ISREG(info.st_mode):
                reason = 'not_regular'
            elif path.suffix.casefold() != '.md':
                reason = 'not_markdown'
            elif info.st_size > MAX_FILE_BYTES:
                reason = 'too_large'
            else:
                payload = _read(root, relative)
                if len(payload) > MAX_FILE_BYTES:
                    reason = 'too_large'
                else:
                    try:
                        body = payload.decode('utf-8')
                    except UnicodeError:
                        reason = 'invalid_utf8'
                    else:
                        if not body.strip():
                            reason = 'empty'
                        else:
                            total += len(payload)
                            if len(files) >= MAX_FILES or total > MAX_TOTAL_BYTES:
                                raise VaultError('import_limit', 'Import exceeds the bounded file or byte limit.')
                            files.append({'path': relative, 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)})
                            bodies[relative] = body
            if reason:
                excluded.append({'path': relative, 'reason': reason})
    groups = {}
    for item in files:
        groups.setdefault(unicodedata.normalize('NFC', item['path']).casefold(), []).append(item)
    collisions = {item['path'] for group in groups.values() if len(group) > 1 for item in group}
    excluded.extend({'path': path, 'reason': 'case_collision'} for path in collisions)
    files = [item for item in files if item['path'] not in collisions]
    return sorted(files, key=lambda item: item['path']), sorted(excluded, key=lambda item: item['path']), bodies


def _separate(root, vault):
    target = vault.root.resolve()
    locks = target.parent / '.remember-dammit-locks'
    if (root.is_relative_to(target) or target.is_relative_to(root)
            or root.is_relative_to(locks) or locks.is_relative_to(root)):
        raise VaultError('invalid_source', 'Source and canonical target must be separate trees.')


def _safe_record(record, scope):
    return (record['scope'] == scope and record['evidence'] == 'source-excerpt'
            and record['disclosure'] == 'private' and record['remote_allowed'] is False
            and record['kind'] == 'source' and record['state'] == 'active' and not record['sources'])


def _head(vault, identifier, scope):
    try:
        history = vault.history(identifier)
    except VaultError as exc:
        if exc.code == 'not_found':
            return None
        raise
    if not history[0]['actor'].startswith('markdown-import:') or not _safe_record(history[-1], scope):
        raise VaultError('import_conflict', 'Import identity has incompatible target content or policy.')
    return history[-1]


def _operation(item, collection, scope):
    return 'import-' + _digest({'collection': collection, 'scope': scope, **item})


def plan_import(source_root, *, collection, scope, vault=None) -> dict:
    """Read a source tree and preview additions/corrections without writing.

    Pass an initialized Vault to observe current heads when updating existing
    logical sources. A preview without a target can only create/retry additions.
    Limits: 1 MiB/file, 16 MiB admitted bytes, 1000 files, 10000 scanned entries.
    Links, hidden/system/cache directories, invalid UTF-8, empty/nonportable files
    and case/Unicode-normalization collisions are reported as exclusions.
    """
    validate_identifier(collection, 'Collection ID')
    _scope(scope)
    root = _root(source_root)
    if vault is not None:
        _separate(root, vault)
    try:
        files, excluded, bodies = _scan(root)
        for item in files:
            item['record_id'] = 'import-' + _digest([collection, scope, item['path']])
            head = _head(vault, item['record_id'], scope) if vault is not None else None
            item['action'] = 'create' if head is None else ('noop' if head['body'] == bodies[item['path']] else 'correct')
            item['expected'] = None if head is None else {'id': head['id'], 'revision': head['revision']}
            item['operation_id'] = _operation(item, collection, scope)
        plan = {'schema': 1, 'source_root': str(root), 'collection': collection, 'scope': scope,
                'vault_id': vault.vault_id if vault is not None else None, 'files': files, 'excluded': excluded,
                'disclosure': 'private', 'remote_allowed': False, 'evidence': 'source-excerpt'}
        plan['plan_id'] = _digest(plan)
        encoded = json.dumps(plan, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) + 1 > MAX_PLAN_BYTES:
            raise VaultError('import_limit', 'Preview exceeds the bounded plan byte limit.')
        return plan
    except OSError:
        raise VaultError('invalid_source', 'Source tree could not be read safely.') from None


def _validate(plan):
    try:
        if (not isinstance(plan, dict) or type(plan.get('schema')) is not int or plan['schema'] != 1
                or set(plan) != {'schema', 'source_root', 'collection', 'scope', 'vault_id', 'files',
                                 'excluded', 'disclosure', 'remote_allowed', 'evidence', 'plan_id'}):
            raise ValueError
        value = dict(plan)
        identifier = value.pop('plan_id')
        if identifier != _digest(value):
            raise ValueError
        validate_identifier(plan['collection'], 'Collection ID')
        _scope(plan['scope'])
        if (plan['disclosure'] != 'private' or plan['remote_allowed'] is not False
                or plan['evidence'] != 'source-excerpt'):
            raise ValueError
        files = plan['files']
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise ValueError
        paths = set()
        for item in files:
            if not isinstance(item, dict) or set(item) != {'path', 'sha256', 'bytes', 'record_id', 'action', 'expected', 'operation_id'}:
                raise ValueError
            if not _portable(item['path']) or item['path'] in paths or item['action'] not in ('create', 'correct', 'noop'):
                raise ValueError
            if (type(item['bytes']) is not int or not 0 < item['bytes'] <= MAX_FILE_BYTES
                    or not isinstance(item['sha256'], str) or len(item['sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in item['sha256'])):
                raise ValueError
            paths.add(item['path'])
            if item['record_id'] != 'import-' + _digest([plan['collection'], plan['scope'], item['path']]):
                raise ValueError
            request = {key: value for key, value in item.items() if key != 'operation_id'}
            if item['operation_id'] != _operation(request, plan['collection'], plan['scope']):
                raise ValueError
            if (item['action'] == 'create') != (item['expected'] is None):
                raise ValueError
            if item['expected'] is not None:
                if not isinstance(item['expected'], dict) or set(item['expected']) != {'id', 'revision'}:
                    raise ValueError
                validate_identifier(item['expected']['id'], 'Record ID')
        return plan
    except (KeyError, TypeError, ValueError, UnicodeError, VaultError):
        raise VaultError('invalid_plan', 'Import plan is invalid; generate a fresh preview.') from None


def apply_import(vault, plan) -> dict:
    """Apply a fully preflighted plan with stable per-file retry operations.

    Validation errors raise VaultError before writes. Write-time failures return
    a JSON partial result (including possibly committed-but-unacknowledged failed
    operation); retry the same plan to resolve that ambiguity. Process death has
    no report, but stable operation IDs still make same-plan retry safe. The
    source text is read once into bounded memory; later source edits never change
    the accepted preview bytes written by this invocation.
    """
    _validate(plan)
    root = _root(plan['source_root'])
    _separate(root, vault)
    if plan['vault_id'] is not None and plan['vault_id'] != vault.vault_id:
        raise VaultError('invalid_plan', 'Import preview belongs to another target vault.')
    try:
        files, excluded, bodies = _scan(root)
    except (OSError, VaultError):
        raise VaultError('source_changed', 'Source manifest changed or is no longer safe; preview again.') from None
    observed = [{key: item[key] for key in ('path', 'sha256', 'bytes')} for item in plan['files']]
    if files != observed or excluded != plan['excluded']:
        raise VaultError('source_changed', 'Source manifest changed; preview again before importing.')
    ready = []
    for item in plan['files']:
        head = _head(vault, item['record_id'], plan['scope'])
        completed = (head is not None and head['actor'] == 'markdown-import:' + item['operation_id']
                     and head['body'] == bodies[item['path']])
        expected = item['expected']
        if not completed:
            if expected is None:
                if head is not None:
                    raise VaultError('stale_revision', 'Existing source requires a preview against its target vault.')
            elif head is None or {'id': head['id'], 'revision': head['revision']} != expected:
                raise VaultError('stale_revision', 'Target source changed after preview; preview again.')
        if item['action'] == 'noop' and head['body'] != bodies[item['path']]:
            raise VaultError('invalid_plan', 'No-op preview must match the observed target body.')
        ready.append(head if completed or item['action'] == 'noop' else None)
    # Target preflight can take time in a large vault. Reobserve the complete
    # source manifest at the last pre-write boundary, then use admitted bytes.
    try:
        final_files, final_excluded, _ = _scan(root)
    except (OSError, VaultError):
        raise VaultError('source_changed', 'Source changed during preflight; preview again.') from None
    if final_files != observed or final_excluded != plan['excluded']:
        raise VaultError('source_changed', 'Source changed during preflight; preview again.')
    result = {'status': 'complete', 'plan_id': plan['plan_id'], 'atomic': False,
              'completed': [], 'retry_same_plan': True}
    for index, item in enumerate(plan['files']):
        try:
            record = ready[index]
            if record is None:
                fields = {'title': item['path'], 'body': bodies[item['path']],
                          'actor': 'markdown-import:' + item['operation_id'], 'operation_id': item['operation_id']}
                if item['action'] == 'create':
                    record = vault.put(**fields, record_id=item['record_id'], scope=plan['scope'], kind='source',
                                       evidence='source-excerpt', disclosure='private', remote_allowed=False)
                else:
                    record = vault.correct(item['expected']['id'], expected_revision=item['expected']['revision'],
                                           **fields, sources=[])
            result['completed'].append({'index': index, 'path': item['path'], 'record_id': record['id'],
                                        'revision': record['revision']})
        except (VaultError, OSError, ValueError) as exc:
            result.update(status='partial', failed_index=index,
                          error={'code': exc.code if isinstance(exc, VaultError) else 'import_failed',
                                 'message': 'Import interrupted; completed records remain. Retry the identical plan.'})
            break
    return result
