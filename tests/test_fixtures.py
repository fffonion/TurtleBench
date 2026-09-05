from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "fixtures" / "fixed-v1"


class FixtureTests(unittest.TestCase):
    def setUp(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
