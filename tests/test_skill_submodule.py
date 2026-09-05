from __future__ import annotations

import configparser
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBMODULE_PATH = ROOT / "skills" / "situation-puzzle"
SUBMODULE_URL = "https://github.com/fffonion/situation-puzzle-skill"


class SkillSubmoduleTests(unittest.TestCase):
    def test_skill_submodule_url(self) -> None:
        config = configparser.ConfigParser()
        loaded = config.read(ROOT / ".gitmodules", encoding="utf-8")
        self.assertTrue(loaded)
        section = 'submodule "skills/situation-puzzle"'
        self.assertIn(section, config)
        self.assertEqual(config[section]["path"], "skills/situation-puzzle")
        self.assertEqual(config[section]["url"], SUBMODULE_URL)

    def test_skill_checkout_has_manifest(self) -> None:
        self.assertTrue((SUBMODULE_PATH / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
