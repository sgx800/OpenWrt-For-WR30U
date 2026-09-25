#!/usr/bin/env python3
"""Normalize Kconfig fragments and fail closed on target/plugin drift."""
from __future__ import annotations
import re
import sys
from pathlib import Path

DEVICE = 'CONFIG_TARGET_DEVICE_mediatek_filogic_DEVICE_xiaomi_mi-router-wr30u-stock'
APP = 'CONFIG_PACKAGE_luci-app-'
THEME = 'CONFIG_PACKAGE_luci-theme-'
DEVICE_KEY = re.compile(r'^CONFIG_TARGET_DEVICE_(?!PACKAGES_).+_DEVICE_.+$')
STANDARD_APPS = {APP + 'firewall', APP + 'opkg'}


def parse(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        match = re.fullmatch(r'(CONFIG_[A-Za-z0-9_+.-]+)=(.*)', line)
        if match:
            result[match[1]] = match[2]
            continue
        match = re.fullmatch(r'# (CONFIG_[A-Za-z0-9_+.-]+) is not set', line)
        if match:
            result[match[1]] = 'n'
    return result


def requirements(private: dict[str, str]) -> set[str]:
    return {key for key, value in private.items()
            if value == 'y' and key.startswith((APP, THEME))}


def normalize(config: dict[str, str], private: dict[str, str]) -> dict[str, str]:
    config = dict(config)
    config.update(private)
    required = requirements(private)
    if not required:
        raise ValueError('Personal plugin list is empty')
    allowed = required | STANDARD_APPS
    for key in list(config):
        if DEVICE_KEY.fullmatch(key):
            config[key] = 'n'
        if key.startswith((APP, THEME)) and key not in allowed:
            config[key] = 'n'
        # Keep the existing no-USB choice even if upstream adds USB modules.
        if key.startswith('CONFIG_PACKAGE_kmod-usb'):
            config[key] = 'n'
    config.update({
        'CONFIG_TARGET_mediatek': 'y',
        'CONFIG_TARGET_mediatek_filogic': 'y',
        'CONFIG_TARGET_MULTI_PROFILE': 'y',
        'CONFIG_TARGET_ALL_PROFILES': 'n',
        DEVICE: 'y',
    })
    return config


def verify(config: dict[str, str], private: dict[str, str]) -> None:
    devices = {key for key, value in config.items()
               if DEVICE_KEY.fullmatch(key) and value == 'y'}
    if devices != {DEVICE}:
        raise ValueError('Wrong device selection: ' + repr(sorted(devices)))
    if any(config.get(key) != 'y' for key in
           ('CONFIG_TARGET_mediatek', 'CONFIG_TARGET_mediatek_filogic')):
        raise ValueError('Wrong target/subtarget')
    if config.get('CONFIG_TARGET_ALL_PROFILES', 'n') != 'n':
        raise ValueError('All-device profiles must be disabled')
    required = requirements(private)
    if not required:
        raise ValueError('Personal plugin list is empty')
    missing = sorted(key for key in required if config.get(key) != 'y')
    if missing:
        raise ValueError('Selected plugins were dropped by Kconfig: ' + ', '.join(missing))
    extras = sorted(key for key, value in config.items()
                    if value in ('y', 'm') and key.startswith((APP, THEME))
                    and key not in required | STANDARD_APPS)
    if extras:
        raise ValueError('Unexpected LuCI applications/themes: ' + ', '.join(extras))
    print('WR30U stock target and selected plugins verified: ' +
          ', '.join(sorted(key.removeprefix('CONFIG_PACKAGE_') for key in required)))


def self_test() -> None:
    private = {APP + 'homeproxy': 'y', THEME + 'aurora': 'y'}
    parsed = parse('CONFIG_A=y\n# CONFIG_A is not set\nCONFIG_B="x"\n#CONFIG_C=n\n')
    assert parsed == {'CONFIG_A': 'n', 'CONFIG_B': '"x"'}
    result = normalize({DEVICE + '-other': 'y', APP + 'samba4': 'y',
                        'CONFIG_TARGET_DEVICE_PACKAGES_mediatek_filogic_DEVICE_test': '""'}, private)
    assert result['CONFIG_TARGET_DEVICE_PACKAGES_mediatek_filogic_DEVICE_test'] == '""'
    verify(result, private)
    assert normalize(result, private) == result
    for bad in (
        dict(result, **{DEVICE + '-other': 'y'}),
        dict(result, **{APP + 'homeproxy': 'n'}),
        dict(result, **{APP + 'samba4': 'm'}),
    ):
        try:
            verify(bad, private)
        except ValueError:
            pass
        else:
            raise AssertionError('Configuration guard accepted an invalid case')
    print('All configuration guard tests passed.')


def main() -> None:
    if sys.argv[1:] == ['self-test']:
        self_test()
        return
    if len(sys.argv) != 4 or sys.argv[1] not in ('normalize', 'verify'):
        raise SystemExit('Usage: wr30u-config.py {normalize|verify} CONFIG PRIVATE; or self-test')
    mode, path, personal = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    config, private = parse(path.read_text()), parse(personal.read_text())
    if mode == 'normalize':
        config = normalize(config, private)
        path.write_text(''.join(
            f'# {key} is not set\n' if value == 'n' else f'{key}={value}\n'
            for key, value in sorted(config.items())))
    else:
        verify(config, private)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(f'WR30U configuration error: {exc}') from exc
