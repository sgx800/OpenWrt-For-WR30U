#!/usr/bin/env python3
"""Check native WR30U source/config/image contracts without patching drivers."""
from __future__ import annotations
import argparse
import hashlib
import re
import shutil
from pathlib import Path

DEVICE = 'xiaomi_mi-router-wr30u-stock'
PROFILE = 'CONFIG_TARGET_mediatek_filogic_DEVICE_' + DEVICE
DRIVERS = {'kmod-mt7915e', 'kmod-mt7981-firmware', 'mt7981-wo-firmware'}
INFRA = {'luci-app-firewall', 'luci-app-package-manager', 'luci-app-opkg',
         'luci-theme-bootstrap'}
BANNED = {'kmod-mt_wifi', 'kmod-mt_wifi7', 'kmod-mt_hwifi'}


def parse(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        m = re.fullmatch(r'(CONFIG_[A-Za-z0-9_+.-]+)=(.*)', line.strip())
        n = re.fullmatch(r'# (CONFIG_[A-Za-z0-9_+.-]+) is not set', line.strip())
        if m:
            result[m[1]] = m[2]
        elif n:
            result[n[1]] = 'n'
    return result


def apps(policy: dict[str, str]) -> set[str]:
    selected = {key.removeprefix('CONFIG_PACKAGE_') for key, value in policy.items()
                if value == 'y' and key.startswith(('CONFIG_PACKAGE_luci-app-',
                                                   'CONFIG_PACKAGE_luci-theme-'))}
    if not selected:
        raise ValueError('The personal application list is empty')
    return selected


def check_apps(packages: set[str], selected: set[str]) -> None:
    missing = selected - packages
    extra = {p for p in packages if p.startswith(('luci-app-', 'luci-theme-'))}
    extra -= selected | INFRA
    if missing or extra:
        raise ValueError(f'Application mismatch: missing={sorted(missing)}, extra={sorted(extra)}')


def check_source(root: Path) -> None:
    image = (root / 'target/linux/mediatek/image/filogic.mk').read_text()
    m = re.search(r'^define Device/' + re.escape(DEVICE) + r'\n(.*?)^endef',
                  image, re.M | re.S)
    if not m or not all(re.search(r'\b' + re.escape(p) + r'\b', m[1]) for p in DRIVERS):
        raise ValueError('WR30U native device/driver definition changed; review before building')
    if not re.search(r'^TARGET_DEVICES\s*\+=\s*' + re.escape(DEVICE) + r'\s*$', image, re.M):
        raise ValueError('WR30U stock target is not registered')
    print('Native WR30U stock / mt76 source definition verified')


def check_config(config: dict[str, str], policy: dict[str, str]) -> None:
    selected_profiles = {k for k, v in config.items() if v == 'y'
                         and re.fullmatch(r'CONFIG_TARGET_.+_DEVICE_.+', k)
                         and not k.startswith('CONFIG_TARGET_DEVICE_PACKAGES_')}
    if selected_profiles != {PROFILE}:
        raise ValueError(f'Wrong selected device(s): {sorted(selected_profiles)}')
    for k in ('CONFIG_TARGET_mediatek', 'CONFIG_TARGET_mediatek_filogic'):
        if config.get(k) != 'y':
            raise ValueError('Wrong target/subtarget: ' + k)
    for k in ('CONFIG_TARGET_MULTI_PROFILE', 'CONFIG_TARGET_ALL_PROFILES'):
        if config.get(k, 'n') != 'n':
            raise ValueError('Only a native single-device profile is allowed: ' + k)
    packages = {k.removeprefix('CONFIG_PACKAGE_') for k, v in config.items()
                if k.startswith('CONFIG_PACKAGE_') and v == 'y'}
    check_apps(packages, apps(policy))
    if not DRIVERS <= packages or BANNED & packages:
        raise ValueError('Native mt76 driver selection was changed')
    for k, v in policy.items():
        if v == 'y' and config.get(k) != 'y':
            raise ValueError('Required selection removed by Kconfig: ' + k)
        if v == 'n' and config.get(k, 'n') != 'n':
            raise ValueError('An explicitly disabled option was selected: ' + k)
    print('Resolved WR30U native configuration and applications verified')


def patch_tailscale(root: Path) -> None:
    """Custom asvow LuCI owns its config/init; the feed still owns the daemon."""
    p = root / 'feeds/packages/net/tailscale/Makefile'
    lines = p.read_text().splitlines(keepends=True)
    remove = []
    for relative in ('etc/init.d/tailscale', 'etc/config/tailscale'):
        if not (root / 'package/luci-app-tailscale/root' / relative).is_file():
            raise ValueError('asvow package no longer provides ' + relative)
        hits = [line for line in lines
                if re.search(r'\$\(INSTALL_(?:BIN|DATA)\)', line)
                and './files/' in line and '/'+relative in line]
        if len(hits) != 1:
            raise ValueError('Tailscale install recipe changed: ' + relative)
        remove += hits
    # Ownership of the UCI file belongs to luci-app-tailscale as well.
    remove += [line for line in lines if line.strip() == '/etc/config/tailscale']
    p.write_text(''.join(line for line in lines if line not in remove))
    print('Resolved Tailscale plugin file ownership; daemon/CLI unmodified')


def collect(root: Path, output: Path, policy: dict[str, str]) -> None:
    target = root / 'bin/targets/mediatek/filogic'
    images = sorted(p for p in target.iterdir() if p.is_file()
                    and p.name.endswith(('.bin', '.itb', '.ubi', '.img', '.img.gz', '.fip')))
    if len(images) != 1 or not images[0].name.endswith('-'+DEVICE+'-squashfs-sysupgrade.bin'):
        raise ValueError('Expected exactly one native WR30U stock sysupgrade image: ' +
                         repr([p.name for p in images]))
    if images[0].stat().st_size == 0:
        raise ValueError('Empty firmware image')
    manifests = list(target.glob('*.manifest'))
    if len(manifests) != 1:
        raise ValueError('Expected one firmware package manifest')
    packages = {line.split()[0] for line in manifests[0].read_text().splitlines() if line.strip()}
    check_apps(packages, apps(policy))
    if not DRIVERS <= packages or BANNED & packages:
        raise ValueError('Firmware manifest does not contain the native Wi-Fi drivers')
    output.mkdir(parents=True, exist_ok=True)
    files = images + manifests + list(target.glob('*.buildinfo')) + list(target.glob('*.json'))
    for p in files:
        shutil.copy2(p, output / p.name)
    sums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                   for p in images)
    (output / 'firmware-sha256sums').write_text(sums)
    print('Verified firmware image and manifest collected')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['source', 'config', 'tailscale', 'collect'])
    parser.add_argument('root', type=Path)
    parser.add_argument('--policy', type=Path, default=Path('Config/plugins.config'))
    parser.add_argument('--output', type=Path, default=Path('output'))
    args = parser.parse_args()
    if args.command == 'source':
        check_source(args.root)
    elif args.command == 'tailscale':
        patch_tailscale(args.root)
    else:
        policy = parse(args.policy.read_text())
        if args.command == 'config':
            check_config(parse((args.root / '.config').read_text()), policy)
        else:
            collect(args.root, args.output, policy)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit('WR30U validation failed: ' + str(exc)) from exc
