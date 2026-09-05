import json
import tempfile
import unittest
from pathlib import Path

from turtlebench import pages


class PublicResultTests(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run = root / "sample-run"
        (run / "summaries").mkdir(parents=True)
        summary = {
            "overall_score": 85.9,
            "success_rate": 0.75,
            "rounds_median": 22.0,
            "valid_games": 3,
            "invalid_games": 1,
            "player": {
                "slug": "luna-max",
                "display_name": "Luna max baseline",
                "provider": "openai-codex",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "max",
            },
            "player_resources": {
                "games": 3,
                "games_with_usage": 3,
                "player_active_time_s": 120.5,
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_tokens": 300,
                "cache_write_tokens": 5,
                "reasoning_tokens": 7,
                "api_call_count": 9,
            },
        }
        (run / "summaries" / "luna-max.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        for trial, hints in enumerate((0, 2, 1), start=1):
            trial_dir = run / "games" / "luna-max" / "PUZZLE" / f"trial-{trial:02d}"
            trial_dir.mkdir(parents=True)
            score = {
                "validity": "valid",
                "status": "solved",
                "raw": {"hints_used": hints},
            }
            (trial_dir / "score.json").write_text(json.dumps(score), encoding="utf-8")

        retry = run / "games" / "luna-max" / "PUZZLE" / "trial-01-retry-01-invalid-host"
        retry.mkdir(parents=True)
        (retry / "score.json").write_text(
            json.dumps({"validity": "valid", "raw": {"hints_used": 99}}),
            encoding="utf-8",
        )
        return run

    def test_build_public_run_aggregates_only_public_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.make_run(Path(tmp))
            result = pages.build_public_run(run, pricing={})

        self.assertEqual(result["run_id"], "sample-run")
        self.assertEqual(len(result["models"]), 1)
        model = result["models"][0]
        self.assertEqual(model["slug"], "luna-max")
        self.assertEqual(model["name"], "GPT-5.6 Luna")
        self.assertEqual(model["family"], "gpt-5.6-luna")
        self.assertEqual(model["reasoning_effort"], "max")
        self.assertEqual(model["overall_score"], 85.9)
        self.assertEqual(model["games"], 3)
        self.assertEqual(model["active_time_s"], 120.5)
        self.assertEqual(
            model["tokens"],
            {
                "total": 425,
                "input": 100,
                "output": 20,
                "cache_read": 300,
                "cache_write": 5,
            },
        )
        self.assertEqual(
            model["behavior"],
            {
                "solve_rate": 0.75,
                "rounds_median": 22.0,
                "hints_median": 1,
                "samples": 3,
            },
        )
        serialized = json.dumps(result)
        self.assertNotIn("session_id", serialized)
        self.assertNotIn(str(run), serialized)
        self.assertNotIn("display_name", serialized)

    def test_invalid_and_retry_directories_do_not_affect_hint_median(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.make_run(Path(tmp))
            invalid = run / "games" / "luna-max" / "PUZZLE-2" / "trial-01"
            invalid.mkdir(parents=True)
            (invalid / "score.json").write_text(
                json.dumps({"validity": "invalid_host", "raw": {"hints_used": 88}}),
                encoding="utf-8",
            )

            result = pages.build_public_run(run, pricing={})

        self.assertEqual(result["models"][0]["behavior"]["hints_median"], 1)


if __name__ == "__main__":
    unittest.main()
