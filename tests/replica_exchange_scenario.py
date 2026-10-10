"""Artifact-exchange acceptance CLI, deliberately outside unittest discovery.

Only GitHub Actions transports files. This helper uses synthetic records and
local immutable export/import APIs, with no network or model/provider calls.
The simulate command exercises all paths on ONE host and cannot prove cross-OS.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import platform
import shutil
import sys

from remember_dammit.errors import VaultError
from remember_dammit.local_state import local_state_directory
from remember_dammit.replication import export_bundle, import_bundle
from remember_dammit.retrieval import context, reindex, search
from remember_dammit.storage import Vault


REPLICAS = {'windows': 'win32', 'mac': 'darwin', 'linux': 'linux'}
QUERY = 'exchangefixture'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path):
    require(path.is_file(), f'Missing required artifact file: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def host():
    return {'platform': sys.platform, 'python_version': platform.python_version(),
            'python_implementation': platform.python_implementation()}


def paths(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output.with_name(output.name + '-work')
    workspace.mkdir(parents=True, exist_ok=False)
    return output, workspace


def clone_bundle(seed, target):
    # Copy only portable authority, never local caches, locks or user state.
    require((seed / 'bundle' / 'COMPLETE.json').is_file(),
            f'Missing required artifact file: {seed / "bundle" / "COMPLETE.json"}')
    shutil.copytree(seed / 'bundle' / '.remember', target / '.remember')
    vault = Vault(target)
    receipt = import_bundle(vault, seed / 'bundle')
    require(receipt['complete'], 'Seed bundle admission was incomplete')
    metadata = read_json(seed / 'seed.json')
    require(vault.snapshot_id() == metadata['snapshot'], 'Seed snapshot differs from artifact metadata')
    require(receipt['manifest_digest'] == metadata['manifest_digest'], 'Seed manifest differs from metadata')
    return vault


def observed(vault, identifier):
    return [{key: record[key] for key in ('id', 'revision')}
            for record in vault.heads(identifier)]


def immutable_inventory(vault):
    return {p.relative_to(vault.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (vault.root / '.remember').rglob('*') if p.is_file()}


def prepare(output):
    output, workspace = paths(output)
    vault = Vault.initialize(workspace / 'seed', format_version=2)
    decision = vault.put(title='Common decision', body=QUERY + ' original decision.',
                         kind='decision', scope='project:common', record_id='common-decision')
    vault.put(title='Synthetic personal note', body=QUERY + ' personal evidence.',
              scope='personal', record_id='personal-note')
    vault.grant('common', 'personal-note')
    vault.put(title='Removable common note', body=QUERY + ' removable original.',
              scope='project:common', record_id='removable-note')
    receipt = export_bundle(vault, output / 'bundle')
    require(receipt['complete'], 'Seed export did not complete')
    metadata = {**host(), **receipt, 'decision_revision': decision['revision'],
                'vault_id': vault.vault_id, 'vault_schema': 2}
    write_json(output / 'seed.json', metadata)
    return metadata


def produce(seed, output, replica, mode):
    if mode == 'ci':
        require(sys.platform == REPLICAS[replica],
                f'{replica} requires actual platform {REPLICAS[replica]}, got {sys.platform}')
    seed = Path(seed).resolve()
    output, workspace = paths(output)
    vault = clone_bundle(seed, workspace / 'replica')
    metadata = read_json(seed / 'seed.json')
    source = vault.put(title=f'{replica} source detail', kind='source',
                       body=f'{QUERY} independent {replica} source detail.',
                       scope='project:common', record_id=f'source-{replica}')
    contribution = vault.put(title=f'{replica} project contribution',
                             body=f'{QUERY} independent {replica} contribution.',
                             scope=f'project:{replica}', record_id=f'contribution-{replica}')
    correction = vault.correct('common-decision', expected_revision=metadata['decision_revision'],
                               title=f'{replica} decision', actor=replica,
                               body=f'{QUERY} corrected independently on {replica}.',
                               sources=[source['id']])
    require({r['id'] for r in vault.heads('common-decision')} == {correction['id']},
            'Replica must correct the shared seed head independently')
    if replica == 'windows':
        vault.revoke('common', 'personal-note')
        vault.delete('removable-note', expected_heads=observed(vault, 'removable-note'))
    elif replica == 'mac':
        vault.correct('removable-note',
                      expected_revision=vault.get('removable-note')['revision'],
                      title='Offline Mac removable edit', body=QUERY + ' retained offline edit.')
        vault.put(title='Common derived personal evidence',
                  body=QUERY + ' personal dependent must disappear after revoke.',
                  scope='project:common', sources=['personal-note'], record_id='personal-dependent')
        visible = {r['id'] for r in search(vault, QUERY, project='common', limit=100)['records']}
        require({'personal-note', 'personal-dependent'} <= visible,
                'Mac dependent must be permitted before learning the revoke')
    else:
        require(vault.grants_for('common') == {'personal-note'}, 'Linux must retain old policy')
        require(vault.get('removable-note')['state'] == 'active', 'Linux must retain the old note')
    receipt = export_bundle(vault, output / 'bundle')
    require(receipt['complete'], 'Replica export did not complete')
    result = {**host(), **receipt, 'replica': replica, 'mode': mode,
              'seed_snapshot': metadata['snapshot'], 'seed_manifest_digest': metadata['manifest_digest'],
              'vault_id': vault.vault_id, 'contribution': contribution, 'correction': correction,
              'source': source}
    write_json(output / 'producer.json', result)
    return result


def logical_view(vault):
    return {'snapshot': vault.snapshot_id(), 'records': vault.list_records(),
            'operation_heads': vault.operation_heads(),
            'decision_heads': vault.heads('common-decision'),
            'decision_history': vault.history('common-decision'),
            'removable_history': vault.history('removable-note'),
            'common_grants': sorted(vault.grants_for('common')),
            'search': {name: search(vault, QUERY, project=name, limit=100)
                       for name in ('common', *REPLICAS)},
            'context': context(vault, QUERY, project='common', budget_bytes=50000)}


def check_merged(vault, producers):
    records = {r['id']: r for r in vault.list_records()}
    for name in REPLICAS:
        record = records[f'contribution-{name}']
        require(record['scope'] == f'project:{name}' and record['state'] == 'active',
                f'{name} project contribution was lost or changed scope')
    heads = vault.heads('common-decision')
    expected_ids = {p['correction']['id'] for p in producers}
    require(len(heads) == 3 and {r['id'] for r in heads} == expected_ids,
            'All three concurrent decision heads must survive')
    require(all(r['state'] == 'active' and len(r['conflicts_with']) == 2 for r in heads),
            'Decision branches must expose conflicts without a winner')
    require(vault.get('common-decision')['state'] == 'superseded', 'Seed decision became active again')
    for producer in producers:
        record = records[producer['correction']['id']]
        require(record['sources'] == [producer['source']['id']], 'Correction source linkage changed')
    history = vault.history('removable-note')
    require(len(history) == 2 and all(r['state'] == 'retracted' for r in history),
            'Delete must cover the concurrent offline correction and preserve its history')
    require(vault.grants_for('common') == set(), 'Old replica revived a revoked personal grant')
    hidden = {'personal-note', 'personal-dependent', *(r['id'] for r in history)}
    for packet in (search(vault, QUERY, project='common', limit=100),
                   context(vault, QUERY, project='common', budget_bytes=50000)):
        ids = {r['id'] for r in packet['records']}
        require(not (hidden & ids), 'Retrieval exposed a revoked source/dependent or deleted lineage')
        require(expected_ids <= ids, 'Retrieval silently chose one decision winner')
        require('unresolved_correction_branches' in packet['warnings'], 'Retrieval omitted conflict warning')


def verify(seed, replicas, output, mode):
    seed, replicas = Path(seed).resolve(), Path(replicas).resolve()
    seed_metadata = read_json(seed / 'seed.json')
    bundles, producers = {}, []
    for name, expected_platform in REPLICAS.items():
        directory = replicas / f'exchange-replica-{name}'
        producer = read_json(directory / 'producer.json')
        require(producer['replica'] == name and producer['mode'] == mode, 'Unexpected producer label/mode')
        require(producer['seed_snapshot'] == seed_metadata['snapshot'] and
                producer['seed_manifest_digest'] == seed_metadata['manifest_digest'] and
                producer['vault_id'] == seed_metadata['vault_id'], 'Producers used different seed artifacts')
        require(producer['complete'], 'Incomplete producer receipt')
        require(producer['python_version'].startswith('3.12.') if mode == 'ci' else True,
                'CI producer must run Python 3.12')
        if mode == 'ci':
            require(producer['platform'] == expected_platform, 'CI artifact did not come from the required OS')
        marker = read_json(directory / 'bundle' / 'COMPLETE.json')
        require(marker['digest'] == producer['manifest_digest'] and
                marker['snapshot'] == producer['snapshot'], 'Producer manifest binding differs')
        bundles[name] = directory / 'bundle'
        producers.append(producer)
    output, workspace = paths(output)
    observations, reference = [], None
    for number, order in enumerate(itertools.permutations(REPLICAS)):
        vault = clone_bundle(seed, workspace / f'permutation-{number}')
        for name in order:
            require(import_bundle(vault, bundles[name])['complete'], 'Incomplete bundle import')
        check_merged(vault, producers)
        before = logical_view(vault)
        inventory = immutable_inventory(vault)
        for name in order:
            receipt = import_bundle(vault, bundles[name])
            require(receipt['complete'] and receipt['added'] == 0, 'Repeated import was not idempotent')
        require(logical_view(vault) == before and immutable_inventory(vault) == inventory,
                'Repeated import changed logical state or immutable bytes')
        first_index = Path(reindex(vault)['path'])
        require(first_index.parent.resolve() == local_state_directory(vault.root, 'indexes').resolve(),
                'Refuse to remove a path outside this test vault local index directory')
        first_index.unlink()
        rebuilt = reindex(vault)
        require(Path(rebuilt['path']).is_file() and rebuilt['snapshot'] == before['snapshot'],
                'Deleted local index was not rebuilt for the same snapshot')
        require(logical_view(vault) == before and immutable_inventory(vault) == inventory,
                'Index rebuild changed scopes, heads, history or canonical objects')
        if reference is None:
            reference = before
        require(before == reference, 'Arrival permutations did not converge in logical view and snapshot')
        observations.append({'order': list(order), 'snapshot': before['snapshot'],
                             'record_count': len(before['records']), 'decision_head_count': 3,
                             'removable_history_count': 2, 'repeat_import_unchanged': True,
                             'reindex_unchanged': True})
    # Resolution gets its own copy; compare convergence before any resolution.
    resolution = clone_bundle(seed, workspace / 'resolution')
    for name in ('windows', 'mac'):
        require(import_bundle(resolution, bundles[name])['complete'], 'Resolution setup import failed')
    stale = observed(resolution, 'common-decision')
    require(len(stale) == 2, 'Expected exactly two observed heads before third arrival')
    require(import_bundle(resolution, bundles['linux'])['complete'], 'Third resolution head import failed')
    before_rejection = immutable_inventory(resolution)
    try:
        resolution.resolve('common-decision', expected_heads=stale,
                           title='Stale resolution', body=QUERY + ' must be rejected.')
    except VaultError as error:
        require(error.code == 'stale_heads', f'Wrong stale resolution error: {error.code}')
        stale_code = error.code
    else:
        raise RuntimeError('Resolution accepted stale two-head observation after third arrival')
    require(immutable_inventory(resolution) == before_rejection, 'Stale resolution mutated immutable state')
    fresh = observed(resolution, 'common-decision')
    require(len(fresh) == 3, 'Fresh resolution must observe all three heads')
    resolved = resolution.resolve('common-decision', expected_heads=fresh,
                                  title='Explicitly resolved decision', body=QUERY + ' observed all branches.')
    require({r['id'] for r in resolution.heads('common-decision')} == {resolved['id']},
            'Fresh three-head resolution failed')
    require(set(resolved['supersedes_all']) == {r['id'] for r in fresh}, 'Resolution lost a predecessor')
    report = {**host(), 'mode': mode, 'cross_os_proven': mode == 'ci',
              'transport': 'GitHub Actions artifacts' if mode == 'ci' else 'local simulation copies',
              'seed': seed_metadata, 'producers': producers, 'permutations': observations,
              'permutation_count': len(observations), 'unique_snapshots': 1,
              'contribution_count': 3, 'decision_head_count': 3,
              'stale_resolution_code': stale_code, 'resolved_head_count': 1,
              'converged_logical_view': reference, 'resolved_snapshot': resolution.snapshot_id()}
    write_json(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'produce', 'verify', 'simulate'):
        sub = commands.add_parser(name)
        sub.add_argument('--output', type=Path, required=True)
        if name in ('produce', 'verify'):
            sub.add_argument('--seed', type=Path, required=True)
            sub.add_argument('--mode', choices=('ci', 'simulation'), default='ci')
        if name == 'produce':
            sub.add_argument('--replica', choices=REPLICAS, required=True)
        if name == 'verify':
            sub.add_argument('--replicas', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.output)
    elif args.command == 'produce':
        result = produce(args.seed, args.output, args.replica, args.mode)
    elif args.command == 'verify':
        result = verify(args.seed, args.replicas, args.output, args.mode)
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        prepare(args.output / 'seed')
        for name in REPLICAS:
            produce(args.output / 'seed', args.output / 'replicas' / f'exchange-replica-{name}',
                    name, 'simulation')
        result = verify(args.output / 'seed', args.output / 'replicas',
                        args.output / 'verification', 'simulation')
    print(json.dumps({key: result[key] for key in ('platform', 'python_version', 'snapshot',
                     'mode', 'cross_os_proven', 'permutation_count') if key in result}, sort_keys=True))


if __name__ == '__main__':
    main()
