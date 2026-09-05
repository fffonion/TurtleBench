#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

TERMINAL_STATUSES = {"stopped", "solved", "max_rounds", "error"}
PUBLIC_TYPES = {"surface", "question", "response", "hint", "answer", "control", "exit"}


class ProtocolError(RuntimeError):
    pass


class WaitTimeout(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


@contextmanager
def _locked(path: Path, exclusive: bool) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    lock_path = _lock_path(path)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        os.fchmod(lock_file.fileno(), 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_unlocked(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProtocolError(f"状态文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"状态文件不是有效 JSON：{path}") from exc
    if not isinstance(value, dict) or value.get("format_version") != 1:
        raise ProtocolError("不支持的状态文件格式")
    return value


def _write_unlocked(path: Path, state: dict[str, Any]) -> None:
    data = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def initialize(path: str | Path, max_rounds: int = 50, game_id: str | None = None, force: bool = False) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not 1 <= max_rounds <= 50:
        raise ProtocolError("max_rounds 必须在 1 到 50 之间")
    with _locked(path, exclusive=True):
        if path.exists() and not force:
            raise ProtocolError(f"状态文件已存在：{path}")
        state: dict[str, Any] = {
            "format_version": 1,
            "game_id": game_id or f"game-{uuid.uuid4().hex[:12]}",
            "created_at": _now(),
            "updated_at": _now(),
            "revision": 0,
            "status": "awaiting_host",
            "round": 0,
            "max_rounds": max_rounds,
            "pending_hints": 0,
            "player_hint_limit": 2,
            "player_hints_used": 0,
            "player_hints_remaining": 2,
            "stop_reason": None,
            "events": [],
        }
        _write_unlocked(path, state)
        return state


def snapshot(path: str | Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    with _locked(path, exclusive=False):
        return _read_unlocked(path)


def _check_revision(state: dict[str, Any], expected_revision: int | None) -> None:
    if expected_revision is not None and state["revision"] != expected_revision:
        raise ProtocolError(
            f"revision 冲突：预期 {expected_revision}，当前 {state['revision']}；请重新读取"
        )


def _new_event(state: dict[str, Any], actor: str, event_type: str, text: str, **extra: Any) -> dict[str, Any]:
    event = {
        "seq": state["revision"] + 1,
        "at": _now(),
        "round": state["round"],
        "actor": actor,
        "type": event_type,
        "text": text,
    }
    event.update(extra)
    return event


def append_event(
    path: str | Path,
    actor: str,
    event_type: str,
    text: str,
    expected_revision: int | None = None,
    finish: str | None = None,
) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    actor = actor.strip().lower()
    event_type = event_type.strip().lower()
    text = text.strip()
    if actor not in {"host", "player"}:
        raise ProtocolError("actor 只能是 host 或 player")
    if event_type not in PUBLIC_TYPES - {"control"}:
        raise ProtocolError("不支持的事件类型")
    if not text:
        raise ProtocolError("写入内容不能为空")
    if finish not in {None, "solved", "stopped", "error"}:
        raise ProtocolError("不支持的结束原因")
    if finish and event_type not in {"response", "answer", "exit"}:
        raise ProtocolError("该事件类型不能结束游戏")

    with _locked(path, exclusive=True):
        state = _read_unlocked(path)
        _check_revision(state, expected_revision)
        if state["status"] in TERMINAL_STATUSES:
            raise ProtocolError(f"游戏已经结束：{state['status']}")

        status = state["status"]
        if event_type == "surface":
            if actor != "host" or status != "awaiting_host":
                raise ProtocolError("只有主持人能在开场阶段写入汤面")
            state["status"] = "player_turn"
        elif event_type == "question":
            if actor != "player" or status != "player_turn":
                raise ProtocolError("当前不是玩家提问阶段")
            if state["round"] >= state["max_rounds"]:
                raise ProtocolError("已达到最大轮数")
            state["round"] += 1
            state["status"] = "host_turn"
        elif event_type in {"response", "answer"}:
            if actor != "host" or status != "host_turn":
                raise ProtocolError("当前不是主持人回答阶段")
            if finish == "solved" or event_type == "answer":
                state["status"] = "solved"
                state["stop_reason"] = "solved"
            elif finish in {"stopped", "error"}:
                state["status"] = finish
                state["stop_reason"] = finish
            elif state["round"] >= state["max_rounds"]:
                state["status"] = "max_rounds"
                state["stop_reason"] = "max_rounds"
            else:
                state["status"] = "player_turn"
        elif event_type == "hint":
            if actor != "host":
                raise ProtocolError("只有主持人能写入提示")
            if state["pending_hints"] < 1:
                raise ProtocolError("当前没有待处理的提示指令")
            state["pending_hints"] -= 1
        elif event_type == "exit":
            state["status"] = finish or "error"
            state["stop_reason"] = finish or "error"

        event = _new_event(state, actor, event_type, text)
        state["revision"] = event["seq"]
        state["events"].append(event)
        state["updated_at"] = _now()
        _write_unlocked(path, state)
        return state


def add_control(
    path: str | Path,
    command: str,
    text: str = "",
    expected_revision: int | None = None,
    actor: str = "main",
) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    command = command.strip().lower()
    actor = actor.strip().lower()
    if command not in {"hint", "stop"}:
        raise ProtocolError("控制指令只能是 hint 或 stop")
    if actor not in {"main", "player"}:
        raise ProtocolError("控制指令 actor 只能是 main 或 player")
    if actor == "player" and command != "hint":
        raise ProtocolError("玩家只能写入 hint 控制指令")
    with _locked(path, exclusive=True):
        state = _read_unlocked(path)
        _check_revision(state, expected_revision)
        if state["status"] in TERMINAL_STATUSES:
            return state
        if command == "hint":
            limit = state.setdefault("player_hint_limit", 2)
            used = state.setdefault("player_hints_used", 0)
            state.setdefault("player_hints_remaining", max(0, limit - used))
            if actor == "player":
                if used >= limit:
                    raise ProtocolError("玩家的两次提示机会已经用完")
                used += 1
                state["player_hints_used"] = used
                state["player_hints_remaining"] = limit - used
            state["pending_hints"] += 1
            display = text.strip() or "给提示"
        else:
            state["status"] = "stopped"
            state["stop_reason"] = "user_stop"
            display = text.strip() or "停止"
        event = _new_event(state, actor, "control", display, command=command)
        state["revision"] = event["seq"]
        state["events"].append(event)
        state["updated_at"] = _now()
        _write_unlocked(path, state)
        return state


def _relevant(event: dict[str, Any], role: str) -> bool:
    if event.get("type") == "control":
        if event.get("command") == "stop":
            return True
        return role == "host" and event.get("command") == "hint"
    if role == "host":
        return event.get("actor") == "player" and event.get("type") == "question"
    return event.get("actor") == "host" and event.get("type") in {
        "surface", "response", "hint", "answer", "exit"
    }


def wait_for_update(
    path: str | Path,
    role: str,
    after_revision: int,
    timeout: float | None = None,
    poll_interval: float = 0.25,
) -> dict[str, Any]:
    role = role.strip().lower()
    if role not in {"host", "player"}:
        raise ProtocolError("role 只能是 host 或 player")
    if poll_interval <= 0:
        raise ProtocolError("poll_interval 必须大于 0")
    deadline = None if timeout is None or timeout <= 0 else time.monotonic() + timeout
    path = Path(path).expanduser().resolve()
    while True:
        state = snapshot(path)
        events = [
            event for event in state["events"]
            if event["seq"] > after_revision and _relevant(event, role)
        ]
        if events or state["status"] in TERMINAL_STATUSES:
            return {
                "timeout": False,
                "revision": state["revision"],
                "status": state["status"],
                "round": state["round"],
                "max_rounds": state["max_rounds"],
                "pending_hints": state["pending_hints"],
                "player_hints_used": state.get("player_hints_used", 0),
                "player_hints_remaining": state.get("player_hints_remaining", 2),
                "stop_reason": state["stop_reason"],
                "events": events,
            }
        if deadline is not None and time.monotonic() >= deadline:
            raise WaitTimeout("等待超时")
        time.sleep(poll_interval)


def exchange(
    path: str | Path,
    role: str,
    event_type: str,
    text: str,
    expected_revision: int,
    finish: str | None = None,
    timeout: float | None = None,
    poll_interval: float = 0.25,
) -> dict[str, Any]:
    state = append_event(path, role, event_type, text, expected_revision, finish)
    if state["status"] in TERMINAL_STATUSES:
        return {
            "timeout": False,
            "revision": state["revision"],
            "status": state["status"],
            "round": state["round"],
            "max_rounds": state["max_rounds"],
            "pending_hints": state["pending_hints"],
            "player_hints_used": state.get("player_hints_used", 0),
            "player_hints_remaining": state.get("player_hints_remaining", 2),
            "stop_reason": state["stop_reason"],
            "events": [],
        }
    return wait_for_update(path, role, state["revision"], timeout, poll_interval)


def _dump(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="带锁的海龟汤双代理通信邮箱")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.add_argument("--file", required=True)
    p.add_argument("--max-rounds", type=int, default=50)
    p.add_argument("--game-id")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("snapshot")
    p.add_argument("--file", required=True)

    p = sub.add_parser("wait")
    p.add_argument("--file", required=True)
    p.add_argument("--role", choices=["host", "player"], required=True)
    p.add_argument("--after-revision", type=int, required=True)
    p.add_argument("--timeout", type=float, default=0)
    p.add_argument("--poll-interval", type=float, default=0.25)

    for name in ("write", "exchange"):
        p = sub.add_parser(name)
        p.add_argument("--file", required=True)
        p.add_argument("--role", choices=["host", "player"], required=True)
        p.add_argument("--type", dest="event_type", required=True,
                       choices=sorted(PUBLIC_TYPES - {"control"}))
        p.add_argument("--text", required=True)
        p.add_argument("--expected-revision", type=int, required=True)
        p.add_argument("--finish", choices=["solved", "stopped", "error"])
        if name == "exchange":
            p.add_argument("--timeout", type=float, default=0)
            p.add_argument("--poll-interval", type=float, default=0.25)

    p = sub.add_parser("control")
    p.add_argument("--file", required=True)
    p.add_argument("--command", choices=["hint", "stop"], required=True)
    p.add_argument("--text", default="")
    p.add_argument("--expected-revision", type=int)
    p.add_argument("--actor", choices=["main", "player"], default="main")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            result = initialize(args.file, args.max_rounds, args.game_id, args.force)
        elif args.command == "snapshot":
            result = snapshot(args.file)
        elif args.command == "wait":
            result = wait_for_update(
                args.file, args.role, args.after_revision, args.timeout, args.poll_interval
            )
        elif args.command == "write":
            result = append_event(
                args.file, args.role, args.event_type, args.text,
                args.expected_revision, args.finish,
            )
        elif args.command == "exchange":
            result = exchange(
                args.file, args.role, args.event_type, args.text,
                args.expected_revision, args.finish, args.timeout, args.poll_interval,
            )
        else:
            result = add_control(
                args.file, args.command, args.text, args.expected_revision, args.actor
            )
        _dump(result)
        return 0
    except WaitTimeout:
        _dump({"timeout": True})
        return 3
    except ProtocolError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
