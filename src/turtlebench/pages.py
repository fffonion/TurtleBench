"""Export sanitized benchmark aggregates for the TurtleBench dashboard."""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

_TRIAL_DIR = re.compile(r"^trial-\d+$")
_LAB_PREFIX = {
    "claude": "Claude",
    "deepseek": "DeepSeek",
    "gpt": "GPT",
    "grok": "Grok",
    "minimax": "MiniMax",
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _public_model_name(model_id: str) -> str:
    leaf = model_id.rsplit("/", 1)[-1]
    words = leaf.replace("-", " ").split()
    if not words:
        return model_id
    first = words[0].lower()
    if first == "gpt" and len(words) > 1:
        version = words[1]
        rest = " ".join(word.capitalize() for word in words[2:])
        return f"GPT-{version}{' ' + rest if rest else ''}"
    if first in _LAB_PREFIX:
        return " ".join([_LAB_PREFIX[first], *[word.upper() if word == "m3" else word.capitalize() for word in words[1:]]])
    return " ".join(word.capitalize() for word in words)


def _valid_hint_values(run_dir: Path, slug: str) -> list[int | float]:
    values: list[int | float] = []
    games_dir = run_dir / "games" / slug
    if not games_dir.exists():
        return values
    for path in games_dir.glob("*/trial-*/score.json"):
        if not _TRIAL_DIR.fullmatch(path.parent.name):
            continue
        score = _read_json(path)
        if score.get("validity") != "valid":
            continue
        raw = score.get("raw")
        if not isinstance(raw, dict):
            continue
        hints = raw.get("hints_used")
        if isinstance(hints, (int, float)) and not isinstance(hints, bool):
            values.append(hints)
    return values


def _public_model(run_dir: Path, summary: dict[str, Any], pricing: dict[str, Any]) -> dict[str, Any]:
    player = summary.get("player")
    resources = summary.get("player_resources")
    if not isinstance(player, dict) or not isinstance(resources, dict):
        raise ValueError("summary requires player and player_resources objects")

    slug = str(player["slug"])
    token_counts = {
        "input": int(resources.get("input_tokens", 0)),
        "output": int(resources.get("output_tokens", 0)),
        "cache_read": int(resources.get("cache_read_tokens", 0)),
        "cache_write": int(resources.get("cache_write_tokens", 0)),
    }
    hints = _valid_hint_values(run_dir, slug)
    tokens = {"total": sum(token_counts.values()), **token_counts}
    model_id = str(player["model"])
    return {
        "slug": slug,
        "name": _public_model_name(model_id),
        "provider": str(player["provider"]),
        "model": model_id,
        "family": model_id.rsplit("/", 1)[-1],
        "reasoning_effort": str(player["reasoning_effort"]),
        "overall_score": float(summary["overall_score"]),
        "games": int(resources.get("games", summary.get("valid_games", 0))),
        "active_time_s": float(resources.get("player_active_time_s", 0.0)),
        "tokens": tokens,
        "price_usd": pricing.get(slug),
        "behavior": {
            "solve_rate": float(summary["success_rate"]),
            "rounds_median": float(summary["rounds_median"]),
            "hints_median": statistics.median(hints) if hints else None,
            "samples": int(summary.get("valid_games", resources.get("games", 0))),
        },
    }


def build_public_run(run_dir: str | Path, pricing: dict[str, Any]) -> dict[str, Any]:
    """Build an allowlisted public aggregate from one benchmark run directory."""

    run_path = Path(run_dir)
    summaries_dir = run_path / "summaries"
    if not summaries_dir.is_dir():
        raise ValueError(f"missing summaries directory: {summaries_dir}")
    models = [
        _public_model(run_path, _read_json(path), pricing)
        for path in sorted(summaries_dir.glob("*.json"))
    ]
    if not models:
        raise ValueError("run has no model summaries")
    return {"run_id": run_path.name, "models": models}
