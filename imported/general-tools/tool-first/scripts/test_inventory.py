import tempfile
import unittest
from pathlib import Path
from inventory import inventory


class InventoryTests(unittest.TestCase):
    def test_bounded_discovery_and_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / 'group' / 'video'
            repo.mkdir(parents=True)
            (repo / '.git').mkdir()
            (repo / 'README.md').write_text('example')
            skill = repo / 'skills' / 'video' / 'SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.write_text('example')
            # A nested dependency must not become a second project.
            (repo / 'nested').mkdir()
            (repo / 'nested' / 'package.json').write_text('{}')
            self.assertEqual(inventory([root], 1)['projects'], [])
            found = inventory([root], 2)['projects']
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]['path'], str(repo.resolve()))
            self.assertIn('skills/video/SKILL.md', found[0]['entrypoints'])
            self.assertTrue(found[0]['git'])
            self.assertEqual(len(inventory([root, repo], 2)['projects']), 1)

    def test_skips_generated_hidden_and_symlink_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('node_modules', '.hidden', 'models'):
                target = root / name
                target.mkdir()
                (target / 'package.json').write_text('{}')
            (root / 'alias').symlink_to(root / '.hidden', target_is_directory=True)
            self.assertEqual(inventory([root])['projects'], [])
            self.assertTrue(inventory([root / 'alias'])['warnings'])

    def test_missing_root_reported_and_negative_depth_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            result = inventory([Path(temp) / 'missing'])
            self.assertEqual(result['projects'], [])
            self.assertTrue(result['warnings'])
        with self.assertRaises(ValueError):
            inventory([], -1)


if __name__ == '__main__':
    unittest.main()
