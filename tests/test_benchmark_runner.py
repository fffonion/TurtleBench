import hashlib
import http.server
import json
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from turtlebench import benchmark_runner as br


class BenchmarkRunnerTests(unittest.TestCase):
    def test_ensure_suite_downloads_and_extracts_missing_fixture_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source" / "fixed-v1"
            source.mkdir(parents=True)
            (source / "manifest.json").write_text('{"puzzles": []}\n', encoding="utf-8")
            archive = root / "fixtures.zip"
            subprocess.run(
                ["zip", "-q", "-r", "-P", "123456", str(archive), "fixed-v1"],
                cwd=source.parent,
                check=True,
            )
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            destination = root / "install" / "fixed-v1"

            result = br.ensure_suite(destination, archive.as_uri(), digest, "123456")

            self.assertEqual(result, destination)
            self.assertEqual(
                (destination / "manifest.json").read_text(encoding="utf-8"),
                '{"puzzles": []}\n',
            )

    def test_ensure_suite_keeps_existing_fixture_directory_without_download(self):
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "fixed-v1"
            destination.mkdir()
            marker = destination / "local-marker"
            marker.write_text("keep", encoding="utf-8")

            result = br.ensure_suite(
                destination,
                "file:///this/path/must/not/be-opened.zip",
                "0" * 64,
                "wrong-password",
            )

            self.assertEqual(result, destination)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_ensure_suite_retries_a_truncated_download(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source" / "fixed-v1"
            source.mkdir(parents=True)
            (source / "manifest.json").write_text('{"puzzles": []}\n', encoding="utf-8")
            archive = root / "fixtures.zip"
            subprocess.run(
                ["zip", "-q", "-r", "-P", "123456", str(archive), "fixed-v1"],
                cwd=source.parent,
                check=True,
            )
            payload = archive.read_bytes()

            class Handler(http.server.BaseHTTPRequestHandler):
                requests = 0

                def do_GET(self):
                    type(self).requests += 1
                    body = payload[: len(payload) // 2] if self.requests == 1 else payload
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(body)
                    self.close_connection = True

                def log_message(self, format, *args):
                    pass

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                destination = root / "install" / "fixed-v1"
                result = br.ensure_suite(
                    destination,
                    f"http://127.0.0.1:{server.server_port}/fixtures.zip",
                    hashlib.sha256(payload).hexdigest(),
                    "123456",
                )
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

            self.assertEqual(result, destination)
            self.assertEqual(Handler.requests, 2)

    def test_parser_accepts_runtime_paths(self):
        args = br.build_parser().parse_args([
            "--fixtures", "/tmp/fixtures",
            "--runs-dir", "/tmp/runs",
            "--state-db", "/tmp/state.db",
            "--api-url", "http://127.0.0.1:9999",
        ])
        self.assertEqual(args.fixtures, Path("/tmp/fixtures"))
        self.assertEqual(args.runs_dir, Path("/tmp/runs"))
        self.assertEqual(args.state_db, Path("/tmp/state.db"))
        self.assertEqual(args.api_url, "http://127.0.0.1:9999")
        self.assertEqual(args.max_attempts_per_player, 100)

    def test_api_game_concurrency_reserves_two_server_slots(self):
        self.assertEqual(br.api_game_concurrency(12, 8), 4)
        self.assertEqual(br.api_game_concurrency(2, 8), 2)
        self.assertEqual(br.api_game_concurrency(12, 2), 1)

    def test_attempt_state_reserves_only_remaining_capacity(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            state_path = run_dir / "games/model-a/attempts.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps({
                "player_slug": "model-a",
                "target_valid_games": 36,
                "max_attempts": 100,
                "attempts_started": 96,
                "retry_round": 2,
                "pending_slots": [],
            }), encoding="utf-8")
            state = br.load_attempt_state(run_dir, "model-a", 100)

            reserved = br.reserve_attempt_slots(state_path, state, [f"P:{i}" for i in range(8)])

            self.assertEqual(reserved, ["P:0", "P:1", "P:2", "P:3"])
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["attempts_started"], 100)
            self.assertEqual(saved["pending_slots"], reserved)

    def test_attempt_limit_rejects_less_than_target(self):
        with self.assertRaisesRegex(ValueError, "at least 36"):
            br.validate_attempt_limit(35, 36)
        with self.assertRaises(SystemExit):
            br.build_parser().parse_args(["--max-attempts-per-player", "35"])

    def test_partial_summary_requires_retry(self):
        self.assertTrue(br.summary_needs_retry({"valid_games": 17, "invalid_games": 19}, 36))
        self.assertFalse(br.summary_needs_retry({"valid_games": 36, "invalid_games": 0}, 36))
        self.assertFalse(br.summary_needs_retry({
            "valid_games": 35,
            "invalid_games": 1,
            "attempt_limit_reached": True,
        }, 36))

    def test_retry_stop_state_marks_attempt_limit(self):
        self.assertEqual(br.retry_stop_state(36, 36, 36, 100), (True, False))
        self.assertEqual(br.retry_stop_state(35, 36, 99, 100), (False, False))
        self.assertEqual(br.retry_stop_state(35, 36, 100, 100), (True, True))

    def test_attempt_state_recovers_physical_attempt_count(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            paths = [
                run_dir / "games/model-a/P1/trial-01/game.json",
                run_dir / "games/model-a/P1/trial-01-retry-old/game.json",
                run_dir / "retry-archives/pass-1/games/model-a/P2/trial-02/game.json",
            ]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            state = br.load_attempt_state(run_dir, "model-a", 100)

            self.assertEqual(state["attempts_started"], 3)

    def test_player_matrix_preserves_requested_order(self):
        self.assertEqual(
            [p["slug"] for p in br.PLAYER_MATRIX],
            ["luna-max", "luna-high", "minimax-m3-max", "deepseek-v4-flash-max", "deepseek-provider-v4-flash-max", "deepseek-deepseek-v4-1-flash-max", "kong-ai-gateway-zai-org-glm-5-3-high", "commandcode-deepseek-v4-1-flash-beta-high", "claude-sonnet-5-high", "gpt-5-6-sol-high", "gpt-5-6-sol-medium", "gpt-6-astra-high", "grok-4-6-high"],
        )

    def test_minimax_uses_openrouter_free_route(self):
        minimax = next(p for p in br.PLAYER_MATRIX if p["slug"] == "minimax-m3-max")
        self.assertEqual(minimax["provider"], "openrouter")
        self.assertEqual(minimax["model"], "minimax/minimax-m3:free")
        self.assertEqual(minimax["reasoning_effort"], "max")

    def test_deepseek_uses_commandcode_model_id(self):
        deepseek = next(p for p in br.PLAYER_MATRIX if p["slug"] == "deepseek-v4-flash-max")
        self.assertEqual(deepseek["provider"], "commandcode")
        self.assertEqual(deepseek["model"], "deepseek-ai/deepseek-v4-flash")

    def test_deepseek_provider_uses_official_v4_flash_max(self):
        deepseek = next(p for p in br.PLAYER_MATRIX if p["slug"] == "deepseek-provider-v4-flash-max")
        self.assertEqual(deepseek["provider"], "deepseek")
        self.assertEqual(deepseek["model"], "deepseek-v4-flash")
        self.assertEqual(deepseek["reasoning_effort"], "max")

    def test_deepseek_v4_1_uses_expiring_model_route(self):
        deepseek = next(p for p in br.PLAYER_MATRIX if p["slug"] == "deepseek-deepseek-v4-1-flash-max")
        self.assertEqual(deepseek["provider"], "deepseek")
        self.assertEqual(deepseek["model"], "deepseek-v4.1-flash-expires-on-0910")
        self.assertEqual(deepseek["reasoning_effort"], "max")

    def test_glm_5_3_uses_kong_route(self):
        glm = next(p for p in br.PLAYER_MATRIX if p["slug"] == "kong-ai-gateway-zai-org-glm-5-3-high")
        self.assertEqual(glm["provider"], "kong-ai-gateway")
        self.assertEqual(glm["model"], "zai-org/GLM-5.3")
        self.assertEqual(glm["reasoning_effort"], "high")

    def test_deepseek_v4_1_flash_beta_uses_commandcode_route(self):
        deepseek = next(p for p in br.PLAYER_MATRIX if p["slug"] == "commandcode-deepseek-v4-1-flash-beta-high")
        self.assertEqual(deepseek["provider"], "commandcode")
        self.assertEqual(deepseek["model"], "deepseek/deepseek-v4.1-flash-beta")
        self.assertEqual(deepseek["reasoning_effort"], "high")

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

    def test_gpt_sol_uses_openai_codex_medium(self):
        sol = next(p for p in br.PLAYER_MATRIX if p["slug"] == "gpt-5-6-sol-medium")
        self.assertEqual(sol["provider"], "openai-codex")
        self.assertEqual(sol["model"], "gpt-5.6-sol")
        self.assertEqual(sol["reasoning_effort"], "medium")

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

    def test_api_client_creates_turtle_soup_session_and_returns_usage_delta(self):
        calls: dict[str, Any] = {"session": None, "run": None}
        completed = False

        class Handler(http.server.BaseHTTPRequestHandler):
            def _json(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.assert_auth()
                if self.path == "/api/sessions/tb-session-1":
                    if calls["session"] is None:
                        self._json(404, {"error": "missing"})
                    else:
                        tokens = 19 if completed else 7
                        self._json(200, {"session": {
                            "provider": "provider-a", "model": "model-a",
                            "api_call_count": 2 if completed else 1,
                            "input_tokens": tokens, "output_tokens": 5 if completed else 2,
                            "cache_read_tokens": 3 if completed else 1,
                            "cache_write_tokens": 0, "reasoning_tokens": 4 if completed else 1,
                        }})
                elif self.path == "/api/sessions/tb-session-1/messages":
                    self._json(200, {"data": []})
                elif self.path == "/v1/toolsets":
                    self._json(200, {"data": [{"name": name} for name in ("terminal", "web", "file", "memory")]})
                elif self.path == "/v1/runs/run-1":
                    self._json(200, {"status": "completed", "output": "role completed"})
                else:
                    self._json(404, {"error": "unknown"})

            def do_POST(self):
                nonlocal completed
                self.assert_auth()
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size))
                if self.path == "/api/sessions":
                    calls["session"] = payload
                    self._json(201, {"session": payload})
                elif self.path == "/v1/runs":
                    calls["run"] = payload
                    completed = True
                    self._json(202, {"run_id": "run-1"})
                else:
                    self._json(404, {"error": "unknown"})

            def assert_auth(self):
                if self.headers.get("Authorization") != "Bearer secret":
                    raise AssertionError("missing bearer auth")

            def log_message(self, format, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = br.HermesApiClient(f"http://127.0.0.1:{server.server_port}", "secret", poll_interval=0.01)
            result = client.turn(
                session_id="tb-session-1", session_title="TurtleBench role",
                provider="provider-a", model="model-a", reasoning="high",
                prompt="run role", timeout_s=2,
            )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(calls["session"]["source"], "turtle-soup")
        self.assertEqual(calls["run"]["session_id"], "tb-session-1")
        self.assertEqual(calls["run"]["provider"], "provider-a")
        self.assertEqual(calls["run"]["model"], "model-a")
        self.assertEqual(calls["run"]["model_options"], {"reasoning_effort": "high"})
        self.assertEqual(calls["run"]["conversation_history"], [])
        self.assertTrue(calls["run"]["skip_context_files"])
        self.assertEqual(set(calls["run"]["disabled_toolsets"]), {"web", "file", "memory", "skills"})
        self.assertEqual(result.output, "role completed")
        self.assertEqual(result.run_id, "run-1")
        self.assertEqual(result.usage["session_id"], "tb-session-1")
        self.assertEqual(result.usage["api_call_count"], 1)
        self.assertEqual(result.usage["input_tokens"], 12)
        self.assertEqual(result.usage["reasoning_tokens"], 3)

    def test_api_client_retries_transient_poll_timeout(self):
        state = {"session_exists": False, "polls": 0}
        client = br.HermesApiClient("http://api", "secret", poll_interval=0.001)

        def request(method, path, payload=None, expected=(200,)):
            if path == "api/sessions/tb-session-timeout":
                if not state["session_exists"]:
                    raise br.HermesApiError(404, "missing")
                calls = 2 if state["polls"] else 1
                return {"session": {
                    "provider": "provider-a", "model": "model-a",
                    "api_call_count": calls, "input_tokens": 20 * calls,
                    "output_tokens": 5 * calls, "cache_read_tokens": 3 * calls,
                    "cache_write_tokens": 0, "reasoning_tokens": 2 * calls,
                }}
            if path == "api/sessions":
                state["session_exists"] = True
                return {}
            if path == "api/sessions/tb-session-timeout/messages":
                return {"data": []}
            if path == "v1/toolsets":
                return {"data": [{"name": name} for name in ("terminal", "file")]}
            if path == "v1/runs":
                return {"run_id": "run-timeout"}
            if path == "v1/runs/run-timeout":
                state["polls"] += 1
                if state["polls"] == 1:
                    raise TimeoutError("transient socket timeout")
                return {"status": "completed", "output": "role completed"}
            raise AssertionError(f"unexpected request: {method} {path}")

        with mock.patch.object(client, "_request", side_effect=request):
            result = client.turn(
                session_id="tb-session-timeout", session_title="TurtleBench role",
                provider="provider-a", model="model-a", reasoning="high",
                prompt="run role", timeout_s=2,
            )

        self.assertEqual(result.output, "role completed")
        self.assertEqual(state["polls"], 2)

    def test_api_sessions_keep_turtle_soup_source(self):
        self.assertEqual(br.SESSION_SOURCE, "turtle-soup")

    def test_role_prompts_avoid_reserved_evaluation_terms(self):
        prompts = [
            br.host_prompt(Path("puzzle.json"), Path("game.json"), "g1"),
            br.player_prompt(Path("game.json"), "g1"),
            br.judge_prompt(Path("puzzle.json"), [Path("t1"), Path("t2"), Path("t3")], Path("judge.json"), {"display_name": "model", "provider": "provider", "model": "model", "reasoning_effort": "high"}),
        ]
        for prompt in prompts:
            for term in ("benchmark", "评测", "跑分", "测试"):
                self.assertNotIn(term, prompt)

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

    def test_finalize_preserves_existing_valid_score(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            player = {"slug": "model-a", "provider": "provider", "model": "model", "reasoning_effort": "high"}
            puzzle = {"id": "P1", "path": "P1.json", "difficulty": "简单"}
            root = run_dir / "games" / player["slug"] / puzzle["id"]
            raw = {"rounds": 1, "hints_used": 0, "player_latency_p50_s": 1, "player_latency_p90_s": 1, "player_active_time_s": 1}
            pre = {"player": player, "status": "solved", "raw": raw, "process_exit": {"host": 0, "player": 0}}
            for trial in (1, 2, 3):
                td_trial = root / f"trial-{trial:02d}"
                td_trial.mkdir(parents=True)
                (td_trial / "preliminary.json").write_text(json.dumps(pre), encoding="utf-8")
            existing = {"puzzle_id": "P1", "trial": 1, "validity": "valid", "status": "solved", "sentinel": "preserve-me"}
            (root / "trial-01" / "score.json").write_text(json.dumps(existing), encoding="utf-8")
            judge_item = {"trial": trial, "validity": "valid", "atomic_question_rate": 1, "useful_constraint_rate": 1,
                          "redundant_question_rate": 0, "unsupported_story_guess_rate": 0, "irrelevant_branch_max": 0,
                          "contradiction_count": 0, "partial_misread_count": 0, "excluded_revisit_count": 0,
                          "protocol_recovery_failure_count": 0, "reasoning_chain_parts": {"a": 1},
                          "question_information_parts": {"a": 1}, "final_closure": 5, "hint_effective_count": 0,
                          "hint_ineffective_count": 0, "hint_early_count": 0, "hint_consecutive": False,
                          "hint_hoarding": False, "failure_tags": [], "notes": []}
            (root / "judge.json").write_text(json.dumps([judge_item | {"trial": trial} for trial in (1, 2, 3)]), encoding="utf-8")

            scores = br.finalize_scores(run_dir, player, {"puzzles": [puzzle]})

            self.assertEqual(next(s for s in scores if s["trial"] == 1), existing)

    def test_judge_output_requires_complete_scoring_fields(self):
        fields = {
            "trial": 1, "validity": "valid", "atomic_question_rate": 1,
            "useful_constraint_rate": 1, "redundant_question_rate": 0,
            "unsupported_story_guess_rate": 0, "irrelevant_branch_max": 0,
            "contradiction_count": 0, "partial_misread_count": 0,
            "excluded_revisit_count": 0, "protocol_recovery_failure_count": 0,
            "reasoning_chain_parts": {}, "question_information_parts": {},
            "final_closure": 5, "hint_effective_count": 0,
            "hint_ineffective_count": 0, "hint_early_count": 0,
            "hint_consecutive": False, "hint_hoarding": False,
            "failure_tags": [], "notes": [],
        }
        complete = [fields | {"trial": trial} for trial in (1, 2, 3)]

        self.assertTrue(br.is_valid_judge_output(complete))
        incomplete = [dict(item) for item in complete]
        incomplete[2].pop("reasoning_chain_parts")
        self.assertFalse(br.is_valid_judge_output(incomplete))

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
            judge = invalid.parent / "judge.json"
            judge.write_text("[]", encoding="utf-8")
            summary = run_dir / "summaries" / f"{player}.json"
            summary.parent.mkdir(parents=True)
            summary.write_text("{}", encoding="utf-8")
            archive = run_dir / "reruns-invalid" / "pass-1"

            counts = br.archive_invalid_trials(run_dir, [player], archive)

            self.assertEqual(counts, {player: 1})
            self.assertTrue(valid.exists())
            self.assertFalse(invalid.exists())
            self.assertTrue((archive / "games" / player / "SPB-C-E-01" / "trial-02" / "score.json").exists())
            self.assertFalse(judge.exists())
            self.assertTrue((archive / "games" / player / "SPB-C-E-01" / "judge.json").exists())
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
    async def test_api_role_writes_session_metadata_without_cli_process(self):
        calls: dict[str, Any] = {"session": None, "run": None}

        class Handler(http.server.BaseHTTPRequestHandler):
            def _json(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/api/sessions/") and self.path.endswith("/messages"):
                    self._json(200, {"data": []})
                elif self.path.startswith("/api/sessions/"):
                    if calls["session"] is None:
                        self._json(404, {"error": "missing"})
                    else:
                        self._json(200, {"session": {"provider": "p", "model": "m", "api_call_count": 1}})
                elif self.path == "/v1/toolsets":
                    self._json(200, {"data": [{"name": "terminal"}]})
                elif self.path.startswith("/v1/runs/"):
                    self._json(200, {"status": "completed", "output": "done"})
                else:
                    self._json(404, {})

            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size))
                if self.path == "/api/sessions":
                    calls["session"] = payload
                    self._json(201, {"session": payload})
                elif self.path == "/v1/runs":
                    calls["run"] = payload
                    self._json(202, {"run_id": "run-role"})
                else:
                    self._json(404, {})

            def log_message(self, format, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                log = Path(td) / "role.log"
                client = br.HermesApiClient(f"http://127.0.0.1:{server.server_port}", "", poll_interval=0.01)
                rc, usage = await br.run_api_role(
                    client, "tb-role-1", "role title", "p", "m", "high", "prompt", log, 2,
                )
                text = log.read_text(encoding="utf-8")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(rc, 0)
        self.assertEqual(usage["session_id"], "tb-role-1")
        self.assertIn("session_id: tb-role-1", text)
        self.assertIn("run_id: run-role", text)
        self.assertIn("done", text)

    async def test_run_game_uses_api_sessions_for_both_roles(self):
        sessions = {}
        runs = {}
        lock = threading.Lock()

        class Handler(http.server.BaseHTTPRequestHandler):
            def _json(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/v1/toolsets":
                    self._json(200, {"data": [{"name": "terminal"}, {"name": "web"}]})
                    return
                if self.path.startswith("/api/sessions/"):
                    parts = self.path.split("/")
                    session_id = parts[3]
                    if session_id not in sessions:
                        self._json(404, {"error": "missing"})
                    elif self.path.endswith("/messages"):
                        self._json(200, {"data": []})
                    else:
                        self._json(200, {"session": {
                            "provider": sessions[session_id].get("provider", ""),
                            "model": sessions[session_id]["model"],
                            "api_call_count": int(sessions[session_id].get("done", False)),
                            "input_tokens": 10 if sessions[session_id].get("done") else 0,
                            "output_tokens": 2 if sessions[session_id].get("done") else 0,
                        }})
                    return
                if self.path.startswith("/v1/runs/"):
                    run_id = self.path.rsplit("/", 1)[-1]
                    self._json(200, {"status": "completed", "output": f"completed {run_id}"})
                    return
                self._json(404, {})

            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size))
                if self.path == "/api/sessions":
                    sessions[payload["id"]] = dict(payload)
                    self._json(201, {"session": payload})
                    return
                if self.path == "/v1/runs":
                    with lock:
                        run_id = f"run-{len(runs) + 1}"
                        runs[run_id] = payload
                        sessions[payload["session_id"]]["provider"] = payload["provider"]
                        sessions[payload["session_id"]]["done"] = True
                    self._json(202, {"run_id": run_id})
                    return
                self._json(404, {})

            def log_message(self, format, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        old_runtime = br.RUNTIME
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                fixtures = root / "fixtures"
                fixtures.mkdir()
                (fixtures / "puzzle.json").write_text("{}", encoding="utf-8")
                br.RUNTIME = br.RuntimePaths(fixtures, root / "runs", root / "state.db")
                client = br.HermesApiClient(f"http://127.0.0.1:{server.server_port}", "", poll_interval=0.01)
                player = {"slug": "model-a", "provider": "player-provider", "model": "player-model", "reasoning_effort": "high"}
                puzzle = {"id": "P1", "path": "puzzle.json"}

                score_path = await br.run_game(root / "run", player, puzzle, 1, 5, api_client=client)

                trial = score_path.parent
                preliminary = json.loads((trial / "preliminary.json").read_text(encoding="utf-8"))
                role_sessions = json.loads((trial / "sessions.json").read_text(encoding="utf-8"))
        finally:
            br.RUNTIME = old_runtime
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(len(sessions), 2)
        self.assertEqual({item["source"] for item in sessions.values()}, {"turtle-soup"})
        self.assertEqual({payload["provider"] for payload in runs.values()}, {br.HOST["provider"], "player-provider"})
        self.assertIn(role_sessions["host"], sessions)
        self.assertIn(role_sessions["player"], sessions)
        self.assertEqual(preliminary["process_exit"], {"host": 0, "player": 0})
        self.assertEqual(preliminary["raw"]["player_usage"]["session_id"], role_sessions["player"])

    async def test_run_player_requeues_only_invalid_slots(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            player = {
                "slug": "model-a",
                "provider": "test",
                "model": "model-a",
                "reasoning_effort": "max",
            }
            manifest = {"puzzles": [{"id": "P1", "path": "puzzles/P1.json"}]}
            game_calls = []
            finalize_calls = 0

            async def fake_run_game(run_dir, player, puzzle, trial, timeout_s):
                game_calls.append((puzzle["id"], trial))
                trial_dir = run_dir / "games" / player["slug"] / puzzle["id"] / f"trial-{trial:02d}"
                trial_dir.mkdir(parents=True, exist_ok=True)
                (trial_dir / "game.json").write_text(json.dumps({"status": "solved"}), encoding="utf-8")
                (trial_dir / "preliminary.json").write_text("{}", encoding="utf-8")

            async def fake_run_judge(run_dir, player, puzzle, timeout_s):
                output = run_dir / "games" / player["slug"] / puzzle["id"] / "judge.json"
                output.write_text("[]", encoding="utf-8")
                return output

            def fake_finalize(run_dir, player, manifest):
                nonlocal finalize_calls
                finalize_calls += 1
                scores = []
                for trial in (1, 2, 3):
                    validity = "invalid_host" if finalize_calls == 1 and trial == 1 else "valid"
                    score = {"puzzle_id": "P1", "trial": trial, "validity": validity, "status": "solved"}
                    path = run_dir / "games" / player["slug"] / "P1" / f"trial-{trial:02d}" / "score.json"
                    path.write_text(json.dumps(score), encoding="utf-8")
                    scores.append(score)
                return scores

            def fake_aggregate(scores):
                valid = sum(score["validity"] == "valid" for score in scores)
                return {"valid_games": valid, "invalid_games": len(scores) - valid}

            with (
                mock.patch.object(br, "run_game", side_effect=fake_run_game),
                mock.patch.object(br, "run_judge", side_effect=fake_run_judge),
                mock.patch.object(br, "finalize_scores", side_effect=fake_finalize),
                mock.patch.object(br, "aggregate_scores", side_effect=fake_aggregate),
            ):
                summary = await br.run_player(run_dir, player, manifest, 3, 3, 10, max_attempts=4)

            self.assertEqual(game_calls, [("P1", 1), ("P1", 2), ("P1", 3), ("P1", 1)])
            self.assertEqual(summary["valid_games"], 3)
            self.assertEqual(summary["attempts_started"], 4)
            self.assertFalse(summary["attempt_limit_reached"])

    async def test_judge_retries_when_api_run_claims_success_without_output_file(self):
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
            calls = []

            async def fake_run_api_role(client, session_id, session_title, provider, model, reasoning, prompt, log_path, timeout_s):
                calls.append(session_id)
                if len(calls) == 2:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    fields = {
                        "validity": "valid", "atomic_question_rate": 1, "useful_constraint_rate": 1,
                        "redundant_question_rate": 0, "unsupported_story_guess_rate": 0, "irrelevant_branch_max": 0,
                        "contradiction_count": 0, "partial_misread_count": 0, "excluded_revisit_count": 0,
                        "protocol_recovery_failure_count": 0, "reasoning_chain_parts": {},
                        "question_information_parts": {}, "final_closure": 5, "hint_effective_count": 0,
                        "hint_ineffective_count": 0, "hint_early_count": 0, "hint_consecutive": False,
                        "hint_hoarding": False, "failure_tags": [], "notes": [],
                    }
                    output.write_text(json.dumps([fields | {"trial": i} for i in (1, 2, 3)]), encoding="utf-8")
                return 0, {"session_id": session_id}

            with mock.patch.object(br, "run_api_role", side_effect=fake_run_api_role):
                result = await br.run_judge(run_dir, player, puzzle, 10, api_client=mock.Mock())

            self.assertEqual(result, output)
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0], calls[1])
            sessions = json.loads((output.parent / "judge-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(sessions["source"], "turtle-soup")
            self.assertEqual(sessions["attempts"], calls)


if __name__ == "__main__":
    unittest.main()
