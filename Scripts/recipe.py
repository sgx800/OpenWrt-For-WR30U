#!/usr/bin/env python3
"""Compose and verify WR30U/MT7981 Vendor builds; never invoke a build."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

DEVICE = 'xiaomi_mi-router-wr30u-stock'
PROFILE = 'CONFIG_TARGET_DEVICE_mediatek_filogic_DEVICE_' + DEVICE
EXTRAS = 'CONFIG_TARGET_DEVICE_PACKAGES_mediatek_filogic_DEVICE_' + DEVICE
MT76 = {'kmod-mt7915e', 'kmod-mt7981-firmware', 'mt7981-wo-firmware'}
VENDOR = {'kmod-mt_wifi', 'kmod-conninfra', 'kmod-warp', 'kmod-mediatek_hnat',
          'mtwifi-cfg', 'wifi-dats', 'wifi-scripts', 'datconf-lua'}
INFRA = {'luci-app-firewall', 'luci-app-opkg', 'luci-app-package-manager',
         'luci-theme-bootstrap'}
OTHER_DRIVERS = {'kmod-mt_wifi7', 'kmod-mt_hwifi'}
CHIP = {'CONFIG_MTK_CHIP_MT7981': 'y', 'CONFIG_MTK_FIRST_IF_MT7981': 'y',
        'CONFIG_MTK_CONNINFRA_APSOC_MT7981': 'y', 'CONFIG_MTK_WIFI_DRIVER': 'y',
        'CONFIG_MTK_MT7981_NEW_FW': 'y', 'CONFIG_WARP_CHIPSET': '"mt7981"'}
SYMBOL = r'CONFIG_[A-Za-z0-9_+.-]+'


def parse(text: str) -> dict[str, str]:
    """Kconfig fragments: the last explicit value wins, including unset lines."""
    result = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        m = re.fullmatch(r'(' + SYMBOL + r')=(.*)', line)
        n = re.fullmatch(r'# (' + SYMBOL + r') is not set', line)
        if m:
            value = m[2]
            if not re.fullmatch(r'y|m|n|-?[0-9]+|0x[0-9a-fA-F]+|"(?:[^"\\]|\\.)*"', value):
                raise ValueError(f'Invalid or multiline Kconfig value on line {number}: {line}')
            result[m[1]] = value
        elif n:
            result[n[1]] = 'n'
        elif line and not line.startswith('#'):
            raise ValueError(f'Invalid Kconfig line {number}: {line}')
    return result


def render(config: dict[str, str]) -> str:
    return ''.join(f'# {k} is not set\n' if v == 'n' else f'{k}={v}\n'
                   for k, v in sorted(config.items()))


def compose(recipe: Path) -> dict[str, str]:
    merged = {}
    for name in ('MTK.config', 'WR30U.config', 'plugins.config'):
        merged.update(parse((recipe / 'Config' / name).read_text()))
    return merged


def is_app(name: str) -> bool:
    return name.startswith(('luci-app-', 'luci-theme-'))


def wanted_apps(policy: dict[str, str]) -> set[str]:
    result = {k.removeprefix('CONFIG_PACKAGE_') for k, v in policy.items()
              if k.startswith('CONFIG_PACKAGE_') and v == 'y'
              and is_app(k.removeprefix('CONFIG_PACKAGE_'))}
    if not result:
        raise ValueError('Application policy is empty')
    return result


def catalog(text: str) -> set[str]:
    """Use real build metadata, NOT a name regex, to identify package symbols."""
    result = set(re.findall(r'^Package:\s+(\S+)\s*$', text, re.M))
    if not result:
        raise ValueError('No Package records in tmp/.packageinfo; configuration was not resolved')
    return result


def dependency_map(text: str) -> dict[str, set[str]]:
    """Parse package dependencies from OpenWrt tmp/.packageinfo metadata."""
    result: dict[str, set[str]] = {}
    for block in re.split(r'^@@\s*$', text, flags=re.M):
        package = re.search(r'^Package:\s+(\S+)\s*$', block, re.M)
        if not package:
            continue
        deps: set[str] = set()
        line = re.search(r'^Depends:\s*(.*)$', block, re.M)
        if line:
            for token in line.group(1).split():
                if token.startswith('@'):
                    continue
                token = token.lstrip('+')
                if ':' in token:
                    token = token.rsplit(':', 1)[-1]
                if re.fullmatch(r'[A-Za-z0-9_.+-]+', token):
                    deps.add(token)
        result[package.group(1)] = deps
    return result


def dependency_closure(deps: dict[str, set[str]], roots: set[str]) -> set[str]:
    seen, pending = set(), list(roots)
    while pending:
        package = pending.pop()
        for dep in deps.get(package, set()):
            if dep not in seen:
                seen.add(dep)
                pending.append(dep)
    return seen


def check_apps(packages: set[str], required: set[str],
               deps: dict[str, set[str]] | None = None) -> None:
    missing = required - packages
    allowed_dependencies = dependency_closure(deps or {}, required)
    extra = {p for p in packages if is_app(p)} - required - INFRA - allowed_dependencies
    if missing or extra:
        raise ValueError(f'Application mismatch: missing={sorted(missing)}, extra={sorted(extra)}')


def check_config(config: dict[str, str], policy: dict[str, str], known: set[str],
                 deps: dict[str, set[str]] | None = None) -> None:
    profiles = {k for k, v in config.items() if v == 'y'
                and re.fullmatch(r'CONFIG_TARGET_(?:DEVICE_)?[a-z0-9_]+_DEVICE_.+', k)
                and not k.startswith('CONFIG_TARGET_DEVICE_PACKAGES_')}
    if profiles != {PROFILE}:
        raise ValueError(f'Expected only WR30U stock; selected profiles={sorted(profiles)}')
    for k in ('CONFIG_TARGET_mediatek', 'CONFIG_TARGET_mediatek_filogic',
              'CONFIG_TARGET_MULTI_PROFILE', 'CONFIG_TARGET_PER_DEVICE_ROOTFS'):
        if config.get(k) != 'y':
            raise ValueError(f'Required target option {k}=y; actual={config.get(k, "absent")}')
    if config.get('CONFIG_TARGET_ALL_PROFILES', 'n') != 'n':
        raise ValueError('All-device builds are disabled by this recipe')
    tokens = config.get(EXTRAS, '""').strip('"').split()
    for package in MT76:
        if '-' + package not in tokens or package in tokens or '+' + package in tokens:
            raise ValueError(f'Missing/unusable per-device exclusion for {package}: {tokens}')
    states = {p: config.get('CONFIG_PACKAGE_' + p, 'absent') for p in sorted(VENDOR)}
    print('Vendor package states: ' + json.dumps(states, sort_keys=True), flush=True)
    missing = [p for p in VENDOR if p not in known or states[p] != 'y']
    if missing:
        raise ValueError('Vendor packages must be built into firmware: ' +
                         ', '.join(f'{p}={states[p]}' for p in sorted(missing)))
    for key, expected in CHIP.items():
        if config.get(key) != expected:
            raise ValueError(f'{key}: expected {expected}, actual {config.get(key, "absent")}')
    # The per-device defaults can remain '=m' in build metadata. They are
    # excluded from WR30U's rootfs and MUST be absent from its final manifest.
    bad = [p for p in MT76 | OTHER_DRIVERS if config.get('CONFIG_PACKAGE_' + p) == 'y']
    if bad:
        raise ValueError('Wrong Wi-Fi packages globally included: ' + ', '.join(sorted(bad)))
    required = wanted_apps(policy)
    if required - known:
        raise ValueError('Requested packages absent from source/feeds: ' + repr(sorted(required - known)))
    packages = {p for p in known if config.get('CONFIG_PACKAGE_' + p) == 'y'}
    check_apps(packages, required, deps)
    for k, v in policy.items():
        actual = config.get(k, 'n')
        if v in ('y', 'n') and actual != v:
            raise ValueError(f'Application policy changed: {k} requested={v}, actual={actual}')
    print('WR30U stock, MT7981 Vendor driver and application policy verified')


def check_source(root: Path) -> None:
    needed = ('package/mtk/drivers/mt_wifi/Makefile',
              'package/mtk/drivers/mt_wifi/config.in',
              'package/mtk/drivers/conninfra/Makefile',
              'package/mtk/drivers/warp/Makefile',
              'package/mtk/applications/mtwifi-cfg/Makefile',
              'package/mtk/applications/luci-app-mtwifi-cfg/Makefile',
              'package/mtk/applications/luci-app-eqos-mtk/Makefile',
              'package/mtk/applications/luci-app-turboacc-mtk/Makefile',
              'target/linux/mediatek/dts/mt7981b-xiaomi-mi-router-wr30u-stock.dts')
    missing = [p for p in needed if not (root / p).is_file()]
    if missing:
        raise ValueError('Source is missing the MT7981 Vendor/WR30U components: ' + repr(missing))
    config = (root / needed[1]).read_text()
    for symbol in ('MTK_CHIP_MT7981', 'MTK_FIRST_IF_MT7981', 'MTK_MT7981_NEW_FW'):
        if not re.search(r'^\s*config\s+' + symbol + r'\s*$', config, re.M):
            raise ValueError('Source does not define ' + symbol)
    image = (root / 'target/linux/mediatek/image/filogic.mk').read_text()
    m = re.search(r'^define Device/' + re.escape(DEVICE) + r'\s*\n(.*?)^endef', image, re.M | re.S)
    if not m or not all(p in m[1] for p in MT76):
        raise ValueError('WR30U device defaults changed; review the per-device exclusions')
    print('Source has WR30U stock and the MT7981 mt_wifi Vendor backend')


def patch_tailscale(root: Path) -> None:
    """Only remove duplicate ownership; retain feed daemon/CLI and other rules."""
    path = root / 'feeds/packages/net/tailscale/Makefile'
    lines = path.read_text().splitlines(keepends=True)
    remove = []
    for relative in ('etc/init.d/tailscale', 'etc/config/tailscale'):
        if not (root / 'package/luci-app-tailscale/root' / relative).is_file():
            raise ValueError('Custom Tailscale plugin does not supply ' + relative)
        matches = [s for s in lines if re.search(r'\$\(INSTALL_(?:BIN|DATA)\)', s)
                   and './files/' in s and '/' + relative in s]
        if len(matches) != 1:
            raise ValueError('Tailscale layout changed; review duplicate ownership: ' + relative)
        remove.extend(matches)
    remove.extend(s for s in lines if s.strip() == '/etc/config/tailscale')
    path.write_text(''.join(s for s in lines if s not in remove))
    print('Tailscale: only duplicate init/config install rules and conffile ownership removed')


def check_manifest(text: str, policy: dict[str, str],
                   deps: dict[str, set[str]] | None = None) -> None:
    packages = {s.split()[0] for s in text.splitlines() if s.strip()}
    check_apps(packages, wanted_apps(policy), deps)
    missing, bad = VENDOR - packages, packages & (MT76 | OTHER_DRIVERS)
    if missing or bad:
        raise ValueError(f'Firmware driver mismatch: missing={sorted(missing)}, forbidden={sorted(bad)}')


def collect(root: Path, output: Path, policy: dict[str, str]) -> None:
    target = root / 'bin/targets/mediatek/filogic'
    images = sorted(p for p in target.glob('*sysupgrade.*')
                    if p.is_file() and p.name.endswith(('.bin', '.itb', '.img', '.img.gz')))
    selected = [p for p in images if p.name.endswith('-' + DEVICE + '-squashfs-sysupgrade.bin')]
    if len(selected) != 1 or images != selected or not selected[0].stat().st_size:
        raise ValueError('Expected only the WR30U stock sysupgrade image: ' + repr([p.name for p in images]))
    manifests = sorted(target.glob('*.manifest'))
    named = [p for p in manifests if DEVICE in p.name]
    manifest = named[0] if len(named) == 1 else manifests[0] if len(manifests) == 1 else None
    if manifest is None:
        raise ValueError('Cannot identify the WR30U manifest: ' + repr([p.name for p in manifests]))
    packageinfo = root / 'tmp/.packageinfo'
    deps = dependency_map(packageinfo.read_text()) if packageinfo.is_file() else {}
    check_manifest(manifest.read_text(), policy, deps)
    output.mkdir(parents=True, exist_ok=True)
    for path in selected + [manifest] + sorted(target.glob('*.buildinfo')) + sorted(target.glob('*.json')):
        shutil.copy2(path, output / path.name)
    image = selected[0]
    checksum = hashlib.sha256(image.read_bytes()).hexdigest()
    (output / 'firmware-sha256sums').write_text(f'{checksum}  {image.name}\n')
    print('Image and manifest passed WR30U Vendor checks; hardware validation still required')


def package_plan(recipe: Path) -> str:
    records = json.loads((recipe / 'Config/sources.json').read_text())['extra_packages']
    result, names = [], set()
    for row in records:
        name, repo, ref, path = (row[k] for k in ('name', 'repository', 'ref', 'path'))
        if (not re.fullmatch(r'luci-(?:app|theme)-[a-z0-9.+_-]+', name)
                or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', ref)
                or Path(path).is_absolute() or '..' in Path(path).parts
                or any(c in path for c in '\t\r\n') or name in names):
            raise ValueError('Invalid or duplicate external package specification: ' + repr(row))
        names.add(name)
        result.append('\t'.join((name, repo, ref, path)))
    return '\n'.join(result) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['compose', 'plan', 'source', 'config', 'tailscale', 'collect'])
    parser.add_argument('root', type=Path)
    parser.add_argument('--recipe', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('output'))
    args = parser.parse_args()
    if args.command == 'compose':
        print(render(compose(args.recipe)), end='')
    elif args.command == 'plan':
        print(package_plan(args.recipe), end='')
    elif args.command == 'source':
        check_source(args.root)
    elif args.command == 'tailscale':
        patch_tailscale(args.root)
    else:
        policy = parse((args.recipe / 'Config/plugins.config').read_text())
        if args.command == 'config':
            packageinfo = (args.root / 'tmp/.packageinfo').read_text()
            check_config(parse((args.root / '.config').read_text()), policy,
                         catalog(packageinfo), dependency_map(packageinfo))
        else:
            collect(args.root, args.output, policy)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit('WR30U Vendor validation failed: ' + str(exc)) from exc
