import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from turtlebench import benchmark_runner as br
from turtlebench import game_mailbox


PLAYER = {
    "slug": "resume-player", "provider": "resume-provider",
    "model": "resume-model", "reasoning_effort": "max",
}
PUZZLE = {"id": "SPB-C-H-01", "path": "puzzles/SPB-C-H-01.json"}


class GameResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_quota_interruption_preserves_the_current_game_and_role_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trial_dir = root / "games" / PLAYER["slug"] / PUZZLE["id"] / "trial-02"
            path = trial_dir / "game.json"
            game_mailbox.initialize(path, game_id="resume-game")
            game_mailbox.append_event(path, "host", "surface", "A public puzzle.")
            for index in range(47):
                game_mailbox.append_event(path, "player", "question", f"Question {index + 1}?")
                game_mailbox.append_event(path, "host", "response", "No.")
            before = game_mailbox.snapshot(path)
            sessions = {"source": "turtle-bench", "host": "resume-host", "player": "resume-player"}
            br.atomic_json(trial_dir / "sessions.json", sessions)

            class Client(br.HermesApiClient):
                def __init__(self):
                    super().__init__("http://unused.invalid", "")
                    self.role_sessions = []

                def turn(self, **kwargs):
                    self.role_sessions.append(kwargs["session_id"])
                    if kwargs["provider"] == PLAYER["provider"]:
                        raise br.HermesApiError(None, "HTTP 429: quota exhausted", retryable=True)
                    return br.HermesTurnResult("Host stopped.", {}, "host-run")

                def _session_usage(self, session_id, deadline=None):
                    return {
                        "session_id": session_id, "provider": PLAYER["provider"],
                        "model": PLAYER["model"], "api_call_count": 91,
                        "input_tokens": 2000, "output_tokens": 3000,
                        "cache_read_tokens": 40000, "cache_write_tokens": 0,
                        "reasoning_tokens": 0,
                    }

            client = Client()
            with self.assertRaises(br.HermesApiError):
                await br.run_game(root, PLAYER, PUZZLE, 2, 10, api_client=client)

            after = game_mailbox.snapshot(path)
            self.assertEqual(after["status"], "player_turn")
            self.assertEqual(after["round"], 47)
            self.assertEqual(after["events"], before["events"])
            self.assertEqual(br.load_json(trial_dir / "sessions.json"), sessions)
            self.assertEqual(set(client.role_sessions), {"resume-host", "resume-player"})
            self.assertIn("infrastructure_pause", after)
            self.assertFalse((trial_dir / "preliminary.json").exists())
            self.assertFalse((trial_dir / "score.json").exists())
            self.assertEqual(
                br.load_json(trial_dir / "player_totals.json")["player_usage"]["api_call_count"],
                91,
            )


    async def test_exhausted_transport_failures_pause_instead_of_finalizing_the_game(self):
        failures = (
            br.HermesApiError(503, "HTTP 503: service unavailable", retryable=True),
            TimeoutError("The provider timed out."),
            OSError("The connection was reset."),
        )
        for failure in failures:
            with self.subTest(error=type(failure).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / "games" / PLAYER["slug"] / PUZZLE["id"] / "trial-01" / "game.json"
                game_mailbox.initialize(path, game_id="interrupted-game")
                game_mailbox.append_event(path, "host", "surface", "A public puzzle.")
                before = game_mailbox.snapshot(path)

                class Client(br.HermesApiClient):
                    def turn(self, **kwargs):
                        if kwargs["provider"] == PLAYER["provider"]:
                            raise failure
                        return br.HermesTurnResult("Host stopped.", {}, "host-run")

                    def _session_usage(self, session_id, deadline=None):
                        return {"session_id": session_id, "api_call_count": 2, "input_tokens": 17}

                with self.assertRaises(type(failure)):
                    await br.run_game(root, PLAYER, PUZZLE, 1, 10, api_client=Client("", ""))
                after = game_mailbox.snapshot(path)
                self.assertEqual(after["status"], "player_turn")
                self.assertEqual(after["events"], before["events"])
                self.assertIn("infrastructure_pause", after)
                self.assertFalse(path.with_name("preliminary.json").exists())


    async def test_interruption_cancels_the_peer_run_before_returning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            peer_started = threading.Event()
            peer_cancelled = threading.Event()

            class Client(br.HermesApiClient):
                def __init__(self):
                    super().__init__("http://unused.invalid", "")
                    self.stopped_runs = []

                def _turn(self, **kwargs):
                    if kwargs["provider"] == PLAYER["provider"]:
                        if not peer_started.wait(1):
                            raise AssertionError("The host did not start.")
                        raise br.HermesApiError(429, "HTTP 429: quota exhausted")
                    self._retry_state.active_run_id = "host-run"
                    peer_started.set()
                    cancellation = getattr(self._retry_state, "cancellation_event", None)
                    if cancellation is not None and cancellation.wait(1):
                        peer_cancelled.set()
                        raise asyncio.CancelledError()
                    return br.HermesTurnResult("Host stopped.", {}, "host-run")

                def _request_with_retry(self, method, path, *args, **kwargs):
                    if method == "POST" and path.endswith("/stop"):
                        self.stopped_runs.append(path)
                    return {}

                def _session_usage(self, session_id, deadline=None):
                    return {"session_id": session_id, "api_call_count": 0}

            client = Client()
            with self.assertRaises(br.HermesApiError):
                await br.run_game(root, PLAYER, PUZZLE, 1, 10, api_client=client)
            self.assertTrue(peer_cancelled.is_set())
            self.assertIn("v1/runs/host-run/stop", client.stopped_runs)
            path = root / "games" / PLAYER["slug"] / PUZZLE["id"] / "trial-01" / "game.json"
            self.assertIn("infrastructure_pause", game_mailbox.snapshot(path))


    async def test_resume_continues_the_saved_round_and_keeps_cumulative_usage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trial_dir = root / "games" / PLAYER["slug"] / PUZZLE["id"] / "trial-02"
            path = trial_dir / "game.json"
            game_mailbox.initialize(path, game_id="saved-round")
            game_mailbox.append_event(path, "host", "surface", "A public puzzle.")
            for index in range(47):
                game_mailbox.append_event(path, "player", "question", f"Question {index + 1}?")
                game_mailbox.append_event(path, "host", "response", "No.")
            game_mailbox.add_control(path, "hint", actor="player")
            game_mailbox.append_event(path, "host", "hint", "A public hint.")
            before = game_mailbox.snapshot(path)
            sessions = {"source": "turtle-bench", "host": "saved-host", "player": "saved-player"}
            br.atomic_json(trial_dir / "sessions.json", sessions)
            failure_log = "session_id: saved-player\nAPI call failed after retrying: HTTP 429\n"
            (trial_dir / "player.log").write_text(failure_log)
            game_mailbox.pause_for_infrastructure(path, "HTTP 429")
            question_written = threading.Event()

            class Client(br.HermesApiClient):
                def __init__(self):
                    super().__init__("http://unused.invalid", "")
                    self.role_sessions = []
                    self.prompts = []

                def turn(self, **kwargs):
                    self.role_sessions.append(kwargs["session_id"])
                    self.prompts.append(kwargs["prompt"])
                    if kwargs["provider"] == PLAYER["provider"]:
                        game_mailbox.append_event(path, "player", "question", "The final hypothesis?")
                        question_written.set()
                    else:
                        if not question_written.wait(1):
                            raise AssertionError("The player did not continue.")
                        game_mailbox.append_event(path, "host", "answer", "Correct.", finish="solved")
                    return br.HermesTurnResult("Role completed.", {"api_call_count": 4}, "resumed-run")

                def _session_usage(self, session_id, deadline=None):
                    return {"session_id": session_id, "api_call_count": 96, "input_tokens": 2400}

            client = Client()
            await br.run_game(root, PLAYER, PUZZLE, 2, 10, api_client=client)
            after = game_mailbox.snapshot(path)
            self.assertEqual(after["game_id"], before["game_id"])
            self.assertEqual(after["status"], "solved")
            self.assertEqual(after["round"], 48)
            self.assertEqual(after["events"][:len(before["events"])], before["events"])
            self.assertEqual(after["player_hints_used"], before["player_hints_used"])
            self.assertEqual(after["player_hints_remaining"], before["player_hints_remaining"])
            self.assertNotIn("infrastructure_pause", after)
            self.assertTrue(after["rate_limit_waits"][-1]["ended_at"])
            self.assertEqual(set(client.role_sessions), {"saved-host", "saved-player"})
            self.assertEqual(br.load_json(trial_dir / "sessions.json"), sessions)
            self.assertEqual(br.load_json(trial_dir / "preliminary.json")["raw"]["player_usage"]["api_call_count"], 96)
            self.assertFalse(br.has_infrastructure_api_failure(trial_dir / "player.log"))
            history = list(trial_dir.glob("resume-history/*/player.log"))
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].read_text(), failure_log)
            self.assertTrue(all("Continue the same game" in prompt for prompt in client.prompts))


    async def test_api_failure_after_a_terminal_answer_keeps_the_completed_game(self):
        for finish in ("solved", "max_rounds"):
            with self.subTest(finish=finish), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / "games" / PLAYER["slug"] / PUZZLE["id"] / "trial-01" / "game.json"
                game_mailbox.initialize(path, game_id="completed-game", max_rounds=1)
                game_mailbox.append_event(path, "host", "surface", "A public puzzle.")
                game_mailbox.append_event(path, "player", "question", "The final hypothesis?")
                answered = threading.Event()

                class Client(br.HermesApiClient):
                    def turn(self, **kwargs):
                        if kwargs["provider"] == PLAYER["provider"]:
                            if not answered.wait(1):
                                raise AssertionError("The host did not answer.")
                            raise br.HermesApiError(429, "HTTP 429 after the terminal answer")
                        if finish == "solved":
                            game_mailbox.append_event(path, "host", "answer", "Correct.", finish="solved")
                        else:
                            game_mailbox.append_event(path, "host", "response", "No.")
                        answered.set()
                        return br.HermesTurnResult("Host completed.", {}, "host-run")

                    def _session_usage(self, session_id, deadline=None):
                        return {"session_id": session_id, "api_call_count": 8}

                caught = None
                try:
                    await br.run_game(root, PLAYER, PUZZLE, 1, 10, api_client=Client("", ""))
                except br.HermesApiError as exc:
                    caught = exc
                self.assertIsNone(caught, "The recorded terminal answer should not be discarded.")
                self.assertEqual(game_mailbox.snapshot(path)["status"], finish)
                preliminary = br.load_json(path.with_name("preliminary.json"))
                self.assertEqual(preliminary["status"], finish)
                self.assertEqual(preliminary["process_exit"], {"host": 0, "player": 1})
                self.assertFalse(br.has_infrastructure_api_failure(path.with_name("player.log")))
                self.assertEqual(len(list(path.parent.glob("resume-history/*/player.log"))), 1)


    async def test_interruption_keeps_private_host_error_details_out_of_the_mailbox(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            error = br.HermesApiError(503, "PRIVATE_HOST_DETAIL", retryable=True)

            class Client(br.HermesApiClient):
                def turn(self, **kwargs):
                    if kwargs["provider"] != PLAYER["provider"]:
                        raise error
                    return br.HermesTurnResult("Player stopped.", {}, "player-run")

                def _session_usage(self, session_id, deadline=None):
                    return {"session_id": session_id, "api_call_count": 0}

            with self.assertRaises(br.HermesApiError):
                await br.run_game(root, PLAYER, PUZZLE, 1, 10, api_client=Client("", ""))
            trial_dir = root / "games" / PLAYER["slug"] / PUZZLE["id"] / "trial-01"
            self.assertNotIn("PRIVATE_HOST_DETAIL", (trial_dir / "game.json").read_text())
            self.assertIn("PRIVATE_HOST_DETAIL", (trial_dir / "host.log").read_text())


class MailboxPauseTests(unittest.TestCase):
    def test_paused_game_rejects_public_writes_until_resumed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "game.json"
            game_mailbox.initialize(path, game_id="paused-game")
            game_mailbox.append_event(path, "host", "surface", "A public puzzle.")
            before = game_mailbox.snapshot(path)
            game_mailbox.pause_for_infrastructure(path, "The API connection failed.")
            for actor, event_type, text in (
                ("player", "question", "A new question?"),
                ("host", "exit", "The peer is unavailable."),
            ):
                with self.subTest(actor=actor), self.assertRaises(game_mailbox.ProtocolError):
                    game_mailbox.append_event(path, actor, event_type, text)
            self.assertEqual(game_mailbox.snapshot(path)["events"], before["events"])
            resumed = game_mailbox.resume_after_infrastructure(path)
            self.assertNotIn("infrastructure_pause", resumed)
            game_mailbox.append_event(path, "player", "question", "The next question?")

    def test_pause_wakes_a_mailbox_waiter_without_inventing_a_public_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "game.json"
            state = game_mailbox.initialize(path, game_id="paused-waiter")
            game_mailbox.pause_for_infrastructure(path, "The API connection failed.")
            result = {}

            def wait():
                result.update(game_mailbox.wait_for_update(
                    path, "host", state["revision"], timeout=1, poll_interval=0.001,
                ))

            thread = threading.Thread(target=wait, daemon=True)
            thread.start()
            thread.join(0.1)
            try:
                self.assertFalse(thread.is_alive(), "The pause did not wake the waiter.")
                self.assertTrue(result["paused"])
                self.assertEqual(result["events"], [])
                self.assertEqual(result["revision"], state["revision"])
            finally:
                game_mailbox.resume_after_infrastructure(path)
                game_mailbox.append_event(path, "host", "exit", "Test cleanup.")
                thread.join(1)


class ClientCancellationTests(unittest.TestCase):
    def test_cancelled_role_stops_its_active_api_run_without_waiting_for_timeout(self):
        cancellation = threading.Event()

        class Client(br.HermesApiClient):
            def __init__(self):
                super().__init__("http://unused.invalid", "", poll_interval=0.001)
                self.polls = 0
                self.stops = []

            def _request_with_retry(self, method, path, *args, **kwargs):
                if path == "v1/toolsets":
                    return {"data": [{"name": "terminal"}]}
                if path.startswith("api/sessions/"):
                    return {"data": []} if path.endswith("/messages") else {"session": {}}
                if method == "POST" and path == "v1/runs":
                    return {"run_id": "active-run"}
                if path.endswith("/stop"):
                    self.stops.append(path)
                    return {}
                self.polls += 1
                cancellation.set()
                return {"status": "running"}

        client = Client()
        caught = None
        try:
            client.turn(
                session_id="role-session", session_title="Role cancellation test",
                provider="test-provider", model="test-model", reasoning="default",
                prompt="Continue the current game.", timeout_s=0.02,
                cancellation_event=cancellation,
            )
        except BaseException as exc:
            caught = exc
        self.assertIsInstance(caught, asyncio.CancelledError)
        self.assertEqual(client.polls, 1)
        self.assertEqual(client.stops, ["v1/runs/active-run/stop"])

    def test_cancellation_interrupts_retry_after_without_submitting_another_run(self):
        cancellation = threading.Event()

        class Client(br.HermesApiClient):
            def __init__(self):
                super().__init__("http://unused.invalid", "", retry_attempts=2)
                self.posts = 0

            def _request(self, method, path, *args, **kwargs):
                if path == "v1/toolsets":
                    return {"data": [{"name": "terminal"}]}
                if path.startswith("api/sessions/"):
                    return {"data": []} if path.endswith("/messages") else {"session": {}}
                if method == "POST" and path == "v1/runs":
                    self.posts += 1
                    if self.posts == 1:
                        raise br.HermesApiError(429, "HTTP 429", retry_after=60, retryable=True)
                    return {"run_id": "unwanted-run"}
                return {"status": "completed", "output": "Finished."}

        client = Client()
        caught = None
        with mock.patch.object(br.time, "sleep"):
            try:
                client.turn(
                    session_id="waiting-role", session_title="Retry cancellation test",
                    provider="test-provider", model="test-model", reasoning="default",
                    prompt="Continue the current game.", timeout_s=1,
                    cancellation_event=cancellation,
                    on_rate_limit_wait=lambda _wait: cancellation.set(),
                )
            except BaseException as exc:
                caught = exc
        self.assertIsInstance(caught, asyncio.CancelledError)
        self.assertEqual(client.posts, 1)


class ClientResumeTests(unittest.TestCase):
    def test_rate_limit_resubmission_reloads_persisted_conversation_history(self):
        restored = [{"role": "user", "content": "Previously confirmed public facts."}]

        class Client(br.HermesApiClient):
            def __init__(self):
                super().__init__("http://unused.invalid", "")
                self.message_reads = 0
                self.posts = []

            def _request_with_retry(self, method, path, payload=None, expected=(200,), deadline=None):
                if path == "v1/toolsets":
                    return {"data": [{"name": "terminal"}]}
                if path.endswith("/messages"):
                    self.message_reads += 1
                    return {"data": [] if self.message_reads == 1 else restored}
                if path.startswith("api/sessions/"):
                    return {"session": {}}
                if method == "POST" and path == "v1/runs":
                    self.posts.append(json.loads(json.dumps(payload)))
                    return {"run_id": f"run-{len(self.posts)}"}
                if path == "v1/runs/run-1":
                    return {"status": "failed", "error": "HTTP 429"}
                return {"status": "completed", "output": "Completed."}

            def _resubmit_after_rate_limit(self, exc):
                return True

        client = Client()
        client.turn(
            session_id="resumed-session", session_title="Persisted history test",
            provider="test-provider", model="test-model", reasoning="default",
            prompt="Continue the current game.", timeout_s=1,
        )
        self.assertEqual(len(client.posts), 2)
        self.assertEqual(client.posts[1]["session_id"], "resumed-session")
        self.assertEqual(client.posts[1]["conversation_history"], restored)


if __name__ == "__main__":
    unittest.main()
