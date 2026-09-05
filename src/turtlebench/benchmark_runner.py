#!/usr/bin/env python3
"""Concurrent, resumable situation-puzzle benchmark runner."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES = PROJECT_ROOT / "fixtures" / "fixed-v1"
DEFAULT_RUNS = Path.cwd() / "runs"
DEFAULT_STATE_DB = Path.home() / ".hermes" / "state.db"
MAILBOX_COMMAND = [sys.executable, "-m", "turtlebench.game_mailbox"]


@dataclass(frozen=True)
class RuntimePaths:
    fixtures: Path
    runs_dir: Path
    state_db: Path


RUNTIME = RuntimePaths(DEFAULT_FIXTURES, DEFAULT_RUNS, DEFAULT_STATE_DB)
HOST = {"provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "max"}
JUDGE = HOST.copy()
PLAYER_MATRIX = [
    {"slug": "luna-max", "display_name": "Luna max baseline", "provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "max"},
    {"slug": "luna-high", "display_name": "Luna high baseline", "provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "high"},
    {"slug": "minimax-m3-max", "display_name": "OpenRouter / MiniMax M3 max", "provider": "openrouter", "model": "minimax/minimax-m3:free", "reasoning_effort": "max"},
    {"slug": "deepseek-v4-flash-max", "display_name": "CommandCode / DeepSeek V4 Flash max", "provider": "commandcode", "model": "deepseek-ai/deepseek-v4-flash", "reasoning_effort": "max"},
    {"slug": "deepseek-provider-v4-flash-max", "display_name": "DeepSeek provider / DeepSeek V4 Flash max", "provider": "deepseek", "model": "deepseek-v4-flash", "reasoning_effort": "max"},
    {"slug": "claude-sonnet-5-high", "display_name": "Anthropic / Claude Sonnet 5 high", "provider": "anthropic", "model": "claude-sonnet-5", "reasoning_effort": "high"},
    {"slug": "gpt-5-6-sol-high", "display_name": "OpenAI Codex / GPT-5.6 Sol high", "provider": "openai-codex", "model": "gpt-5.6-sol", "reasoning_effort": "high"},
    {"slug": "gpt-6-astra-high", "display_name": "OpenAI Codex / GPT-6 Astra high", "provider": "openai-codex", "model": "gpt-6-astra", "reasoning_effort": "high"},
    {"slug": "grok-4-6-high", "display_name": "Supplemental / Grok 4.6 high", "provider": "xai-oauth", "model": "grok-4.6", "reasoning_effort": "high"},
]
TERMINAL_STATES = {"solved", "max_rounds", "stopped", "error"}
TERMINAL_VALIDITIES = {"valid", "invalid_host", "invalid_infrastructure"}
SESSION_SOURCE = "turtle-bench"
TARGET_VALID_GAMES = 36


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def validate_attempt_limit(max_attempts: int, target_valid_games: int = TARGET_VALID_GAMES) -> None:
    if max_attempts < target_valid_games:
        raise ValueError(f"max attempts must be at least {target_valid_games}")


def attempt_limit_arg(value: str) -> int:
    parsed = int(value)
    try:
        validate_attempt_limit(parsed)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def summary_needs_retry(summary: dict[str, Any], target_valid_games: int) -> bool:
    if summary.get("attempt_limit_reached"):
        return False
    return int(summary.get("valid_games", 0)) < target_valid_games


def retry_stop_state(
    valid_games: int,
    target_valid_games: int,
    attempts_started: int,
    max_attempts: int,
) -> tuple[bool, bool]:
    limit_reached = attempts_started >= max_attempts and valid_games < target_valid_games
    return valid_games >= target_valid_games or limit_reached, limit_reached


def physical_attempt_count(run_dir: Path, player_slug: str) -> int:
    paths = set((run_dir / "games" / player_slug).glob("*/trial*/game.json"))
    paths.update((run_dir / "retry-archives").glob(f"**/games/{player_slug}/*/trial*/game.json"))
    return len(paths)


def load_attempt_state(
    run_dir: Path,
    player_slug: str,
    max_attempts: int,
    target_valid_games: int = TARGET_VALID_GAMES,
) -> dict[str, Any]:
    validate_attempt_limit(max_attempts, target_valid_games)
    path = run_dir / "games" / player_slug / "attempts.json"
    physical_count = physical_attempt_count(run_dir, player_slug)
    if path.exists():
        state = load_json(path)
        state["max_attempts"] = max_attempts
        state["target_valid_games"] = target_valid_games
        state["attempts_started"] = max(int(state.get("attempts_started", 0)), physical_count)
        state.setdefault("pending_slots", [])
    else:
        state = {
            "player_slug": player_slug,
            "target_valid_games": target_valid_games,
            "max_attempts": max_attempts,
            "attempts_started": physical_count,
            "retry_round": 0,
            "pending_slots": [],
            "updated_at": now_iso(),
        }
    state["updated_at"] = now_iso()
    atomic_json(path, state)
    return state


def reserve_attempt_slots(state_path: Path, state: dict[str, Any], slots: list[str]) -> list[str]:
    remaining = max(0, int(state["max_attempts"]) - int(state["attempts_started"]))
    reserved = slots[:remaining]
    state["attempts_started"] = int(state["attempts_started"]) + len(reserved)
    state["pending_slots"] = list(dict.fromkeys([*state.get("pending_slots", []), *reserved]))
    state["updated_at"] = now_iso()
    atomic_json(state_path, state)
    return reserved


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return round(xs[lo], 3)
    return round(xs[lo] * (hi - pos) + xs[hi] * (pos - lo), 3)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def compute_raw_metrics(game: dict[str, Any]) -> dict[str, Any]:
    events = game.get("events", [])
    surface = next((e for e in events if e.get("type") == "surface"), None)
    questions = [e for e in events if e.get("type") == "question"]
    terminal = next((e for e in reversed(events) if e.get("type") in {"answer", "exit"}), events[-1] if events else None)
    first = 0.0
    if surface and questions:
        first = (parse_time(questions[0]["at"]) - parse_time(surface["at"])).total_seconds()
    latencies: list[float] = []
    player_intervals: list[float] = []
    last_host_action: dict[str, Any] | None = surface
    for event in events:
        if event.get("actor") == "host" and event.get("type") in {"surface", "response", "hint"}:
            last_host_action = event
        elif event.get("actor") == "player" and event.get("type") == "question" and last_host_action:
            interval = max(0.0, (parse_time(event["at"]) - parse_time(last_host_action["at"])).total_seconds())
            player_intervals.append(interval)
            if last_host_action is not surface or event is not questions[0]:
                latencies.append(interval)
            last_host_action = None
    wall = 0.0
    if surface and terminal:
        wall = max(0.0, (parse_time(terminal["at"]) - parse_time(surface["at"])).total_seconds())
    return {
        "rounds": int(game.get("round", 0)),
        "hints_used": int(game.get("player_hints_used", 0)),
        "first_question_latency_s": round(first, 3),
        "player_latency_p50_s": percentile(latencies, 0.5),
        "player_latency_p90_s": percentile(latencies, 0.9),
        "total_wall_time_s": round(wall, 3),
        "player_active_time_s": round(sum(player_intervals), 3),
        "question_count": len(questions),
    }


def parse_session_id(path: Path) -> str | None:
    if not path.exists():
        return None
    match = re.search(r"(?m)^\s*session_id:\s*(\S+)", path.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def load_session_usage(db_path: Path, session_id: str | None) -> dict[str, Any] | None:
    if not session_id or not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path, timeout=2) as conn:
            row = conn.execute(
                """SELECT api_call_count, input_tokens, output_tokens,
                          cache_read_tokens, cache_write_tokens, reasoning_tokens
                   FROM sessions WHERE id = ?""",
                (session_id,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    keys = ("api_call_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")
    return {"session_id": session_id, **dict(zip(keys, map(int, row)))}


def build_cli_command(provider: str, model: str, reasoning: str, prompt: str) -> list[str]:
    return [
        "hermes", "chat", "-Q", "-q", prompt,
        "--provider", provider, "--model", model,
        "--reasoning-effort", reasoning,
        "--toolsets", "terminal", "--max-turns", "180",
        "--ignore-rules", "--source", SESSION_SOURCE, "--yolo",
    ]


def is_completed_score(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = load_json(path)
    except Exception:
        return False
    return data.get("validity") in TERMINAL_VALIDITIES and data.get("status") in TERMINAL_STATES


def archive_invalid_trials(
    run_dir: Path,
    player_slugs: list[str],
    archive_root: Path,
    max_trials: int | None = None,
) -> dict[str, int]:
    """Move invalid trial directories and stale player summaries aside for a clean retry."""
    counts: dict[str, int] = {}
    for slug in player_slugs:
        player_root = run_dir / "games" / slug
        invalid_trials: list[Path] = []
        for score_path in sorted(player_root.glob("*/trial-[0-9][0-9]/score.json")):
            score = load_json(score_path)
            if str(score.get("validity", "")).startswith("invalid_"):
                invalid_trials.append(score_path.parent)
        if max_trials is not None:
            invalid_trials = invalid_trials[:max_trials]
        counts[slug] = len(invalid_trials)
        affected_puzzles = {trial_dir.parent for trial_dir in invalid_trials}
        for trial_dir in invalid_trials:
            destination = archive_root / "games" / slug / trial_dir.relative_to(player_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trial_dir), str(destination))
        for puzzle_root in affected_puzzles:
            judge = puzzle_root / "judge.json"
            if judge.exists():
                destination = archive_root / "games" / slug / puzzle_root.relative_to(player_root) / judge.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(judge), str(destination))
        if invalid_trials:
            summary = run_dir / "summaries" / f"{slug}.json"
            if summary.exists():
                destination = archive_root / "summaries" / summary.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(summary), str(destination))
    atomic_json(archive_root / "manifest.json", {"players": counts, "created_at": now_iso()})
    return counts


def game_needs_run(game_path: Path, preliminary_path: Path) -> bool:
    if not game_path.exists() or not preliminary_path.exists():
        return True
    try:
        return load_json(game_path).get("status") not in TERMINAL_STATES
    except Exception:
        return True


def verify_suite(fixtures: Path | None = None) -> dict[str, Any]:
    suite_dir = fixtures or RUNTIME.fixtures
    manifest = load_json(suite_dir / "manifest.json")
    for entry in manifest["puzzles"]:
        path = suite_dir / entry["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise RuntimeError(f"suite hash mismatch: {entry['id']}")
    if len(manifest["puzzles"]) != 12:
        raise RuntimeError("fixed-v1 must contain 12 puzzles")
    return manifest


def host_prompt(puzzle: Path, game: Path, game_id: str) -> str:
    return f"""你是海龟汤 benchmark 主持人，只能通过带锁邮箱与玩家通信。不得向用户提问、调用子代理或使用消息平台。
