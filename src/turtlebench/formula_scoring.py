"""Unified formula scoring for fixed-version situation-puzzle runs."""

from __future__ import annotations

import difflib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Mapping

FORMULA_SCORE_VERSION = "single"
FIT_INTERCEPT = 38.564459810166795
SOLVE_RATE_COEFFICIENT = 0.500871780911417
INFRASTRUCTURE_VALIDITIES = {"invalid_host", "invalid_infrastructure"}
ACTIVE_STATES = {"running", "player_turn", "host_turn", "awaiting_host"}

_COMPOUND_MARKERS = ("还是", "或者", "而不是", "以及", "并且", "同时", ";", "；")
_PUNCTUATION = re.compile(r"[\s，。！？、；：,.!?;:（）()\[\]{}\"'‘’“”]")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def unified_formula_score(solve_rate: float) -> float:
    """Return the fitted 0-100 score using only the observed solve rate."""

    rate = float(solve_rate)
    if not math.isfinite(rate):
        raise ValueError("solve rate must be finite")
    rate = _clip(rate)
    return round(max(0.0, min(100.0, FIT_INTERCEPT + SOLVE_RATE_COEFFICIENT * rate * 100.0)), 2)


def classify_trial_state(
    game: Mapping[str, Any],
    preliminary: Mapping[str, Any] | None = None,
    score: Mapping[str, Any] | None = None,
) -> str:
    """Classify a primary trial; a valid player error is a failed sample."""

    records = [record for record in (score, preliminary) if isinstance(record, Mapping)]
    if any(record.get("validity") in INFRASTRUCTURE_VALIDITIES for record in records):
        return "infrastructure"
    status = str(game.get("status", ""))
    if status in ACTIVE_STATES or not status:
        return "pending"
    if status == "error":
        if any(record.get("validity") == "valid" for record in records):
            return "failure"
        return "infrastructure"
    if status == "solved":
        return "solved"
    if status in {"max_rounds", "stopped"}:
        return "failure"
    return "infrastructure"


def _normalize_question(text: str) -> str:
    return _PUNCTUATION.sub("", text.lower())


def _response_yield(text: str) -> float:
    value = text.strip()
    if value.startswith(("不相关", "无关")):
        return 0.0
    if value.startswith("是也不是") or value.startswith("部分"):
        return 0.5
    if value.startswith("是") or value.startswith("不是"):
        return 1.0
    return 0.5


