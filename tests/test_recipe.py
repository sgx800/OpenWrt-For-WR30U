import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recipe', ROOT / 'Scripts/recipe.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.policy = r.parse((ROOT / 'Config/plugins.config').read_text())
        self.config = r.compose(ROOT)
        self.known = r.wanted_apps(self.policy) | r.VENDOR | r.INFRA | r.MT76 | r.OTHER_DRIVERS
        self.known |= {'luci-app-samba4', 'luci-app-example_with_underscore'}

    def test_parse_last_assignment_and_unset(self):
        self.assertEqual(r.parse('CONFIG_A=y\n# CONFIG_A is not set\n'), {'CONFIG_A': 'n'})

    def test_reject_multiline_kconfig_string(self):
        with self.assertRaises(ValueError):
            r.parse('CONFIG_A="-a \\\n-b"\n')

    def test_compose_round_trip_and_reference_conflict(self):
        self.assertEqual(r.parse(r.render(self.config)), self.config)
        self.assertEqual(self.config['CONFIG_MTK_BAND_STEERING'], 'y')
        self.assertEqual(len(r.render(self.config).splitlines()), len(self.config))

    def test_vendor_policy(self):
        r.check_config(self.config, self.policy, self.known)

    def test_only_wr30u(self):
        self.config[r.PROFILE + '-ubootmod'] = 'y'
        with self.assertRaisesRegex(ValueError, 'only WR30U'):
            r.check_config(self.config, self.policy, self.known)

    def test_wrong_single_profile_mode(self):
        self.config['CONFIG_TARGET_MULTI_PROFILE'] = 'n'
        with self.assertRaisesRegex(ValueError, 'MULTI_PROFILE'):
            r.check_config(self.config, self.policy, self.known)

    def test_all_devices_rejected(self):
        self.config['CONFIG_TARGET_ALL_PROFILES'] = 'y'
        with self.assertRaisesRegex(ValueError, 'All-device'):
            r.check_config(self.config, self.policy, self.known)

    def test_required_vendor_is_not_optional_module(self):
        self.config['CONFIG_PACKAGE_kmod-mt_wifi'] = 'm'
        with self.assertRaisesRegex(ValueError, 'kmod-mt_wifi=m'):
            r.check_config(self.config, self.policy, self.known)

    def test_driver_chip_mismatch(self):
        self.config['CONFIG_WARP_CHIPSET'] = '"mt7986"'
        with self.assertRaisesRegex(ValueError, 'WARP_CHIPSET'):
            r.check_config(self.config, self.policy, self.known)

    def test_mt76_built_into_all_images_rejected(self):
        self.config['CONFIG_PACKAGE_kmod-mt7915e'] = 'y'
        with self.assertRaisesRegex(ValueError, 'Wrong Wi-Fi'):
            r.check_config(self.config, self.policy, self.known)

    def test_per_device_build_only_module_not_runtime_install(self):
        for p in r.MT76:
            self.config['CONFIG_PACKAGE_' + p] = 'm'
        r.check_config(self.config, self.policy, self.known)

    def test_missing_per_device_exclusion_rejected(self):
        self.config[r.EXTRAS] = '"-kmod-mt7915e"'
        with self.assertRaisesRegex(ValueError, 'per-device exclusion'):
            r.check_config(self.config, self.policy, self.known)

    def test_kconfig_suboptions_not_installable_packages(self):
        self.config['CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray'] = 'y'
        self.config['CONFIG_PACKAGE_luci-app-rclone_INCLUDE_rclone-webui'] = 'y'
        r.check_config(self.config, self.policy, self.known)

    def test_real_underscore_package_not_hidden_by_regex(self):
        self.config['CONFIG_PACKAGE_luci-app-example_with_underscore'] = 'y'
        with self.assertRaisesRegex(ValueError, 'Application mismatch'):
            r.check_config(self.config, self.policy, self.known)

    def test_missing_required_application(self):
        self.config['CONFIG_PACKAGE_luci-app-homeproxy'] = 'n'
        with self.assertRaisesRegex(ValueError, 'missing='):
            r.check_config(self.config, self.policy, self.known)

    def test_absent_application_definition(self):
        self.known.remove('luci-app-wolplus')
        with self.assertRaisesRegex(ValueError, 'absent from source'):
            r.check_config(self.config, self.policy, self.known)

    def test_metadata_registry(self):
        self.assertEqual(r.catalog('Package: a\nVersion: 1\n\nPackage: b\n'), {'a', 'b'})
        with self.assertRaises(ValueError):
            r.catalog('empty')

    def test_new_luci_dependency_requires_explicit_approval(self):
        metadata = ('Package: luci-app-turboacc-mtk\nDepends: +libc +luci-app-ttyd\n@@\n'
                    'Package: luci-app-ttyd\nDepends: +libc +ttyd\n@@\n')
        deps = r.dependency_map(metadata)
        packages = {'luci-app-turboacc-mtk', 'luci-app-ttyd'}
        with self.assertRaisesRegex(ValueError, 'extra='):
            r.check_apps(packages, {'luci-app-turboacc-mtk'})
        r.check_apps(packages, packages, deps)
        with self.assertRaisesRegex(ValueError, 'luci-app-samba4'):
            r.check_apps(packages | {'luci-app-samba4'}, packages, deps)

    def test_manifest_rejects_mt76_even_if_config_permits_build_module(self):
        packages = r.VENDOR | r.wanted_apps(self.policy)
        text = ''.join(p + ' - 1.0\n' for p in sorted(packages))
        r.check_manifest(text, self.policy)
        with self.assertRaisesRegex(ValueError, 'forbidden='):
            r.check_manifest(text + 'kmod-mt7915e - 1.0\n', self.policy)

    def test_source_rejects_non_vendor_tree(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, 'missing the MT7981'):
                r.check_source(Path(d))

    def test_collect_only_correct_image(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / 'bin/targets/mediatek/filogic'
            target.mkdir(parents=True)
            name = 'immortalwrt-mediatek-filogic-' + r.DEVICE + '-squashfs-sysupgrade.bin'
            (target / name).write_bytes(b'unit-test-fixture-not-firmware')
            (target / (name + '.sha256')).write_text('checksum-sidecar')
            packages = r.VENDOR | r.wanted_apps(self.policy) | r.INFRA
            (target / (r.DEVICE + '.manifest')).write_text(''.join(p + ' - 1\n' for p in packages))
            r.collect(root, root / 'output', self.policy)
            self.assertIn(name, (root / 'output/firmware-sha256sums').read_text())
            (target / 'another-device-sysupgrade.bin').write_bytes(b'other')
            with self.assertRaises(ValueError):
                r.collect(root, root / 'output', self.policy)

    def test_tailscale_community_replaces_legacy_plugin(self):
        packages = {item['name']: item for item in
                    json.loads((ROOT / 'Config/sources.json').read_text())['extra_packages']}
        self.assertNotIn('luci-app-tailscale', packages)
        new = packages['luci-app-tailscale-community']
        self.assertEqual(new['repository'], 'Tokisaki-Galaxy/luci-app-tailscale-community')
        self.assertEqual(new['path'], 'luci-app-tailscale-community')
        self.assertEqual(self.policy['CONFIG_PACKAGE_luci-app-tailscale-community'], 'y')
        self.assertNotIn('CONFIG_PACKAGE_luci-app-tailscale', self.policy)
        requested = r.wanted_apps(self.policy)
        self.assertNotIn('luci-app-tailscale', requested)
        self.assertIn('luci-app-tailscale-community', requested)
        with self.assertRaisesRegex(ValueError, 'extra='):
            r.check_apps(requested | {'luci-app-tailscale'}, requested)
        self.assertNotIn('patch_tailscale', (ROOT / 'Scripts/recipe.py').read_text())
        self.assertNotIn('recipe.py" tailscale', (ROOT / 'Scripts/packages.sh').read_text())

    def test_external_sources_are_only_selected_packages(self):
        plan = r.package_plan(ROOT).splitlines()
        self.assertEqual(len(plan), 5)
        names = {line.split('\t')[0] for line in plan}
        self.assertTrue(names <= r.wanted_apps(self.policy))
        self.assertIn('luci-app-wolplus', names)


if __name__ == '__main__':
    unittest.main()
