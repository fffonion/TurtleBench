#!/usr/bin/env python3
"""Concurrent, resumable situation-puzzle benchmark runner."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import http.client
import json
import math
import os
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import game_mailbox
from .formula_scoring import formula_summary_from_run

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES = PROJECT_ROOT / "fixtures" / "fixed-v1"
DEFAULT_RUNS = PROJECT_ROOT / "runs"
DEFAULT_STATE_DB = Path.home() / ".hermes" / "state.db"
MAILBOX_COMMAND = f"PYTHONPATH={PROJECT_ROOT / 'src'} {PROJECT_ROOT / '.venv/bin/python'} -m turtlebench.game_mailbox"


@dataclass(frozen=True)
class RuntimePaths:
    fixtures: Path
    runs_dir: Path
    state_db: Path


RUNTIME = RuntimePaths(DEFAULT_FIXTURES, DEFAULT_RUNS, DEFAULT_STATE_DB)
TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
# Provider 429 wording differs per upstream API: Hermes HTTP envelopes, and
# provider payloads echoed inside a failed run (SenseNova reports
# "Error code: 429 ... rpm exhausted ... quota_exceeded_error"). All of them
# must be recognized as a rate limit so a quota window wait replaces an
# instant retry that burns a trial.
RATE_LIMIT_MARKERS = (
    "http 429",
    "status=429",
    "error code: 429",
    "too many requests",
    "rate limit",
    "rate limited",
    "rpm exhausted",
    "quota_exceeded",
)
DEFAULT_API_RETRY_ATTEMPTS = 8
DEFAULT_API_RETRY_BASE_SECONDS = 1.0
DEFAULT_API_RETRY_MAX_SECONDS = 30.0
# SenseNova's free token plan also enforces a per-minute request cap and
# reports it as "rpm exhausted". That limit resets within a minute or two, so
# it gets a short backoff instead of waiting for the next quota window.
DEFAULT_RPM_BACKOFF_SECONDS = 65.0
RPM_RATE_LIMIT_MARKERS = ("rpm exhausted", "rpm limit", "requests per minute")
JUDGE_RETRY_BASE_SECONDS = 2.0
JUDGE_RETRY_MAX_SECONDS = 60.0
HOST = {"provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "max"}
JUDGE = HOST.copy()
PLAYER_MATRIX = [
    {"slug": "luna-max", "display_name": "Luna max baseline", "provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "max"},
    {"slug": "luna-high", "display_name": "Luna high baseline", "provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "high"},
    {"slug": "minimax-m3-max", "display_name": "OpenRouter / MiniMax M3 max", "provider": "openrouter", "model": "minimax/minimax-m3:free", "reasoning_effort": "max"},
    {"slug": "openrouter-stealth-union-alpha-high", "display_name": "OpenRouter / stealth/union-alpha high", "provider": "openrouter", "model": "stealth/union-alpha", "reasoning_effort": "high"},
    {"slug": "deepseek-v4-flash-max", "display_name": "CommandCode / DeepSeek V4 Flash max", "provider": "commandcode", "model": "deepseek-ai/deepseek-v4-flash", "reasoning_effort": "max"},
    {"slug": "deepseek-provider-v4-flash-max", "display_name": "DeepSeek provider / DeepSeek V4 Flash max", "provider": "deepseek", "model": "deepseek-v4-flash", "reasoning_effort": "max"},
    {"slug": "deepseek-deepseek-v4-1-flash-max", "display_name": "DeepSeek / DeepSeek V4.1 Flash max", "provider": "deepseek", "model": "deepseek-v4.1-flash-expires-on-0910", "reasoning_effort": "max"},
    {"slug": "kong-ai-gateway-zai-org-glm-5-3-high", "display_name": "Kong AI Gateway / zai-org/GLM-5.3 high", "provider": "kong-ai-gateway", "model": "zai-org/GLM-5.3", "reasoning_effort": "high"},
    {"slug": "kong-ai-gateway-zai-org-glm-5-3-flash-high", "display_name": "Kong AI Gateway / zai-org/GLM-5.3-Flash high", "provider": "kong-ai-gateway", "model": "zai-org/GLM-5.3-Flash", "reasoning_effort": "high"},
    {"slug": "kong-ai-gateway-zai-org-glm-5-3-flash-max", "display_name": "Kong AI Gateway / zai-org/GLM-5.3-Flash max", "provider": "kong-ai-gateway", "model": "zai-org/GLM-5.3-Flash", "reasoning_effort": "max"},
    {"slug": "commandcode-deepseek-v4-1-flash-beta-high", "display_name": "CommandCode / deepseek/deepseek-v4.1-flash-beta high", "provider": "commandcode", "model": "deepseek/deepseek-v4.1-flash-beta", "reasoning_effort": "high"},
    {"slug": "commandcode-deepseek-v4-1-flash-high", "display_name": "CommandCode / deepseek/deepseek-v4.1-flash high", "provider": "commandcode", "model": "deepseek/deepseek-v4.1-flash", "reasoning_effort": "high"},
    {"slug": "claude-sonnet-5-high", "display_name": "Anthropic / Claude Sonnet 5 high", "provider": "anthropic", "model": "claude-sonnet-5", "reasoning_effort": "high"},
    {"slug": "gpt-5-6-sol-high", "display_name": "OpenAI Codex / GPT-5.6 Sol high", "provider": "openai-codex", "model": "gpt-5.6-sol", "reasoning_effort": "high"},
    {"slug": "gpt-5-6-sol-medium", "display_name": "OpenAI Codex / GPT-5.6 Sol medium", "provider": "openai-codex", "model": "gpt-5.6-sol", "reasoning_effort": "medium"},
    {"slug": "gpt-6-astra-high", "display_name": "OpenAI Codex / GPT-6 Astra high", "provider": "openai-codex", "model": "gpt-6-astra", "reasoning_effort": "high"},
    {"slug": "grok-4-6-high", "display_name": "Supplemental / Grok 4.6 high", "provider": "xai-oauth", "model": "grok-4.6", "reasoning_effort": "high"},
    {"slug": "bai-qwen3-8-flash-max", "display_name": "Bai / qwen3.8-flash max", "provider": "bai", "model": "qwen3.8-flash", "reasoning_effort": "max"},
    {"slug": "hcnsec-qwen3-8-flash-next-xhigh", "display_name": "HCNSEC / Qwen3.8-Flash-Next xhigh", "provider": "hcnsec", "model": "Qwen3.8-Flash-Next", "reasoning_effort": "xhigh"},
    {"slug": "sensenova-6-8-flash-lite", "display_name": "SenseNova / sensenova-6.8-flash-lite (provider default)", "provider": "sensenova", "model": "sensenova-6.8-flash-lite", "reasoning_effort": "default"},
]
TERMINAL_STATES = {"solved", "max_rounds", "stopped", "error"}
TERMINAL_VALIDITIES = {"valid", "invalid_host", "invalid_infrastructure"}
RESUMED_PAUSE_MARKERS = ("infrastructure_pause", "rate_limit_wait")
NON_RESUMABLE_FAULT_MARKERS = (
    "主持泄露", "泄露", "关键矛盾", "矛盾", "提前退出", "轨迹不足", "协议错误",
)
FAULT_NEGATIONS = ("未见", "未发现", "未出现", "不存在", "没有", "未经")


def mentions_unresolved_fault(reason: str) -> bool:
    """True when the reason asserts a non-infrastructure fault, ignoring negated clauses."""

    for sentence in re.split(r"[；;。\n]", str(reason or "")):
        if any(negation in sentence for negation in FAULT_NEGATIONS):
            continue
        if any(marker in sentence for marker in NON_RESUMABLE_FAULT_MARKERS):
            return True
    return False


def settle_infrastructure_validity(
    status: Any, failed_roles: list[str], judge_validity: Any, judge_reason: Any = "",
) -> str:
    """Settle a judge infrastructure verdict when the pause was already resumed.

    A paused game that later reached a terminal state on the same session is not an
    infrastructure failure: the pause record only proves the run survived a rate limit.
    """

    if failed_roles:
        return "invalid_infrastructure"
    verdict = str(judge_validity or "valid")
    reason = str(judge_reason or "")
    if verdict != "invalid_infrastructure":
        return verdict
    if str(status) not in {"solved", "max_rounds"}:
        return verdict
    if mentions_unresolved_fault(reason):
        return verdict
    if not any(marker in reason for marker in RESUMED_PAUSE_MARKERS):
        return verdict
    return "valid"
SESSION_SOURCE = "turtle-soup"
TARGET_VALID_GAMES = 36
FIXTURE_RELEASE_URL = "https://github.com/fffonion/TurtleBench/releases/download/fixtures-v1/turtlebench-fixed-v1.zip"
FIXTURE_ARCHIVE_SHA256 = "c28746c7b8296a2b8eb36aef6c6cff5ae9418283409c291eaac139c772646069"
FIXTURE_ARCHIVE_PASSWORD = "123456"
JUDGE_REQUIRED_FIELDS = frozenset({
    "trial", "validity", "atomic_question_rate", "useful_constraint_rate",
    "redundant_question_rate", "unsupported_story_guess_rate", "irrelevant_branch_max",
    "contradiction_count", "partial_misread_count", "excluded_revisit_count",
    "protocol_recovery_failure_count", "reasoning_chain_parts", "question_information_parts",
    "final_closure", "hint_effective_count", "hint_ineffective_count", "hint_early_count",
    "hint_consecutive", "hint_hoarding", "failure_tags", "notes",
})


def retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


class HermesApiError(RuntimeError):
    def __init__(
        self,
        status: int | None,
        detail: str,
        retry_after: float | None = None,
        retryable: bool | None = None,
    ):
        super().__init__(detail)
        self.status = status
        self.retry_after = retry_after
        self.retryable = (
            status is None or status in TRANSIENT_HTTP_STATUSES
            if retryable is None else retryable
        )


@dataclass(frozen=True)
class HermesTurnResult:
    output: str
    usage: dict[str, Any]
    run_id: str


def next_quota_window_epoch(
    window_start_epoch: float,
    window_seconds: float,
    *,
    now: float | None = None,
) -> float:
    if window_seconds <= 0:
        raise ValueError("quota window must be positive")
    current = time.time() if now is None else now
    if current < window_start_epoch:
        return window_start_epoch
    completed_windows = math.floor((current - window_start_epoch) / window_seconds) + 1
    return window_start_epoch + completed_windows * window_seconds


class HermesApiClient:
    """Small synchronous client for Hermes API Server's persisted run API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        poll_interval: float = 0.1,
        retry_attempts: int = DEFAULT_API_RETRY_ATTEMPTS,
        retry_base_seconds: float = DEFAULT_API_RETRY_BASE_SECONDS,
        retry_max_seconds: float = DEFAULT_API_RETRY_MAX_SECONDS,
        quota_window_seconds: float | None = None,
        quota_window_start_epoch: float | None = None,
        rpm_backoff_seconds: float = DEFAULT_RPM_BACKOFF_SECONDS,
    ):
        if retry_attempts < 1:
            raise ValueError("retry attempts must be at least one")
        if retry_base_seconds < 0 or retry_max_seconds < retry_base_seconds:
            raise ValueError("retry delay bounds are invalid")
        if rpm_backoff_seconds < 0:
            raise ValueError("rpm backoff must not be negative")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.retry_attempts = retry_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.rpm_backoff_seconds = rpm_backoff_seconds
        if quota_window_seconds is not None and quota_window_seconds <= 0:
            raise ValueError("quota window must be positive")
        self.quota_window_seconds = quota_window_seconds
        self.quota_window_start_epoch = (
            (time.time() if quota_window_start_epoch is None else quota_window_start_epoch)
            if quota_window_seconds is not None else None
        )
        self._retry_state = threading.local()
        self._quota_wait_seconds_total = 0.0
        self._disabled_toolsets: list[str] | None = None

    @property
    def _quota_wait_seconds_total(self) -> float:
        return getattr(self._retry_state, "wait_seconds", 0.0)

    @_quota_wait_seconds_total.setter
    def _quota_wait_seconds_total(self, value: float) -> None:
        self._retry_state.wait_seconds = value

    @staticmethod
    def is_rate_limit_error(exc: BaseException) -> bool:
        if getattr(exc, "status", None) == 429:
            return True
        normalized = str(exc).casefold()
        return any(marker in normalized for marker in RATE_LIMIT_MARKERS)

    @staticmethod
    def is_rpm_rate_limit_error(exc: BaseException) -> bool:
        normalized = str(exc).casefold()
        return any(marker in normalized for marker in RPM_RATE_LIMIT_MARKERS)

    def _check_cancelled(self) -> None:
        event = getattr(self._retry_state, "cancellation_event", None)
        if event is not None and event.is_set():
            raise asyncio.CancelledError()

    def _sleep(self, seconds: float) -> None:
        event = getattr(self._retry_state, "cancellation_event", None)
        if event is None:
            time.sleep(seconds)
        elif event.wait(seconds):
            raise asyncio.CancelledError()

    def wait_out_rpm_limit(self) -> float:
        delay = max(0.0, self.rpm_backoff_seconds)
        if delay:
            print(f"RPM limit; sleeping {delay:.0f}s before retrying", flush=True)
            self._sleep(delay)
            self._quota_wait_seconds_total += delay
        return delay

    def _resubmit_after_rate_limit(self, exc: BaseException) -> bool:
        """Wait out a provider rate limit so the caller resubmits the run."""

        if self.quota_window_seconds is None or not self.is_rate_limit_error(exc):
            return False
        if self.is_rpm_rate_limit_error(exc):
            self.wait_out_rpm_limit()
        else:
            self.wait_for_next_quota_window(getattr(exc, "retry_after", None))
        return True

    def wait_for_next_quota_window(self, retry_after: float | None = None) -> float:
        if self.quota_window_seconds is None or self.quota_window_start_epoch is None:
            return 0.0
        now = time.time()
        target = next_quota_window_epoch(
            self.quota_window_start_epoch, self.quota_window_seconds, now=now
        )
        if retry_after is not None:
            target = max(target, now + max(0.0, retry_after))
        delay = max(0.0, target - now)
        if delay:
            wake_at = datetime.fromtimestamp(target).astimezone().isoformat(timespec="seconds")
            print(
                f"HTTP 429 rate limit; sleeping {delay:.0f}s until quota window {wake_at}",
                flush=True,
            )
            self._sleep(delay)
            self._quota_wait_seconds_total += delay
        return delay

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self._url(path), data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            retry_after = retry_after_seconds(exc.headers.get("Retry-After"))
            raise HermesApiError(
                exc.code,
                f"Hermes API HTTP {exc.code}: {detail}",
                retry_after,
                retryable=exc.code in TRANSIENT_HTTP_STATUSES,
            ) from exc
        except urllib.error.URLError as exc:
            raise HermesApiError(
                None,
                f"Hermes API connection failed: {exc.reason}",
                retryable=True,
            ) from exc
        if status not in expected:
            raise HermesApiError(
                status,
                f"Hermes API HTTP {status}",
                retryable=status in TRANSIENT_HTTP_STATUSES,
            )
        if not response_body.strip():
            return {}
        return json.loads(response_body)

    @staticmethod
    def _is_retryable_error(exc: BaseException) -> bool:
        if isinstance(exc, HermesApiError):
            return exc.retryable
        return isinstance(exc, (TimeoutError, OSError, urllib.error.URLError))

    def _retry_delay(self, retry_number: int, exc: BaseException) -> float:
        delay = min(
            self.retry_max_seconds,
            self.retry_base_seconds * (2 ** retry_number),
        )
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            delay = max(delay, max(0.0, retry_after))
        return delay

    def wait_for_retry_after(self, delay: float) -> float:
        started = time.monotonic()
        started_at = time.time()
        event = {
            "started_at": datetime.fromtimestamp(started_at, timezone.utc).isoformat(),
            "until": datetime.fromtimestamp(started_at + delay, timezone.utc).isoformat(),
            "ended_at": None,
            "retry_after_s": delay,
        }
        callback = getattr(self._retry_state, "on_rate_limit_wait", None)
        if callback is not None:
            callback(event)
        try:
            self._sleep(max(0.0, delay))
        finally:
            waited = max(0.0, time.monotonic() - started)
            self._quota_wait_seconds_total += waited
            event["ended_at"] = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
            if callback is not None:
                callback(event)
        return waited

    def _request_with_retry(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
        deadline: float | None = None,
    ) -> dict[str, Any]:
        deadline = deadline if deadline is not None else time.monotonic() + 300
        last_error: BaseException | None = None
        attempt = 0
        while attempt < self.retry_attempts:
            self._check_cancelled()
            if time.monotonic() >= deadline:
                if last_error is not None:
                    raise last_error
                raise TimeoutError("API request retry deadline expired")
            try:
                return self._request(method, path, payload, expected)
            except (HermesApiError, TimeoutError, OSError) as exc:
                retry_after = getattr(exc, "retry_after", None)
                if self.is_rate_limit_error(exc) and retry_after is not None:
                    deadline += self.wait_for_retry_after(retry_after)
                    last_error = exc
                    continue
                if self.quota_window_seconds is not None and self.is_rate_limit_error(exc):
                    if self.is_rpm_rate_limit_error(exc):
                        waited = self.wait_out_rpm_limit()
                    else:
                        waited = self.wait_for_next_quota_window(
                            getattr(exc, "retry_after", None)
                        )
                    deadline += waited
                    last_error = None
                    attempt = 0
                    continue
                if self.is_rate_limit_error(exc):
                    raise
                last_error = exc
                if (
                    not self._is_retryable_error(exc)
                    or attempt + 1 >= self.retry_attempts
                ):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                self._sleep(min(self._retry_delay(attempt, exc), remaining))
                attempt += 1
        if last_error is not None:
            raise last_error
        raise RuntimeError("API request retry loop exited unexpectedly")

    def _session_usage(self, session_id: str, deadline: float) -> dict[str, Any]:
        value = self._request_with_retry(
            "GET",
            f"api/sessions/{urllib.parse.quote(session_id, safe='')}",
            deadline=deadline,
        )
        session = value.get("session", value)
        keys = (
            "api_call_count", "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "reasoning_tokens",
        )
        return {
            "session_id": session_id,
            "provider": str(session.get("provider", "")),
            "model": str(session.get("model", "")),
            **{key: int(session.get(key, 0) or 0) for key in keys},
        }

    def _ensure_session(self, session_id: str, title: str, model: str, deadline: float) -> None:
        try:
            self._session_usage(session_id, deadline)
            return
        except HermesApiError as exc:
            if exc.status != 404:
                raise
        self._request_with_retry(
            "POST",
            "api/sessions",
            {
                "id": session_id,
                "title": title[:100],
                "model": model,
                "source": SESSION_SOURCE,
            },
            expected=(201, 409),
            deadline=deadline,
        )

    def _terminal_disabled_toolsets(self, deadline: float) -> list[str]:
        if self._disabled_toolsets is None:
            value = self._request_with_retry(
                "GET", "v1/toolsets", deadline=deadline
            )
            names = [
                str(item.get("name", "")).strip()
                for item in value.get("data", [])
                if isinstance(item, dict)
            ]
            names.extend(("memory", "skills"))
            self._disabled_toolsets = sorted({name for name in names if name and name != "terminal"})
        return self._disabled_toolsets

    def health(self, timeout_s: int = 300) -> None:
        self._request_with_retry(
            "GET",
            "v1/models",
            deadline=time.monotonic() + timeout_s,
        )

    @staticmethod
    def _usage_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "api_call_count", "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "reasoning_tokens",
        )
        return {
            "session_id": after["session_id"],
            "provider": after.get("provider", ""),
            "model": after.get("model", ""),
            **{key: max(0, int(after.get(key, 0)) - int(before.get(key, 0))) for key in keys},
        }

    def turn(
        self, *, on_rate_limit_wait: Callable[[dict[str, Any]], None] | None = None,
        cancellation_event: threading.Event | None = None,
        **kwargs: Any,
    ) -> HermesTurnResult:
        self._retry_state.on_rate_limit_wait = on_rate_limit_wait
        self._retry_state.cancellation_event = cancellation_event
        self._retry_state.active_run_id = None
        try:
            return self._turn(**kwargs)
        finally:
            run_id = self._retry_state.active_run_id
            self._retry_state.cancellation_event = None
            self._retry_state.on_rate_limit_wait = None
            self._retry_state.active_run_id = None
            if run_id and cancellation_event is not None and cancellation_event.is_set():
                with suppress(HermesApiError, TimeoutError, OSError):
                    self._request_with_retry(
                        "POST", f"v1/runs/{urllib.parse.quote(run_id, safe='')}/stop", {},
                        expected=(200, 202, 409), deadline=time.monotonic() + 30,
                    )

    def _turn(
        self,
        *,
        session_id: str,
        session_title: str,
        provider: str,
        model: str,
        reasoning: str,
        prompt: str,
        timeout_s: int,
    ) -> HermesTurnResult:
        deadline = time.monotonic() + timeout_s
        quota_wait_at_start = self._quota_wait_seconds_total

        def current_deadline() -> float:
            return deadline + (self._quota_wait_seconds_total - quota_wait_at_start)

        self._check_cancelled()
        self._ensure_session(session_id, session_title, model, current_deadline())
        before = self._session_usage(session_id, current_deadline())
        messages = self._request_with_retry(
            "GET",
            f"api/sessions/{urllib.parse.quote(session_id, safe='')}/messages",
            deadline=current_deadline(),
        ).get("data", [])
        body = {
            "input": prompt,
            "session_id": session_id,
            "conversation_history": messages,
            "provider": provider,
            "model": model,
            "skip_memory": True,
            "skip_context_files": True,
            "disabled_toolsets": self._terminal_disabled_toolsets(current_deadline()),
            "fail_fast_on_nonretryable_429": False,
        }
        if reasoning != "default":
            body["model_options"] = {"reasoning_effort": reasoning}
        started = self._request_with_retry(
            "POST", "v1/runs", body, expected=(202,), deadline=current_deadline()
        )
        run_id = str(started.get("run_id", ""))
        if not run_id:
            raise HermesApiError(
                None,
                "Hermes API run response omitted run_id",
                retryable=False,
            )
        self._retry_state.active_run_id = run_id
        run_path = f"v1/runs/{urllib.parse.quote(run_id, safe='')}"
        while True:
            while time.monotonic() < current_deadline():
                try:
                    status = self._request_with_retry(
                        "GET", run_path, deadline=current_deadline()
                    )
                except (TimeoutError, OSError):
                    self._sleep(min(self.poll_interval, max(0.0, current_deadline() - time.monotonic())))
                    continue
                state = str(status.get("status", ""))
                if state == "completed":
                    output = str(status.get("output", "")).strip()
                    if not output:
                        raise HermesApiError(
                            None,
                            f"Hermes API run {run_id} completed without output",
                            retryable=True,
                        )
                    after = self._session_usage(session_id, current_deadline())
                    return HermesTurnResult(output, self._usage_delta(before, after), run_id)
                if state == "waiting_for_approval":
                    self._request_with_retry(
                        "POST", f"{run_path}/approval", {"choice": "session", "all": True},
                        expected=(200,), deadline=current_deadline(),
                    )
                elif state in {"failed", "stopped", "cancelled"}:
                    detail = status.get("error") or status.get("message") or "no error detail"
                    failure = HermesApiError(
                        None,
                        f"Hermes API run {run_id} ended with status={state}: {detail}",
                        retryable=run_failure_is_retryable(str(detail)),
                    )
                    # A provider rate limit kills the run without consuming the
                    # trial. Wait out the limit and submit a fresh run in the same
                    # session so the game keeps its mailbox state.
                    if not self._resubmit_after_rate_limit(failure):
                        raise failure
                    break
                self._sleep(min(self.poll_interval, max(0.0, current_deadline() - time.monotonic())))
            else:
                break
            if time.monotonic() >= current_deadline():
                break
            body["conversation_history"] = self._request_with_retry(
                "GET", f"api/sessions/{urllib.parse.quote(session_id, safe='')}/messages",
                deadline=current_deadline(),
            ).get("data", [])
            started = self._request_with_retry(
                "POST", "v1/runs", body, expected=(202,), deadline=current_deadline()
            )
            run_id = str(started.get("run_id", ""))
            if not run_id:
                raise HermesApiError(
                    None,
                    "Hermes API run response omitted run_id",
                    retryable=False,
                )
            self._retry_state.active_run_id = run_id
            run_path = f"v1/runs/{urllib.parse.quote(run_id, safe='')}"
        try:
            self._request_with_retry(
                "POST", f"{run_path}/stop", {},
                expected=(200, 202, 409), deadline=current_deadline(),
            )
        except (HermesApiError, TimeoutError, OSError):
            pass
        raise TimeoutError(f"Hermes API run {run_id} timed out after {timeout_s}s")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def acquire_run_lock(run_dir: Path):
    path = run_dir / "runner.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(f"run is already active: {run_dir}") from exc
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()}\nstarted_at={now_iso()}\n")
    handle.flush()
    return handle


