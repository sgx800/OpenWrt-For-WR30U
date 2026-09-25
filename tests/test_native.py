import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native', ROOT / 'Scripts/native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.policy = native.parse((ROOT / 'Config/plugins.config').read_text())
        self.config = native.parse((ROOT / 'Config/WR30U.config').read_text())
        self.config.update(self.policy)
        self.config.update({'CONFIG_PACKAGE_' + p: 'y' for p in native.DRIVERS | native.INFRA})

    def test_parse(self):
        self.assertEqual(native.parse('CONFIG_A=y\n# CONFIG_A is not set\n#CONFIG_B=y\n'),
                         {'CONFIG_A': 'n'})

    def test_native_config(self):
        native.check_config(self.config, self.policy)

    def test_wrong_device(self):
        self.config[native.PROFILE + '-other'] = 'y'
        with self.assertRaises(ValueError):
            native.check_config(self.config, self.policy)

    def test_missing_plugin(self):
        self.config['CONFIG_PACKAGE_luci-app-homeproxy'] = 'n'
        with self.assertRaises(ValueError):
            native.check_config(self.config, self.policy)

    def test_extra_plugin(self):
        self.config['CONFIG_PACKAGE_luci-app-samba4'] = 'y'
        with self.assertRaises(ValueError):
            native.check_config(self.config, self.policy)

    def test_wrong_driver(self):
        self.config['CONFIG_PACKAGE_kmod-mt_wifi7'] = 'y'
        with self.assertRaises(ValueError):
            native.check_config(self.config, self.policy)

    def test_source_guard(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'target/linux/mediatek/image/filogic.mk'
            p.parent.mkdir(parents=True)
            p.write_text('define Device/' + native.DEVICE + '\n  DEVICE_PACKAGES := ' +
                         ' '.join(sorted(native.DRIVERS)) + '\nendef\nTARGET_DEVICES += ' +
                         native.DEVICE + '\n')
            native.check_source(Path(d))
            p.write_text(p.read_text().replace('kmod-mt7915e', 'kmod-mt_wifi7'))
            with self.assertRaises(ValueError):
                native.check_source(Path(d))

    def test_tailscale_precise_patch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'feeds/packages/net/tailscale/Makefile'
            p.parent.mkdir(parents=True)
            for name in ('etc/init.d/tailscale', 'etc/config/tailscale'):
                f = root / 'package/luci-app-tailscale/root' / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text('test')
            kept = '\t$(INSTALL_BIN) $(GO_PKG_BUILD_BIN_DIR)/tailscaled $(1)/usr/sbin\n'
            kept += '\t$(LN) tailscaled $(1)/usr/sbin/tailscale\n'
            p.write_text('/etc/config/tailscale\n/etc/tailscale/\n' + kept +
                         '\t$(INSTALL_BIN) ./files//tailscale.init $(1)/etc/init.d/tailscale\n' +
                         '\t$(INSTALL_DATA) ./files//tailscale.conf $(1)/etc/config/tailscale\n')
            native.patch_tailscale(root)
            self.assertEqual(p.read_text(), '/etc/tailscale/\n' + kept)
            with self.assertRaises(ValueError):
                native.patch_tailscale(root)

    def test_collect_and_reject_other_images(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / 'bin/targets/mediatek/filogic'
            target.mkdir(parents=True)
            name = 'immortalwrt-mediatek-filogic-' + native.DEVICE + '-squashfs-sysupgrade.bin'
            (target / name).write_bytes(b'fixture-not-real-firmware')
            selected = native.apps(self.policy) | native.DRIVERS | native.INFRA
            (target / 'fixture.manifest').write_text(''.join(p+' - 1.0\n' for p in selected))
            native.collect(root, root / 'out', self.policy)
            self.assertIn(name, (root / 'out/firmware-sha256sums').read_text())
            (target / 'other-sysupgrade.bin').write_bytes(b'wrong-device')
            with self.assertRaises(ValueError):
                native.collect(root, root / 'out', self.policy)


if __name__ == '__main__':
    unittest.main()
