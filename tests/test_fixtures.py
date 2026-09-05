from __future__ import annotations

import hashlib
import json
import os
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = Path(os.environ.get("TURTLEBENCH_FIXTURES", ROOT / "fixtures" / "fixed-v1"))


class FixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        if not (FIXTURE_ROOT / "manifest.json").exists():
            self.skipTest("private fixtures are installed separately from Git")
        self.manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_has_twelve_unique_puzzles(self) -> None:
        puzzles = self.manifest["puzzles"]
        self.assertEqual(len(puzzles), 12)
        self.assertEqual(len({item["id"] for item in puzzles}), 12)

    def test_manifest_has_complete_strata(self) -> None:
        counts = Counter((item["type"], item["difficulty"]) for item in self.manifest["puzzles"])
        self.assertEqual(len(counts), 6)
        self.assertEqual(set(counts.values()), {2})

    def test_manifest_paths_and_hashes_match(self) -> None:
        for item in self.manifest["puzzles"]:
            path = FIXTURE_ROOT / item["path"]
            self.assertTrue(path.is_file(), item["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])

    def test_puzzle_schema(self) -> None:
        required = {"type", "surface", "solution", "hints", "key_facts", "difficulty"}
        for item in self.manifest["puzzles"]:
            puzzle = json.loads((FIXTURE_ROOT / item["path"]).read_text(encoding="utf-8"))
            self.assertTrue(required.issubset(puzzle), item["id"])
            self.assertEqual(puzzle["type"], item["type"])
            self.assertEqual(puzzle["difficulty"], item["difficulty"])
            self.assertGreaterEqual(len(puzzle["hints"]), 3)
            self.assertGreaterEqual(len(puzzle["key_facts"]), 5)


class FixtureDistributionTests(unittest.TestCase):
    def test_private_json_is_absent_from_repository(self) -> None:
        self.assertEqual(list((ROOT / "fixtures").rglob("*.json")), [])

    def test_installer_documents_release_password_and_digest(self) -> None:
        script = (ROOT / "scripts" / "install-fixtures.sh").read_text(encoding="utf-8")
        self.assertIn("fixtures-v1", script)
        self.assertIn('PASSWORD="123456"', script)
        self.assertIn("c28746c7b8296a2b8eb36aef6c6cff5ae9418283409c291eaac139c772646069", script)


if __name__ == "__main__":
    unittest.main()