私密题目：{puzzle}
使用 Python json 模块读取私密题目的全部字段。
公共邮箱：{game}
邮箱命令：python -m turtlebench.game_mailbox
game_id={game_id}，max_rounds=50。

读取题目全部字段。未猜中前，邮箱只能写汤面、是／不是／是也不是／不相关及按序提示；禁止公开汤底、未发布提示、key_facts 或内部推理。完整猜测在核心条件、必要因果链和全部异常解释上等价即可判中。

判定前把问题拆为最小命题：supported=来源明确支持；contradicted=来源明确否定；unspecified=来源未限定且真假不影响核心链。全部关键命题 supported 且无错误限定答“是”；关键命题 contradicted 且无另一条主线成立答“不是”；明确 supported 主线与会改变机制的 contradicted 限定并存，或身份、时间、位置、动作、因果、范围关键错位，答“是也不是”；unspecified 且不参与核心链答“不相关”。相容性不构成肯定证据，宽泛 key_fact 不得外推。保持前后一致。

启动：exchange 写 surface，role=host、type=surface、expected_revision=0、timeout=120；terminal timeout 至少150秒。循环保存最新 revision、status、round、pending_hints、提示额度与待回答问题。收到 question：猜中则写 type=answer、text="猜对了。答案：<solution>"、finish=solved；其余写四类 response 并 exchange 等待。收到 player hint 控制时按序发布下一提示；有待回答问题时先 write 提示，再回答原问题。禁止 main 人工干预。收到终局立即退出。

