import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from turtlebench import benchmark_runner as br


class BenchmarkRunnerTests(unittest.TestCase):
    def test_parser_accepts_runtime_paths(self):
        args = br.build_parser().parse_args([
            "--fixtures", "/tmp/fixtures",
            "--runs-dir", "/tmp/runs",
            "--state-db", "/tmp/state.db",
        ])
        self.assertEqual(args.fixtures, Path("/tmp/fixtures"))
        self.assertEqual(args.runs_dir, Path("/tmp/runs"))
        self.assertEqual(args.state_db, Path("/tmp/state.db"))

    def test_player_matrix_preserves_requested_order(self):
        self.assertEqual(
            [p["slug"] for p in br.PLAYER_MATRIX],
            ["luna-max", "luna-high", "minimax-m3-max", "deepseek-v4-flash-max", "deepseek-provider-v4-flash-max", "claude-sonnet-5-high", "gpt-5-6-sol-high", "gpt-6-astra-high", "grok-4-6-high"],
        )

    def test_deepseek_uses_commandcode_model_id(self):
        deepseek = next(p for p in br.PLAYER_MATRIX if p["slug"] == "deepseek-v4-flash-max")
        self.assertEqual(deepseek["provider"], "commandcode")
        self.assertEqual(deepseek["model"], "deepseek-ai/deepseek-v4-flash")

    def test_deepseek_provider_uses_official_v4_flash_max(self):
        deepseek = next(p for p in br.PLAYER_MATRIX if p["slug"] == "deepseek-provider-v4-flash-max")
        self.assertEqual(deepseek["provider"], "deepseek")
        self.assertEqual(deepseek["model"], "deepseek-v4-flash")
        self.assertEqual(deepseek["reasoning_effort"], "max")

    def test_claude_sonnet_5_uses_anthropic_high(self):
        claude = next(p for p in br.PLAYER_MATRIX if p["slug"] == "claude-sonnet-5-high")
        self.assertEqual(claude["provider"], "anthropic")
        self.assertEqual(claude["model"], "claude-sonnet-5")
        self.assertEqual(claude["reasoning_effort"], "high")

    def test_gpt_sol_uses_openai_codex_high(self):
        sol = next(p for p in br.PLAYER_MATRIX if p["slug"] == "gpt-5-6-sol-high")
        self.assertEqual(sol["provider"], "openai-codex")
        self.assertEqual(sol["model"], "gpt-5.6-sol")
        self.assertEqual(sol["reasoning_effort"], "high")

    def test_gpt_astra_uses_openai_codex_high(self):
        astra = next(p for p in br.PLAYER_MATRIX if p["slug"] == "gpt-6-astra-high")
        self.assertEqual(astra["provider"], "openai-codex")
        self.assertEqual(astra["model"], "gpt-6-astra")
        self.assertEqual(astra["reasoning_effort"], "high")

    def test_deepseek_display_names_are_distinct(self):
        names = {p["slug"]: p["display_name"] for p in br.PLAYER_MATRIX}
        self.assertIn("CommandCode", names["deepseek-v4-flash-max"])
        self.assertIn("DeepSeek provider", names["deepseek-provider-v4-flash-max"])
        self.assertNotEqual(names["deepseek-v4-flash-max"], names["deepseek-provider-v4-flash-max"])

    def test_load_session_usage_returns_player_totals(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "state.db"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, api_call_count INTEGER, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER)")
                conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)", ("s1", 7, 120, 30, 80, 4, 9))
            usage = br.load_session_usage(db, "s1")
            self.assertIsNotNone(usage)
            assert usage is not None
            self.assertEqual(usage["api_call_count"], 7)
            self.assertEqual(usage["input_tokens"], 120)
            self.assertEqual(usage["output_tokens"], 30)
            self.assertEqual(usage["cache_read_tokens"], 80)

    def test_cli_command_pins_provider_model_and_reasoning(self):
        cmd = br.build_cli_command("xai-oauth", "grok-4.6", "high", "prompt")
        self.assertIn("--provider", cmd)
        self.assertEqual(cmd[cmd.index("--provider") + 1], "xai-oauth")
        self.assertEqual(cmd[cmd.index("--model") + 1], "grok-4.6")
        self.assertEqual(cmd[cmd.index("--reasoning-effort") + 1], "high")
        self.assertIn("--ignore-rules", cmd)
        self.assertIn("--source", cmd)
        self.assertEqual(cmd[cmd.index("--source") + 1], "turtle-bench")
        self.assertEqual(cmd[cmd.index("--max-turns") + 1], "180")

    def test_raw_metrics_use_only_player_action_intervals(self):
        game = {
            "status": "solved",
            "round": 2,
            "player_hints_used": 0,
            "events": [
                {"seq": 1, "at": "2026-01-01T00:00:00+00:00", "actor": "host", "type": "surface", "text": "s"},
                {"seq": 2, "at": "2026-01-01T00:00:10+00:00", "actor": "player", "type": "question", "text": "q1"},
                {"seq": 3, "at": "2026-01-01T00:00:30+00:00", "actor": "host", "type": "response", "text": "是"},
                {"seq": 4, "at": "2026-01-01T00:00:50+00:00", "actor": "player", "type": "question", "text": "q2"},
                {"seq": 5, "at": "2026-01-01T00:01:00+00:00", "actor": "host", "type": "answer", "text": "a"},
            ],
        }
        raw = br.compute_raw_metrics(game)
        self.assertEqual(raw["first_question_latency_s"], 10.0)
        self.assertEqual(raw["player_latency_p50_s"], 20.0)
        self.assertEqual(raw["player_latency_p90_s"], 20.0)
        self.assertEqual(raw["total_wall_time_s"], 60.0)
        self.assertEqual(raw["player_active_time_s"], 30.0)
        self.assertEqual(raw["question_count"], 2)

    def test_aggregate_uses_six_strata_macro_average(self):
        scores = []
        for prefix, value in [("C-E", 10), ("C-M", 20), ("C-H", 30), ("A-E", 40), ("A-M", 50), ("A-H", 60)]:
            typ, diff = prefix.split("-")
            for puzzle_no in (1, 2):
                for trial in (1, 2, 3):
                    scores.append({
                        "puzzle_id": f"SPB-{typ}-{diff}-0{puzzle_no}",
                        "trial": trial,
                        "validity": "valid",
                        "status": "solved",
                        "raw": {"rounds": 5, "hints_used": 0, "player_latency_p50_s": 2, "player_latency_p90_s": 3,
                                "player_active_time_s": 12, "player_usage": {"input_tokens": 100, "output_tokens": 20,
                                "cache_read_tokens": 80, "cache_write_tokens": 0, "reasoning_tokens": 5, "api_call_count": 2}},
                        "scores": {"total": value},
                        "failure_tags": [],
                    })
        summary = br.aggregate_scores(scores)
        self.assertEqual(summary["overall_score"], 35.0)
        self.assertEqual(summary["success_rate"], 1.0)
        self.assertEqual(len(summary["strata"]), 6)
        self.assertEqual(summary["player_resources"]["games_with_usage"], 36)
        self.assertEqual(summary["player_resources"]["input_tokens"], 3600)
        self.assertEqual(summary["player_resources"]["player_active_time_s"], 432.0)

    def test_aggregate_reports_unavailable_when_no_valid_games(self):
        scores = [{"validity": "invalid_infrastructure", "status": "error"}]
        summary = br.aggregate_scores(scores)
        self.assertIsNone(summary["overall_score"])
        self.assertIsNone(summary["success_rate"])
        self.assertEqual(summary["valid_games"], 0)
        self.assertEqual(summary["invalid_games"], 1)

    def test_resume_skips_existing_terminal_score(self):
        with tempfile.TemporaryDirectory() as td:
            score = Path(td) / "score.json"
            score.write_text(json.dumps({"validity": "valid", "status": "solved"}), encoding="utf-8")
            self.assertTrue(br.is_completed_score(score))
            score.write_text(json.dumps({"validity": "pending", "status": "running"}), encoding="utf-8")
            self.assertFalse(br.is_completed_score(score))

    def test_archive_invalid_trials_preserves_valid_trials(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            player = "model-a"
            valid = run_dir / "games" / player / "SPB-C-E-01" / "trial-01"
            invalid = run_dir / "games" / player / "SPB-C-E-01" / "trial-02"
            valid.mkdir(parents=True)
            invalid.mkdir(parents=True)
            (valid / "score.json").write_text(json.dumps({"validity": "valid", "status": "solved"}), encoding="utf-8")
            (invalid / "score.json").write_text(json.dumps({"validity": "invalid_host", "status": "solved"}), encoding="utf-8")
            summary = run_dir / "summaries" / f"{player}.json"
            summary.parent.mkdir(parents=True)
            summary.write_text("{}", encoding="utf-8")
            archive = run_dir / "reruns-invalid" / "pass-1"

            counts = br.archive_invalid_trials(run_dir, [player], archive)

            self.assertEqual(counts, {player: 1})
            self.assertTrue(valid.exists())
            self.assertFalse(invalid.exists())
            self.assertTrue((archive / "games" / player / "SPB-C-E-01" / "trial-02" / "score.json").exists())
            self.assertTrue((archive / "summaries" / f"{player}.json").exists())
            self.assertTrue((archive / "manifest.json").exists())

    def test_terminal_game_with_preliminary_does_not_rerun(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / "game.json"
            pre = root / "preliminary.json"
            game.write_text(json.dumps({"status": "solved"}), encoding="utf-8")
            pre.write_text("{}", encoding="utf-8")
            self.assertFalse(br.game_needs_run(game, pre))
            pre.unlink()
            self.assertTrue(br.game_needs_run(game, pre))

    def test_api_failure_log_is_infrastructure_failure(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "player.log"
            log.write_text("API call failed after 5 retries: HTTP 429", encoding="utf-8")
            self.assertTrue(br.has_infrastructure_api_failure(log))
            log.write_text("Reached maximum iterations (180)", encoding="utf-8")
            self.assertFalse(br.has_infrastructure_api_failure(log))
            log.write_text("角色、状态、轮次", encoding="utf-8")
            self.assertFalse(br.has_infrastructure_api_failure(log))


class BenchmarkRunnerAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_judge_retries_when_cli_claims_success_without_output(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            player = {
                "slug": "luna-max",
                "provider": "openai-codex",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "max",
            }
            puzzle = {"id": "SPB-C-E-01", "path": "puzzles/SPB-C-E-01.json"}
            output = run_dir / "games/luna-max/SPB-C-E-01/judge.json"
            calls = 0

            async def fake_run_cli(cmd, log_path, timeout_s):
                nonlocal calls
                calls += 1
                if calls == 2:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(json.dumps([{"trial": i} for i in (1, 2, 3)]), encoding="utf-8")
                return 0

            with mock.patch.object(br, "run_cli", side_effect=fake_run_cli):
                result = await br.run_judge(run_dir, player, puzzle, 10)

            self.assertEqual(result, output)
            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
