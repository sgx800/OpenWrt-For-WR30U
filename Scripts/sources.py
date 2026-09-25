#!/usr/bin/env python3
"""Source selection and replay. Config/sources.json is the single input policy."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
import recipe

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT = ('Config/MTK.config', 'Config/WR30U.config', 'Config/plugins.config',
               'Config/sources.json', 'Scripts/recipe.py', 'Scripts/packages.sh',
               'Scripts/sources.py', 'Scripts/release.py', '.github/workflows/WR30U.yml')


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def command(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def commit(value: str) -> str:
    if not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('Expected a complete Git commit SHA: ' + repr(value))
    return value


def fingerprint(root: Path = ROOT) -> dict[str, str]:
    return {name: sha256(root / name) for name in FINGERPRINT}


def selection(root: Path = ROOT, replay: str = '') -> dict:
    spec = json.loads((root / 'Config/sources.json').read_text())
    recipe.package_plan(root)  # Validate the existing package policy.
    fw = spec['firmware']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', fw['repository']):
        raise ValueError('Invalid firmware repository')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', fw['branch']):
        raise ValueError('Invalid firmware branch')
    result = {'firmware': {k: fw[k] for k in ('repository', 'branch')},
              'extra_packages': spec['extra_packages']}
    if fw.get('commit'):
        result['firmware']['commit'] = commit(fw['commit'])
    if not replay:
        return result
    lock = json.loads(Path(replay).read_text())
    if lock.get('schema') != 1 or lock.get('device') != recipe.DEVICE:
        raise ValueError('Unsupported source lock or wrong device')
    if lock['recipe_files'] != fingerprint(root):
        raise ValueError('Recipe changed; use the release recipe commit before replaying its lock')
    for key in ('repository', 'branch'):
        if lock['firmware'][key] != fw[key]:
            raise ValueError('Source lock does not match firmware policy')
    commit(lock['firmware']['commit'])
    expected = {r['name']: r for r in spec['extra_packages']}
    actual = {r['name']: r for r in lock['extra_packages']}
    if actual.keys() != expected.keys() or len(actual) != len(lock['extra_packages']):
        raise ValueError('Source lock has a different package selection')
    for name, row in actual.items():
        if any(row[k] != expected[name][k] for k in ('repository', 'ref', 'path')):
            raise ValueError('Source lock changes package origin: ' + name)
        commit(row['commit'])
    return lock


def feed_definitions(root: Path) -> list[dict]:
    # Read the native declaration, not the generated replay override.
    result = []
    for line in (root / 'feeds.conf.default').read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r'(src-git(?:-full)?)\s+([A-Za-z0-9_-]+)\s+(https://\S+)', line)
        if not m:
            raise ValueError('Unsupported feed declaration; review before building: ' + line)
        method, name, location = m.groups()
        url = re.split(r'[;^]', location, maxsplit=1)[0]
        result.append({'name': name, 'method': method, 'url': url, 'location': location})
    if not result or len({r['name'] for r in result}) != len(result):
        raise ValueError('Missing or duplicate feeds')
    return result


def replay_feeds(native: list[dict], locked: list[dict]) -> str:
    by_name = {r['name']: r for r in locked}
    if {r['name'] for r in native} != by_name.keys() or len(locked) != len(by_name):
        raise ValueError('Locked feed set differs from native feeds')
    lines = []
    for row in native:
        old = by_name[row['name']]
        if old['url'] != row['url']:
            raise ValueError('Locked feed origin differs: ' + row['name'])
        lines.append(f"{row['method']} {row['name']} {row['url']}^{commit(old['commit'])}\n")
    return ''.join(lines)


def fetch(root: Path, spec: dict) -> None:
    fw = spec['firmware']
    if root.exists():
        raise ValueError('Source directory already exists; use a clean build directory')
    url = 'https://github.com/' + fw['repository'] + '.git'
    if fw.get('commit'):
        root.mkdir(parents=True)
        command('git', 'init', '-q', str(root))
        command('git', '-C', str(root), 'remote', 'add', 'origin', url)
        command('git', '-C', str(root), 'fetch', '--depth=1', 'origin', fw['commit'])
        command('git', '-C', str(root), 'checkout', '-B', fw['branch'], 'FETCH_HEAD')
    else:
        command('git', 'clone', '--depth=1', '--single-branch', '--branch', fw['branch'], url, str(root))
    actual = command('git', '-C', str(root), 'rev-parse', 'HEAD')
    if fw.get('commit') and actual != fw['commit']:
        raise ValueError('Firmware SHA did not match lock')
    recipe.check_source(root)
    values = {'SOURCE_REPO': url, 'SOURCE_BRANCH': fw['branch'], 'SOURCE_SHA': commit(actual)}
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'], 'a') as stream:
            stream.writelines(f'{k}={v}\n' for k, v in values.items())
    print(json.dumps(values, sort_keys=True))


def feeds(root: Path, spec: dict) -> None:
    native = feed_definitions(root)
    if 'feeds' in spec:
        (root / 'feeds.conf').write_text(replay_feeds(native, spec['feeds']))
    subprocess.run(['./scripts/feeds', 'update', '-a'], cwd=root, check=True)
    if 'feeds' in spec:
        for row in spec['feeds']:
            actual = command('git', '-C', str(root / 'feeds' / row['name']), 'rev-parse', 'HEAD')
            if actual != row['commit']:
                raise ValueError('Feed fetch silently used a different SHA: ' + row['name'])
    subprocess.run(['./scripts/feeds', 'install', '-a'], cwd=root, check=True)


def plan(spec: dict) -> str:
    return ''.join('\t'.join((r['name'], r['repository'], r.get('commit') or r['ref'], r['path']))
                   + '\n' for r in spec['extra_packages'])


def record(root: Path, spec: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fw = dict(spec['firmware'], commit=commit(command('git', '-C', str(root), 'rev-parse', 'HEAD')))
    resolved_feeds, patches = [], {}
    for row in feed_definitions(root):
        path = root / 'feeds' / row['name']
        resolved_feeds.append(dict(row, commit=commit(command('git', '-C', str(path), 'rev-parse', 'HEAD'))))
        patch = subprocess.check_output(['git', '-C', str(path), 'diff', '--binary', 'HEAD'])
        name = 'feed-' + row['name'] + '.patch'
        (output / name).write_bytes(patch)
        patches[name] = sha256(output / name)
    records = {}
    for line in (output / 'extra-package-sources.txt').read_text().splitlines():
        name, repo, ref, sha = line.split()
        if name in records:
            raise ValueError('Duplicate imported package record: ' + name)
        records[name] = (repo, ref, commit(sha))
    extras = []
    for row in spec['extra_packages']:
        repo, ref, sha = records.pop(row['name'])
        if repo != row['repository'] or ref != (row.get('commit') or row['ref']):
            raise ValueError('Imported package differs from source selection')
        if row.get('commit') and sha != row['commit']:
            raise ValueError('Imported package SHA differs from source lock')
        extras.append(dict(row, commit=sha))
    if records:
        raise ValueError('Unrequested imported packages')
    if spec.get('patches') is not None and patches != spec['patches']:
        raise ValueError('Compatibility patch result differs from replay lock')
    lock = {'schema': 1, 'device': recipe.DEVICE, 'recipe_files': fingerprint(),
            'firmware': fw, 'feeds': resolved_feeds, 'extra_packages': extras, 'patches': patches}
    (output / 'sources.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    effective = root / ('feeds.conf' if (root / 'feeds.conf').exists() else 'feeds.conf.default')
    (output / 'feeds.effective.conf').write_bytes(effective.read_bytes())
    print('Recorded complete source lock and feed patches')


def verify(root: Path) -> None:
    # Do not automatically authorize newly introduced LuCI dependency applications.
    # ttyd and all approved applications are already explicit in plugins.config.
    policy = recipe.parse((ROOT / 'Config/plugins.config').read_text())
    recipe.check_config(recipe.parse((root / '.config').read_text()), policy,
                        recipe.catalog((root / 'tmp/.packageinfo').read_text()))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('fetch', 'feeds', 'plan', 'record', 'verify'))
    p.add_argument('root', type=Path)
    p.add_argument('--lock', default=os.environ.get('WR30U_SOURCE_LOCK', ''))
    p.add_argument('--output', type=Path, default=ROOT / 'output')
    args = p.parse_args()
    spec = selection(replay=args.lock)
    if args.operation == 'verify':
        verify(args.root)
    elif args.operation == 'plan':
        print(plan(spec), end='')
    elif args.operation == 'record':
        record(args.root.resolve(), spec, args.output)
    else:
        globals()[args.operation](args.root.resolve(), spec)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit('Source selection failed: ' + str(exc)) from exc