def question_quality(game: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate reproducible question quality from the public event stream."""

    events = game.get("events", [])
    if not isinstance(events, list):
        events = []
    questions: list[str] = []
    responses: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        actor = event.get("actor")
        event_type = event.get("type")
        text = str(event.get("text", "")).strip()
        if actor == "player" and event_type == "question" and text:
            questions.append(text)
        elif actor == "host" and event_type == "response" and text:
            responses.append(text)

    question_count = len(questions)
    if question_count == 0:
        return {
            "factor": 0.0,
            "score": 0.0,
            "question_count": 0,
            "response_count": len(responses),
            "atomicity": 0.0,
            "response_yield": 0.0,
            "novelty": 0.0,
        }

    compound_count = sum(any(marker in text for marker in _COMPOUND_MARKERS) for text in questions)
    atomicity = 1.0 - compound_count / question_count
    normalized = [_normalize_question(text) for text in questions]
    duplicate_count = 0
    for index, current in enumerate(normalized):
        if any(
            difflib.SequenceMatcher(None, current, previous).ratio() >= 0.9
            for previous in normalized[:index]
            if current and previous
        ):
            duplicate_count += 1
    novelty = 1.0 - duplicate_count / question_count
    paired_responses = responses[:question_count]
    response_yield = (
        statistics.mean(_response_yield(text) for text in paired_responses)
        if paired_responses
        else 0.0
    )
    factor = _clip(0.4 * atomicity + 0.35 * response_yield + 0.25 * novelty)
    return {
        "factor": round(factor, 6),
        "score": round(10.0 * factor, 6),
        "question_count": question_count,
        "response_count": len(responses),
        "atomicity": round(atomicity, 6),
        "response_yield": round(response_yield, 6),
        "novelty": round(novelty, 6),
    }


def _stratum_key(puzzle: Mapping[str, Any]) -> str:
    puzzle_id = str(puzzle.get("id", ""))
    parts = puzzle_id.split("-")
    if len(parts) >= 3 and parts[1] and parts[2]:
        return f"{parts[1]}-{parts[2]}"
    type_code = "C" if str(puzzle.get("type", "")).startswith("浓") else "A"
    difficulty_code = {"简单": "E", "中等": "M", "困难": "H"}.get(
        str(puzzle.get("difficulty", "")), "U"
    )
    return f"{type_code}-{difficulty_code}"


def formula_summary_from_run(
    run_dir: str | Path,
    player_slug: str,
    manifest: Mapping[str, Any],
    repeats: int = 3,
) -> dict[str, Any]:
    """Score the expected sample set from solved trials only."""

    if repeats < 1:
        raise ValueError("repeats must be positive")
    puzzles = manifest.get("puzzles")
    if not isinstance(puzzles, list):
        raise ValueError("manifest requires a puzzles list")

    root = Path(run_dir) / "games" / player_slug
    trial_records = 0
    terminal_trial_records = 0
    infrastructure_trials = 0
    pending_trials = 0
    solved_trials = 0
    puzzles_observed = 0
    puzzles_covered = 0
    question_quality_scores: list[float] = []
    puzzle_details: dict[str, dict[str, Any]] = {}

    for puzzle in puzzles:
        if not isinstance(puzzle, dict):
            raise ValueError("manifest puzzle entries must be objects")
        puzzle_id = str(puzzle["id"])
        puzzle_root = root / puzzle_id
        observed = terminal = infra = pending = solved_count = 0
        for trial in range(1, repeats + 1):
            trial_dir = puzzle_root / f"trial-{trial:02d}"
            game_path = trial_dir / "game.json"
            if not game_path.exists():
                continue
            observed += 1
            game = _read_json(game_path)
            question_quality_scores.append(question_quality(game)["score"])
            preliminary_path = trial_dir / "preliminary.json"
            score_path = trial_dir / "score.json"
            preliminary = _read_json(preliminary_path) if preliminary_path.exists() else {}
            score = _read_json(score_path) if score_path.exists() else {}
            state = classify_trial_state(game, preliminary, score)
            if state == "infrastructure":
                infra += 1
                continue
            if state == "pending":
                pending += 1
                continue
            terminal += 1
            if state == "solved":
                solved_count += 1

        trial_records += observed
        puzzles_observed += int(observed > 0)
        terminal_trial_records += terminal
        infrastructure_trials += infra
        pending_trials += pending
        solved_trials += solved_count
        puzzles_covered += int(terminal > 0)
        puzzle_details[puzzle_id] = {
            "solved_count": solved_count,
            "terminal_trials": terminal,
            "records": observed,
            "expected_trials": repeats,
            "infrastructure_trials": infra,
            "pending_trials": pending,
            "solve_rate": round(solved_count / repeats, 3),
            "stratum": _stratum_key(puzzle),
        }

    total_trials = len(puzzles) * repeats
    solve_rate = solved_trials / total_trials if total_trials else 0.0
    formula_score = unified_formula_score(solve_rate)
    baseline_component = round(FIT_INTERCEPT, 2)
    solve_component = round(SOLVE_RATE_COEFFICIENT * solve_rate * 100.0, 2)
    return {
        "score_version": FORMULA_SCORE_VERSION,
        "overall_score": formula_score,
        "baseline_component": baseline_component,
        "solve_rate_coefficient": SOLVE_RATE_COEFFICIENT,
        "solve_rate": round(solve_rate, 6),
        "solve_component": solve_component,
        "provisional": terminal_trial_records < total_trials,
        "puzzles_covered": puzzles_covered,
        "puzzles_observed": puzzles_observed,
        "puzzles_total": len(puzzles),
        "trial_records": trial_records,
        "terminal_trial_records": terminal_trial_records,
        "expected_trials": total_trials,
        "coverage": round(terminal_trial_records / total_trials, 3) if total_trials else 0.0,
        "observed_coverage": round(trial_records / total_trials, 3) if total_trials else 0.0,
        "infrastructure_trials": infrastructure_trials,
        "pending_trials": pending_trials,
        "solved_trials": solved_trials,
        "solved_puzzles": sum(detail["solved_count"] > 0 for detail in puzzle_details.values()),
        "mixed_puzzles": sum(0 < detail["solved_count"] < repeats for detail in puzzle_details.values()),
        "stability_score": round(solve_rate, 3),
        "question_quality_score": round(statistics.mean(question_quality_scores), 3) if question_quality_scores else 0.0,
        "strata": {},
        "puzzles": puzzle_details,
    }
