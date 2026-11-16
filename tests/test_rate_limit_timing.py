import unittest
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

from turtlebench import benchmark_runner as br


class RateLimitTimingTests(unittest.TestCase):
    def test_player_429_wait_is_removed_from_latency_and_speed_metrics(self):
        game = {
            "status": "solved", "round": 2, "player_hints_used": 0,
            "events": [
                {"actor": "host", "type": "surface", "at": "2026-01-01T00:00:00+00:00"},
                {"actor": "player", "type": "question", "at": "2026-01-01T00:00:10+00:00"},
                {"actor": "host", "type": "response", "at": "2026-01-01T00:00:30+00:00"},
                {"actor": "player", "type": "question", "at": "2026-01-01T00:01:40+00:00"},
                {"actor": "host", "type": "answer", "at": "2026-01-01T00:02:00+00:00"},
            ],
            "rate_limit_waits": [
                {"actor": "player", "started_at": "2026-01-01T00:00:02+00:00", "ended_at": "2026-01-01T00:00:07+00:00"},
                {"actor": "player", "started_at": "2026-01-01T00:00:40+00:00", "ended_at": "2026-01-01T00:01:40+00:00"},
                {"actor": "host", "started_at": "2026-01-01T00:00:07+00:00", "ended_at": "2026-01-01T00:00:09+00:00"},
            ],
        }
        raw = br.compute_raw_metrics(game)

        self.assertEqual(raw["first_question_latency_s"], 5.0)
        self.assertEqual(raw["player_latency_p50_s"], 10.0)
        self.assertEqual(raw["player_latency_p90_s"], 10.0)
        self.assertEqual(raw["player_active_time_s"], 15.0)
        self.assertEqual(raw["player_rate_limit_wait_s"], 65)
        self.assertEqual(raw["total_wall_time_s"], 120)
        self.assertEqual(br.speed_score(raw), br.speed_score({"player_latency_p50_s": 10, "player_latency_p90_s": 10}))


    def test_wait_budget_is_isolated_between_role_threads(self):
        client = br.HermesApiClient("http://example.invalid", "")
        client._quota_wait_seconds_total = 7
        with ThreadPoolExecutor(max_workers=1) as pool:
            other_role_wait = pool.submit(lambda: client._quota_wait_seconds_total).result()

        self.assertEqual(other_role_wait, 0)
        self.assertEqual(client._quota_wait_seconds_total, 7)

    def test_turn_reports_actual_retry_wait_start_and_end(self):
        client = br.HermesApiClient("http://example.invalid", "", poll_interval=0, retry_attempts=1)
        clock = {"now": 0.0, "posts": 0}
        recorded = []

        def request(method, path, payload=None, expected=(200,)):
            if path.endswith("/messages"):
                return {"data": []}
            if path.startswith("api/sessions/"):
                return {"session": {"provider": "provider-a", "model": "model-a"}}
            if path == "v1/toolsets":
                return {"data": [{"name": "terminal"}]}
            if path == "v1/runs":
                clock["posts"] += 1
                if clock["posts"] == 1:
                    raise br.HermesApiError(429, "rate limited", retry_after=120)
                return {"run_id": "run-wait"}
            return {"status": "completed", "output": "role complete"}

        def sleep(seconds):
            clock["now"] += seconds

        fake_time = SimpleNamespace(time=lambda: clock["now"], monotonic=lambda: clock["now"], sleep=sleep)
        caught = None
        with mock.patch.object(client, "_request", side_effect=request), mock.patch.object(br, "time", fake_time):
            try:
                client.turn(
                    session_id="test-player", session_title="test role", provider="provider-a",
                    model="model-a", reasoning="max", prompt="role instructions", timeout_s=5,
                    on_rate_limit_wait=lambda event: recorded.append(dict(event)),
                )
            except Exception as error:
                caught = error

        self.assertIsNone(caught)
        self.assertEqual(len(recorded), 2)
        self.assertIsNone(recorded[0]["ended_at"])
        self.assertEqual(recorded[0]["started_at"], "1970-01-01T00:00:00+00:00")
        self.assertEqual(recorded[1]["ended_at"], "1970-01-01T00:02:00+00:00")
        self.assertEqual(recorded[1]["retry_after_s"], 120)
        self.assertEqual(client._quota_wait_seconds_total, 120)

    def test_mailbox_timeout_excludes_a_recorded_peer_quota_wait(self):
        clock = {"now": 0.0}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.json"
            br.game_mailbox.initialize(path, game_id="test-peer-wait")
            br.game_mailbox.append_event(path, "host", "surface", "public setup", 0)
            br.game_mailbox.record_rate_limit_wait(path, "player", {
                "started_at": "1970-01-01T00:00:00+00:00", "ended_at": None,
                "until": "1970-01-01T00:00:05+00:00", "retry_after_s": 5,
            })

            def sleep(seconds):
                clock["now"] += seconds
                if clock["now"] >= 5.5 and br.game_mailbox.snapshot(path)["revision"] == 1:
                    br.game_mailbox.append_event(path, "player", "question", "first question", 1)

            fake_time = SimpleNamespace(time=lambda: clock["now"], monotonic=lambda: clock["now"], sleep=sleep)
            caught = None
            result = None
            with mock.patch.object(br.game_mailbox, "time", fake_time):
                try:
                    result = br.game_mailbox.wait_for_update(path, "host", 1, timeout=1, poll_interval=0.25)
                except Exception as error:
                    caught = error

        self.assertIsNone(caught)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(clock["now"], 5.5)


class RateLimitRoleTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_persists_wait_updates_without_changing_mailbox_revision(self):
        client = br.HermesApiClient("http://example.invalid", "")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game_path = root / "game.json"
            br.game_mailbox.initialize(game_path, game_id="test-rate-limit")

            def turn(**kwargs):
                callback = kwargs["on_rate_limit_wait"]
                event = {
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "until": "2026-01-01T00:02:00+00:00", "ended_at": None,
                    "retry_after_s": 120,
                }
                callback(dict(event))
                event["ended_at"] = "2026-01-01T00:02:01+00:00"
                callback(dict(event))
                return br.HermesTurnResult("role complete", {}, "run-test")

            with mock.patch.object(client, "turn", side_effect=turn):
                rc, _ = await br.run_api_role(
                    client, "test-player", "test role", "provider-a", "model-a",
                    "max", "role instructions", root / "player.log", 10,
                )
            game = br.game_mailbox.snapshot(game_path)

        self.assertEqual(rc, 0)
        self.assertEqual(game["revision"], 0)
        self.assertEqual(len(game["rate_limit_waits"]), 1)
        self.assertEqual(game["rate_limit_waits"][0]["actor"], "player")
        self.assertEqual(game["rate_limit_waits"][0]["ended_at"], "2026-01-01T00:02:01+00:00")


if __name__ == "__main__":
    unittest.main()
