import asyncio
import io
import tempfile
from pathlib import Path
import unittest
import urllib.error
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from email.message import Message
from unittest import mock

from turtlebench import benchmark_runner as br


class RetryAfterTests(unittest.TestCase):
    def test_retry_after_is_not_truncated_by_local_backoff_cap(self):
        client = br.HermesApiClient("http://example.invalid", "")
        error = br.HermesApiError(429, "rate limited", retry_after=120)

        self.assertEqual(client._retry_delay(0, error), 120)


    def test_http_date_retry_after_is_preserved_as_a_server_deadline(self):
        client = br.HermesApiClient("http://example.invalid", "")
        headers = Message()
        headers["Retry-After"] = "Thu, 01 Jan 1970 00:02:00 GMT"
        response = urllib.error.HTTPError(
            "http://example.invalid/v1/models", 429, "rate limited", headers,
            io.BytesIO(b'{"error":{"message":"Rate limit exceeded"}}'),
        )
        caught = None
        with mock.patch.object(br.urllib.request, "urlopen", side_effect=response), mock.patch.object(
            br.time, "time", return_value=0,
        ):
            try:
                client._request("GET", "v1/models")
            except Exception as error:
                caught = error

        self.assertIsInstance(caught, br.HermesApiError)
        self.assertEqual(caught.retry_after, 120)

    def test_request_waits_full_retry_after_without_using_the_active_timeout(self):
        client = br.HermesApiClient("http://example.invalid", "", retry_attempts=1)
        clock = {"now": 100.0}
        calls = []
        sleeps = []

        def request(*args, **kwargs):
            calls.append(clock["now"])
            if len(calls) == 1:
                raise br.HermesApiError(429, "rate limited", retry_after=120)
            return {"ok": True}

        def sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        caught = None
        result = None
        with mock.patch.object(client, "_request", side_effect=request), mock.patch.object(
            br.time, "monotonic", side_effect=lambda: clock["now"],
        ), mock.patch.object(br.time, "sleep", side_effect=sleep):
            try:
                result = client._request_with_retry("GET", "v1/models", deadline=105)
            except Exception as error:
                caught = error

        self.assertIsNone(caught)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls, [100, 220])
        self.assertEqual(sleeps, [120])
        self.assertEqual(client._quota_wait_seconds_total, 120)

    def test_quota_429_without_retry_after_does_not_guess_a_delay(self):
        client = br.HermesApiClient("http://example.invalid", "", retry_attempts=3)
        error = br.HermesApiError(429, "Token plan limit reached")
        with mock.patch.object(client, "_request", side_effect=error) as request, mock.patch.object(
            br.time, "sleep",
        ) as sleep:
            with self.assertRaises(br.HermesApiError):
                client._request_with_retry("GET", "v1/models")

        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    def test_run_request_leaves_provider_retry_after_to_existing_gateway_logic(self):
        client = br.HermesApiClient("http://example.invalid", "", poll_interval=0)
        posted = []

        def request(method, path, payload=None, expected=(200,)):
            if path.endswith("/messages"):
                return {"data": []}
            if path.startswith("api/sessions/"):
                return {"session": {"provider": "provider-a", "model": "model-a"}}
            if path == "v1/toolsets":
                return {"data": [{"name": "terminal"}]}
            if path == "v1/runs":
                posted.append(payload)
                return {"run_id": "run-provider-wait"}
            if path == "v1/runs/run-provider-wait":
                return {"status": "completed", "output": "role complete"}
            raise AssertionError((method, path))

        with mock.patch.object(client, "_request", side_effect=request):
            client.turn(
                session_id="test-player", session_title="test role", provider="provider-a",
                model="model-a", reasoning="max", prompt="role instructions", timeout_s=10,
            )

        self.assertIs(posted[0]["fail_fast_on_nonretryable_429"], False)


    def test_real_http_429_waits_until_retry_after_before_resubmitting(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(time.monotonic())
                if len(received) == 1:
                    self.send_response(429)
                    self.send_header("Retry-After", "1")
                    body = b'{"error":{"message":"Rate limit exceeded","type":"rate_limit_error"}}'
                else:
                    self.send_response(200)
                    body = b'{"data":[]}'
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = br.HermesApiClient(
                "http://127.0.0.1:" + str(server.server_port), "", retry_attempts=1,
                retry_base_seconds=0.001, retry_max_seconds=0.01,
            )
            result = client._request_with_retry("GET", "v1/models")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertEqual(result, {"data": []})
        self.assertEqual(len(received), 2)
        self.assertGreaterEqual(received[1] - received[0], 1)


    def test_unusable_retry_after_does_not_create_an_immediate_retry_loop(self):
        with mock.patch.object(br.time, "time", return_value=120):
            for value in ("0", "-1", "Thu, 01 Jan 1970 00:00:00 GMT", "nan", "inf", "invalid"):
                with self.subTest(value=value):
                    self.assertIsNone(br.retry_after_seconds(value))


class RateLimitRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_quota_failure_without_retry_after_propagates_out_of_the_role(self):
        client = br.HermesApiClient("http://example.invalid", "")
        error = br.HermesApiError(429, "Token plan limit reached")
        caught = None
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "player.log"
            with mock.patch.object(client, "turn", side_effect=error):
                try:
                    await br.run_api_role(
                        client, "test-player", "test role", "provider-a", "model-a",
                        "max", "role instructions", log, 10,
                    )
                except Exception as failure:
                    caught = failure
            logged = log.read_text()

        self.assertIs(caught, error)
        self.assertIn("retryable: false", logged)


    async def test_game_closes_its_peer_before_propagating_a_quota_pause(self):
        client = br.HermesApiClient("http://example.invalid", "")
        error = br.HermesApiError(429, "Token plan limit reached")
        player = {"slug": "player-a", "provider": "provider-a", "model": "model-a", "reasoning_effort": "max"}
        puzzle = {"id": "SPB-C-E-01", "path": "unused.json"}
        peers = []
        state = {"peer_finished": False}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game_path = root / "games/player-a/SPB-C-E-01/trial-01/game.json"

            async def role(_client, session_id, *args, **kwargs):
                if session_id.endswith("-player"):
                    raise error
                peers.append(asyncio.current_task())
                while br.load_json(game_path)["status"] != "error":
                    await asyncio.sleep(0)
                state["peer_finished"] = True
                return 0, {}

            caught = None
            with mock.patch.object(br, "run_api_role", side_effect=role), mock.patch.object(
                br, "host_prompt", return_value="host instructions",
            ), mock.patch.object(br, "player_prompt", return_value="player instructions"):
                try:
                    await asyncio.wait_for(br.run_game(root, player, puzzle, 1, 10, client), 1)
                except Exception as failure:
                    caught = failure
                game_status = br.load_json(game_path)["status"]
                finished = state["peer_finished"]
                for task in peers:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*peers, return_exceptions=True)

        self.assertIs(caught, error)
        self.assertEqual(game_status, "error")
        self.assertTrue(finished)

if __name__ == "__main__":
    unittest.main()
