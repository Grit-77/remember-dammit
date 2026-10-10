"""Immutable causal vault objects; local caches are never replay authority.

The operation frontier and record heads are separate graphs. Sorting determines
presentation only. Admission is validated against each operation's causal past,
so raw unions of independently valid offline writes do not invent a replay order.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import uuid

import yaml

from .errors import VaultError
from .locking import writer_lock
from .storage import (Vault, _canonical, _digest, _id, _metadata, _strings,
                      _FIELDS, _DIGEST, _root_path, _fsync_directory)


def _publish(path, data):
    """Publish fully flushed bytes with an atomic, no-overwrite hard link.

    Unlike replace after an existence check, link cannot overwrite an object
    arriving from an offline transport between that check and publication.
    The temporary name is disposable; both names briefly point to flushed bytes.
    """
    if path.exists():
        if path.read_bytes() != data:
            raise VaultError('integrity_error', 'An immutable path contains different bytes.')
        return
    temporary = path.parent / ('.pending-' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise VaultError('integrity_error', 'An immutable path contains different bytes.') from None
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _hash(value):
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


class CausalVault(Vault):
    def __new__(cls, root, *, _allow_migration=False):
        return object.__new__(cls)

    def __init__(self, root, *, _allow_migration=False):
        self._allow_migration = _allow_migration
        super().__init__(root)

    @classmethod
    def initialize(cls, root, *, format_version=2):
        if format_version != 2:
            return Vault.initialize(root, format_version=format_version)
        path = _root_path(root)
        try:
            with writer_lock(path):
                if (path / '.remember').exists():
                    vault = Vault(path)
                    vault.list_records()
                    return vault
                if path.exists() and (not path.is_dir() or any(path.iterdir())):
                    raise VaultError('invalid_vault', 'Initialization requires a new or empty directory.')
                path.mkdir(parents=True, exist_ok=True)
                managed = path / '.remember'
                managed.mkdir()
                for directory in ('revisions', 'operations', 'acks'):
                    (managed / directory).mkdir()
                config = dict(schema=2, vault_id=str(uuid.uuid4()), policy={'grants': {}})
                _publish(managed / 'vault.json', _canonical(config))
                return cls(path)
        except OSError:
            raise VaultError('storage_error', 'Vault initialization could not be persisted.') from None

    def _config(self):
        if not self._allow_migration and self._safe('.migration-INCOMPLETE.json').exists():
            raise VaultError('incomplete_transfer', 'This migration destination is not yet verified.')
        try:
            self._safe('.remember', directory=True)
            for directory in ('revisions', 'operations', 'acks'):
                self._safe('.remember/' + directory, directory=True)
            config = json.loads(self._safe('.remember/vault.json').read_bytes())
            if (not isinstance(config, dict) or set(config) != {'schema', 'vault_id', 'policy'}
                    or type(config['schema']) is not int or config['schema'] != 2):
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
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise VaultError('invalid_vault', 'The vault metadata or layout is invalid.') from None

    def _read_record(self, descriptor):
        try:
            if not isinstance(descriptor, dict) or set(descriptor) != {'id', 'path', 'revision'}:
                raise ValueError
            _id(descriptor['id'])
            if not _hash(descriptor['revision']) or descriptor['path'] != '.remember/revisions/' + descriptor['revision'] + '.md':
                raise ValueError
            path = self._safe(descriptor['path'])
            if not path.exists():
                raise VaultError('incomplete_transfer', 'A referenced revision has not arrived.')
            payload = path.read_bytes()
            if _digest(payload) != descriptor['revision']:
                raise ValueError
            text = payload.decode('utf-8')
            if not text.startswith('---\n'):
                raise ValueError
            frontmatter, body = text[4:].split('\n---\n', 1)
            properties = yaml.safe_load(frontmatter)
            if (not isinstance(properties, dict) or set(properties) != {'rd_schema', *(f'rd_{f}' for f in _FIELDS)}
                    or type(properties['rd_schema']) is not int or properties['rd_schema'] != 1):
                raise ValueError
            record = {key[3:]: value for key, value in properties.items() if key != 'rd_schema'}
            record['body'] = body
            _metadata(record)
            if record['id'] != descriptor['id']:
                raise ValueError
            record.update(path=descriptor['path'], revision=descriptor['revision'])
            return record
        except VaultError as exc:
            if exc.code in ('incomplete_transfer', 'integrity_error'):
                raise
            raise VaultError('integrity_error', 'A committed revision is invalid.') from None
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, yaml.YAMLError, RecursionError):
            raise VaultError('integrity_error', 'A committed revision is changed or invalid.') from None

    def _nodes(self):
        nodes = {}
        directory = self._safe('.remember/operations', directory=True)
        for path in sorted(directory.glob('*.json')):
            try:
                self._safe(path.relative_to(self.root).as_posix())
                payload = path.read_bytes()
                op = json.loads(payload)
                fields = {'schema', 'vault_id', 'operation_id', 'request_digest', 'parents',
                          'action', 'result', 'supersedes_all', 'digest'}
                if not isinstance(op, dict) or set(op) != fields:
                    raise ValueError
                if (type(op['schema']) is not int or op['schema'] != 2
                        or op['vault_id'] != self.vault_id or not _hash(op['request_digest'])
                        or not _hash(op['digest']) or path.name != op['digest'] + '.json'
                        or payload != _canonical(op)):
                    raise ValueError
                _id(op['operation_id'], 'Operation ID')
                if (not isinstance(op['parents'], list) or any(not _hash(p) for p in op['parents'])
                        or op['parents'] != sorted(set(op['parents']))
                        or not isinstance(op['supersedes_all'], list)
                        or op['supersedes_all'] != sorted(set(op['supersedes_all']))):
                    raise ValueError
                for predecessor in op['supersedes_all']:
                    _id(predecessor)
                if op['digest'] != _digest(_canonical({k: v for k, v in op.items() if k != 'digest'})):
                    raise ValueError
                nodes[op['digest']] = op
            except VaultError as exc:
                if exc.code == 'integrity_error':
                    raise
                raise VaultError('integrity_error', 'A committed operation is invalid.') from None
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                raise VaultError('integrity_error', 'A committed operation is changed or invalid.') from None
        for op in nodes.values():
            if any(parent not in nodes for parent in op['parents']):
                raise VaultError('incomplete_transfer', 'A causal parent operation has not arrived.')
        for path in sorted(self._safe('.remember/acks', directory=True).glob('*.json')):
            try:
                self._safe(path.relative_to(self.root).as_posix())
                data = path.read_bytes()
                ack = json.loads(data)
                if (not isinstance(ack, dict) or set(ack) != {'schema', 'vault_id', 'operation'}
                        or type(ack['schema']) is not int or ack['schema'] != 2
                        or ack['vault_id'] != self.vault_id or not _hash(ack['operation'])
                        or path.name != ack['operation'] + '.json' or data != _canonical(ack)):
                    raise ValueError
                if ack['operation'] not in nodes:
                    raise VaultError('incomplete_transfer', 'An acknowledged operation has not arrived.')
            except VaultError:
                raise
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                raise VaultError('integrity_error', 'An acknowledgement is invalid.') from None
        return nodes

    @staticmethod
    def _topology(nodes):
        remaining = set(nodes)
        order, ancestors = [], {}
        while remaining:
            ready = sorted(key for key in remaining if all(p in ancestors for p in nodes[key]['parents']))
            if not ready:
                raise VaultError('integrity_error', 'The operation graph contains a causal cycle.')
            for key in ready:
                past = set(nodes[key]['parents'])
                for parent in nodes[key]['parents']:
                    past.update(ancestors[parent])
                ancestors[key] = past
                order.append(key)
                remaining.remove(key)
        return order, ancestors

    def _project(self, selected, nodes, raw, ancestors, config):
        records, successors, record_parents, roots, tombstones = {}, {}, {}, {}, {}
        for key in selected:
            op = nodes[key]
            if op['action'] in ('put', 'correct', 'resolve'):
                record = deepcopy(raw[key])
                rid = record['id']
                predecessors = op['supersedes_all']
                root = roots[predecessors[0]] if predecessors else rid
                if rid in records:
                    if records[rid]['revision'] != record['revision'] or record_parents[rid] != predecessors:
                        raise VaultError('identity_conflict', 'Different revisions claim the same record identity.')
                elif any(existing.casefold() == rid.casefold() for existing in records):
                    raise VaultError('identity_conflict', 'Record identities collide under case folding.')
                record.update(supersedes_all=list(predecessors), lineage_id=root, conflicts_with=[])
                records[rid] = record
                roots[rid] = root
                record_parents[rid] = list(predecessors)
                for predecessor in predecessors:
                    successors.setdefault(predecessor, set()).add(rid)
            elif op['action'] == 'retract':
                root = op['result']['lineage_id']
                tombstones.setdefault(root, []).append(key)
        lineage_heads = {}
        for rid, root in roots.items():
            if rid not in successors:
                lineage_heads.setdefault(root, []).append(rid)
        for leaves in lineage_heads.values():
            leaves.sort()
        current = deepcopy(records)
        for rid, record in current.items():
            if roots[rid] in tombstones:
                record['state'] = 'retracted'
            elif rid in successors:
                record['state'] = 'superseded'
            else:
                record['conflicts_with'] = [other for other in lineage_heads[roots[rid]] if other != rid]
        grants = {}
        policy_events = {}
        for key in selected:
            op = nodes[key]
            if op['action'] in ('grant', 'revoke'):
                pair = (op['result']['project'], op['result']['record_id'])
                policy_events.setdefault(pair, {'grant': [], 'revoke': []})[op['action']].append(key)
        initial = config['policy']['grants']
        pairs = set(policy_events) | {(p, r) for p, admitted in initial.items() for r in admitted}
        for project, rid in pairs:
            events = policy_events.get((project, rid), {'grant': [], 'revoke': []})
            revokes = set(events['revoke'])
            effective = ((not revokes and rid in initial.get(project, []))
                         or any(revokes.issubset(ancestors[g]) for g in events['grant']))
            if effective and rid in roots and roots[rid] not in tombstones:
                grants.setdefault(project, set()).add(rid)
        return dict(records=records, current=current, successors=successors,
                    record_parents=record_parents, lineages=roots, lineage_heads=lineage_heads,
                    tombstones=tombstones, grants=grants)

    def _validate_admission(self, op, record, past):
        action, result, predecessors = op['action'], op['result'], op['supersedes_all']
        if action in ('put', 'correct', 'resolve'):
            if action == 'put':
                if predecessors or record['supersedes'] is not None:
                    raise ValueError
            else:
                if (not predecessors or (action == 'correct' and len(predecessors) != 1)
                        or any(p not in past['records'] for p in predecessors)):
                    raise ValueError
                roots = {past['lineages'][p] for p in predecessors}
                if len(roots) != 1:
                    raise ValueError
                root = next(iter(roots))
                if root in past['tombstones']:
                    raise ValueError
                if predecessors != past['lineage_heads'][root]:
                    raise ValueError
                if record['supersedes'] != (predecessors[0] if len(predecessors) == 1 else None):
                    raise ValueError
                for p in predecessors:
                    old = past['records'][p]
                    if any(record[f] != old[f] for f in ('scope', 'kind', 'evidence', 'disclosure', 'remote_allowed')):
                        raise ValueError
            existing = past['records'].get(record['id'])
            if existing is not None and existing['revision'] != record['revision']:
                raise VaultError('identity_conflict', 'A record identity was reused.')
            # Preserve the historical direct-source admission contract, including
            # valid v1 receipts. New local writes enforce transitive eligibility.
            super()._sources(record['sources'], record['scope'], past)
        elif action in ('grant', 'revoke'):
            if not isinstance(result, dict) or set(result) != {'project', 'record_id', 'granted'} or predecessors:
                raise ValueError
            _id(result['project'], 'Project ID')
            _id(result['record_id'], 'Record ID')
            record = past['records'].get(result['record_id'])
            if (record is None or record['scope'] != 'personal'
                    or type(result['granted']) is not bool or result['granted'] != (action == 'grant')):
                raise ValueError
        elif action == 'retract':
            if (not isinstance(result, dict) or set(result) != {'lineage_id', 'retracted'}
                    or result['retracted'] is not True or predecessors
                    or result['lineage_id'] not in past['lineage_heads']):
                raise ValueError
        else:
            raise ValueError

    def _load(self):
        config = self._config()
        nodes = self._nodes()
        order, ancestors = self._topology(nodes)
        raw = {key: self._read_record(nodes[key]['result']) for key in order
               if nodes[key]['action'] in ('put', 'correct', 'resolve')}
        for key in order:
            past_order = [previous for previous in order if previous in ancestors[key]]
            past = self._project(past_order, nodes, raw, ancestors, config)
            try:
                self._validate_admission(nodes[key], raw.get(key), past)
            except VaultError as exc:
                if exc.code in ('integrity_error', 'incomplete_transfer', 'identity_conflict'):
                    raise
                raise VaultError('integrity_error', 'A committed operation violates its causal admission policy.') from None
            except (ValueError, TypeError, KeyError):
                raise VaultError('integrity_error', 'A committed operation violates its causal admission policy.') from None
        data = self._project(order, nodes, raw, ancestors, config)
        for project, admitted in config['policy']['grants'].items():
            if any(rid not in data['records'] or data['records'][rid]['scope'] != 'personal' for rid in admitted):
                raise VaultError('integrity_error', 'The initial policy references an invalid record.')
        by_id = {}
        for key in order:
            by_id.setdefault(nodes[key]['operation_id'], []).append(key)
        operations, conflicts = {}, {}
        for operation_id, keys in by_id.items():
            receipts = {_canonical({f: nodes[k][f] for f in ('action', 'request_digest', 'result', 'supersedes_all')}) for k in keys}
            if len(receipts) != 1:
                conflicts[operation_id] = sorted(keys)
            else:
                operations[operation_id] = nodes[keys[0]]
        referenced = {p for op in nodes.values() for p in op['parents']}
        heads = sorted(set(nodes) - referenced)
        snapshot = _digest(_canonical({'config': config, 'operations': sorted(nodes)}))
        data.update(operations=operations, operation_conflicts=conflicts, operation_nodes=nodes,
                    operation_heads=heads, heads=heads, ancestors=ancestors, operation_order=order,
                    snapshot=snapshot, head=heads, checkpoint=None)
        return data

    def _ack(self, digest):
        _publish(self._safe('.remember/acks/' + digest + '.json'),
                 _canonical(dict(schema=2, vault_id=self.vault_id, operation=digest)))

    def _sources(self, sources, scope, data):
        """New writes cannot promote a currently withheld indirect dependency."""
        pending = [(source_id, scope) for source_id in sources]
        visited = set()
        while pending:
            source_id, selected_scope = pending.pop()
            if (source_id, selected_scope) in visited:
                continue
            visited.add((source_id, selected_scope))
            super()._sources([source_id], selected_scope, data)
            source = data['current'][source_id]
            pending.extend((child, selected_scope) for child in source['sources'])

    def _recover_checkpoint(self, data):
        # A valid marker is committed even if the process died before its ack.
        for key in data['operation_nodes']:
            self._ack(key)

    def _retry(self, data, operation_id, request_digest):
        if operation_id in data['operation_conflicts']:
            raise VaultError('operation_conflict', 'This operation ID has conflicting historical receipts.')
        op = data['operations'].get(operation_id)
        if op is None:
            return None
        if op['request_digest'] != request_digest:
            raise VaultError('operation_conflict', 'This operation ID was used with another request.')
        return deepcopy(data['records'][op['result']['id']] if op['action'] in ('put', 'correct', 'resolve') else op['result'])

    def _commit(self, action, result, operation_id, request_digest, data, *, supersedes_all=None):
        if self._load()['snapshot'] != data['snapshot']:
            raise VaultError('stale_revision', 'The vault changed before publication.')
        if supersedes_all is None:
            supersedes_all = []
            if action == 'correct':
                supersedes_all = [self._read_record(result)['supersedes']]
        op = dict(schema=2, vault_id=self.vault_id, operation_id=operation_id,
                  request_digest=request_digest, parents=data['operation_heads'], action=action,
                  result=result, supersedes_all=sorted(supersedes_all))
        op['digest'] = _digest(_canonical(op))
        _publish(self._safe('.remember/operations/' + op['digest'] + '.json'), _canonical(op))
        self._ack(op['digest'])

    def _write_record(self, record):
        metadata = {'rd_schema': 1, **{f'rd_{field}': record[field] for field in sorted(_FIELDS)}}
        text = '---\n' + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=True).rstrip('\n')
        payload = (text + '\n---\n' + record['body']).encode('utf-8')
        revision = _digest(payload)
        relative = '.remember/revisions/' + revision + '.md'
        _publish(self._safe(relative), payload)
        record.update(path=relative, revision=revision)
        parent = record['supersedes']
        record.setdefault('supersedes_all', [parent] if parent else [])
        record.setdefault('lineage_id', self._load()['lineages'][parent] if parent else record['id'])
        record['conflicts_with'] = []
        return {field: record[field] for field in ('id', 'path', 'revision')}

    def heads(self, record_id):
        _id(record_id, 'Record ID')
        data = self._load()
        if record_id not in data['records']:
            raise VaultError('not_found', 'The record does not exist.')
        return [data['current'][rid] for rid in data['lineage_heads'][data['lineages'][record_id]]]

    def operation_heads(self):
        return self._load()['operation_heads']

    def history(self, record_id):
        _id(record_id, 'Record ID')
        data = self._load()
        if record_id not in data['records']:
            raise VaultError('not_found', 'The record does not exist.')
        root = data['lineages'][record_id]
        emitted, result = set(), []
        for key in data['operation_order']:
            op = data['operation_nodes'][key]
            if op['action'] in ('put', 'correct', 'resolve'):
                rid = op['result']['id']
                if data['lineages'][rid] == root and rid not in emitted:
                    result.append(data['current'][rid])
                    emitted.add(rid)
        return result

    def correct(self, record_id, *, expected_revision, title, body, operation_id=None,
                actor='local', aliases=None, sources=None, expected_snapshot=None):
        # Reuse the legacy request digest so editing receipts stay compatible.
        request = dict(action='correct', record_id=record_id, expected_revision=expected_revision,
                       title=title, body=body, actor=actor, aliases=aliases, sources=sources)
        try:
            request_digest = _digest(_canonical(request))
        except (TypeError, ValueError, UnicodeError):
            raise VaultError('invalid_input', 'The request must contain valid JSON values.') from None
        operation_id = _id(operation_id if operation_id is not None else uuid.uuid4().hex, 'Operation ID')
        _id(record_id, 'Record ID')
        self._snapshot_input(expected_snapshot)
        try:
            with writer_lock(self.root):
                data = self._load()
                self._recover_checkpoint(data)
                receipt = self._retry(data, operation_id, request_digest)
                if receipt is not None:
                    return receipt
                self._snapshot_guard(data, expected_snapshot)
                old = data['current'].get(record_id)
                if old is None:
                    raise VaultError('not_found', 'The record does not exist.')
                root = data['lineages'][record_id]
                if (old['revision'] != expected_revision or data['lineage_heads'][root] != [record_id]
                        or root in data['tombstones']):
                    raise VaultError('stale_revision', 'The correction must name the unique current head revision.')
                record = self._successor([old], title, body, actor, aliases, sources, root)
                self._sources(record['sources'], record['scope'], data)
                descriptor = self._write_record(record)
                self._commit('correct', descriptor, operation_id, request_digest, data, supersedes_all=[record_id])
                return deepcopy(record)
        except OSError:
            raise VaultError('storage_error', 'The correction could not be persisted; retry with the same operation ID.') from None

    @staticmethod
    def _snapshot_input(snapshot):
        if snapshot is not None and not _hash(snapshot):
            raise VaultError('invalid_input', 'expected_snapshot must be a vault snapshot digest.')

    @staticmethod
    def _snapshot_guard(data, snapshot):
        if snapshot is not None and snapshot != data['snapshot']:
            raise VaultError('source_changed', 'Vault content or sharing policy changed after preflight.')

    @staticmethod
    def _successor(predecessors, title, body, actor, aliases, sources, root):
        record = {f: deepcopy(predecessors[0][f]) for f in _FIELDS | {'body'}}
        supplied = _strings(aliases, 'aliases') if aliases is not None else []
        record.update(id=uuid.uuid4().hex, title=title, body=body,
                      supersedes=predecessors[0]['id'] if len(predecessors) == 1 else None,
                      actor=actor, created_at=datetime.now(timezone.utc).isoformat(),
                      aliases=list(dict.fromkeys([*supplied, *(a for p in predecessors for a in [*p['aliases'], p['title']])])),
                      sources=_strings(sources, 'sources', ids=True) if sources is not None
                      else sorted({s for p in predecessors for s in p['sources']}),
                      supersedes_all=sorted(p['id'] for p in predecessors), lineage_id=root,
                      conflicts_with=[])
        _metadata(record)
        return record

    @staticmethod
    def _observed_heads(expected_heads):
        if not isinstance(expected_heads, list) or not expected_heads:
            raise VaultError('invalid_input', 'expected_heads must be a nonempty list of ID/revision pairs.')
        result = []
        for descriptor in expected_heads:
            if not isinstance(descriptor, dict) or set(descriptor) != {'id', 'revision'} or not _hash(descriptor['revision']):
                raise VaultError('invalid_input', 'Each observed head must contain exactly id and revision.')
            _id(descriptor['id'], 'Record ID')
            result.append((descriptor['id'], descriptor['revision']))
        if len({rid for rid, revision in result}) != len(result):
            raise VaultError('invalid_input', 'Observed heads must not contain duplicate IDs.')
        return sorted(result)

    def _compare_heads(self, data, record_id, observed):
        if record_id not in data['records']:
            raise VaultError('not_found', 'The record does not exist.')
        root = data['lineages'][record_id]
        actual = [(rid, data['records'][rid]['revision']) for rid in data['lineage_heads'][root]]
        if actual != observed or root in data['tombstones']:
            raise VaultError('stale_heads', 'The exact observed head set is no longer current.')
        return root, [data['current'][rid] for rid, revision in actual]

    def resolve(self, record_id, *, expected_heads, title, body, sources=None, aliases=None,
                operation_id=None, actor='local', expected_snapshot=None):
        _id(record_id, 'Record ID')
        observed = self._observed_heads(expected_heads)
        self._snapshot_input(expected_snapshot)
        operation_id = _id(operation_id if operation_id is not None else uuid.uuid4().hex, 'Operation ID')
        try:
            request_digest = _digest(_canonical(dict(action='resolve', record_id=record_id,
                expected_heads=[dict(id=i, revision=r) for i, r in observed], title=title, body=body,
                sources=sources, aliases=aliases, actor=actor)))
        except (TypeError, ValueError, UnicodeError):
            raise VaultError('invalid_input', 'The request must contain valid JSON values.') from None
        try:
            with writer_lock(self.root):
                data = self._load()
                self._recover_checkpoint(data)
                receipt = self._retry(data, operation_id, request_digest)
                if receipt is not None:
                    return receipt
                self._snapshot_guard(data, expected_snapshot)
                root, predecessors = self._compare_heads(data, record_id, observed)
                record = self._successor(predecessors, title, body, actor, aliases, sources, root)
                self._sources(record['sources'], record['scope'], data)
                descriptor = self._write_record(record)
                self._commit('resolve', descriptor, operation_id, request_digest, data,
                             supersedes_all=record['supersedes_all'])
                return deepcopy(record)
        except OSError:
            raise VaultError('storage_error', 'The resolution could not be persisted; retry with the same operation ID.') from None

    def delete(self, record_id, *, expected_heads, operation_id=None):
        _id(record_id, 'Record ID')
        observed = self._observed_heads(expected_heads)
        operation_id = _id(operation_id if operation_id is not None else uuid.uuid4().hex, 'Operation ID')
        request_digest = _digest(_canonical(dict(action='retract', record_id=record_id,
            expected_heads=[dict(id=i, revision=r) for i, r in observed])))
        try:
            with writer_lock(self.root):
                data = self._load()
                self._recover_checkpoint(data)
                receipt = self._retry(data, operation_id, request_digest)
                if receipt is not None:
                    return receipt
                root, predecessors = self._compare_heads(data, record_id, observed)
                result = dict(lineage_id=root, retracted=True)
                self._commit('retract', result, operation_id, request_digest, data)
                return result
        except OSError:
            raise VaultError('storage_error', 'The retraction could not be persisted; retry with the same operation ID.') from None

    retract = delete

    def doctor(self):
        report = super().doctor()
        report['storage_mode'] = 'causal-immutable-revisions'
        try:
            data = self._load()
            report['operation_heads'] = data['operation_heads']
            report['operation_conflicts'] = data['operation_conflicts']
            report['conflicts'] = {root: leaves for root, leaves in data['lineage_heads'].items()
                                   if len(leaves) > 1 and root not in data['tombstones']}
            report['tombstones'] = data['tombstones']
            for operation_id, digests in data['operation_conflicts'].items():
                report['issues'].append(dict(code='operation_conflict', operation_id=operation_id, digests=digests))
            report['unacknowledged_operations'] = sorted(key for key in data['operation_nodes']
                if not self._safe('.remember/acks/' + key + '.json').exists())
            report['uncommitted_files'] += sorted(p.relative_to(self.root).as_posix()
                for p in self._safe('.remember/acks', directory=True).glob('.pending-*'))
            report['ok'] = not report['issues']
        except VaultError:
            pass
        return report


def convert_v1_to_v2(source, target):
    """Deterministic out-of-place conversion; caller owns backup and preflight.

    No source mutation. The destination is unpublished until its caller emits a
    migration success receipt. An interrupted destination is preserved as-is.
    """
    source_vault = Vault(source)
    if source_vault._config()['schema'] != 1:
        raise VaultError('invalid_vault', 'Migration requires a valid format 1 source.')
    data = source_vault._load()
    path = _root_path(target)
    if path == source_vault.root or path.is_relative_to(source_vault.root) or source_vault.root.is_relative_to(path):
        raise VaultError('invalid_input', 'Migration destination overlaps its source.')
    try:
        with writer_lock(path):
            if path.exists() and (not path.is_dir() or any(p.name != '.migration-INCOMPLETE.json' for p in path.iterdir())):
                raise VaultError('invalid_vault', 'Migration destination must be empty.')
            path.mkdir(parents=True, exist_ok=True)
            managed = path / '.remember'
            managed.mkdir()
            for directory in ('revisions', 'operations', 'acks'):
                (managed / directory).mkdir()
            config = source_vault._config()
            config['schema'] = 2
            _publish(managed / 'vault.json', _canonical(config))
            target_vault = CausalVault(path, _allow_migration=True)
            previous = []
            mapping = {}
            for old in data['operations'].values():
                action = old['action']
                result = deepcopy(old['result'])
                supersedes_all = []
                if action in ('put', 'correct'):
                    record = data['records'][result['id']]
                    payload = source_vault._safe(result['path']).read_bytes()
                    result['path'] = '.remember/revisions/' + result['revision'] + '.md'
                    _publish(target_vault._safe(result['path']), payload)
                    if record['supersedes'] is not None:
                        supersedes_all = [record['supersedes']]
                op = dict(schema=2, vault_id=config['vault_id'], operation_id=old['operation_id'],
                          request_digest=old['request_digest'], parents=previous,
                          action=action, result=result, supersedes_all=supersedes_all)
                op['digest'] = _digest(_canonical(op))
                _publish(managed / 'operations' / (op['digest'] + '.json'), _canonical(op))
                target_vault._ack(op['digest'])
                mapping[old['digest']] = op['digest']
                previous = [op['digest']]
            target_vault._load()
            if source_vault.snapshot_id() != data['snapshot']:
                raise VaultError('source_changed', 'The migration source changed during conversion.')
            target_vault._migration_operation_mapping = mapping
            return target_vault
    except OSError:
        raise VaultError('storage_error', 'The migration destination could not be persisted.') from None
