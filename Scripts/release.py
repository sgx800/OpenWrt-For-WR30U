#!/usr/bin/env python3
"""Package or publish verified artifacts. Never builds firmware or executes artifact code."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
import recipe
import sources

ROOT = Path(__file__).resolve().parents[1]
INDEX = 'release-assets.sha256'
META = 'build-metadata.json'
IMAGE_SUFFIX = '-' + recipe.DEVICE + '-squashfs-sysupgrade.bin'


def gh(*args: str) -> str:
    proc = subprocess.run(['gh', *args], text=True, capture_output=True)
    if proc.returncode:
        # Do not print tokens or change the release target to bypass an error.
        raise RuntimeError(proc.stderr.strip() or 'GitHub command failed')
    return proc.stdout.strip()


def api(path: str):
    return json.loads(gh('api', path))


def pages(path: str, key: str = '') -> list:
    result = json.loads(gh('api', '--paginate', '--slurp', path))
    return [item for page in result for item in (page[key] if key else page)]


def wait_release(base: str, tag: str, draft: bool | None = None, attempts: int = 15) -> dict:
    """Wait for GitHub's release listing to reflect create/edit operations."""
    for attempt in range(attempts):
        found = next((r for r in pages(f'{base}/releases?per_page=100')
                      if r['tag_name'] == tag and (draft is None or r['draft'] == draft)), None)
        if found is not None:
            return found
        if attempt + 1 < attempts:
            time.sleep(1)
    state = 'any state' if draft is None else ('draft' if draft else 'published')
    raise RuntimeError(f'Release {tag} did not become visible as {state} after {attempts} attempts')


def numeric(value: str) -> str:
    if not re.fullmatch(r'[1-9][0-9]*', str(value)):
        raise ValueError('Expected a positive Run ID or attempt')
    return str(value)


