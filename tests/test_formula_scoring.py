import json
import tempfile
import unittest
from pathlib import Path

from turtlebench.formula_scoring import (
    classify_trial_state,
    formula_summary_from_run,
    question_quality,
    unified_formula_score,
)


class FormulaScoringTests(unittest.TestCase):
    manifest = {
        "puzzles": [{"id": "P-01", "difficulty": "简单", "type": "浓汤类型"}],
    }

    def write_trial(
        self,
        root: Path,
        number: int,
        status: str,
        rounds: int = 10,
        validity: str | None = None,
        events: list[dict] | None = None,
    ) -> None:
        trial = root / f"trial-{number:02d}"
        trial.mkdir(parents=True)
        (trial / "game.json").write_text(
            json.dumps({"status": status, "round": rounds, "stop_reason": status, "events": events or []}),
            encoding="utf-8",
        )
        (trial / "preliminary.json").write_text(
            json.dumps({"validity": validity or "pending", "raw": {}}),
            encoding="utf-8",
        )
        if validity is not None:
            (trial / "score.json").write_text(
                json.dumps({"validity": validity, "status": status, "scores": {"total": 75.0}}),
                encoding="utf-8",
            )

    def test_valid_player_error_is_a_failed_sample(self):
        self.assertEqual(
            classify_trial_state({"status": "error"}, {"validity": "valid"}),
            "failure",
        )
        self.assertEqual(
            classify_trial_state({"status": "error"}, {"validity": "invalid_infrastructure"}),
            "infrastructure",
        )
        self.assertEqual(
            classify_trial_state({"status": "solved"}, {"validity": "invalid_host"}),
            "infrastructure",
        )
        self.assertEqual(
            classify_trial_state({"status": "max_rounds"}, {"validity": "valid"}),
            "failure",
        )

        with tempfile.TemporaryDirectory() as tmp:
            trial_root = Path(tmp) / "games" / "player" / "P-01"
            self.write_trial(trial_root, 1, "solved", validity="valid")
            self.write_trial(trial_root, 2, "error", validity="valid")
            self.write_trial(trial_root, 3, "error", validity="invalid_infrastructure")
            result = formula_summary_from_run(tmp, "player", self.manifest)

        self.assertEqual(result["terminal_trial_records"], 2)
        self.assertEqual(result["infrastructure_trials"], 1)
        self.assertEqual(result["coverage"], 0.667)
        self.assertEqual(result["solved_trials"], 1)
        self.assertEqual(result["solve_rate"], 0.333333)
        self.assertEqual(result["baseline_component"], 38.56)
        self.assertEqual(result["solve_component"], 16.7)
        self.assertEqual(result["overall_score"], 55.26)
        self.assertEqual(result["score_version"], "single")
        self.assertTrue(result["provisional"])

    def test_one_of_36_solves_has_bounded_effect(self):
        manifest = {
            "puzzles": [
                {"id": f"SPB-{kind}-{difficulty}-{number:02d}", "difficulty": difficulty_name, "type": type_name}
                for kind, difficulty, difficulty_name, type_name in (
                    ("A", "E", "简单", "荒诞类型"),
                    ("A", "M", "中等", "荒诞类型"),
                    ("A", "H", "困难", "荒诞类型"),
                    ("C", "E", "简单", "浓汤类型"),
                    ("C", "M", "中等", "浓汤类型"),
                    ("C", "H", "困难", "浓汤类型"),
                )
                for number in (1, 2)
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            player_root = Path(tmp) / "games" / "player"
            for puzzle_index, puzzle in enumerate(manifest["puzzles"]):
                root = player_root / puzzle["id"]
                for trial in range(1, 4):
                    status = "solved" if puzzle_index == 0 and trial == 1 else "error"
                    self.write_trial(root, trial, status, validity="valid")
            result = formula_summary_from_run(tmp, "player", manifest)

        self.assertEqual(result["expected_trials"], 36)
        self.assertEqual(result["solved_trials"], 1)
        self.assertEqual(result["solve_rate"], 0.027778)
        self.assertEqual(result["overall_score"], 39.96)
        self.assertEqual(result["baseline_component"], 38.56)
        self.assertEqual(result["solve_component"], 1.39)
        self.assertFalse(result["provisional"])

    def test_fitted_formula_uses_only_solve_rate(self):
        self.assertEqual(unified_formula_score(0.0), 38.56)
        self.assertEqual(unified_formula_score(1 / 36), 39.96)
        self.assertEqual(unified_formula_score(1 / 3), 55.26)
        self.assertEqual(unified_formula_score(1.0), 88.65)

    def test_formula_score_is_independent_of_cost_and_elapsed_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = []
            for slug, rounds, latency, price in (
                ("fast-cheap", 3, 0.2, 0.01),
                ("slow-expensive", 50, 900.0, 99.0),
            ):
                player_root = Path(tmp) / slug / "games" / "player" / "P-01"
                for trial, status in ((1, "solved"), (2, "error"), (3, "error")):
                    self.write_trial(player_root, trial, status, rounds=rounds, validity="valid")
                    trial_dir = player_root / f"trial-{trial:02d}"
                    game_path = trial_dir / "game.json"
                    game = json.loads(game_path.read_text(encoding="utf-8"))
                    game["total_wall_time_s"] = latency
                    game_path.write_text(json.dumps(game), encoding="utf-8")
                    score_path = trial_dir / "score.json"
                    score = json.loads(score_path.read_text(encoding="utf-8"))
                    score["price_usd"] = price
                    score["raw"] = {"player_latency_p50_s": latency, "player_latency_p90_s": latency}
                    score_path.write_text(json.dumps(score), encoding="utf-8")
                results.append(formula_summary_from_run(Path(tmp) / slug, "player", self.manifest))

        self.assertEqual(results[0]["overall_score"], results[1]["overall_score"])
        self.assertEqual(results[0]["solve_rate"], results[1]["solve_rate"])

    def test_question_quality_is_deterministic(self):
        events = [
            {"actor": "player", "type": "question", "text": "他在室内吗？"},
            {"actor": "host", "type": "response", "text": "是"},
            {"actor": "player", "type": "question", "text": "他在室内还是室外？"},
            {"actor": "host", "type": "response", "text": "不相关"},
            {"actor": "player", "type": "question", "text": "他在室内还是室外？"},
            {"actor": "host", "type": "response", "text": "不是"},
        ]
        quality = question_quality({"events": events})
        self.assertEqual(quality["question_count"], 3)
        self.assertEqual(quality["atomicity"], round(1 / 3, 6))
        self.assertEqual(quality["response_yield"], round(2 / 3, 6))
        self.assertEqual(quality["novelty"], round(2 / 3, 6))
        self.assertEqual(quality["factor"], round(8 / 15, 6))

    def test_missing_trials_are_zeroed_and_marked_provisional(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial_root = Path(tmp) / "games" / "player" / "P-01"
            self.write_trial(trial_root, 1, "solved", validity="valid")
            result = formula_summary_from_run(tmp, "player", self.manifest)

        self.assertEqual(result["trial_records"], 1)
        self.assertEqual(result["expected_trials"], 3)
        self.assertEqual(result["solve_rate"], 0.333333)
        self.assertEqual(result["overall_score"], 55.26)
        self.assertTrue(result["provisional"])


if __name__ == "__main__":
    unittest.main()
