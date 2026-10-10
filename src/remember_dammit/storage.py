"""Portable immutable Markdown records and an atomic operation journal.

Commit markers are the sole publication point. Orphan payloads are preserved
and ignored by readers. This foundation detects external edits and does not
implement native-editor reconciliation or offline synchronization.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import yaml

from .errors import VaultError
from .locking import writer_lock
from .validation import validate_identifier

_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_STATES = {'active', 'proposed', 'superseded', 'retracted'}
_EVIDENCE = {'user-statement', 'source-excerpt', 'agent-inference', 'observation'}
_DISCLOSURE = {'private', 'shared', 'public'}
_FIELDS = {'id', 'kind', 'scope', 'state', 'title', 'aliases', 'sources', 'supersedes',
           'evidence', 'disclosure', 'remote_allowed', 'actor', 'created_at'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _id(value, label='ID'):
    return validate_identifier(value, label)


def _scope(value):
    if value in ('personal', 'shared'):
        return value
    if isinstance(value, str) and ':' in value:
        prefix, name = value.split(':', 1)
        if prefix in ('project', 'session'):
            try:
                _id(name, 'Scope ID')
                return value
            except VaultError:
                pass
    raise VaultError('invalid_scope', 'Select a valid personal, shared, project, or session scope.')


def _strings(values, label, *, ids=False):
    if values is None:
        return []
    if not isinstance(values, list):
        raise VaultError('invalid_input', f'{label} must be a list.')
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise VaultError('invalid_input', f'{label} entries must be nonempty strings.')
        if ids:
            _id(value, 'Source ID')
        if value not in result:
            result.append(value)
    return result


def _metadata(record):
    _id(record.get('id'), 'Record ID')
    _id(record.get('kind'), 'Kind')
    _scope(record.get('scope'))
    for field in ('title', 'actor', 'created_at'):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise VaultError('invalid_input', f'{field} must be a nonempty string.')
    if not isinstance(record.get('body'), str) or not record['body'].strip():
        raise VaultError('invalid_input', 'body must be a nonempty string.')
    for field, valid in [('state', _STATES), ('evidence', _EVIDENCE), ('disclosure', _DISCLOSURE)]:
        if not isinstance(record.get(field), str) or record[field] not in valid:
            raise VaultError('invalid_input', f'Invalid {field}.')
    if type(record.get('remote_allowed')) is not bool:
        raise VaultError('invalid_input', 'remote_allowed must be a boolean.')
    _strings(record.get('aliases'), 'aliases')
    _strings(record.get('sources'), 'sources', ids=True)
    if record.get('supersedes') is not None:
        _id(record['supersedes'], 'Predecessor ID')


def _fsync_directory(directory):
    # Windows exposes no portable directory fsync. File flush + atomic rename
    # are exercised there; power-loss durability still needs platform trials.
    if os.name != 'nt':
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _publish(path, data):
    """Flush new bytes before atomic publication; caller owns writer lock."""
    temporary = path.parent / ('.pending-' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise VaultError('integrity_error', 'Publication would overwrite existing content.')
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        # Keep the immutable payload orphan if marker publication failed.
        if temporary.exists():
            temporary.unlink()


def _is_link(path):
    junction_check = getattr(path, 'is_junction', None)
    if path.is_symlink() or (callable(junction_check) and junction_check()):
        return True
    if os.name == 'nt':
        # The centralized native guard also covers Python 3.11 junctions.
        from .local_state import _is_link as native_link_check
        return native_link_check(path)
    return False


def _root_path(root):
    try:
        path = Path(root).absolute()
        if _is_link(path):
            raise VaultError('invalid_vault', 'The selected vault root must not be a link.')
        return path.resolve()
    except (TypeError, ValueError, OSError):
        raise VaultError('invalid_vault', 'Select a valid vault path.') from None


class Vault:
    """Open an explicitly initialized vault; all returned data is detached."""

    def __new__(cls, root):
        if cls is Vault:
            if (_root_path(root) / '.migration-INCOMPLETE.json').exists():
                raise VaultError('incomplete_transfer', 'This migration destination is not yet verified.')
            try:
                config = json.loads((_root_path(root) / '.remember/vault.json').read_bytes())
            except RecursionError:
                raise VaultError('invalid_vault', 'The vault metadata or layout is invalid.') from None
            except (OSError, ValueError, TypeError):
                config = {}
            if isinstance(config, dict) and config.get('schema') == 2:
                from .storage_v2 import CausalVault
                return object.__new__(CausalVault)
        return object.__new__(cls)

    def __init__(self, root):
        self._root = _root_path(root)
        self._vault_id = self._config()['vault_id']

    @classmethod
    def initialize(cls, root, *, format_version=2):
        if type(format_version) is not int or format_version not in (1, 2):
            raise VaultError('invalid_input', 'format_version must be 1 or 2.')
        if format_version == 2 and not (_root_path(root) / '.remember').exists():
            from .storage_v2 import CausalVault
            return CausalVault.initialize(root)
        path = _root_path(root)
        try:
            with writer_lock(path):
                if (path / '.remember').exists():
                    vault = cls(path)
                    vault.list_records()
                    return vault
                if path.exists() and (not path.is_dir() or any(path.iterdir())):
                    raise VaultError('invalid_vault', 'Initialization requires a new or empty directory.')
                path.mkdir(parents=True, exist_ok=True)
                managed = path / '.remember'
                managed.mkdir()
                (managed / 'revisions').mkdir()
                (managed / 'operations').mkdir()
                config = {'schema': 1, 'vault_id': str(uuid.uuid4()), 'policy': {'grants': {}}}
                _publish(managed / 'head.json', _canonical(
                    {'schema': 1, 'vault_id': config['vault_id'], 'sequence': 0, 'digest': None}))
                _publish(managed / 'vault.json', _canonical(config))
                return cls(path)
        except OSError:
            raise VaultError('storage_error', 'Vault initialization could not be persisted.') from None

    @property
    def root(self):
        return self._root

    @property
    def vault_id(self):
        return self._vault_id

    def _safe(self, relative, *, directory=False):
        if not isinstance(relative, str) or '\\' in relative:
            raise VaultError('integrity_error', 'Invalid managed path.')
        parts = Path(relative).parts
        if not parts or Path(relative).is_absolute() or any(part in ('..', '.') for part in parts):
            raise VaultError('integrity_error', 'Invalid managed path.')
        path = self._root
        for part in parts:
            path = path / part
            if _is_link(path):
                raise VaultError('integrity_error', 'A managed path is an external link.')
        if not path.resolve().is_relative_to(self._root):
            raise VaultError('integrity_error', 'A managed path leaves the vault.')
        if directory and not path.is_dir():
            raise VaultError('invalid_vault', 'The vault layout is incomplete.')
        return path

    def _config(self):
        try:
            if not self._root.is_dir():
                raise VaultError('invalid_vault', 'The selected directory is not an initialized vault.')
            self._safe('.remember', directory=True)
            self._safe('.remember/revisions', directory=True)
            self._safe('.remember/operations', directory=True)
            config = json.loads(self._safe('.remember/vault.json').read_bytes())
            if (not isinstance(config, dict) or type(config.get('schema')) is not int
                    or config['schema'] != 1):
                raise ValueError
            uuid.UUID(config['vault_id'])
            if hasattr(self, '_vault_id') and config['vault_id'] != self._vault_id:
                raise ValueError
            policy = config['policy']
            if not isinstance(policy, dict) or set(policy) != {'grants'} or not isinstance(policy['grants'], dict):
                raise ValueError
            for project, records in policy['grants'].items():
                _id(project, 'Project ID')
                if not isinstance(records, list) or _strings(records, 'grants', ids=True) != records:
                    raise ValueError
            return config
        except VaultError as exc:
            if exc.code == 'integrity_error':
                raise
            raise VaultError('invalid_vault', 'The vault metadata or layout is invalid.') from None
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise VaultError('invalid_vault', 'The vault metadata or layout is invalid.') from None

    def _read_record(self, descriptor):
        try:
            if not isinstance(descriptor, dict) or set(descriptor) != {'id', 'path', 'revision'}:
                raise ValueError
            _id(descriptor['id'])
            if not isinstance(descriptor['revision'], str) or not _DIGEST.fullmatch(descriptor['revision']):
                raise ValueError
            relative = descriptor['path']
            if not isinstance(relative, str) or not re.fullmatch(r'\.remember/revisions/[a-f0-9]{32}\.md', relative):
                raise ValueError
            data = self._safe(relative).read_bytes()
            if _digest(data) != descriptor['revision']:
                raise ValueError
            text = data.decode('utf-8')
            if not text.startswith('---\n'):
                raise ValueError
            frontmatter, body = text[4:].split('\n---\n', 1)
            properties = yaml.safe_load(frontmatter)
            if not isinstance(properties, dict) or set(properties) != {'rd_schema', *(f'rd_{f}' for f in _FIELDS)}:
                raise ValueError
            if type(properties['rd_schema']) is not int or properties['rd_schema'] != 1:
                raise ValueError
            record = {key[3:]: value for key, value in properties.items() if key != 'rd_schema'}
            record['body'] = body
            _metadata(record)
            if record['id'] != descriptor['id']:
                raise ValueError
            record.update(path=relative, revision=descriptor['revision'])
            return record
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, yaml.YAMLError, VaultError):
            raise VaultError('integrity_error', 'A committed revision is missing, changed, or invalid.') from None

    def _read_checkpoint(self):
        try:
            checkpoint = json.loads(self._safe('.remember/head.json').read_bytes())
            if (not isinstance(checkpoint, dict)
                    or set(checkpoint) != {'schema', 'vault_id', 'sequence', 'digest'}
                    or type(checkpoint['schema']) is not int or checkpoint['schema'] != 1
                    or checkpoint['vault_id'] != self._vault_id
                    or type(checkpoint['sequence']) is not int or checkpoint['sequence'] < 0):
                raise ValueError
            if checkpoint['sequence'] == 0:
                if checkpoint['digest'] is not None:
                    raise ValueError
            elif not isinstance(checkpoint['digest'], str) or not _DIGEST.fullmatch(checkpoint['digest']):
                raise ValueError
            return checkpoint
        except (OSError, ValueError, TypeError, KeyError, VaultError):
            raise VaultError('integrity_error', 'The committed-head checkpoint is missing or invalid.') from None

    def _write_checkpoint(self, sequence, digest):
        """Flush and atomically replace managed highwater metadata.

        An acknowledged operation has an anchor outside its immutable marker.
        This detects lost journal tails, including lost revocations. Coordinated
        rollback of the entire vault AND checkpoint cannot be detected locally.
        """
        checkpoint = dict(schema=1, vault_id=self._vault_id, sequence=sequence, digest=digest)
        path = self._safe('.remember/head.json')
        temporary = path.parent / ('.pending-' + uuid.uuid4().hex)
        try:
            with temporary.open('xb') as handle:
                handle.write(_canonical(checkpoint))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _recover_checkpoint(self, data):
        # Called under the writer lock. Valid markers ahead of the checkpoint
        # are committed but unacknowledged crash survivors; anchor before retry.
        if data['checkpoint']['sequence'] != len(data['operations']):
            self._write_checkpoint(len(data['operations']), data['head'])

    def _load(self):
        """Replay a complete marker set, validating every referenced payload."""
        config = self._config()
        checkpoint = self._read_checkpoint()
        records, operations, successors, grants = {}, {}, {}, {}
        previous = None
        paths = sorted(self._safe('.remember/operations', directory=True).glob('*.json'))
        if checkpoint['sequence'] > len(paths):
            raise VaultError('integrity_error', 'The committed journal lost its checkpointed tail.')
        for sequence, path in enumerate(paths, 1):
            try:
                self._safe(path.relative_to(self._root).as_posix())
                op = json.loads(path.read_bytes())
                required = {'schema', 'sequence', 'operation_id', 'request_digest', 'previous',
                            'action', 'result', 'digest'}
                if not isinstance(op, dict) or set(op) != required:
                    raise ValueError
                _id(op['operation_id'], 'Operation ID')
                if (type(op['schema']) is not int or op['schema'] != 1 or type(op['sequence']) is not int
                        or op['sequence'] != sequence or op['previous'] != previous
                        or path.name != f"{sequence:020d}-{op['operation_id']}.json"
                        or op['operation_id'] in operations
                        or not isinstance(op['request_digest'], str)
                        or not _DIGEST.fullmatch(op['request_digest'])):
                    raise ValueError
                unsigned = {key: value for key, value in op.items() if key != 'digest'}
                if op['digest'] != _digest(_canonical(unsigned)):
                    raise ValueError
                if sequence == checkpoint['sequence'] and op['digest'] != checkpoint['digest']:
                    raise ValueError
                action = op['action']
                if action in ('put', 'correct'):
                    record = self._read_record(op['result'])
                    if any(existing.casefold() == record['id'].casefold() for existing in records):
                        raise ValueError
                    parent = record['supersedes']
                    if action == 'put' and parent is not None:
                        raise ValueError
                    if action == 'correct':
                        if parent not in records or parent in successors:
                            raise ValueError
                        old = records[parent]
                        if any(record[field] != old[field] for field in
                               ('scope', 'disclosure', 'remote_allowed', 'kind', 'evidence')):
                            raise ValueError
                        successors[parent] = record['id']
                    records[record['id']] = record
                elif action in ('grant', 'revoke'):
                    result = op['result']
                    if not isinstance(result, dict) or set(result) != {'project', 'record_id', 'granted'}:
                        raise ValueError
                    _id(result['project'], 'Project ID')
                    record = records.get(result['record_id'])
                    if (record is None or record['scope'] != 'personal'
                            or type(result['granted']) is not bool or result['granted'] != (action == 'grant')):
                        raise ValueError
                    admitted = grants.setdefault(result['project'], set())
                    if result['granted']:
                        admitted.add(result['record_id'])
                    else:
                        admitted.discard(result['record_id'])
                else:
                    raise ValueError
                operations[op['operation_id']] = op
                previous = op['digest']
            except VaultError as exc:
                if exc.code == 'integrity_error':
                    raise
                raise VaultError('integrity_error', 'A committed operation is invalid.') from None
            except (OSError, ValueError, TypeError, KeyError):
                raise VaultError('integrity_error', 'A committed operation is missing, changed, or invalid.') from None
        for project, admitted in config['policy']['grants'].items():
            for record_id in admitted:
                if record_id not in records or records[record_id]['scope'] != 'personal':
                    raise VaultError('integrity_error', 'The disclosure policy references an invalid record.')
            # Config supplies the initial policy; journal changes are the latest authority.
            initial = set(admitted)
            for op in operations.values():
                if op['action'] in ('grant', 'revoke') and op['result']['project'] == project:
                    if op['result']['granted']:
                        initial.add(op['result']['record_id'])
                    else:
                        initial.discard(op['result']['record_id'])
            grants[project] = initial
        current = deepcopy(records)
        for predecessor in successors:
            current[predecessor]['state'] = 'superseded'
        snapshot = _digest(_canonical({'config': config, 'head': previous}))
        return {'records': records, 'current': current, 'operations': operations,
                'successors': successors, 'grants': grants, 'snapshot': snapshot, 'head': previous,
                'checkpoint': checkpoint}

    def list_records(self):
        return list(self._load()['current'].values())

    def get(self, record_id):
        _id(record_id, 'Record ID')
        record = self._load()['current'].get(record_id)
        if record is None:
            raise VaultError('not_found', 'The record does not exist.')
        return record

    def history(self, record_id):
        _id(record_id, 'Record ID')
        data = self._load()
        if record_id not in data['current']:
            raise VaultError('not_found', 'The record does not exist.')
        cursor = record_id
        while data['current'][cursor]['supersedes'] is not None:
            cursor = data['current'][cursor]['supersedes']
        lineage = []
        while cursor is not None:
            lineage.append(data['current'][cursor])
            cursor = data['successors'].get(cursor)
        return lineage

    def snapshot_id(self):
        return self._load()['snapshot']

    def heads(self, record_id):
        """The explicitly preserved v1 format has one linear lineage head."""
        return [self.history(record_id)[-1]]

    def operation_heads(self):
        head = self._load()['head']
        return [head] if head is not None else []

    def grants_for(self, project):
        _id(project, 'Project ID')
        return set(self._load()['grants'].get(project, set()))

    def _sources(self, sources, scope, data):
        for source_id in sources:
            source = data['current'].get(source_id)
            if source is None:
                raise VaultError('not_found', 'A source record does not exist.')
            eligible = source['scope'] in (scope, 'shared')
            if scope.startswith('project:') and source['scope'] == 'personal':
                eligible = source_id in data['grants'].get(scope[8:], set())
            if not eligible or source['state'] != 'active':
                raise VaultError('source_scope', 'A source is not eligible in the selected scope.')

    def _retry(self, data, operation_id, request_digest):
        old = data['operations'].get(operation_id)
        if old is None:
            return None
        if old['request_digest'] != request_digest:
            raise VaultError('operation_conflict', 'This operation ID was used with another request.')
        if old['action'] in ('put', 'correct'):
            return deepcopy(data['records'][old['result']['id']])
        return deepcopy(old['result'])

    def _commit(self, action, result, operation_id, request_digest, data):
        # Detect an arbitrary editor touching admitted payloads or policy while
        # the writer prepared its new payload. Participating writers are locked.
        if self._load()['snapshot'] != data['snapshot']:
            raise VaultError('stale_revision', 'The vault changed before publication.')
        sequence = len(data['operations']) + 1
        op = {'schema': 1, 'sequence': sequence, 'operation_id': operation_id,
              'request_digest': request_digest, 'previous': data['head'],
              'action': action, 'result': result}
        op['digest'] = _digest(_canonical(op))
        path = self._safe('.remember/operations', directory=True) / f'{sequence:020d}-{operation_id}.json'
        _publish(path, _canonical(op))
        self._write_checkpoint(sequence, op['digest'])

    def _write_record(self, record):
        metadata = {'rd_schema': 1, **{f'rd_{field}': record[field] for field in sorted(_FIELDS)}}
        text = '---\n' + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=True).rstrip('\n')
        payload = (text + '\n---\n' + record['body']).encode('utf-8')
        relative = '.remember/revisions/' + uuid.uuid4().hex + '.md'
        _publish(self._safe(relative), payload)
        record.update(path=relative, revision=_digest(payload))
        return {field: record[field] for field in ('id', 'path', 'revision')}

    def put(self, *, title, body, scope, kind='note', aliases=None, sources=None,
            evidence='user-statement', disclosure='private', remote_allowed=False,
            record_id=None, operation_id=None, actor='local', state='active'):
        request = dict(action='put', title=title, body=body, scope=scope, kind=kind,
                       aliases=aliases, sources=sources, evidence=evidence, disclosure=disclosure,
                       remote_allowed=remote_allowed, record_id=record_id, actor=actor, state=state)
        try:
            request_digest = _digest(_canonical(request))
        except (TypeError, ValueError, UnicodeError):
            raise VaultError('invalid_input', 'The request must contain valid JSON values.') from None
        operation_id = _id(operation_id if operation_id is not None else uuid.uuid4().hex, 'Operation ID')
        if record_id is not None:
            _id(record_id, 'Record ID')
        record = dict(id=record_id if record_id is not None else uuid.uuid4().hex,
                      title=title, body=body, scope=scope, kind=kind,
                      aliases=_strings(aliases, 'aliases'), sources=_strings(sources, 'sources', ids=True),
                      supersedes=None, evidence=evidence, disclosure=disclosure,
                      remote_allowed=remote_allowed, actor=actor, state=state,
                      created_at=datetime.now(timezone.utc).isoformat())
        _metadata(record)
        try:
            with writer_lock(self._root):
                data = self._load()
                self._recover_checkpoint(data)
                old = self._retry(data, operation_id, request_digest)
                if old is not None:
                    return old
                if any(key.casefold() == record['id'].casefold() for key in data['records']):
                    raise VaultError('invalid_record', 'That record ID is already admitted.')
                self._sources(record['sources'], record['scope'], data)
                descriptor = self._write_record(record)
                self._commit('put', descriptor, operation_id, request_digest, data)
                return deepcopy(record)
        except OSError:
            raise VaultError('storage_error', 'The operation could not be persisted; retry with the same operation ID.') from None

    def correct(self, record_id, *, expected_revision, title, body, operation_id=None,
                actor='local', aliases=None, sources=None, expected_snapshot=None):
        """Correct a head, optionally binding prior checks to a vault snapshot.

        The snapshot is a precondition for a new write, not part of its request
        identity. An exact operation replay still returns its historical receipt.
        """
        _id(record_id, 'Record ID')
        if expected_snapshot is not None and (
                not isinstance(expected_snapshot, str) or len(expected_snapshot) != 64
                or any(character not in '0123456789abcdef' for character in expected_snapshot)):
            raise VaultError('invalid_input', 'expected_snapshot must be a vault snapshot digest.')
        operation_id = _id(operation_id if operation_id is not None else uuid.uuid4().hex, 'Operation ID')
        request = dict(action='correct', record_id=record_id, expected_revision=expected_revision,
                       title=title, body=body, actor=actor, aliases=aliases, sources=sources)
        try:
            request_digest = _digest(_canonical(request))
        except (TypeError, ValueError, UnicodeError):
            raise VaultError('invalid_input', 'The request must contain valid JSON values.') from None
        try:
            with writer_lock(self._root):
                data = self._load()
                self._recover_checkpoint(data)
                old_result = self._retry(data, operation_id, request_digest)
                if old_result is not None:
                    return old_result
                if expected_snapshot is not None and data['snapshot'] != expected_snapshot:
                    raise VaultError('source_changed', 'Vault content or sharing policy changed after preflight.')
                old = data['current'].get(record_id)
                if old is None:
                    raise VaultError('not_found', 'The record does not exist.')
                if old['revision'] != expected_revision or record_id in data['successors']:
                    raise VaultError('stale_revision', 'The correction must name the current predecessor revision.')
                record = deepcopy(data['records'][record_id])
                record.pop('path')
                record.pop('revision')
                supplied_aliases = _strings(aliases, 'aliases') if aliases is not None else []
                record.update(id=uuid.uuid4().hex, title=title, body=body, supersedes=record_id,
                              actor=actor, created_at=datetime.now(timezone.utc).isoformat(),
                              aliases=list(dict.fromkeys([*supplied_aliases, *old['aliases'], old['title']])),
                              sources=_strings(sources, 'sources', ids=True) if sources is not None else old['sources'])
                _metadata(record)
                self._sources(record['sources'], record['scope'], data)
                descriptor = self._write_record(record)
                self._commit('correct', descriptor, operation_id, request_digest, data)
                return deepcopy(record)
        except OSError:
            raise VaultError('storage_error', 'The correction could not be persisted; retry with the same operation ID.') from None

    def _policy_change(self, action, project, record_id, operation_id):
        _id(project, 'Project ID')
        _id(record_id, 'Record ID')
        operation_id = _id(operation_id if operation_id is not None else uuid.uuid4().hex, 'Operation ID')
        request_digest = _digest(_canonical(dict(action=action, project=project, record_id=record_id)))
        try:
            with writer_lock(self._root):
                data = self._load()
                self._recover_checkpoint(data)
                old_result = self._retry(data, operation_id, request_digest)
                if old_result is not None:
                    return old_result
                record = data['current'].get(record_id)
                if record is None:
                    raise VaultError('not_found', 'The record does not exist.')
                if record['scope'] != 'personal':
                    raise VaultError('source_scope', 'Only a personal record can be granted to a project.')
                result = dict(project=project, record_id=record_id, granted=action == 'grant')
                self._commit(action, result, operation_id, request_digest, data)
                return result
        except OSError:
            raise VaultError('storage_error', 'The policy operation could not be persisted.') from None

    def grant(self, project, record_id, *, operation_id=None):
        return self._policy_change('grant', project, record_id, operation_id)

    def revoke(self, project, record_id, *, operation_id=None):
        return self._policy_change('revoke', project, record_id, operation_id)

    def doctor(self):
        issues, orphan_payloads, uncommitted_files = [], [], []
        try:
            data = self._load()
            referenced = {record['path'] for record in data['records'].values()}
            orphan_payloads = sorted(path.relative_to(self._root).as_posix()
                                     for path in self._safe('.remember/revisions', directory=True).glob('*.md')
                                     if path.relative_to(self._root).as_posix() not in referenced)
            uncommitted_files = sorted(path.relative_to(self._root).as_posix()
                                      for directory in ('', 'revisions', 'operations')
                                      for path in self._safe(f'.remember/{directory}', directory=True).glob('.pending-*'))
            for record in data['current'].values():
                for source in record['sources']:
                    if source not in data['current']:
                        issues.append(dict(code='missing_source', record_id=record['id'], source_id=source))
                    elif data['current'][source]['state'] != 'active':
                        issues.append(dict(code='stale_source', record_id=record['id'], source_id=source))
                    else:
                        try:
                            self._sources([source], record['scope'], data)
                        except VaultError as exc:
                            issues.append(dict(code=exc.code, record_id=record['id'], source_id=source))
        except VaultError as exc:
            issues.append(dict(code=exc.code, message=exc.message))
        return dict(ok=not issues, vault_id=self._vault_id, issues=issues,
                    orphan_payloads=orphan_payloads, uncommitted_files=uncommitted_files,
                    storage_mode='immutable-revisions',
                    editor_reconciliation='unsupported')