超时或 revision 冲突：先 snapshot。自己刚写事件已存在则保存 revision 后 wait；不存在则按最新 revision 重试一次。连续3次等待无 revision 前进，尽量写 type=exit、finish=error 后退出。第50轮回应后退出。最终只返回角色、game_id、status、round、revision、是否正常退出；禁止返回私密内容。"""


def player_prompt(game: Path, game_id: str) -> str:
    return f"""你是海龟汤 benchmark 隔离玩家，只能通过带锁邮箱与主持人通信。不得向用户提问、调用子代理或使用消息平台。
公共邮箱：{game}
邮箱命令：python -m turtlebench.game_mailbox
game_id={game_id}，max_rounds=50，自主提示上限2。

禁止读取、搜索、定位或推断私密题目、汤底、提示数组、key_facts、manifest、题组目录、出题记录或主持人上下文。只能使用邮箱公开的 surface、response 和 hint；文件名与目录不得作为线索。

每轮只写一个可由“是／不是／是也不是／不相关”判断的问题，或一个完整猜测；只引入一个新变量。完整猜测也必须作为普通 `question` 写入，禁止传 `--finish`；只有主持人的判定可以结束对局。优先检查动作字面性、身份或状态、关系、时间、地点机制、意图和因果。`是` 只确认最小命题，随后切分、细化、连边或验因。`是也不是` 不得整体记真，只验证一个会改变核心链的限定。`不相关` 后停止该支线。每获2—3个肯定，按时间或因果压缩事实。连续否定回到最近肯定；连续无关回到人物、时间、动作、关系和动机。

