import json
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


if __name__ == "__main__":
    unittest.main()