def release_run_lock(handle) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@dataclass(frozen=True)
class TelegramProgressConfig:
    token: str = field(repr=False)
    chat_id: str
    thread_id: str
    interval_seconds: float
    api_base_url: str = "https://api.telegram.org"
    proxy: str | None = None


def load_progress_config(
    environ: Mapping[str, str] | None = None,
) -> TelegramProgressConfig | None:
    """Load opt-in progress notifications without providing any destination defaults."""
    env = os.environ if environ is None else environ
    token = str(env.get("TURTLEBENCH_TELEGRAM_BOT_TOKEN", "")).strip()
    chat_id = str(env.get("TURTLEBENCH_TELEGRAM_CHAT_ID", "")).strip()
    thread_id = str(env.get("TURTLEBENCH_TELEGRAM_THREAD_ID", "")).strip()
    if not token or not chat_id or not thread_id:
        return None

    interval_value = str(env.get("TURTLEBENCH_PROGRESS_INTERVAL_SECONDS", "3600")).strip()
    try:
        interval_seconds = float(interval_value)
    except ValueError:
        return None
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        return None

    api_base_url = str(
        env.get("TURTLEBENCH_TELEGRAM_API_BASE_URL", "https://api.telegram.org")
    ).strip().rstrip("/")
    if not api_base_url:
        return None
    proxy = str(env.get("TURTLEBENCH_TELEGRAM_PROXY", "")).strip() or None
    return TelegramProgressConfig(
        token=token,
        chat_id=chat_id,
        thread_id=thread_id,
        interval_seconds=interval_seconds,
        api_base_url=api_base_url,
        proxy=proxy,
    )


