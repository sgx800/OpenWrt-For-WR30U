"""Offline tests for source locking, release retention, and workflow policy."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / 'Scripts'))
import recipe
import sources
import release


class MaintenanceTests(unittest.TestCase):
    def test_sources_json_is_the_single_origin_policy(self):
        spec = sources.selection()
        raw = json.loads((ROOT / 'Config/sources.json').read_text())
        self.assertEqual(spec['firmware']['repository'], raw['firmware']['repository'])
        self.assertEqual(spec['firmware']['branch'], raw['firmware']['branch'])
        self.assertEqual(sources.plan(spec), recipe.package_plan(ROOT))
        self.assertIn('Scripts/release.py', sources.FINGERPRINT)

    def test_replay_rejects_recipe_drift(self):
        lock = dict(sources.selection(), schema=1, device=recipe.DEVICE,
                    recipe_files=sources.fingerprint(), feeds=[], patches={})
        lock['firmware'] = dict(lock['firmware'], commit='a' * 40)
        lock['extra_packages'] = [dict(x, commit='b' * 40) for x in lock['extra_packages']]
        lock['recipe_files']['Config/plugins.config'] = '0' * 64
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'lock.json'; p.write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError, 'Recipe changed'):
                sources.selection(replay=str(p))

    def test_release_retention_keeps_latest_three_published(self):
        rows = [
            {'id': i, 'draft': False, 'published_at': f'2026-09-{i:02d}T00:00:00Z'}
            for i in range(1, 6)
        ] + [{'id': 99, 'draft': True, 'published_at': None}]
        self.assertEqual([x['id'] for x in release.old_releases(rows, 5)], [2, 1])
        with self.assertRaisesRegex(ValueError, 'refuse to delete'):
            release.old_releases(rows, 88)

    def test_publish_artifact_selection_is_exact(self):
        rows = [
            {'name': 'wr30u-release-123-1', 'expired': False},
            {'name': 'wr30u-release-123-2', 'expired': False},
            {'name': 'wr30u-release-123-3', 'expired': True},
            {'name': 'wr30u-diagnostics-123-4', 'expired': False},
        ]
        self.assertEqual(release.artifact_choice(rows, '123')[1], '2')

    def test_workflow_policy_and_permissions(self):
        w = yaml.load((ROOT / '.github/workflows/WR30U.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(w['name'], 'WR30U')
        self.assertEqual(set(w['on']), {'schedule', 'workflow_dispatch'})
        self.assertEqual(w['on']['schedule'], [{'cron': '0 21 * * 0'}])
        self.assertEqual(w['permissions'], {'contents': 'read'})
        self.assertEqual(w['jobs']['cleanup']['permissions'], {'actions': 'write', 'contents': 'read'})
        self.assertEqual(w['jobs']['build']['permissions'], {'contents': 'read'})
        self.assertEqual(w['jobs']['release']['permissions'], {'actions': 'read', 'contents': 'write'})
        self.assertEqual(w['jobs']['build']['needs'], 'cleanup')
        self.assertEqual(w['jobs']['release']['needs'], 'build')
        uses = [step['uses'] for job in w['jobs'].values() for step in job.get('steps', []) if 'uses' in step]
        self.assertTrue(uses)
        for action in uses:
            self.assertRegex(action, r'^[\w-]+/[\w-]+@[0-9a-f]{40}$')

    def test_publish_mode_skips_cleanup_and_build_but_runs_release(self):
        w = yaml.load((ROOT / '.github/workflows/WR30U.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertIn("inputs.MODE != 'publish'", w['jobs']['cleanup']['if'])
        self.assertIn("inputs.MODE != 'publish'", w['jobs']['build']['if'])
        self.assertIn("inputs.MODE == 'publish'", w['jobs']['release']['if'])
        text = (ROOT / '.github/workflows/WR30U.yml').read_text()
        self.assertNotIn('SOURCE_REPO:', text)
        self.assertNotIn('SOURCE_BRANCH:', text)


if __name__ == '__main__':
    unittest.main()