核心条件、时间顺序、动作机制、最终反应已有三项支持，且能解释全部异常时提交完整猜测，停止确认装饰细节。同一语义区域连续两次“是也不是”后停止同义改写；最多再验证两轮并提交修订链。第35轮起每轮检查闭合；第45轮起禁止新支线，提交最佳完整猜测。完整猜测按隐藏条件／前史→关键动作→被误读事实→最终反应及原因。不得加入改变身份、时间、机制或因果方向的新前提。邮箱中不得写内部推理、候选列表或多问题组合。

提示仅在连续至少3问无新增约束或无法形成高信息下一问时使用，最多2次，以 player_hints_remaining 为准。调用 control --actor player --command hint --expected-revision <rev>；成功后保存 revision 并 wait，禁止重复请求。

启动：wait --role player --after-revision 0 --timeout 120；terminal timeout 至少150秒。收到 response/hint 后更新约束并继续；收到终局立即退出。超时或 revision 冲突先 snapshot；自己刚写事件已存在则保存 revision 后 wait，不存在才重试一次。连续3次无 revision 前进，尽量写 type=exit、finish=error 后退出。round达到50不得创建第51问。最终只返回角色、game_id、status、round、revision、是否正常退出；禁止包含答案、候选答案或私密信息。"""


def init_game(path: Path, game_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([*MAILBOX_COMMAND, "init", "--file", str(path), "--game-id", game_id, "--max-rounds", "50"], check=True, stdout=subprocess.DEVNULL)


async def run_cli(cmd: list[str], log_path: Path, timeout_s: int) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as out:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=out, stderr=asyncio.subprocess.STDOUT, cwd=str(Path.home()))
        try:
            return await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=20)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            return 124


def has_infrastructure_api_failure(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    return "API call failed after " in log_path.read_text(encoding="utf-8", errors="replace")


async def mark_error_if_needed(game_path: Path, reason: str) -> None:
    try:
        game = load_json(game_path)
        if game.get("status") in TERMINAL_STATES:
            return
        proc = await asyncio.create_subprocess_exec(
            *MAILBOX_COMMAND, "write", "--file", str(game_path),
            "--role", "host", "--type", "exit", "--text", reason,
            "--expected-revision", str(game["revision"]), "--finish", "error",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception:
        return


async def run_game(run_dir: Path, player: dict[str, str], puzzle: dict[str, Any], trial: int, timeout_s: int) -> Path:
    trial_dir = run_dir / "games" / player["slug"] / puzzle["id"] / f"trial-{trial:02d}"
    score_path = trial_dir / "score.json"
    if is_completed_score(score_path):
        return score_path
    game_path = trial_dir / "game.json"
    preliminary_path = trial_dir / "preliminary.json"
    if not game_needs_run(game_path, preliminary_path):
        return score_path
    if game_path.exists():
        try:
            old = load_json(game_path)
            if old.get("status") not in TERMINAL_STATES:
                game_path.rename(trial_dir / f"game.interrupted-{int(datetime.now().timestamp())}.json")
        except Exception:
            game_path.rename(trial_dir / f"game.invalid-{int(datetime.now().timestamp())}.json")
    if not game_path.exists():
        init_game(game_path, f"{player['slug']}-{puzzle['id']}-t{trial:02d}")
    host_cmd = build_cli_command(HOST["provider"], HOST["model"], HOST["reasoning_effort"], host_prompt(RUNTIME.fixtures / puzzle["path"], game_path, load_json(game_path)["game_id"]))
    player_cmd = build_cli_command(player["provider"], player["model"], player["reasoning_effort"], player_prompt(game_path, load_json(game_path)["game_id"]))
    host_task = asyncio.create_task(run_cli(host_cmd, trial_dir / "host.log", timeout_s))
    player_task = asyncio.create_task(run_cli(player_cmd, trial_dir / "player.log", timeout_s))
    host_rc, player_rc = await asyncio.gather(host_task, player_task)
    await mark_error_if_needed(game_path, f"角色进程提前退出 host={host_rc} player={player_rc}")
    game = load_json(game_path)
    raw = compute_raw_metrics(game)
    raw["player_usage"] = load_session_usage(
        RUNTIME.state_db,
        parse_session_id(trial_dir / "player.log"),
    )
    atomic_json(trial_dir / "player_totals.json", {
        "game_id": game.get("game_id"),
        "status": game.get("status"),
        "player_active_time_s": raw["player_active_time_s"],
        "total_wall_time_s": raw["total_wall_time_s"],
        "player_usage": raw["player_usage"],
    })
    preliminary = {
        "suite_version": "fixed-v1", "puzzle_id": puzzle["id"], "trial": trial,
        "player": {k: player[k] for k in ("provider", "model", "reasoning_effort")},
        "validity": "pending", "status": game.get("status", "error"), "raw": raw,
        "process_exit": {"host": host_rc, "player": player_rc},
    }
    atomic_json(preliminary_path, preliminary)
    return score_path


def judge_prompt(puzzle_path: Path, trial_dirs: list[Path], output_path: Path, player: dict[str, str]) -> str:
    games = "\n".join(f"- trial {i+1}: {d / 'game.json'}" for i, d in enumerate(trial_dirs))
    return f"""你是海龟汤 benchmark 评分员。只评估公开轨迹及主持判定质量，不参与游戏。