class TelegramProgressError(RuntimeError):
    pass


class TelegramProgressSender:
    def __init__(self, config: TelegramProgressConfig):
        self.config = config
        handlers = (
            [urllib.request.ProxyHandler({"http": config.proxy, "https": config.proxy})]
            if config.proxy else []
        )
        self._opener = urllib.request.build_opener(*handlers)

    def method_url(self, method: str) -> str:
        base = self.config.api_base_url
        if "{token}" in base:
            prefix = base.replace("{token}", self.config.token)
        elif base.endswith("/bot"):
            prefix = base + self.config.token
        elif base.endswith("/bot" + self.config.token):
            prefix = base
        else:
            prefix = base + "/bot" + self.config.token
        return f"{prefix}/{method}"

    def send(self, text: str, attempts: int = 4) -> int:
        data = urllib.parse.urlencode({
            "chat_id": self.config.chat_id,
            "message_thread_id": self.config.thread_id,
            "text": text,
            "disable_notification": "false",
        }).encode("utf-8")
        url = self.method_url("sendMessage")
        for attempt in range(attempts):
            request = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            try:
                with self._opener.open(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                try:
                    error_payload = json.loads(body)
                except json.JSONDecodeError:
                    error_payload = {}
                if exc.code == 429 and attempt + 1 < attempts:
                    retry_after = float((error_payload.get("parameters") or {}).get("retry_after", 1))
                    time.sleep(max(0.2, retry_after))
                    continue
                description = error_payload.get("description", f"HTTP {exc.code}")
                raise TelegramProgressError(f"Telegram sendMessage 失败：{description}") from exc
            except (OSError, urllib.error.URLError) as exc:
                if attempt + 1 < attempts:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise TelegramProgressError(
                    f"Telegram sendMessage 网络失败：{type(exc).__name__}"
                ) from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TelegramProgressError("Telegram sendMessage 返回了无效响应") from exc

            if not payload.get("ok"):
                raise TelegramProgressError(
                    f"Telegram sendMessage 失败：{payload.get('description', '未知错误')}"
                )
            result = payload.get("result")
            if not isinstance(result, dict) or "message_id" not in result:
                raise TelegramProgressError("Telegram sendMessage 没有返回 message_id")
            return int(result["message_id"])
        raise TelegramProgressError("Telegram sendMessage 重试耗尽")


def _optional_json(path: Path) -> dict[str, Any] | None:
    try:
        value = load_json(path)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def progress_snapshot(
    run_dir: Path,
    player: dict[str, str],
    manifest: dict[str, Any],
    repeats: int,
) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    completed = 0
    active = 0
    scored = 0
    active_slots: list[dict[str, Any]] = []
    puzzles = manifest.get("puzzles", [])
    player_root = run_dir / "games" / player["slug"]
    for puzzle in puzzles:
        puzzle_id = str(puzzle["id"])
        for trial in range(1, repeats + 1):
            trial_dir = player_root / puzzle_id / f"trial-{trial:02d}"
            preliminary = _optional_json(trial_dir / "preliminary.json")
            game = _optional_json(trial_dir / "game.json")
            state = preliminary or game
            if state is None:
                continue
            status = str(state.get("status", ""))
            if status in TERMINAL_STATES:
                completed += 1
                statuses[status] += 1
            else:
                active += 1
                active_slots.append({
                    "puzzle_id": puzzle_id,
                    "trial": trial,
                    "status": status or "unknown",
                    "round": int(state.get("round", 0) or 0),
                })
            if _optional_json(trial_dir / "score.json") is not None:
                scored += 1
    expected = len(puzzles) * repeats
    return {
        "expected": expected,
        "completed": completed,
        "active": active,
        "pending": max(0, expected - completed - active),
        "scored": scored,
        "statuses": dict(statuses),
        "active_slots": active_slots,
    }


def render_progress_message(
    run_dir: Path,
    players: list[dict[str, str]],
    manifest: dict[str, Any],
    repeats: int,
) -> str:
    meta = _optional_json(run_dir / "run.json") or {}
    run_id = str(meta.get("run_id", run_dir.name))
    run_status = str(meta.get("status", "running"))
    lines = ["TurtleBench 跑分进度", f"Run：{run_id}", f"状态：{run_status}"]
    if "completed_players" in meta and players:
        completed_players = {str(slug) for slug in meta.get("completed_players", [])}
        remaining_players = [
            player for player in players
            if str(player.get("slug", "")) not in completed_players
        ]
        players = remaining_players[:1] if remaining_players else players[-1:]
    status_order = ("solved", "max_rounds", "stopped", "error")
    for player in players:
        snapshot = progress_snapshot(run_dir, player, manifest, repeats)
        label = str(player.get("display_name", player["slug"]))
        line = (
            f"{label}：已完成 {snapshot['completed']}/{snapshot['expected']}，"
            f"运行中 {snapshot['active']}，待处理 {snapshot['pending']}，"
            f"已评分 {snapshot['scored']}/{snapshot['expected']}"
        )
        status_parts = [
            f"{status} {snapshot['statuses'][status]}"
            for status in status_order
            if snapshot["statuses"].get(status, 0)
        ]
        if status_parts:
            line += "；" + "，".join(status_parts)
        lines.append(line)
        for slot in snapshot["active_slots"][:5]:
            lines.append(
                f"当前：{slot['puzzle_id']} / trial-{slot['trial']:02d} "
                f"({slot['status']}，第 {slot['round']} 轮)"
            )
        if len(snapshot["active_slots"]) > 5:
            lines.append(f"当前：其余 {len(snapshot['active_slots']) - 5} 局并行执行")
    text = "\n".join(lines)
    if len(text) > 3900:
        suffix = "\n\n……内容已截断……"
        text = text[: 3900 - len(suffix)] + suffix
    return text


class ProgressReporter:
    def __init__(
        self,
        run_dir: Path,
        players: list[dict[str, str]],
        manifest: dict[str, Any],
        repeats: int,
        sender: Any,
        interval_seconds: float,
    ):
        if interval_seconds <= 0:
            raise ValueError("progress interval must be greater than zero")
        self.run_dir = run_dir
        self.players = players
        self.manifest = manifest
        self.repeats = repeats
        self.sender = sender
        self.interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def _send_once(self) -> None:
        text = render_progress_message(
            self.run_dir, self.players, self.manifest, self.repeats
        )
        try:
            message_id = await asyncio.to_thread(self.sender.send, text)
            if message_id is not None:
                print(f"progress notification sent message_id={message_id}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                f"progress notification failed: {type(exc).__name__}",
                file=sys.stderr,
                flush=True,
            )

    async def run(self) -> None:
        await self._send_once()
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.interval_seconds
                )
            except asyncio.TimeoutError:
                if self._stop_event.is_set():
                    break
                await self._send_once()