def leaf(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
        raise ValueError('Unsafe asset name: ' + repr(value))
    return value


def pack(output: Path, root: Path = ROOT) -> Path:
    lock = json.loads((output / 'sources.lock.json').read_text())
    if lock.get('schema') != 1 or lock['recipe_files'] != sources.fingerprint(root):
        raise ValueError('Source lock does not describe this recipe')
    images = list(output.glob('*-sysupgrade.bin'))
    manifests = list(output.glob('*.manifest'))
    if len(images) != 1 or not images[0].name.endswith(IMAGE_SUFFIX) or len(manifests) != 1:
        raise ValueError('Expected one WR30U stock image and one manifest')
    policy = recipe.parse((root / 'Config/plugins.config').read_text())
    recipe.check_manifest(manifests[0].read_text(), policy)
    checksum = (output / 'firmware-sha256sums').read_text().split()
    if checksum != [sources.sha256(images[0]), images[0].name]:
        raise ValueError('Firmware checksum mismatch')
    bundle = output / 'release'
    if bundle.exists():
        raise ValueError('Release bundle already exists; do not overwrite a prior build')
    bundle.mkdir()
    selected = images + manifests + [output / n for n in (
        'firmware-sha256sums', 'sources.lock.json', 'resolved.config',
        'config.buildinfo', 'feeds.buildinfo', 'version.buildinfo')]
    for path in selected:
        shutil.copy2(path, bundle / path.name)
    shutil.copy2(root / 'Config/plugins.config', bundle / 'plugins.config')
    # Include the actual recipe, dependency metadata, and compatibility diffs.
    # The archive is a download asset, never extracted/executed by the publisher.
    snapshot = set(sources.FINGERPRINT) | {'Scripts/release.py', 'README.md', 'LICENSE',
                                          '.gitattributes', '.gitignore'}
    snapshot |= {str(p.relative_to(root)) for p in (root / 'tests').glob('*.py')}
    with tarfile.open(bundle / 'traceability.tar.gz', 'w:gz') as archive:
        for name in sorted(snapshot):
            archive.add(root / name, arcname='recipe/' + name, recursive=False)
        for path in sorted(output.iterdir()):
            if path.is_file() and path not in images:
                archive.add(path, arcname='build/' + path.name, recursive=False)
    metadata = {'schema': 1, 'device': recipe.DEVICE,
                'repository': os.environ['GITHUB_REPOSITORY'],
                'recipe_commit': sources.commit(os.environ['GITHUB_SHA']),
                'run_id': numeric(os.environ['GITHUB_RUN_ID']),
                'run_attempt': numeric(os.environ['GITHUB_RUN_ATTEMPT']),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'image': images[0].name, 'manifest': manifests[0].name}
    (bundle / META).write_text(json.dumps(metadata, indent=2) + '\n')
    (bundle / INDEX).write_text(''.join(f'{sources.sha256(p)}  {p.name}\n'
                                      for p in sorted(bundle.iterdir())))
    validate_bundle(bundle)
    print('Complete release bundle:', bundle)
    return bundle


def validate_bundle(bundle: Path) -> dict:
    if any(p.is_symlink() or not p.is_file() for p in bundle.iterdir()):
        raise ValueError('Bundle must contain regular files only')
    index = {}
    for line in (bundle / INDEX).read_text().splitlines():
        digest, name = line.split()
        leaf(name)
        if name in index or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid or duplicate checksum record')
        index[name] = digest
    actual = {p.name for p in bundle.iterdir()}
    if actual != set(index) | {INDEX}:
        raise ValueError('Bundle file list does not match checksum index')
    for name, digest in index.items():
        path = bundle / name
        if path.is_symlink() or not path.is_file() or sources.sha256(path) != digest:
            raise ValueError('Asset checksum mismatch: ' + name)
    required = {META, 'sources.lock.json', 'resolved.config', 'plugins.config',
                'traceability.tar.gz', 'firmware-sha256sums',
                'config.buildinfo', 'feeds.buildinfo', 'version.buildinfo'}
    if not required <= index.keys():
        raise ValueError('Release lacks traceability files')
    m = json.loads((bundle / META).read_text())
    if m.get('schema') != 1 or m.get('device') != recipe.DEVICE:
        raise ValueError('Unsupported bundle or wrong device')
    numeric(m['run_id']); numeric(m['run_attempt']); sources.commit(m['recipe_commit'])
    datetime.fromisoformat(m['created_at'])
    image, manifest = leaf(m['image']), leaf(m['manifest'])
    if image not in index or not image.endswith(IMAGE_SUFFIX) or manifest not in index:
        raise ValueError('Wrong firmware asset')
    if {n for n in index if n.endswith('.bin')} != {image}:
        raise ValueError('Unexpected additional firmware')
    if (bundle / 'firmware-sha256sums').read_text().split() != [index[image], image]:
        raise ValueError('Firmware checksum index disagrees')
    lock = json.loads((bundle / 'sources.lock.json').read_text())
    if lock.get('schema') != 1 or lock.get('device') != m['device']:
        raise ValueError('Source lock missing or wrong device')
    sources.commit(lock['firmware']['commit'])
    recipe.check_manifest((bundle / manifest).read_text(),
                          recipe.parse((bundle / 'plugins.config').read_text()))
    return m


def artifact_choice(artifacts: list, run_id: str) -> tuple[dict, str]:
    choices = []
    for row in artifacts:
        match = re.fullmatch('wr30u-release-' + re.escape(run_id) + r'-([1-9][0-9]*)', row['name'])
        if match and not row['expired']:
            choices.append((int(match[1]), row))
    if not choices:
        raise ValueError('No verified release artifact. Old diagnostic-only artifacts are not auto-published')
    attempt, row = max(choices, key=lambda item: item[0])
    return row, str(attempt)


def validate_run(run: dict, jobs: list, repository: str, local_run: str) -> None:
    if (run['head_repository']['full_name'] != repository
            or run['path'] != '.github/workflows/WR30U.yml'
            or run['event'] not in ('workflow_dispatch', 'schedule')
            or (str(run['id']) != local_run and run['status'] != 'completed')):
        raise ValueError('Not an eligible run from this repository and workflow')
    # An overall failed run is eligible when build succeeded and only publishing failed.
    if not any(j['name'] == 'build' and j['conclusion'] == 'success' for j in jobs):
        raise ValueError('Source build job has not succeeded')


def old_releases(releases: list, current_id: int) -> list[dict]:
    published = [r for r in releases if not r['draft']]
    if not any(r['id'] == current_id for r in published):
        raise ValueError('New release not confirmed; refuse to delete old releases')
    published.sort(key=lambda r: (r['published_at'], r['id']), reverse=True)
    return published[3:]


def verify_remote(release: dict, bundle: Path) -> None:
    expected = {p.name: p for p in bundle.iterdir()}
    actual = {a['name']: a for a in release['assets']}
    if actual.keys() != expected.keys():
        raise ValueError('Remote release asset set differs; not pruning history')
    for name, path in expected.items():
        asset = actual[name]
        if asset['size'] != path.stat().st_size:
            raise ValueError('Remote asset size differs: ' + name)
        if asset.get('digest') != 'sha256:' + sources.sha256(path):
            raise ValueError('Remote SHA256 unavailable or mismatched: ' + name)


def publish(run_id: str, repository: str, work: Path) -> str:
    numeric(run_id)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository')
    base = 'repos/' + repository
    run = api(f'{base}/actions/runs/{run_id}')
    artifacts = pages(f'{base}/actions/runs/{run_id}/artifacts?per_page=100', 'artifacts')
    artifact, attempt = artifact_choice(artifacts, run_id)
    jobs = pages(f'{base}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100', 'jobs')
    validate_run(run, jobs, repository, os.environ.get('GITHUB_RUN_ID', ''))
    work.mkdir(parents=True, exist_ok=True)
    bundle = work / 'bundle'
    gh('run', 'download', run_id, '--repo', repository, '--name', artifact['name'], '--dir', str(bundle))
    m = validate_bundle(bundle)
    if (m['repository'] != repository or m['run_id'] != run_id or m['run_attempt'] != attempt
            or m['recipe_commit'] != run['head_sha']):
        raise ValueError('Artifact does not match source run/commit')
    tag = f'WR30U-{run_id}-{attempt}'  # Stable across retries; never retag a different commit.
    title_time = datetime.fromisoformat(m['created_at']).astimezone(timezone(timedelta(hours=8)))
    lock = json.loads((bundle / 'sources.lock.json').read_text())
    manifest = (bundle / m['manifest']).read_text()
    packages = [line.split() for line in manifest.splitlines() if line.strip()]
    kernel = next((p[2] for p in packages if p[0] == 'kernel' and len(p) > 2), 'unknown')
    body = (f"# WR30U stock / MTK Vendor mt_wifi\n\nBuild verified; hardware testing still required. "
            f"Not for ubootmod.\n\nSource: {lock['firmware']['repository']}\n"
            f"Branch: {lock['firmware']['branch']}\nSource SHA: {lock['firmware']['commit']}\n"
            f"Recipe SHA: {m['recipe_commit']}\nKernel: {kernel}\n"
            f"Build: https://github.com/{repository}/actions/runs/{run_id}\n\n"
            '## LuCI applications and themes\n' + '\n'.join(sorted(p[0] for p in packages if recipe.is_app(p[0])))
            + '\n\n## Firmware SHA256\n```text\n' + (bundle / 'firmware-sha256sums').read_text()
            + '```\n\nSource lock, final config, and recipe/patch snapshot are attached.\n')
    notes = work / 'RELEASE.md'
    notes.write_text(body)
    releases = pages(f'{base}/releases?per_page=100')
    existing = next((r for r in releases if r['tag_name'] == tag), None)
    if not existing:
        gh('release', 'create', tag, '--repo', repository, '--target', m['recipe_commit'],
           '--title', 'WR30U - ' + title_time.strftime('%Y-%m-%d %H:%M +08:00'),
           '--notes-file', str(notes), '--draft')
        existing = wait_release(base, tag, draft=True)
    # Draft creation need not create a tag yet. Check an existing ref, but do not
    # confuse an unpublished tag with a failed source/permission verification.
    refs = api(f'{base}/git/matching-refs/tags/{tag}')
    if any(r['ref'] == 'refs/tags/' + tag for r in refs):
        if api(f'{base}/commits/{tag}')['sha'] != m['recipe_commit']:
            raise ValueError('Existing release tag points to a different recipe commit')
    if existing['draft']:
        if existing['target_commitish'] != m['recipe_commit']:
            raise ValueError('Draft release targets a different recipe commit')
        gh('release', 'upload', tag, '--repo', repository, '--clobber',
           *(str(p) for p in sorted(bundle.iterdir())))
        draft = wait_release(base, tag, draft=True)
        verify_remote(draft, bundle)
        gh('release', 'edit', tag, '--repo', repository, '--draft=false', '--latest')
    published = wait_release(base, tag, draft=False)
    if api(f'{base}/commits/{tag}')['sha'] != m['recipe_commit']:
        raise ValueError('Published release tag differs from build commit; not pruning history')
    verify_remote(published, bundle)
    for old in old_releases(pages(f'{base}/releases?per_page=100'), published['id']):
        gh('release', 'delete', old['tag_name'], '--repo', repository, '--cleanup-tag', '--yes')
    print('Published and verified:', published['html_url'])
    return published['html_url']


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('pack', 'publish'))
    p.add_argument('--output', type=Path, default=ROOT / 'output')
    p.add_argument('--run-id', default=os.environ.get('PUBLISH_RUN_ID', ''))
    args = p.parse_args()
    if args.operation == 'pack':
        pack(args.output)
    else:
        with tempfile.TemporaryDirectory(prefix='wr30u-release-') as work:
            publish(args.run_id, os.environ['GITHUB_REPOSITORY'], Path(work))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        raise SystemExit('Release failed (no automatic rebuild): ' + str(exc)) from exc
