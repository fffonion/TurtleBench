#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from turtlebench import game_mailbox


class MailboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = game_mailbox

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "game.json"
        self.m.initialize(self.state, max_rounds=2, game_id="test-game")

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_turns_and_max_round_exit(self):
        s = self.m.append_event(self.state, "host", "surface", "题面", expected_revision=0)
        self.assertEqual(s["status"], "player_turn")
        s = self.m.append_event(self.state, "player", "question", "问题一", expected_revision=1)
        self.assertEqual((s["round"], s["status"]), (1, "host_turn"))
        s = self.m.append_event(self.state, "host", "response", "是", expected_revision=2)
        self.assertEqual(s["status"], "player_turn")
        s = self.m.append_event(self.state, "player", "question", "问题二", expected_revision=3)
        self.assertEqual((s["round"], s["status"]), (2, "host_turn"))
        s = self.m.append_event(self.state, "host", "response", "不是", expected_revision=4)
        self.assertEqual(s["status"], "max_rounds")
        self.assertEqual(s["stop_reason"], "max_rounds")

    def test_turn_violation_is_rejected(self):
        with self.assertRaises(self.m.ProtocolError):
            self.m.append_event(self.state, "player", "question", "越权", expected_revision=0)

    def test_hint_control_preserves_turn_and_stop_is_terminal(self):
        self.m.append_event(self.state, "host", "surface", "题面", expected_revision=0)
        s = self.m.add_control(self.state, "hint", expected_revision=1)
        self.assertEqual(s["status"], "player_turn")
        self.assertEqual(s["pending_hints"], 1)
        s = self.m.append_event(self.state, "host", "hint", "提示", expected_revision=2)
        self.assertEqual(s["status"], "player_turn")
        self.assertEqual(s["pending_hints"], 0)
        s = self.m.add_control(self.state, "stop", expected_revision=3)
        self.assertEqual(s["status"], "stopped")
        with self.assertRaises(self.m.ProtocolError):
            self.m.append_event(self.state, "player", "question", "继续", expected_revision=4)

    def test_player_can_request_two_hints_but_third_is_rejected(self):
        self.m.append_event(self.state, "host", "surface", "题面", expected_revision=0)

        first = self.m.add_control(
            self.state, "hint", expected_revision=1, actor="player"
        )
        self.assertEqual(first["pending_hints"], 1)
        self.assertEqual(first["player_hints_used"], 1)
        self.assertEqual(first["player_hints_remaining"], 1)
        self.assertEqual(first["events"][-1]["actor"], "player")
        self.assertTrue(self.m._relevant(first["events"][-1], "host"))
        self.m.append_event(self.state, "host", "hint", "提示一", expected_revision=2)

        second = self.m.add_control(
            self.state, "hint", expected_revision=3, actor="player"
        )
        self.assertEqual(second["player_hints_used"], 2)
        self.assertEqual(second["player_hints_remaining"], 0)
        self.m.append_event(self.state, "host", "hint", "提示二", expected_revision=4)

        with self.assertRaises(self.m.ProtocolError):
            self.m.add_control(
                self.state, "hint", expected_revision=5, actor="player"
            )

    def test_main_hint_does_not_consume_player_hint_budget(self):
        self.m.append_event(self.state, "host", "surface", "题面", expected_revision=0)
        state = self.m.add_control(self.state, "hint", expected_revision=1)
        self.assertEqual(state["player_hints_used"], 0)
        self.assertEqual(state["player_hints_remaining"], 2)

    def test_solved_exit(self):
        self.m.append_event(self.state, "host", "surface", "题面", expected_revision=0)
        self.m.append_event(self.state, "player", "question", "完整猜测", expected_revision=1)
        s = self.m.append_event(
            self.state,
            "host",
            "answer",
            "猜中",
            expected_revision=2,
            finish="solved",
        )
        self.assertEqual(s["status"], "solved")
        self.assertEqual(s["stop_reason"], "solved")

    def test_player_question_cannot_finish_game(self):
        self.m.append_event(self.state, "host", "surface", "题面", expected_revision=0)
        with self.assertRaises(self.m.ProtocolError):
            self.m.append_event(
                self.state,
                "player",
                "question",
                "完整猜测",
                expected_revision=1,
                finish="solved",
            )
        s = self.m.snapshot(self.state)
        self.assertEqual(s["status"], "player_turn")
        self.assertEqual(s["revision"], 1)

    def test_blocking_wait_returns_after_relevant_write(self):
        revision = self.m.snapshot(self.state)["revision"]
        result = {}

        def waiter():
            result.update(self.m.wait_for_update(self.state, "host", revision, timeout=3, poll_interval=0.02))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.08)
        self.m.add_control(self.state, "hint", expected_revision=revision)
        t.join(2)
        self.assertFalse(t.is_alive())
        self.assertEqual(result["events"][-1]["type"], "control")
        self.assertEqual(result["events"][-1]["command"], "hint")

    def test_stop_wakes_both_roles(self):
        self.m.append_event(self.state, "host", "surface", "题面", expected_revision=0)
        revision = self.m.snapshot(self.state)["revision"]
        results = {}

        def waiter(role):
            results[role] = self.m.wait_for_update(
                self.state, role, revision, timeout=3, poll_interval=0.02
            )

        threads = [threading.Thread(target=waiter, args=(role,)) for role in ("host", "player")]
        for thread in threads:
            thread.start()
        time.sleep(0.08)
        self.m.add_control(self.state, "stop", expected_revision=revision)
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results["host"]["status"], "stopped")
        self.assertEqual(results["player"]["status"], "stopped")

    def test_lock_and_expected_revision_allow_only_one_writer(self):
        self.m.append_event(self.state, "host", "surface", "题面", expected_revision=0)

        def writer(text):
            try:
                self.m.append_event(self.state, "player", "question", text, expected_revision=1)
                return "ok"
            except self.m.ProtocolError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, ["甲", "乙"]))
        self.assertEqual(sorted(results), ["ok", "rejected"])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["revision"], 2)
        self.assertEqual(len([e for e in state["events"] if e["type"] == "question"]), 1)

    def test_cli_wait_timeout_has_distinct_exit_code(self):
        proc = subprocess.run(
            [sys.executable, "-m", "turtlebench.game_mailbox", "wait", "--file", str(self.state),
             "--role", "player", "--after-revision", "0", "--timeout", "0.05", "--poll-interval", "0.01"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 3)
        self.assertIn('"timeout": true', proc.stdout)


if __name__ == "__main__":
    unittest.main()