def download_verified_archive(url: str, destination: Path, expected_sha256: str, attempts: int = 8) -> None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            offset = destination.stat().st_size if destination.exists() else 0
            headers = {"User-Agent": "TurtleBench/0.1"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                append = offset > 0 and response.status == 206
                with destination.open("ab" if append else "wb") as output:
                    shutil.copyfileobj(response, output)
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if digest != expected_sha256:
                raise RuntimeError(f"fixture archive hash mismatch: {digest}")
            return
        except (OSError, RuntimeError, http.client.HTTPException) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(2**attempt, 8))
    destination.unlink(missing_ok=True)
    raise RuntimeError(f"failed to download fixture archive after {attempts} attempts") from last_error


def ensure_suite(
    suite_dir: Path,
    archive_url: str = FIXTURE_RELEASE_URL,
    expected_sha256: str = FIXTURE_ARCHIVE_SHA256,
    password: str = FIXTURE_ARCHIVE_PASSWORD,
) -> Path:
    if suite_dir.exists():
        return suite_dir

    suite_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="turtlebench-fixtures-", dir=suite_dir.parent) as td:
        temporary_dir = Path(td)
        archive = temporary_dir / "turtlebench-fixed-v1.zip"
        download_verified_archive(archive_url, archive, expected_sha256)

        with zipfile.ZipFile(archive) as bundle:
            members = bundle.namelist()
            if not members or any(
                name.startswith("/") or ".." in Path(name).parts or not name.startswith("fixed-v1/")
                for name in members
            ):
                raise RuntimeError("fixture archive has an invalid layout")
            bundle.extractall(temporary_dir, pwd=password.encode())

        extracted = temporary_dir / "fixed-v1"
        if not (extracted / "manifest.json").is_file():
            raise RuntimeError("fixture archive is missing fixed-v1/manifest.json")
        try:
            os.replace(extracted, suite_dir)
        except FileExistsError:
            pass
    return suite_dir


def validate_attempt_limit(max_attempts: int, target_valid_games: int = TARGET_VALID_GAMES) -> None:
    if max_attempts < target_valid_games:
        raise ValueError(f"max attempts must be at least {target_valid_games}")


