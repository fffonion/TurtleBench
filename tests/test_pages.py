import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from turtlebench import pages

ROOT = Path(__file__).resolve().parents[1]


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
        self.assertEqual(model["name"], "OpenAI Codex / GPT-5.6 Luna")
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

        self.assertEqual(result["models"][0]["behavior"]["hints_median"], 1.0)

    def test_compression_time_is_removed_from_public_active_time(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = self.make_run(root)
            summary_path = run / "summaries" / "luna-max.json"
            summary = json.loads(summary_path.read_text())
            summary["player_resources"]["player_active_time_s"] = 142
            summary_path.write_text(json.dumps(summary))

            score_path = run / "games" / "luna-max" / "PUZZLE" / "trial-01" / "score.json"
            score = json.loads(score_path.read_text())
            score["raw"]["player_usage"] = {"session_id": "session-one"}
            score_path.write_text(json.dumps(score))
            (score_path.parent / "player.log").write_text("compacting context…\n")

            db_path = root / "state.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, timestamp REAL)"
            )
            connection.executemany(
                "INSERT INTO messages(id, session_id, timestamp) VALUES (?, ?, ?)",
                [
                    (1, "session-one", 0.0),
                    (2, "session-one", 10.0),
                    (3, "session-one", 100.0),
                    (4, "session-one", 100.000001),
                    (5, "session-one", 100.000002),
                    (6, "session-one", 110.0),
                ],
            )
            connection.commit()
            connection.close()

            result = pages.build_public_run(run, pricing={}, state_db=db_path)

        model = result["models"][0]
        self.assertEqual(model["compression_time_s"], 90.0)
        self.assertEqual(model["active_time_s"], 52.0)

    def test_session_compression_time_sums_multiple_compactions(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "state.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, timestamp REAL)"
            )
            connection.executemany(
                "INSERT INTO messages(id, session_id, timestamp) VALUES (?, ?, ?)",
                [
                    (1, "s", 0.0), (2, "s", 10.0),
                    (3, "s", 40.0), (4, "s", 40.000001), (5, "s", 40.000002),
                    (6, "s", 50.0),
                    (7, "s", 70.0), (8, "s", 70.000001), (9, "s", 70.000002),
                ],
            )
            connection.commit()
            connection.close()

            self.assertEqual(pages.session_compression_time(db_path, "s"), 50.0)

    def test_build_public_run_calculates_price_from_snapshot(self):
        snapshot = {
            "source": "https://models.dev",
            "source_model_id": "openai/gpt-5.6-luna",
            "source_provider_id": "openai",
            "fetched_at": "2026-09-05T00:00:00Z",
            "usd_per_million_tokens": {
                "input": 1,
                "output": 10,
                "cache_read": 0.1,
                "cache_write": 2,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            run = self.make_run(Path(tmp))
            result = pages.build_public_run(run, pricing={"luna-max": snapshot})

        model = result["models"][0]
        self.assertEqual(model["pricing"], snapshot)
        self.assertEqual(model["price_usd"]["total"], 0.00034)


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.mapping = {
            "openai-codex:gpt-5.6-luna": {
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "canonical_model": "openai/gpt-5.6-luna",
            },
            "commandcode:deepseek-ai/deepseek-v4-flash": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "canonical_model": "deepseek/deepseek-v4-flash",
            },
        }

    def test_resolves_mapping_and_prefers_off_peak_rates(self):
        catalog = {
            "openai": {
                "models": {
                    "gpt-5.6-luna": {
                        "cost": {
                            "input": 1,
                            "output": 6,
                            "cache_read": 0.1,
                            "off_peak": {
                                "input": 0.5,
                                "output": 3,
                                "cache_read": 0.05,
                            },
                            "peak": {"input": 2, "output": 12},
                        }
                    }
                }
            }
        }

        price = pages.resolve_pricing(
            "openai-codex",
            "gpt-5.6-luna",
            self.mapping,
            catalog,
            "2026-09-05T00:00:00Z",
        )

        self.assertEqual(price["source_provider_id"], "openai")
        self.assertEqual(price["source_model_id"], "openai/gpt-5.6-luna")
        self.assertEqual(
            price["usd_per_million_tokens"],
            {"input": 0.5, "output": 3.0, "cache_read": 0.05, "cache_write": None},
        )

    def test_commandcode_maps_to_deepseek_price(self):
        catalog = {
            "deepseek": {
                "models": {
                    "deepseek-v4-flash": {
                        "cost": {"input": 0.14, "output": 0.28, "cache_read": 0.014}
                    }
                }
            }
        }

        price = pages.resolve_pricing(
            "commandcode",
            "deepseek-ai/deepseek-v4-flash",
            self.mapping,
            catalog,
            "2026-09-05T00:00:00Z",
        )

        self.assertEqual(price["source_provider_id"], "deepseek")

    def test_rejects_promotional_or_free_plan_prices(self):
        for provider, cost in (
            ("openai-token-plan", {"input": 1, "output": 2}),
            ("openai", {"input": 0, "output": 0}),
            ("openai", {"input": 1, "output": 2, "promotion": {"ends": "soon"}}),
        ):
            mapping = {
                "bench:model": {
                    "provider": provider,
                    "model": "model",
                    "canonical_model": "lab/model",
                }
            }
            catalog = {provider: {"models": {"model": {"cost": cost}}}}
            with self.subTest(provider=provider, cost=cost):
                with self.assertRaises(ValueError):
                    pages.resolve_pricing(
                        "bench", "model", mapping, catalog, "2026-09-05T00:00:00Z"
                    )

    def test_calculates_category_prices_and_handles_missing_rates(self):
        tokens = {"total": 425, "input": 100, "output": 20, "cache_read": 300, "cache_write": 5}
        pricing = {
            "usd_per_million_tokens": {
                "input": 1,
                "output": 10,
                "cache_read": 0.1,
                "cache_write": None,
            }
        }

        value = pages.calculate_price(tokens, pricing)

        self.assertEqual(value["input"], 0.0001)
        self.assertEqual(value["output"], 0.0002)
        self.assertEqual(value["cache_read"], 0.00003)
        self.assertIsNone(value["cache_write"])
        self.assertIsNone(value["total"])

        tokens["cache_write"] = 0
        value = pages.calculate_price(tokens, pricing)
        self.assertEqual(value["cache_write"], 0.0)
        self.assertEqual(value["total"], 0.00033)

    def test_repository_mapping_covers_benchmark_models(self):
        mapping = pages.load_mapping(ROOT / "pricing" / "models-dev-mapping.json")
        expected = {
            "openai-codex:gpt-5.6-luna",
            "minimax-cn:minimax-m3",
            "commandcode:deepseek-ai/deepseek-v4-flash",
            "deepseek:deepseek-v4-flash",
            "anthropic:claude-sonnet-5",
            "openai-codex:gpt-5.6-sol",
            "xai-oauth:grok-4.6",
            "openai-codex:gpt-6-astra",
        }
        self.assertTrue(expected.issubset(mapping))


class SiteBuildTests(unittest.TestCase):
    def public_run(self, run_id: str) -> dict:
        return {
            "run_id": run_id,
            "title": run_id,
            "suite_version": "fixed-v1",
            "puzzle_count": 12,
            "repeats": 3,
            "published_at": "2026-09-05T00:00:00Z",
            "models": [],
        }

    def test_write_site_preserves_history_and_selects_latest_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "site"
            pages.write_site(output, self.public_run("run-one"), ROOT / "web")
            pages.write_site(output, self.public_run("run-two"), ROOT / "web")

            index = json.loads((output / "data" / "index.json").read_text())

            self.assertEqual(index["default_run"], "run-two")
            self.assertEqual([run["id"] for run in index["runs"]], ["run-two", "run-one"])
            self.assertEqual(index["runs"][0]["file"], "data/runs/run-two.json")
            self.assertTrue((output / "index.html").exists())
            self.assertTrue((output / "assets" / "app.js").exists())
            self.assertTrue((output / ".nojekyll").exists())
            self.assertTrue((output / "data" / "runs" / "run-one.json").exists())

    def test_write_site_replaces_matching_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "site"
            first = self.public_run("same-run")
            pages.write_site(output, first, ROOT / "web")
            second = self.public_run("same-run")
            second["models"] = [{"slug": "updated"}]
            pages.write_site(output, second, ROOT / "web")

            stored = json.loads((output / "data" / "runs" / "same-run.json").read_text())
            index = json.loads((output / "data" / "index.json").read_text())

        self.assertEqual(stored["models"], [{"slug": "updated"}])
        self.assertEqual(len(index["runs"]), 1)

    def test_public_safety_rejects_private_fields_and_paths(self):
        for unsafe in (
            {"session_id": "abc"},
            {"surface": "secret prompt"},
            {"value": "/home/wow/private"},
            {"api_key": "hidden"},
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    pages.assert_public_safe(unsafe)

    def test_prepare_public_run_adds_metadata_and_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = PublicResultTests().make_run(Path(tmp))
            (run / "summary.json").write_text(
                json.dumps(
                    {
                        "run": {
                            "status": "completed",
                            "suite_version": "fixed-v1",
                            "repeats": 3,
                            "started_at": "2026-09-03T08:17:19Z",
                        }
                    }
                ),
                encoding="utf-8",
            )
            mapping = {
                "openai-codex:gpt-5.6-luna": {
                    "provider": "openai",
                    "model": "gpt-5.6-luna",
                    "canonical_model": "openai/gpt-5.6-luna",
                }
            }
            catalog = {
                "openai": {
                    "models": {
                        "gpt-5.6-luna": {
                            "cost": {
                                "input": 1,
                                "output": 10,
                                "cache_read": 0.1,
                                "cache_write": 2,
                            }
                        }
                    }
                }
            }

            result = pages.prepare_public_run(
                run, mapping, catalog, "2026-09-05T00:00:00Z"
            )

        self.assertEqual(result["suite_version"], "fixed-v1")
        self.assertEqual(result["repeats"], 3)
        self.assertEqual(result["puzzle_count"], 1)
        self.assertEqual(result["published_at"], "2026-09-05T00:00:00Z")
        self.assertEqual(result["models"][0]["price_usd"]["total"], 0.00034)

    def test_prepare_public_run_rejects_incomplete_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = PublicResultTests().make_run(Path(tmp))
            (run / "summary.json").write_text(
                json.dumps({"run": {"status": "running"}}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                pages.prepare_public_run(run, {}, {}, "2026-09-05T00:00:00Z")

    def test_page_cli_has_build_and_publish_commands(self):
        parser = pages.build_parser()
        build = parser.parse_args(["build", "--run-dir", "/tmp/run", "--output", "/tmp/site"])
        publish = parser.parse_args(["publish", "--run-dir", "/tmp/run"])

        self.assertEqual(build.command, "build")
        self.assertEqual(build.output, "/tmp/site")
        self.assertEqual(publish.command, "publish")
        self.assertEqual(publish.branch, "gh-pages")


if __name__ == "__main__":
    unittest.main()