私密题目：{puzzle_path}
三个公开邮箱：
{games}
输出文件：{output_path}

读取题目 solution/key_facts 仅用于核验主持判断及最终闭合度；不得把私密内容写入输出。逐局检查：主持泄露、关键矛盾、把 unspecified 反复判为“是也不是”、提示顺序、提前退出。validity 只能为 valid、invalid_host、invalid_infrastructure。玩家自身失败、拒绝、协议错误仍为 valid。

对每局公开问题逐条分类并输出以下字段：trial；validity；validity_reason；atomic_question_rate、useful_constraint_rate、redundant_question_rate、unsupported_story_guess_rate（0到1）；irrelevant_branch_max；contradiction_count；partial_misread_count；excluded_revisit_count；protocol_recovery_failure_count；reasoning_chain_parts（承接性、层级推进、跨异常连接、分支回收，各0到5）；question_information_parts（原子性、压缩能力、去重与聚焦，各0到5）；final_closure（0到5）；hint_effective_count；hint_ineffective_count；hint_early_count；hint_consecutive（布尔）；hint_hoarding（布尔）；failure_tags；notes。failure_tags 仅用规范标签。notes 只写可由公开轨迹核验的简短依据，禁止写汤底、未发布提示或 key_facts。

将三个对象组成 JSON 数组。使用 terminal 运行 Python，把合法 UTF-8 JSON 原子写入 {output_path}。写后重新读取并验证数组恰有3项、trial为1到3。最终回复仅报告写入成功与路径。
玩家配置：{player['provider']} / {player['model']} / {player['reasoning_effort']}。"""


async def run_judge(run_dir: Path, player: dict[str, str], puzzle: dict[str, Any], timeout_s: int) -> Path:
    puzzle_root = run_dir / "games" / player["slug"] / puzzle["id"]
    trial_dirs = [puzzle_root / f"trial-{i:02d}" for i in (1, 2, 3)]
    output = puzzle_root / "judge.json"

    def valid_output() -> bool:
        if not output.exists():
            return False
        try:
            data = load_json(output)
            if not isinstance(data, list) or len(data) != 3:
                return False
            trials = set()
            for item in data:
                if not isinstance(item, dict):
                    return False
                trials.add(item.get("trial"))
            return trials == {1, 2, 3}
        except Exception:
            return False

    if valid_output():
        return output

    cmd = build_cli_command(JUDGE["provider"], JUDGE["model"], JUDGE["reasoning_effort"], judge_prompt(RUNTIME.fixtures / puzzle["path"], trial_dirs, output, player))
    last_rc: int | None = None
    for attempt in range(1, 4):
        log_path = puzzle_root / ("judge.log" if attempt == 1 else f"judge-retry-{attempt:02d}.log")
        last_rc = await run_cli(cmd, log_path, timeout_s)
        if last_rc == 0 and valid_output():
            return output
        if output.exists():
            output.replace(puzzle_root / f"judge-invalid-attempt-{attempt:02d}.json")
    raise RuntimeError(f"judge failed after 3 attempts for {player['slug']} {puzzle['id']} rc={last_rc}")


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def outcome_score(status: str, rounds: int, difficulty: str) -> float:
    if status != "solved":
        return 0.0
    budget = {"简单": 15, "中等": 25, "困难": 40}[difficulty]
    efficiency = 10.0 if rounds <= budget else 10.0 * max(0.0, (50 - rounds) / (50 - budget))
    return 20.0 + efficiency


def speed_score(raw: dict[str, Any]) -> float:
    p50 = float(raw.get("player_latency_p50_s", 0))
    p90 = float(raw.get("player_latency_p90_s", 0))
    return 7 * clamp((60 - p50) / 55, 0, 1) + 3 * clamp((120 - p90) / 110, 0, 1)


def finalize_scores(run_dir: Path, player: dict[str, str], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    for puzzle in manifest["puzzles"]:
        root = run_dir / "games" / player["slug"] / puzzle["id"]
        judged = {int(x["trial"]): x for x in load_json(root / "judge.json")}
        for trial in (1, 2, 3):
            td = root / f"trial-{trial:02d}"
            pre = load_json(td / "preliminary.json")
            raw = pre["raw"] | {k: judged[trial][k] for k in (
                "atomic_question_rate", "useful_constraint_rate", "redundant_question_rate",
                "unsupported_story_guess_rate", "irrelevant_branch_max", "contradiction_count",
                "partial_misread_count")}
            j = judged[trial]
            reasoning = sum(float(v) for v in j["reasoning_chain_parts"].values())
            info = sum(float(v) for v in j["question_information_parts"].values())
            hint = 6 + 2 * min(2, int(j["hint_effective_count"])) - 2 * int(j["hint_early_count"]) - 2 * int(j["hint_ineffective_count"])
            if j["hint_consecutive"]:
                hint -= 2
            if pre["status"] == "solved" and raw["hints_used"] == 0 and int(j["irrelevant_branch_max"]) <= 4:
                hint += 4
            if j["hint_hoarding"]:
                hint -= 2
            consistency = 10 - 2 * int(j["contradiction_count"]) - int(j["excluded_revisit_count"]) - 2 * int(j["partial_misread_count"]) - 2 * int(j["protocol_recovery_failure_count"])
            if pre["process_exit"]["player"] != 0 and pre["status"] not in {"solved", "max_rounds"}:
                consistency = 0
            failed_roles = [
                role for role in ("host", "player")
                if has_infrastructure_api_failure(td / f"{role}.log")
            ]
            validity = "invalid_infrastructure" if failed_roles else j["validity"]
            validity_reason = (
                f"{', '.join(failed_roles)} API call failed before normal completion"
                if failed_roles else j.get("validity_reason", "")
            )
            parts = {
                "outcome_round_efficiency": outcome_score(pre["status"], int(raw["rounds"]), puzzle["difficulty"]),
                "reasoning_chain": reasoning,
                "question_information": info,
                "hint_strategy": clamp(hint, 0, 10),
                "consistency_recovery": clamp(consistency, 0, 10),
                "final_closure": clamp(float(j["final_closure"]), 0, 5),
                "response_speed": speed_score(raw),
            }
            parts = {k: round(v, 1) for k, v in parts.items()}
            score = {
                "suite_version": "fixed-v1", "puzzle_id": puzzle["id"], "trial": trial,
                "player": pre["player"], "validity": validity, "status": pre["status"],
                "raw": raw, "scores": parts | {"total": round(sum(parts.values()), 1)},
                "failure_tags": j["failure_tags"], "notes": j["notes"],
                "validity_reason": validity_reason, "process_exit": pre["process_exit"],
            }
            atomic_json(td / "score.json", score)
            scores.append(score)
    return scores


def iqr(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return round(percentile(values, .75) - percentile(values, .25), 1)


def aggregate_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [s for s in scores if s.get("validity") == "valid"]
    by_puzzle: dict[str, list[dict[str, Any]]] = {}
    for score in valid:
        by_puzzle.setdefault(score["puzzle_id"], []).append(score)
    puzzle_summary: dict[str, Any] = {}
    for pid, items in sorted(by_puzzle.items()):
        totals = [float(x["scores"]["total"]) for x in items]
        solved = [x for x in items if x["status"] == "solved"]
        puzzle_summary[pid] = {
            "score_median": round(statistics.median(totals), 1), "score_iqr": iqr(totals),
            "success_rate": round(len(solved) / len(items), 3),
            "rounds_median": round(statistics.median([x["raw"]["rounds"] for x in items]), 1),
        }
    strata: dict[str, float] = {}
    for typ in ("C", "A"):
        for diff in ("E", "M", "H"):
            vals = [v["score_median"] for pid, v in puzzle_summary.items() if f"-{typ}-{diff}-" in pid]
            if vals:
                strata[f"{typ}-{diff}"] = round(statistics.mean(vals), 1)
    dimensions = {}
    keys = ["outcome_round_efficiency", "reasoning_chain", "question_information", "hint_strategy", "consistency_recovery", "final_closure", "response_speed"]
    for key in keys:
        dimensions[key] = round(statistics.mean([float(s["scores"].get(key, 0.0)) for s in valid]), 1) if valid else None
    tags: dict[str, int] = {}
    for s in valid:
        for tag in s.get("failure_tags", []):
            tags[tag] = tags.get(tag, 0) + 1
    resource_rows = [s for s in scores if isinstance(s.get("raw", {}).get("player_usage"), dict)]
    token_keys = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "api_call_count")
    player_resources = {
        "games": len(scores),
        "games_with_usage": len(resource_rows),
        "player_active_time_s": round(sum(float(s.get("raw", {}).get("player_active_time_s", 0)) for s in scores), 3),
    }
    for key in token_keys:
        player_resources[key] = sum(int(s["raw"]["player_usage"].get(key, 0)) for s in resource_rows)
        player_resources[f"average_{key}_per_game"] = round(player_resources[key] / len(resource_rows), 3) if resource_rows else 0.0
    player_resources["average_player_active_time_s"] = round(player_resources["player_active_time_s"] / len(scores), 3) if scores else 0.0
    return {
        "overall_score": round(statistics.mean(strata.values()), 1) if strata else None,
        "success_rate": round(sum(s["status"] == "solved" for s in valid) / len(valid), 3) if valid else None,
        "rounds_median": round(statistics.median([s["raw"]["rounds"] for s in valid]), 1) if valid else None,
        "hints_used_rate": round(sum(s["raw"]["hints_used"] > 0 for s in valid) / len(valid), 3) if valid else None,
        "player_latency_p50_s": round(statistics.median([s["raw"]["player_latency_p50_s"] for s in valid]), 3) if valid else None,
        "player_latency_p90_s": round(statistics.median([s["raw"]["player_latency_p90_s"] for s in valid]), 3) if valid else None,
        "valid_games": len(valid), "invalid_games": len(scores) - len(valid),
        "strata": strata, "dimensions": dimensions, "failure_tags": dict(sorted(tags.items())),
        "puzzles": puzzle_summary,
        "player_resources": player_resources,
    }


async def run_player(
    run_dir: Path,
    player: dict[str, str],
    manifest: dict[str, Any],
    repeats: int,
    concurrency: int,
    timeout_s: int,
    max_attempts: int = 100,
) -> dict[str, Any]:
    if repeats != 3:
        raise RuntimeError("current judge path requires exactly 3 repeats")
    target_valid_games = len(manifest["puzzles"]) * repeats
    validate_attempt_limit(max_attempts, target_valid_games)
    state_path = run_dir / "games" / player["slug"] / "attempts.json"
    state = load_attempt_state(run_dir, player["slug"], max_attempts, target_valid_games)
    slots = {
        f"{puzzle['id']}:{trial:02d}": (puzzle, trial)
        for trial in range(1, repeats + 1)
        for puzzle in manifest["puzzles"]
    }
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(puzzle: dict[str, Any], trial: int):
        async with semaphore:
            return await run_game(run_dir, player, puzzle, trial, timeout_s)

    while True:
        pending = [key for key in state.get("pending_slots", []) if key in slots]
        missing = []
        resumable = []
        for key, (puzzle, trial) in slots.items():
            trial_dir = run_dir / "games" / player["slug"] / puzzle["id"] / f"trial-{trial:02d}"
            game_path = trial_dir / "game.json"
            preliminary_path = trial_dir / "preliminary.json"
            if not game_path.exists():
                if key not in pending:
                    missing.append(key)
            elif game_needs_run(game_path, preliminary_path):
                resumable.append(key)
        reserved = reserve_attempt_slots(state_path, state, missing) if missing else []
        runnable = list(dict.fromkeys([*pending, *reserved, *resumable]))
        if runnable:
            await asyncio.gather(*(guarded(*slots[key]) for key in runnable))
            state["pending_slots"] = []
            state["updated_at"] = now_iso()
            atomic_json(state_path, state)

        await asyncio.gather(*(run_judge(run_dir, player, p, timeout_s) for p in manifest["puzzles"]))
        scores = finalize_scores(run_dir, player, manifest)
        valid_games = sum(score.get("validity") == "valid" for score in scores)
        should_stop, limit_reached = retry_stop_state(
            valid_games, target_valid_games, int(state["attempts_started"]), max_attempts
        )
        if should_stop:
            summary = aggregate_scores(scores)
            summary.update({
                "player": player,
                "target_valid_games": target_valid_games,
                "attempts_started": int(state["attempts_started"]),
                "max_attempts": max_attempts,
                "attempt_limit_reached": limit_reached,
            })
            atomic_json(run_dir / "summaries" / f"{player['slug']}.json", summary)
            return summary

        remaining = max_attempts - int(state["attempts_started"])
        state["retry_round"] = int(state.get("retry_round", 0)) + 1
        state["updated_at"] = now_iso()
        atomic_json(state_path, state)
        archive_root = (
            run_dir / "retry-archives" / "auto" / player["slug"] /
            f"round-{state['retry_round']:03d}"
        )
        archived = archive_invalid_trials(run_dir, [player["slug"]], archive_root, max_trials=remaining)
        if archived[player["slug"]] == 0:
            raise RuntimeError(f"{player['slug']} has {valid_games}/{target_valid_games} valid games but no invalid trials to retry")


def render_report(run_meta: dict[str, Any], summaries: list[dict[str, Any]]) -> str:
    def number(value: Any) -> str:
        return "N/A" if value is None else f"{value:.1f}"

    def percent(value: Any) -> str:
        return "N/A" if value is None else f"{value:.1%}"

    display_names = {p["slug"]: p.get("display_name", p["slug"]) for p in PLAYER_MATRIX}

    lines = ["# Situation Puzzle Baseline", "", f"- Run: `{run_meta['run_id']}`", "- Suite: `fixed-v1`", "- Host: `openai-codex / gpt-5.6-luna / max`", f"- Session source: `{run_meta['session_source']}`", f"- Repeats: {run_meta['repeats']}", ""]
    lines += ["| Player | Score | Success | Rounds median | Hint rate | Valid/Invalid |", "|---|---:|---:|---:|---:|---:|"]
    for s in summaries:
        p=s["player"]
        lines.append(f"| {display_names.get(p['slug'], p['slug'])} | {number(s['overall_score'])} | {percent(s['success_rate'])} | {number(s['rounds_median'])} | {percent(s['hints_used_rate'])} | {s['valid_games']}/{s['invalid_games']} |")
    lines += ["", "## Strata", "", "| Player | C-E | C-M | C-H | A-E | A-M | A-H |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in summaries:
        st=s["strata"]
        slug = s["player"]["slug"]
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(display_names.get(slug, slug),*[st.get(k,"-") for k in ("C-E","C-M","C-H","A-E","A-M","A-H")]))
    return "\n".join(lines)+"\n"


async def async_main(args: argparse.Namespace) -> None:
    global RUNTIME
    RUNTIME = RuntimePaths(
        fixtures=args.fixtures.expanduser().resolve(),
        runs_dir=args.runs_dir.expanduser().resolve(),
        state_db=args.state_db.expanduser().resolve(),
    )
    manifest = verify_suite(RUNTIME.fixtures)
    run_id = args.run_id or f"baseline-luna-max-host-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = RUNTIME.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(args.players.split(",")) if args.players else {p["slug"] for p in PLAYER_MATRIX}
    players = [p for p in PLAYER_MATRIX if p["slug"] in wanted]
    unknown = wanted - {p["slug"] for p in PLAYER_MATRIX}
    if unknown:
        raise RuntimeError(f"unknown players: {sorted(unknown)}")
    meta_path = run_dir / "run.json"
    meta = load_json(meta_path) if meta_path.exists() else {
        "run_id": run_id, "suite_version": "fixed-v1", "manifest": str(RUNTIME.fixtures / "manifest.json"),
        "host": HOST, "players": players, "repeats": args.repeats, "max_rounds": 50,
        "player_hint_limit": 2, "concurrency": args.concurrency, "session_source": SESSION_SOURCE, "started_at": now_iso(),
        "status": "running", "completed_players": [],
    }
    if meta.get("session_source", SESSION_SOURCE) != SESSION_SOURCE:
        raise RuntimeError(f"run source mismatch: {meta.get('session_source')} != {SESSION_SOURCE}")
    meta["session_source"] = SESSION_SOURCE
    meta["max_attempts_per_player"] = args.max_attempts_per_player
    atomic_json(meta_path, meta)
    summaries=[]
    for player in players:
        summary_path = run_dir / "summaries" / f"{player['slug']}.json"
        existing_summary = load_json(summary_path) if summary_path.exists() else None
        if existing_summary is not None and not summary_needs_retry(existing_summary, TARGET_VALID_GAMES):
            summary = existing_summary
        else:
            summary=await run_player(
                run_dir, player, manifest, args.repeats, args.concurrency, args.timeout,
                max_attempts=args.max_attempts_per_player,
            )
        summaries.append(summary)
        if player["slug"] not in meta["completed_players"]:
            meta["completed_players"].append(player["slug"])
        atomic_json(meta_path, meta)
    meta["status"]="completed"; meta["completed_at"]=now_iso(); atomic_json(meta_path,meta)
    atomic_json(run_dir / "summary.json", {"run": meta, "models": summaries})
    (run_dir / "REPORT.md").write_text(render_report(meta,summaries),encoding="utf-8")
    print(run_dir)


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description="Run the TurtleBench situation-puzzle benchmark")
    parser.add_argument("--run-id")
    parser.add_argument("--players", help="comma-separated slugs")
    parser.add_argument("--repeats",type=int,default=3)
    parser.add_argument("--concurrency",type=int,default=12)
    parser.add_argument("--timeout",type=int,default=7200)
    parser.add_argument("--max-attempts-per-player", type=attempt_limit_arg, default=100)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB)
    return parser


def main() -> None:
    asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    main()
