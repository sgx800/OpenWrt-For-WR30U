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

    def test_selected_app_dependency_is_allowed_but_unrelated_app_is_not(self):
        metadata = (
            'Package: luci-app-turboacc-mtk\n'
            'Depends: +libc +luci-app-ttyd +kmod-bonding @!PACKAGE_luci-app-turboacc\n@@\n'
            'Package: luci-app-ttyd\nDepends: +libc +ttyd\n@@\n'
            'Package: ttyd\nDepends: +libc\n@@\n'
            'Package: luci-app-samba4\nDepends: +libc\n@@\n'
        )
        deps = r.dependency_map(metadata)
        self.assertIn('luci-app-ttyd', r.dependency_closure(
            deps, {'luci-app-turboacc-mtk'}))
        packages = {'luci-app-turboacc-mtk', 'luci-app-ttyd'}
        r.check_apps(packages, {'luci-app-turboacc-mtk'}, deps)
        with self.assertRaisesRegex(ValueError, 'luci-app-samba4'):
            r.check_apps(packages | {'luci-app-samba4'},
                         {'luci-app-turboacc-mtk'}, deps)

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

    def test_tailscale_precise_ownership_patch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'feeds/packages/net/tailscale/Makefile'
            p.parent.mkdir(parents=True)
            for name in ('etc/init.d/tailscale', 'etc/config/tailscale'):
                f = root / 'package/luci-app-tailscale/root' / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text('fixture')
            keep = '/etc/tailscale/\n\t$(INSTALL_BIN) $(GO_PKG_BUILD_BIN_DIR)/tailscaled $(1)/usr/sbin\n'
            keep += '\t$(LN) tailscaled $(1)/usr/sbin/tailscale\n'
            p.write_text('/etc/config/tailscale\n' + keep +
                         '\t$(INSTALL_BIN) ./files//tailscale.init $(1)/etc/init.d/tailscale\n' +
                         '\t$(INSTALL_DATA) ./files//tailscale.conf $(1)/etc/config/tailscale\n')
            r.patch_tailscale(root)
            self.assertEqual(p.read_text(), keep)
            with self.assertRaises(ValueError):
                r.patch_tailscale(root)

    def test_external_sources_are_only_selected_packages(self):
        plan = r.package_plan(ROOT).splitlines()
        self.assertEqual(len(plan), 5)
        names = {line.split('\t')[0] for line in plan}
        self.assertTrue(names <= r.wanted_apps(self.policy))
        self.assertIn('luci-app-wolplus', names)

    def test_workflow_release_policy(self):
        text = (ROOT / '.github/workflows/WR30U.yml').read_text()
        self.assertIn('softprops/action-gh-release@v3.0.3', text)
        self.assertIn('output/*-sysupgrade.bin', text)
        self.assertIn('output/*.manifest', text)
        self.assertIn('output/firmware-sha256sums', text)
        self.assertIn('output/*.buildinfo', text)
        self.assertIn(".[3:] | .[].tagName", text)
        self.assertIn('gh release delete "$TAG"', text)
        self.assertIn('--cleanup-tag --yes', text)

    def test_workflow_cleanup_policy(self):
        text = (ROOT / '.github/workflows/WR30U.yml').read_text()
        self.assertIn('ophub/delete-releases-workflows@main', text)
        self.assertIn('  actions: write', text)
        self.assertIn('          delete_releases: false', text)
        self.assertIn('          delete_tags: false', text)
        self.assertIn('          delete_workflows: true', text)
        self.assertIn('          workflows_keep_day: 0', text)
        self.assertIn('  build:\n    needs: cleanup', text)

    def test_workflow_triggers_and_source_identity(self):
        workflows = list((ROOT / '.github/workflows').glob('*.yml'))
        self.assertEqual(len(workflows), 1)
        text = workflows[0].read_text()
        self.assertIn('  workflow_dispatch:', text)
        self.assertIn("  schedule:\n    - cron: '0 21 * * 0'", text)
        for event in ('push', 'pull_request', 'workflow_run', 'repository_dispatch'):
            self.assertNotIn('\n  ' + event + ':', text)
        self.assertIn('        default: true', text)
        self.assertIn('  contents: write', text)
        source = json.loads((ROOT / 'Config/sources.json').read_text())['firmware']
        self.assertIn('SOURCE_BRANCH: ' + source['branch'], text)
        self.assertIn('https://github.com/' + source['repository'] + '.git', text)
        self.assertNotIn('native.py', text)


if __name__ == '__main__':
    unittest.main()
