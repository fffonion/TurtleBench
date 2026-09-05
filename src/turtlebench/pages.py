"""Export sanitized benchmark aggregates for the TurtleBench dashboard."""

from __future__ import annotations

import json
import re
import statistics
from decimal import Decimal
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


def load_mapping(path: str | Path) -> dict[str, Any]:
    """Load the versioned benchmark-to-models.dev identity mapping."""

    return _read_json(Path(path))


def resolve_pricing(
    provider: str,
    model: str,
    mapping: dict[str, Any],
    catalog: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    """Resolve a benchmark identity to a non-promotional models.dev rate snapshot."""

    source = mapping.get(f"{provider}:{model}")
    if not isinstance(source, dict):
        raise ValueError(f"missing models.dev mapping for {provider}:{model}")
    source_provider = str(source["provider"])
    source_model = str(source["model"])
    if any(term in source_provider.lower() for term in ("token-plan", "free")):
        raise ValueError(f"refusing plan price from {source_provider}")
    try:
        entry = catalog[source_provider]["models"][source_model]
        cost = entry["cost"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"missing models.dev price for {source_provider}:{source_model}") from exc
    if not isinstance(cost, dict):
        raise ValueError(f"missing models.dev cost object for {source_provider}:{source_model}")
    if any(key in cost for key in ("discount", "promotion", "promotional", "trial")):
        raise ValueError(f"refusing promotional price for {source_provider}:{source_model}")

    selected = dict(cost)
    for key in ("off_peak", "offpeak"):
        if isinstance(cost.get(key), dict):
            selected.update(cost[key])
            break
    if selected.get("input") == 0 and selected.get("output") == 0:
        raise ValueError(f"refusing free-plan price for {source_provider}:{source_model}")

    rates: dict[str, float | None] = {}
    for category in ("input", "output", "cache_read", "cache_write"):
        value = selected.get(category)
        rates[category] = float(value) if isinstance(value, (int, float)) else None
    return {
        "source": "https://models.dev",
        "source_model_id": str(source["canonical_model"]),
        "source_provider_id": source_provider,
        "fetched_at": fetched_at,
        "usd_per_million_tokens": rates,
    }


def calculate_price(tokens: dict[str, int], pricing: dict[str, Any]) -> dict[str, float | None]:
    """Calculate USD token-category costs from a models.dev rate snapshot."""

    rates = pricing.get("usd_per_million_tokens")
    if not isinstance(rates, dict):
        raise ValueError("pricing snapshot requires usd_per_million_tokens")
    result: dict[str, float | None] = {}
    for category in ("input", "output", "cache_read", "cache_write"):
        count = int(tokens.get(category, 0))
        rate = rates.get(category)
        if rate is None:
            result[category] = 0.0 if count == 0 else None
            continue
        amount = Decimal(count) * Decimal(str(rate)) / Decimal(1_000_000)
        result[category] = round(float(amount), 12)
    components = [result[key] for key in ("input", "output", "cache_read", "cache_write")]
    if any(value is None for value in components):
        result["total"] = None
    else:
        result["total"] = round(sum(value for value in components if value is not None), 12)
    return result


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
    price_snapshot = pricing.get(slug)
    price_usd = calculate_price(tokens, price_snapshot) if isinstance(price_snapshot, dict) else None
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
        "price_usd": price_usd,
        "pricing": price_snapshot,
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