def api_game_concurrency(requested_games: int, api_run_slots: int) -> int:
    return max(1, min(requested_games, max(1, api_run_slots // 2)))


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


def should_reuse_summary(
    summary: dict[str, Any] | None,
    target_valid_games: int,
    retry_failed: bool = False,
) -> bool:
    return (
        summary is not None
        and not retry_failed
        and not summary_needs_retry(summary, target_valid_games)
    )


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
        start, end = parse_time(surface["at"]), parse_time(questions[0]["at"])
        first = max(
            0.0, (end - start).total_seconds()
            - game_mailbox.rate_limit_wait_seconds(game, start, end, actor="player"),
        )
    latencies: list[float] = []
    player_intervals: list[float] = []
    player_wait = 0.0
    last_host_action: dict[str, Any] | None = surface
    for event in events:
        if event.get("actor") == "host" and event.get("type") in {"surface", "response", "hint"}:
            last_host_action = event
        elif event.get("actor") == "player" and event.get("type") == "question" and last_host_action:
            start, end = parse_time(last_host_action["at"]), parse_time(event["at"])
            waited = game_mailbox.rate_limit_wait_seconds(game, start, end, actor="player")
            player_wait += waited
            interval = max(0.0, (end - start).total_seconds() - waited)
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
        "player_rate_limit_wait_s": round(player_wait, 3),
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
    puzzle_ids: set[str] | None = None,
) -> dict[str, int]:
    """Move invalid trial directories and stale player summaries aside for a clean retry."""
    counts: dict[str, int] = {}
    for slug in player_slugs:
        player_root = run_dir / "games" / slug
        invalid_trials: list[Path] = []
        for score_path in sorted(player_root.glob("*/trial-[0-9][0-9]/score.json")):
            if puzzle_ids is not None and score_path.parent.parent.name not in puzzle_ids:
                continue
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


def reopen_timeout_aborted_game(
    trial_dir: Path,
    game_path: Path,
    score_path: Path,
    preliminary_path: Path,
    puzzle: dict[str, Any],
    trial: int,
) -> dict[str, Any] | None:
    """Reopen a game an idle host closed on timeout and clear its aborted scoring files.

    A host only reports ``等待超时`` after minutes without player input, which is what
    happens when the runner was killed or restarted mid-game. The rounds are preserved
    and the aborted attempt's stale score/preliminary evidence is moved aside so the
    game can be scored again after it actually finishes.
    """

    if not game_path.exists():
        return None
    try:
        state = load_json(game_path)
    except Exception:
        return None
    if state.get("status") != "error":
        return None
    reopened = game_mailbox.reopen_interrupted_game(game_path)
    if reopened.get("status") == "error":
        return None
    stale = [path for path in (score_path, preliminary_path) if path.exists()]
    if stale:
        target = trial_dir / f"aborted-{int(datetime.now().timestamp())}"
        target.mkdir(parents=True, exist_ok=True)
        for path in stale:
            shutil.copy2(path, target / path.name)
            path.unlink()
    print(
        f"reopened timeout-aborted {puzzle['id']} t{trial:02d} as {reopened['status']} "
        f"after {reopened.get('round')} rounds",
        flush=True,
    )
    return reopened


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
    return f"""你是海龟汤固定题组主持人，只能通过带锁邮箱与玩家通信。不得向用户提问、调用子代理或使用消息平台。
私密题目：{puzzle}
使用 Python json 模块读取私密题目的全部字段。
公共邮箱：{game}
邮箱命令：{MAILBOX_COMMAND}
game_id={game_id}，max_rounds=50。

读取题目全部字段。未猜中前，邮箱只能写汤面、是／不是／是也不是／不相关及按序提示；禁止公开汤底、未发布提示、key_facts 或内部推理。完整猜测在核心条件、必要因果链和全部异常解释上等价即可判中。

判定前把问题拆为最小命题：supported=来源明确支持；contradicted=来源明确否定；unspecified=来源未限定且真假不影响核心链。全部关键命题 supported 且无错误限定答“是”；关键命题 contradicted 且无另一条主线成立答“不是”；明确 supported 主线与会改变机制的 contradicted 限定并存，或身份、时间、位置、动作、因果、范围关键错位，答“是也不是”；unspecified 且不参与核心链答“不相关”。相容性不构成肯定证据，宽泛 key_fact 不得外推。保持前后一致。

启动：先 snapshot。若邮箱已有 surface、事件、非零 revision 或终态，保存现有 game_id、revision、round 和 status，禁止重新 initialize 或覆盖 surface；只有空邮箱且 expected_revision=0 时才 exchange 写 surface，role=host、type=surface、timeout=120；terminal timeout 至少150秒。循环保存最新 revision、status、round、pending_hints、提示额度与待回答问题。收到 question：猜中则写 type=answer、text="猜对了。答案：<solution>"、finish=solved；其余写四类 response 并 exchange 等待。收到 player hint 控制时按序发布下一提示；有待回答问题时先 write 提示，再回答原问题。禁止 main 人工干预。收到终局立即退出。

超时或 revision 冲突：先 snapshot。自己刚写事件已存在则保存 revision 后 wait；不存在则按最新 revision 重试一次。连续3次等待无 revision 前进，尽量写 type=exit、finish=error 后退出。第50轮回应后退出。最终只返回角色、game_id、status、round、revision、是否正常退出；禁止返回私密内容。"""


def player_prompt(game: Path, game_id: str) -> str:
    return f"""你是海龟汤固定题组隔离玩家，只能通过带锁邮箱与主持人通信。不得向用户提问、调用子代理或使用消息平台。
公共邮箱：{game}
邮箱命令：{MAILBOX_COMMAND}
game_id={game_id}，max_rounds=50，自主提示上限2。

禁止读取、搜索、定位或推断私密题目、汤底、提示数组、key_facts、manifest、题组目录、出题记录或主持人上下文。只能使用邮箱公开的 surface、response 和 hint；文件名与目录不得作为线索。

每轮只写一个可由“是／不是／是也不是／不相关”判断的问题，或一个完整猜测；只引入一个新变量。完整猜测也必须作为普通 `question` 写入，禁止传 `--finish`；只有主持人的判定可以结束对局。优先检查动作字面性、身份或状态、关系、时间、地点机制、意图和因果。`是` 只确认最小命题，随后切分、细化、连边或验因。`是也不是` 不得整体记真，只验证一个会改变核心链的限定。`不相关` 后停止该支线。每获2—3个肯定，按时间或因果压缩事实。连续否定回到最近肯定；连续无关回到人物、时间、动作、关系和动机。

核心条件、时间顺序、动作机制、最终反应已有三项支持，且能解释全部异常时提交完整猜测，停止确认装饰细节。同一语义区域连续两次“是也不是”后停止同义改写；最多再验证两轮并提交修订链。第35轮起每轮检查闭合；第45轮起禁止新支线，提交最佳完整猜测。完整猜测按隐藏条件／前史→关键动作→被误读事实→最终反应及原因。不得加入改变身份、时间、机制或因果方向的新前提。邮箱中不得写内部推理、候选列表或多问题组合。

提示仅在连续至少3问无新增约束或无法形成高信息下一问时使用，最多2次，以 player_hints_remaining 为准。调用 control --actor player --command hint --expected-revision <rev>；成功后保存 revision 并 wait，禁止重复请求。

启动：先 snapshot。若邮箱已有 surface、事件、非零 revision 或终态，保存现有 game_id、revision、round 和 status，禁止重新 initialize；只有空邮箱时才按当前 revision wait。收到 response/hint 后更新约束并继续；收到终局立即退出。超时或 revision 冲突先 snapshot；自己刚写事件已存在则保存 revision 后 wait，不存在才重试一次。连续3次无 revision 前进，尽量写 type=exit、finish=error 后退出。round达到50不得创建第51问。最终只返回角色、game_id、status、round、revision、是否正常退出；禁止包含答案、候选答案或私密信息。"""


def init_game(path: Path, game_id: str) -> None:
    game_mailbox.initialize(path, game_id=game_id, max_rounds=50)


def run_failure_is_retryable(detail: str) -> bool:
    normalized = str(detail).casefold()
    transient_markers = (
        "timed out",
        "timeout",
        "broken pipe",
        "no sse events",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "server busy",
        "overloaded",
        *RATE_LIMIT_MARKERS,
        "http 502",
        "http 503",
        "http 504",
    )
    return any(marker in normalized for marker in transient_markers)


def _retryable_api_exception(exc: BaseException) -> bool:
    if isinstance(exc, HermesApiError):
        return exc.retryable
    return isinstance(exc, (TimeoutError, OSError, urllib.error.URLError))


def _write_api_role_failure(
    log_path: Path,
    session_id: str,
    exc: BaseException,
    retryable: bool,
) -> None:
    log_path.write_text(
        f"session_id: {session_id}\n"
        f"API call failed after retrying: {exc}\n"
        f"retryable: {str(retryable).lower()}\n",
        encoding="utf-8",
    )


async def run_api_role(
    client: HermesApiClient,
    session_id: str,
    session_title: str,
    provider: str,
    model: str,
    reasoning: str,
    prompt: str,
    log_path: Path,
    timeout_s: int,
    cancellation_event: threading.Event | None = None,
) -> tuple[int, dict[str, Any] | None]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    turn_options: dict[str, Any] = {}
    if cancellation_event is not None:
        turn_options["cancellation_event"] = cancellation_event
    game_path = log_path.parent / "game.json"
    if log_path.stem in {"host", "player"} and game_path.is_file():
        turn_options["on_rate_limit_wait"] = lambda wait: game_mailbox.record_rate_limit_wait(
            game_path, log_path.stem, wait,
        )
    try:
        result = await asyncio.to_thread(
            client.turn,
            session_id=session_id,
            session_title=session_title,
            provider=provider,
            model=model,
            reasoning=reasoning,
            prompt=prompt,
            timeout_s=timeout_s,
            **turn_options,
        )
    except TimeoutError as exc:
        _write_api_role_failure(log_path, session_id, exc, retryable=True)
        if log_path.stem in {"host", "player"} and game_path.is_file():
            raise
        return 124, None
    except Exception as exc:
        if log_path.stem in {"host", "player"} and game_path.is_file():
            retryable = _retryable_api_exception(exc)
            if client.is_rate_limit_error(exc) and getattr(exc, "retry_after", None) is None and client.quota_window_seconds is None:
                retryable = False
            _write_api_role_failure(log_path, session_id, exc, retryable)
            raise
        if (
            client.is_rate_limit_error(exc)
            and getattr(exc, "retry_after", None) is None
            and client.quota_window_seconds is None
        ):
            _write_api_role_failure(log_path, session_id, exc, retryable=False)
            raise
        rate_limited = (
            client.quota_window_seconds is not None
            and client.is_rate_limit_error(exc)
        )
        if rate_limited:
            await asyncio.to_thread(
                client.wait_for_next_quota_window,
                getattr(exc, "retry_after", None),
            )
        _write_api_role_failure(
            log_path, session_id, exc,
            rate_limited or _retryable_api_exception(exc),
        )
        return 1, None
    log_path.write_text(
        f"session_id: {session_id}\nrun_id: {result.run_id}\n{result.output}\n",
        encoding="utf-8",
    )
    return 0, result.usage


def role_failure_is_retryable(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    return "retryable: true" in log_path.read_text(
        encoding="utf-8", errors="replace"
    ).lower()


def has_infrastructure_api_failure(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    return "API call failed after " in log_path.read_text(encoding="utf-8", errors="replace")


async def mark_error_if_needed(game_path: Path, reason: str) -> None:
    try:
        game = load_json(game_path)
        if game.get("status") in TERMINAL_STATES:
            return
        game_mailbox.append_event(
            game_path,
            actor="host",
            event_type="exit",
            text=reason,
            expected_revision=int(game["revision"]),
            finish="error",
        )
    except Exception:
        return


def recover_terminal_preliminary(
    trial_dir: Path,
    player: dict[str, str],
    puzzle: dict[str, Any],
    game: dict[str, Any],
) -> Path:
    """Create missing preliminary data without rerunning a terminal mailbox."""
    raw = compute_raw_metrics(game)
    totals = _optional_json(trial_dir / "player_totals.json") or {}
    usage = totals.get("player_usage")
    if not isinstance(usage, dict):
        usage = {
            "session_id": None,
            "provider": player["provider"],
            "model": player["model"],
            "api_call_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
        }
    raw["player_usage"] = usage
    process_exit = totals.get("process_exit")
    if not isinstance(process_exit, dict):
        process_exit = {"host": 0, "player": 0}
    preliminary = {
        "suite_version": "fixed-v1",
        "puzzle_id": puzzle["id"],
        "trial": int(trial_dir.name.removeprefix("trial-")),
        "player": {k: player[k] for k in ("provider", "model", "reasoning_effort")},
        "validity": "pending",
        "status": game.get("status", "error"),
        "raw": raw,
        "process_exit": process_exit,
    }
    path = trial_dir / "preliminary.json"
    atomic_json(path, preliminary)
    return path


def save_game_player_totals(trial_dir: Path, usage: dict[str, Any] | None) -> dict[str, Any]:
    game = load_json(trial_dir / "game.json")
    raw = compute_raw_metrics(game)
    raw["player_usage"] = usage
    atomic_json(trial_dir / "player_totals.json", {
        "game_id": game.get("game_id"), "status": game.get("status"),
        "player_active_time_s": raw["player_active_time_s"],
        "total_wall_time_s": raw["total_wall_time_s"], "player_usage": usage,
    })
    return raw


async def run_game(
    run_dir: Path,
    player: dict[str, str],
    puzzle: dict[str, Any],
    trial: int,
    timeout_s: int,
    api_client: HermesApiClient | None = None,
) -> Path:
    if api_client is None:
        raise RuntimeError("Hermes API client is required")
    trial_dir = run_dir / "games" / player["slug"] / puzzle["id"] / f"trial-{trial:02d}"
    score_path = trial_dir / "score.json"
    game_path = trial_dir / "game.json"
    preliminary_path = trial_dir / "preliminary.json"
    reopened_game = reopen_timeout_aborted_game(trial_dir, game_path, score_path, preliminary_path, puzzle, trial)
    if is_completed_score(score_path):
        return score_path
    if not game_needs_run(game_path, preliminary_path):
        return score_path
    existing_game: dict[str, Any] | None = reopened_game
    if existing_game is None and game_path.exists():
        try:
            existing_game = load_json(game_path)
        except Exception:
            game_path.rename(trial_dir / f"game.invalid-{int(datetime.now().timestamp())}.json")
    if existing_game is not None and existing_game.get("status") in TERMINAL_STATES and not preliminary_path.exists():
        recover_terminal_preliminary(trial_dir, player, puzzle, existing_game)
        return score_path
    if not game_path.exists():
        init_game(game_path, f"{player['slug']}-{puzzle['id']}-t{trial:02d}")
    game_id = str(load_json(game_path)["game_id"])
    session_path = trial_dir / "sessions.json"
    resuming_session = session_path.exists()
    session_suffix = uuid.uuid4().hex[:12]
    if resuming_session:
        sessions = load_json(session_path)
        history = trial_dir / "resume-history" / session_suffix
        for role in ("host", "player"):
            log = trial_dir / f"{role}.log"
            if log.is_file():
                history.mkdir(parents=True, exist_ok=True)
                shutil.copy2(log, history / log.name)
        game_mailbox.resume_after_infrastructure(game_path)
    else:
        sessions = {
            "source": SESSION_SOURCE,
            "host": f"tb-{session_suffix}-host",
            "player": f"tb-{session_suffix}-player",
        }
        atomic_json(session_path, sessions)
    resume_note = (
        "\nContinue the same game after an API interruption. Snapshot first. "
        "When it is your turn, act on the already saved question or response; "
        "otherwise wait. Do not replay committed questions, answers or hint requests."
    ) if resuming_session else ""
    cancellation_event = threading.Event()
    host_task = asyncio.create_task(run_api_role(
        api_client,
        sessions["host"],
        f"TurtleBench host {player['slug']} {puzzle['id']} t{trial:02d} {session_suffix}",
        HOST["provider"], HOST["model"], HOST["reasoning_effort"],
        host_prompt(RUNTIME.fixtures / puzzle["path"], game_path, game_id) + resume_note,
        trial_dir / "host.log", timeout_s, cancellation_event=cancellation_event,
    ))
    player_task = asyncio.create_task(run_api_role(
        api_client,
        sessions["player"],
        f"TurtleBench player {player['slug']} {puzzle['id']} t{trial:02d} {session_suffix}",
        player["provider"], player["model"], player["reasoning_effort"],
        player_prompt(game_path, game_id) + resume_note,
        trial_dir / "player.log", timeout_s, cancellation_event=cancellation_event,
    ))
    try:
        (host_rc, _host_usage), (player_rc, player_usage) = await asyncio.gather(host_task, player_task)
    except BaseException as exc:
        game_mailbox.pause_for_infrastructure(game_path, "api_interruption")
        cancellation_event.set()
        results = await asyncio.gather(host_task, player_task, return_exceptions=True)
        usage = (_optional_json(trial_dir / "player_totals.json") or {}).get("player_usage")
        try:
            usage = await asyncio.to_thread(
                api_client._session_usage, sessions["player"], time.monotonic() + 30,
            )
        except (HermesApiError, TimeoutError, OSError):
            pass
        save_game_player_totals(trial_dir, usage)
        game = load_json(game_path)
        if not isinstance(exc, (HermesApiError, TimeoutError, OSError)) or game["status"] not in {"solved", "max_rounds"}:
            raise
        host_rc, player_rc = [
            result[0] if isinstance(result, tuple) else (124 if isinstance(result, TimeoutError) else 1)
            for result in results
        ]
        player_usage = usage
        history = trial_dir / "resume-history" / uuid.uuid4().hex[:12]
        for role in ("host", "player"):
            log = trial_dir / f"{role}.log"
            if has_infrastructure_api_failure(log):
                history.mkdir(parents=True, exist_ok=True)
                shutil.copy2(log, history / log.name)
                log.write_text(
                    f"session_id: {sessions[role]}\nMailbox completed: {game['status']}\n"
                    f"Original transport log: {history / log.name}\n",
                    encoding="utf-8",
                )
    await mark_error_if_needed(game_path, f"角色进程提前退出 host={host_rc} player={player_rc}")
    game = load_json(game_path)
    if resuming_session:
        player_usage = await asyncio.to_thread(
            api_client._session_usage, sessions["player"], time.monotonic() + 30,
        )
    raw = save_game_player_totals(trial_dir, player_usage)
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
    return f"""你是海龟汤固定题组评分员。只分析公开轨迹及主持判定质量，不参与游戏。
私密题目：{puzzle_path}
三个公开邮箱：
{games}
输出文件：{output_path}

读取题目 solution/key_facts 仅用于核验主持判断及最终闭合度；不得把私密内容写入输出。逐局检查：主持泄露、关键矛盾、把 unspecified 反复判为“是也不是”、提示顺序、提前退出。validity 只能为 valid、invalid_host、invalid_infrastructure。玩家自身失败、拒绝、协议错误仍为 valid。

若某局最终 status 为 solved 或 max_rounds，且 host.log、player.log 未见角色中途失败退出，则 game.json 元数据中 source=infrastructure_pause 的 rate_limit_wait 记录代表一次已被同局续跑消化的暂停（同一 game_id、同一 session、轮次连续），validity 必须为 valid：不得因该暂停记录判 invalid_infrastructure。仅当该局未终局、公开日志显示角色中途失败退出，或出现主持泄露、关键矛盾、提前退出时，才判 invalid_infrastructure。

对每局公开问题逐条分类并输出以下字段：trial；validity；validity_reason；atomic_question_rate、useful_constraint_rate、redundant_question_rate、unsupported_story_guess_rate（0到1）；irrelevant_branch_max；contradiction_count；partial_misread_count；excluded_revisit_count；protocol_recovery_failure_count；reasoning_chain_parts（承接性、层级推进、跨异常连接、分支回收，各0到5）；question_information_parts（原子性、压缩能力、去重与聚焦，各0到5）；final_closure（0到5）；hint_effective_count；hint_ineffective_count；hint_early_count；hint_consecutive（布尔）；hint_hoarding（布尔）；failure_tags；notes。failure_tags 仅用规范标签。notes 只写可由公开轨迹核验的简短依据，禁止写汤底、未发布提示或 key_facts。

将三个对象组成 JSON 数组。只允许读取本消息列出的 `20260918` 路径和对应 fixed-v1 题目；禁止访问其他 matrix 目录或旧 run。必须真实执行 terminal 写文件，最终回复不能代替文件写入。使用 `/home/wow/workspace/TurtleBench/.venv/bin/python` 将合法 UTF-8 JSON 原子写入 {output_path}；写后立即用同一绝对解释器检查 `test -s`、重新读取并验证数组恰有3项、trial为1到3。只有现场文件存在且验证通过后，最终回复才报告写入成功与路径。
玩家配置：{player['provider']} / {player['model']} / {player['reasoning_effort']}。"""


def is_valid_judge_output(data: Any) -> bool:
    if not isinstance(data, list) or len(data) != 3:
        return False
    trials = set()
    for item in data:
        if not isinstance(item, dict) or JUDGE_REQUIRED_FIELDS - set(item):
            return False
        if not isinstance(item["reasoning_chain_parts"], dict) or not isinstance(item["question_information_parts"], dict):
            return False
        trials.add(item.get("trial"))
    return trials == {1, 2, 3}


async def run_judge(
    run_dir: Path,
    player: dict[str, str],
    puzzle: dict[str, Any],
    timeout_s: int,
    api_client: HermesApiClient | None = None,
) -> Path:
    if api_client is None:
        raise RuntimeError("Hermes API client is required")
    puzzle_root = run_dir / "games" / player["slug"] / puzzle["id"]
    trial_dirs = [puzzle_root / f"trial-{i:02d}" for i in (1, 2, 3)]
    output = puzzle_root / "judge.json"

    def valid_output() -> bool:
        if not output.exists():
            return False
        try:
            return is_valid_judge_output(load_json(output))
        except Exception:
            return False

    if valid_output():
        return output

    prompt = judge_prompt(RUNTIME.fixtures / puzzle["path"], trial_dirs, output, player)
    deadline = time.monotonic() + timeout_s
    last_rc: int | None = None
    session_ids: list[str] = []
    nonretryable_attempts = 0
    attempt = 0
    while True:
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"judge failed after {attempt} attempts for {player['slug']} "
                f"{puzzle['id']} rc={last_rc} (timeout)"
            )
        attempt += 1
        log_path = puzzle_root / (
            "judge.log" if attempt == 1 else f"judge-retry-{attempt:02d}.log"
        )
        suffix = uuid.uuid4().hex[:12]
        session_id = f"tb-{suffix}-judge"
        session_ids.append(session_id)
        atomic_json(puzzle_root / "judge-sessions.json", {
            "source": SESSION_SOURCE,
            "attempts": session_ids,
        })
        remaining_s = max(1, math.ceil(deadline - time.monotonic()))
        last_rc, _usage = await run_api_role(
            api_client,
            session_id,
            f"TurtleBench judge {player['slug']} {puzzle['id']} a{attempt} {suffix}",
            JUDGE["provider"], JUDGE["model"], JUDGE["reasoning_effort"],
            prompt, log_path, remaining_s,
        )
        if last_rc == 0 and valid_output():
            return output
        if output.exists():
            output.replace(puzzle_root / f"judge-invalid-attempt-{attempt:02d}.json")

        retryable = last_rc != 0 and role_failure_is_retryable(log_path)
        if not retryable:
            nonretryable_attempts += 1
            if nonretryable_attempts >= 3:
                raise RuntimeError(
                    f"judge failed after {attempt} attempts for "
                    f"{player['slug']} {puzzle['id']} rc={last_rc}"
                )
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"judge failed after {attempt} attempts for {player['slug']} "
                f"{puzzle['id']} rc={last_rc} (timeout)"
            )
        delay = min(
            JUDGE_RETRY_MAX_SECONDS,
            JUDGE_RETRY_BASE_SECONDS * (2 ** min(attempt - 1, 6)),
            max(0.0, deadline - time.monotonic()),
        )
        print(
            f"judge retry: {player['slug']} {puzzle['id']} "
            f"attempt={attempt + 1} delay={delay:.1f}s "
            f"retryable={retryable}",
            file=sys.stderr,
            flush=True,
        )
        await asyncio.sleep(delay)


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


RESTORABLE_SCORE_KEYS = (
    "outcome_round_efficiency",
    "reasoning_chain",
    "question_information",
    "hint_strategy",
    "consistency_recovery",
    "final_closure",
)
SUBJECTIVE_SCORE_KEYS = (*RESTORABLE_SCORE_KEYS, "response_speed")


def restore_time_inclusive_score(score: dict[str, Any]) -> bool:
    """Restore the original score from preserved pre-normalization components and latency."""
    if score.get("score_version") != "time-free-v1":
        return False
    components = score.get("score_components_90")
    raw = score.get("raw")
    if not isinstance(components, dict) or not isinstance(raw, dict):
        return False
    if any(
        not isinstance(raw.get(key), (int, float)) or isinstance(raw.get(key), bool)
        for key in ("player_latency_p50_s", "player_latency_p90_s")
    ):
        return False
    if any(not isinstance(components.get(key), (int, float)) for key in RESTORABLE_SCORE_KEYS):
        return False
    parts = {key: round(float(components[key]), 1) for key in RESTORABLE_SCORE_KEYS}
    parts["response_speed"] = round(speed_score(raw), 1)
    score["scores"] = parts | {"total": round(sum(parts.values()), 1)}
    score.pop("score_components_90", None)
    score.pop("score_version", None)
    return True


def finalize_scores(run_dir: Path, player: dict[str, str], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    for puzzle in manifest["puzzles"]:
        root = run_dir / "games" / player["slug"] / puzzle["id"]
        existing_scores: dict[int, dict[str, Any]] = {}
        all_scores_valid = True
        for trial in (1, 2, 3):
            score_path = root / f"trial-{trial:02d}" / "score.json"
            if not score_path.exists():
                all_scores_valid = False
                break
            try:
                existing_score = load_json(score_path)
            except Exception:
                all_scores_valid = False
                break
            if (
                not isinstance(existing_score, dict)
                or existing_score.get("validity") != "valid"
                or existing_score.get("status") not in TERMINAL_STATES
            ):
                all_scores_valid = False
                break
            existing_scores[trial] = existing_score
        if all_scores_valid:
            for trial in (1, 2, 3):
                existing_score = existing_scores[trial]
                if restore_time_inclusive_score(existing_score):
                    atomic_json(root / f"trial-{trial:02d}" / "score.json", existing_score)
                scores.append(existing_score)
            continue

        judged = {int(x["trial"]): x for x in load_json(root / "judge.json")}
        for trial in (1, 2, 3):
            td = root / f"trial-{trial:02d}"
            score_path = td / "score.json"
            existing_score = load_json(score_path) if score_path.exists() else None
            if is_completed_score(score_path) and isinstance(existing_score, dict) and existing_score.get("validity") == "valid":
                if restore_time_inclusive_score(existing_score):
                    atomic_json(score_path, existing_score)
                scores.append(existing_score)
                continue
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
            validity = settle_infrastructure_validity(
                pre["status"], failed_roles, j["validity"], j.get("validity_reason", ""),
            )
            validity_reason = (
                f"{', '.join(failed_roles)} API call failed before normal completion"
                if failed_roles else j.get("validity_reason", "")
            )
            if validity == "valid" and str(j["validity"]) == "invalid_infrastructure":
                validity_reason = (
                    "该局已正常终局，公开元数据中的 infrastructure_pause 记录属于同局续跑后已消化的暂停，"
                    "不构成基础设施故障。"
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
                "suite_version": "fixed-v1",
                "puzzle_id": puzzle["id"], "trial": trial,
                "player": pre["player"], "validity": validity, "status": pre["status"],
                "raw": raw, "scores": parts | {"total": round(sum(parts.values()), 1)},
                "failure_tags": j["failure_tags"], "notes": j["notes"],
                "validity_reason": validity_reason, "process_exit": pre["process_exit"],
            }
            atomic_json(td / "score.json", score)
            scores.append(score)
    return scores

def finalize_puzzle_scores(
    run_dir: Path,
    player: dict[str, str],
    puzzle: dict[str, Any],
) -> list[dict[str, Any]]:
    """Finalize exactly one puzzle after its three trials are judged."""

    return finalize_scores(run_dir, player, {"puzzles": [puzzle]})


def iqr(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return round(percentile(values, .75) - percentile(values, .25), 1)


def aggregate_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [s for s in scores if s.get("validity") == "valid"]
    scoreable = [
        score for score in valid
        if isinstance(score.get("scores"), dict)
        and isinstance(score["scores"].get("total"), (int, float))
        and all(isinstance(score["scores"].get(key), (int, float)) for key in SUBJECTIVE_SCORE_KEYS)
    ]
    scoreable_by_puzzle: dict[str, list[dict[str, Any]]] = {}
    valid_by_puzzle: dict[str, list[dict[str, Any]]] = {}
    for score in scoreable:
        scoreable_by_puzzle.setdefault(score["puzzle_id"], []).append(score)
    for score in valid:
        valid_by_puzzle.setdefault(score["puzzle_id"], []).append(score)
    puzzle_summary: dict[str, Any] = {}
    for pid, items in sorted(valid_by_puzzle.items()):
        score_items = scoreable_by_puzzle.get(pid, [])
        totals = [float(item["scores"]["total"]) for item in score_items]
        solved = [item for item in items if item["status"] == "solved"]
        puzzle_summary[pid] = {
            "score_median": round(statistics.median(totals), 1) if totals else None,
            "score_iqr": iqr(totals) if totals else None,
            "success_rate": round(len(solved) / len(items), 3),
            "rounds_median": round(statistics.median([item["raw"]["rounds"] for item in items]), 1),
        }
    strata: dict[str, float] = {}
    for typ in ("C", "A"):
        for diff in ("E", "M", "H"):
            vals = [
                summary["score_median"] for pid, summary in puzzle_summary.items()
                if f"-{typ}-{diff}-" in pid and summary["score_median"] is not None
            ]
            if vals:
                strata[f"{typ}-{diff}"] = round(statistics.mean(vals), 1)
    dimensions = {}
    keys = list(SUBJECTIVE_SCORE_KEYS)
    for key in keys:
        dimensions[key] = round(statistics.mean([float(score["scores"][key]) for score in scoreable]), 1) if scoreable else None
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
        "subjective_score_valid_games": len(scoreable),
        "unscored_valid_games": len(valid) - len(scoreable),
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
    api_client: HermesApiClient | None = None,
    api_run_slots: int = 8,
) -> dict[str, Any]:
    if repeats != 3:
        raise RuntimeError("current judge path requires exactly 3 repeats")
    target_valid_games = len(manifest["puzzles"]) * repeats
    validate_attempt_limit(max_attempts, target_valid_games)
    state_path = run_dir / "games" / player["slug"] / "attempts.json"
    state = load_attempt_state(run_dir, player["slug"], max_attempts, target_valid_games)
    puzzles = {str(puzzle["id"]): puzzle for puzzle in manifest["puzzles"]}
    puzzle_order = [str(puzzle["id"]) for puzzle in manifest["puzzles"]]
    slots = {
        f"{puzzle['id']}:{trial:02d}": (puzzle, trial)
        for puzzle in manifest["puzzles"]
        for trial in range(1, repeats + 1)
    }
    for slot_puzzle, slot_trial in slots.values():
        slot_dir = (
            run_dir / "games" / player["slug"] / slot_puzzle["id"] / f"trial-{slot_trial:02d}"
        )
        reopen_timeout_aborted_game(
            slot_dir,
            slot_dir / "game.json",
            slot_dir / "score.json",
            slot_dir / "preliminary.json",
            slot_puzzle,
            slot_trial,
        )
    puzzle_keys = {
        puzzle_id: {f"{puzzle_id}:{trial:02d}" for trial in range(1, repeats + 1)}
        for puzzle_id in puzzle_order
    }
    game_limit = api_game_concurrency(concurrency, api_run_slots)
    semaphore = asyncio.Semaphore(game_limit)
    game_tasks: dict[asyncio.Task[Any], str] = {}
    judge_tasks: dict[asyncio.Task[Any], str] = {}
    processed_puzzles: set[str] = set()

    async def guarded(puzzle: dict[str, Any], trial: int):
        async with semaphore:
            if api_client is None:
                return await run_game(run_dir, player, puzzle, trial, timeout_s)
            return await run_game(run_dir, player, puzzle, trial, timeout_s, api_client=api_client)

    def score_is_valid(path: Path) -> bool:
        data = _optional_json(path)
        return bool(
            data
            and data.get("validity") == "valid"
            and data.get("status") in TERMINAL_STATES
        )

    def puzzle_has_valid_scores(puzzle_id: str) -> bool:
        return all(
            score_is_valid(
                run_dir / "games" / player["slug"] / puzzle_id / f"trial-{trial:02d}" / "score.json"
            )
            for trial in range(1, repeats + 1)
        )

    def puzzle_ready_for_judge(puzzle_id: str) -> bool:
        return all(
            (
                run_dir / "games" / player["slug"] / puzzle_id / f"trial-{trial:02d}" / "preliminary.json"
            ).exists()
            for trial in range(1, repeats + 1)
        )

    def clear_puzzle_pending(puzzle_id: str) -> None:
        state["pending_slots"] = [
            key for key in state.get("pending_slots", [])
            if key not in puzzle_keys[puzzle_id]
        ]
        state["updated_at"] = now_iso()
        atomic_json(state_path, state)

    def candidate_keys() -> list[str]:
        candidates: list[str] = []
        for key, (puzzle, trial) in slots.items():
            puzzle_id = str(puzzle["id"])
            if puzzle_id in processed_puzzles:
                continue
            if key in game_tasks.values():
                continue
            trial_dir = run_dir / "games" / player["slug"] / puzzle_id / f"trial-{trial:02d}"
            if score_is_valid(trial_dir / "score.json"):
                continue
            if game_needs_run(trial_dir / "game.json", trial_dir / "preliminary.json"):
                candidates.append(key)
        return candidates

    async def judge_puzzle(puzzle_id: str) -> bool:
        puzzle = puzzles[puzzle_id]
        if api_client is None:
            await run_judge(run_dir, player, puzzle, timeout_s)
        else:
            await run_judge(run_dir, player, puzzle, timeout_s, api_client=api_client)
        if not puzzle_ready_for_judge(puzzle_id):
            return True
        puzzle_scores = finalize_puzzle_scores(run_dir, player, puzzle)
        invalid = [
            score for score in puzzle_scores
            if str(score.get("validity", "")).startswith("invalid_")
        ]
        clear_puzzle_pending(puzzle_id)
        if not invalid:
            return False
        remaining = max_attempts - int(state["attempts_started"])
        if remaining <= 0:
            return False
        state["retry_round"] = int(state.get("retry_round", 0)) + 1
        state["updated_at"] = now_iso()
        atomic_json(state_path, state)
        archive_root = (
            run_dir / "retry-archives" / "auto" / player["slug"] /
            f"round-{state['retry_round']:03d}"
        )
        archived = archive_invalid_trials(
            run_dir,
            [player["slug"]],
            archive_root,
            max_trials=remaining,
            puzzle_ids={puzzle_id},
        )
        if archived[player["slug"]] == 0:
            raise RuntimeError(
                f"{player['slug']} {puzzle_id} has invalid trials but none can be retried"
            )
        return True

    while len(processed_puzzles) < len(puzzle_order) or game_tasks or judge_tasks:
        for puzzle_id in puzzle_order:
            if puzzle_id in processed_puzzles or puzzle_id in judge_tasks.values():
                continue
            if puzzle_has_valid_scores(puzzle_id):
                clear_puzzle_pending(puzzle_id)
                processed_puzzles.add(puzzle_id)
            elif puzzle_ready_for_judge(puzzle_id):
                task = asyncio.create_task(judge_puzzle(puzzle_id))
                judge_tasks[task] = puzzle_id

        for key in candidate_keys():
            if len(game_tasks) >= game_limit:
                break
            if key not in state.get("pending_slots", []):
                if not reserve_attempt_slots(state_path, state, [key]):
                    break
            puzzle, trial = slots[key]
            task = asyncio.create_task(guarded(puzzle, trial))
            game_tasks[task] = key

        if not game_tasks and not judge_tasks:
            if len(processed_puzzles) == len(puzzle_order):
                break
            raise RuntimeError(
                f"{player['slug']} has unfinished slots but no runnable game or judge task"
            )
        done, _ = await asyncio.wait(
            [*game_tasks, *judge_tasks],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            if task in game_tasks:
                game_tasks.pop(task)
                task.result()
            else:
                puzzle_id = judge_tasks.pop(task)
                retrying = task.result()
                if not retrying:
                    processed_puzzles.add(puzzle_id)

    scores = finalize_scores(run_dir, player, manifest)
    valid_games = sum(score.get("validity") == "valid" for score in scores)
    _, limit_reached = retry_stop_state(
        valid_games, target_valid_games, int(state["attempts_started"]), max_attempts
    )
    summary = aggregate_scores(scores)
    formula = formula_summary_from_run(
        run_dir,
        player["slug"],
        manifest,
        repeats=repeats,
    )
    summary.update({
        "subjective_score": summary.get("overall_score"),
        "formula_score": formula["overall_score"],
        "formula": formula,
    })
    summary.update({
        "player": player,
        "target_valid_games": target_valid_games,
        "attempts_started": int(state["attempts_started"]),
        "max_attempts": max_attempts,
        "attempt_limit_reached": limit_reached,
    })
    atomic_json(run_dir / "summaries" / f"{player['slug']}.json", summary)
    return summary


def render_report(run_meta: dict[str, Any], summaries: list[dict[str, Any]]) -> str:
    def number(value: Any) -> str:
        return "N/A" if value is None else f"{value:.1f}"

    def percent(value: Any) -> str:
        return "N/A" if value is None else f"{value:.1%}"

    display_names = {p["slug"]: p.get("display_name", p["slug"]) for p in PLAYER_MATRIX}

    lines = [
        "# Situation Puzzle Baseline", "", f"- Run: `{run_meta['run_id']}`",
        "- Suite: `fixed-v1`", "- Host: `openai-codex / gpt-5.6-luna / max`",
        f"- Session source: `{run_meta['session_source']}`",
        "- Subjective score includes the response-speed dimension; price is not included.",
        f"- Repeats: {run_meta['repeats']}", "",
    ]
    lines += ["| Player | Formula | Subjective | Success | Rounds median | Hint rate | Valid/Invalid |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in summaries:
        p=s["player"]
        lines.append(f"| {display_names.get(p['slug'], p['slug'])} | {number(s.get('formula_score'))} | {number(s.get('subjective_score', s.get('overall_score')))} | {percent(s['success_rate'])} | {number(s['rounds_median'])} | {percent(s['hints_used_rate'])} | {s['valid_games']}/{s['invalid_games']} |")
    lines += ["", "## Strata", "", "| Player | C-E | C-M | C-H | A-E | A-M | A-H |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in summaries:
        st=s["strata"]
        slug = s["player"]["slug"]
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(display_names.get(slug, slug),*[st.get(k,"-") for k in ("C-E","C-M","C-H","A-E","A-M","A-H")]))
    return "\n".join(lines)+"\n"


def archive_run_transcripts(
    run_dir: Path,
    runs_root: Path,
    players: list[dict[str, Any]],
) -> list[Path]:
    """Update cumulative per-model transcript archives after scoring completes."""

    run_dir = Path(run_dir).resolve()
    runs_root = Path(runs_root).resolve()
    if not run_dir.is_relative_to(runs_root):
        raise ValueError(f"run directory is outside runs root: {run_dir}")
    archive_dir = runs_root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_fd = os.open(archive_dir, os.O_RDONLY | os.O_DIRECTORY)
    archives: list[Path] = []
    try:
        fcntl.flock(archive_fd, fcntl.LOCK_EX)
        for player in players:
            slug = str(player["slug"])
            if not slug or Path(slug).name != slug or slug in {".", ".."}:
                raise ValueError(f"invalid player slug for transcript archive: {slug!r}")
            archive_path = archive_dir / f"{slug}.zip"
            members: dict[str, bytes] = {}
            if archive_path.exists():
                with zipfile.ZipFile(archive_path, "r") as existing:
                    if existing.testzip() is not None:
                        raise RuntimeError(f"existing transcript archive is corrupt: {archive_path}")
                    for name in existing.namelist():
                        if name.endswith(("score.json", "summary.json")):
                            raise RuntimeError(f"numeric result file found in transcript archive: {archive_path}")
                        if name.endswith("/game.json"):
                            members[name] = existing.read(name)
            for source_run in sorted(runs_root.iterdir()):
                if source_run.name == "archive" or not source_run.is_dir():
                    continue
                if source_run.is_symlink():
                    continue
                source_root = source_run / "games" / slug
                if not source_root.is_dir():
                    continue
                source_resolved = source_run.resolve()
                for game_path in sorted(source_root.rglob("game.json")):
                    if game_path.is_symlink() or not game_path.resolve().is_relative_to(source_resolved):
                        raise ValueError(f"transcript path escapes run directory: {game_path}")
                    member = f"transcripts/{source_run.name}/{game_path.relative_to(source_run).as_posix()}"
                    members[member] = game_path.read_bytes()
            if not members:
                continue

            with tempfile.NamedTemporaryFile(
                prefix=f".{slug}.", suffix=".tmp", dir=archive_dir, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
            expected = sorted(members)
            try:
                with zipfile.ZipFile(
                    temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
                ) as package:
                    for member in expected:
                        package.writestr(member, members[member])
                with zipfile.ZipFile(temporary_path, "r") as package:
                    names = package.namelist()
                    if names != expected or package.testzip() is not None:
                        raise RuntimeError(f"transcript archive verification failed: {archive_path}")
                    if any(name.endswith(("score.json", "summary.json")) for name in names):
                        raise RuntimeError(f"numeric result file entered transcript archive: {archive_path}")
                os.replace(temporary_path, archive_path)
            finally:
                temporary_path.unlink(missing_ok=True)
            archives.append(archive_path)

        master_path = archive_dir / "turtlebench-transcripts-by-model.zip"
        model_archives = sorted(
            path for path in archive_dir.glob("*.zip") if path.name != master_path.name
        )
        if model_archives:
            with tempfile.NamedTemporaryFile(
                prefix=".turtlebench-transcripts-by-model.", suffix=".tmp",
                dir=archive_dir, delete=False,
            ) as temporary:
                temporary_master = Path(temporary.name)
            expected_master = [f"model-zips/{path.name}" for path in model_archives]
            try:
                with zipfile.ZipFile(
                    temporary_master, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
                ) as package:
                    for path, member in zip(model_archives, expected_master, strict=True):
                        with zipfile.ZipFile(path, "r") as model_package:
                            if model_package.testzip() is not None:
                                raise RuntimeError(f"model transcript archive is corrupt: {path}")
                            if any(
                                name.endswith(("score.json", "summary.json"))
                                for name in model_package.namelist()
                            ):
                                raise RuntimeError(f"numeric result file found in transcript archive: {path}")
                        package.write(path, member)
                with zipfile.ZipFile(temporary_master, "r") as package:
                    names = package.namelist()
                    if names != expected_master or package.testzip() is not None:
                        raise RuntimeError("master transcript archive verification failed")
                os.replace(temporary_master, master_path)
            finally:
                temporary_master.unlink(missing_ok=True)
    finally:
        fcntl.flock(archive_fd, fcntl.LOCK_UN)
        os.close(archive_fd)
    return archives


async def async_main(args: argparse.Namespace) -> None:
    global RUNTIME
    RUNTIME = RuntimePaths(
        fixtures=args.fixtures.expanduser().resolve(),
        runs_dir=args.runs_dir.expanduser().resolve(),
        state_db=args.state_db.expanduser().resolve(),
    )
    ensure_suite(RUNTIME.fixtures)
    manifest = verify_suite(RUNTIME.fixtures)
    retry_failed = bool(getattr(args, "retry_failed", False))
    run_id = args.run_id or f"baseline-luna-max-host-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = RUNTIME.runs_dir / run_id
    meta_path = run_dir / "run.json"
    prior_meta = load_json(meta_path) if meta_path.exists() else {}
    requested_hours = getattr(args, "quota_window_hours", None)
    requested_seconds = None if requested_hours is None else float(requested_hours) * 3600
    if requested_seconds is not None and requested_seconds <= 0:
        raise ValueError("quota window hours must be positive")
    saved_seconds = prior_meta.get("quota_window_seconds")
    if saved_seconds is not None:
        if requested_seconds is not None and float(saved_seconds) != requested_seconds:
            raise ValueError("quota window duration differs from the existing run")
        quota_window_seconds = float(saved_seconds)
    else:
        quota_window_seconds = requested_seconds
    explicit_start = getattr(args, "quota_window_start_epoch", None)
    saved_start = prior_meta.get("quota_window_start_epoch")
    if saved_start is not None and explicit_start is not None and float(saved_start) != float(explicit_start):
        raise ValueError("quota window start differs from the existing run")
    quota_window_start_epoch = (
        float(saved_start) if saved_start is not None else
        (float(explicit_start) if explicit_start is not None else None)
    )
    if quota_window_start_epoch is not None and quota_window_seconds is None:
        raise ValueError("quota window start requires --quota-window-hours")
    api_client = HermesApiClient(
        args.api_url,
        os.environ.get("HERMES_API_KEY", ""),
        quota_window_seconds=quota_window_seconds,
        quota_window_start_epoch=quota_window_start_epoch,
    )
    await asyncio.to_thread(api_client.health)
    run_dir.mkdir(parents=True, exist_ok=True)
    run_lock = acquire_run_lock(run_dir)
    wanted = set(args.players.split(",")) if args.players else {p["slug"] for p in PLAYER_MATRIX}
    players = [p for p in PLAYER_MATRIX if p["slug"] in wanted]
    unknown = wanted - {p["slug"] for p in PLAYER_MATRIX}
    if unknown:
        raise RuntimeError(f"unknown players: {sorted(unknown)}")
    meta_path = run_dir / "run.json"
    meta = load_json(meta_path) if meta_path.exists() else {
        "run_id": run_id, "suite_version": "fixed-v1", "manifest": str(RUNTIME.fixtures / "manifest.json"),
        "host": HOST, "players": players, "repeats": args.repeats, "max_rounds": 50,
        "player_hint_limit": 2, "concurrency": args.concurrency, "session_source": SESSION_SOURCE,
        "started_at": now_iso(),
        "status": "running", "completed_players": [],
    }
    existing_source = meta.get("session_source", SESSION_SOURCE)
    if existing_source not in {SESSION_SOURCE, "turtle-bench"}:
        raise RuntimeError(f"run source mismatch: {existing_source} != {SESSION_SOURCE}")
    meta["players"] = players
    meta["repeats"] = args.repeats
    meta["concurrency"] = args.concurrency
    meta["max_rounds"] = 50
    meta["player_hint_limit"] = 2
    meta["session_source"] = SESSION_SOURCE

    meta["api_url"] = args.api_url
    meta["max_attempts_per_player"] = args.max_attempts_per_player
    quota_seconds = getattr(api_client, "quota_window_seconds", None)
    quota_start = getattr(api_client, "quota_window_start_epoch", None)
    if isinstance(quota_seconds, (int, float)) and isinstance(quota_start, (int, float)):
        meta["quota_window_seconds"] = quota_seconds
        meta["quota_window_start_epoch"] = quota_start
        meta["quota_window_started_at"] = datetime.fromtimestamp(
            quota_start, timezone.utc
        ).isoformat()
    if retry_failed and meta.get("status") == "completed":
        meta["status"] = "running"
        meta.pop("completed_at", None)
        meta["completed_players"] = []
    atomic_json(meta_path, meta)
    summaries=[]
    progress_config = load_progress_config()
    progress_reporter = (
        ProgressReporter(
            run_dir=run_dir,
            players=players,
            manifest=manifest,
            repeats=args.repeats,
            sender=TelegramProgressSender(progress_config),
            interval_seconds=progress_config.interval_seconds,
        )
        if progress_config else None
    )
    progress_task = (
        asyncio.create_task(progress_reporter.run())
        if progress_reporter else None
    )
    try:
        for player in players:
            summary_path = run_dir / "summaries" / f"{player['slug']}.json"
            existing_summary = load_json(summary_path) if summary_path.exists() else None
            if should_reuse_summary(existing_summary, TARGET_VALID_GAMES, retry_failed):
                summary = existing_summary
            else:
                summary=await run_player(
                    run_dir, player, manifest, args.repeats, args.concurrency, args.timeout,
                    max_attempts=args.max_attempts_per_player,
                    api_client=api_client,
                    api_run_slots=args.api_run_slots,
                )
            summaries.append(summary)
            if player["slug"] not in meta["completed_players"]:
                meta["completed_players"].append(player["slug"])
            atomic_json(meta_path, meta)
        meta["status"]="completed"; meta["completed_at"]=now_iso(); atomic_json(meta_path,meta)
        atomic_json(run_dir / "summary.json", {"run": meta, "models": summaries})
        (run_dir / "REPORT.md").write_text(render_report(meta,summaries),encoding="utf-8")
        archived = archive_run_transcripts(run_dir, RUNTIME.runs_dir, players)
        for archive_path in archived:
            print(f"transcripts archived: {archive_path}")
    finally:
        if progress_reporter:
            progress_reporter.stop()
        if progress_task:
            with suppress(asyncio.CancelledError):
                await progress_task
        release_run_lock(run_lock)
    print(run_dir)


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description="Run the TurtleBench situation-puzzle benchmark")
    parser.add_argument("--run-id")
    parser.add_argument("--players", help="comma-separated slugs")
    parser.add_argument("--repeats",type=int,default=3)
    parser.add_argument("--concurrency",type=int,default=12)
    parser.add_argument("--timeout",type=int,default=7200)
    parser.add_argument("--max-attempts-per-player", type=attempt_limit_arg, default=100)
    parser.add_argument("--retry-failed", action="store_true", help="rerun invalid slots in a completed run")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB)
    parser.add_argument("--api-url", default=os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642"))
    parser.add_argument("--api-run-slots", type=int, default=8)
    parser.add_argument("--quota-window-hours", type=float)
    parser.add_argument("--quota-window-start-epoch", type=float)
    return parser


def main() -> None:
    asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    main()
