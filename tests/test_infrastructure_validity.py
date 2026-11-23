"""Regressions for settling judge validity when an API interruption was resumed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from turtlebench import benchmark_runner as br  # noqa: E402

PUZZLE = {'id': 'SPB-A-E-02', 'path': 'puzzles/SPB-A-E-02.json', 'difficulty': '简单'}
PLAYER = {'slug': 'minimax-cn-minimax-m3-1-flash-max',
          'provider': 'minimax-cn', 'model': 'MiniMax-M3.1-Flash', 'reasoning_effort': 'max'}


def settle(status, failed_roles, judge_validity, judge_reason=''):
    return br.settle_infrastructure_validity(status, failed_roles, judge_validity, judge_reason)


def test_resumed_terminal_game_keeps_valid():
    reason = ('公开元数据记录一次 source=infrastructure_pause 的 rate_limit_wait；'
              '除此之外未见主持泄露、关键矛盾或提前退出。')
    for status in ('solved', 'max_rounds'):
        assert settle(status, [], 'invalid_infrastructure', reason) == 'valid'


def test_terminal_game_with_other_faults_stays_invalid():
    reason = '公开轨迹显示主持人泄露汤底，且存在关键矛盾。'
    assert settle('solved', [], 'invalid_infrastructure', reason) == 'invalid_infrastructure'


def test_host_invalid_stays_invalid():
    assert settle('solved', [], 'invalid_host', '主持泄露') == 'invalid_host'


def test_unfinished_game_stays_invalid():
    for status in ('player_turn', 'host_turn', 'error', 'stopped'):
        assert settle(status, [], 'invalid_infrastructure', 'rate_limit_wait') == 'invalid_infrastructure'


def test_failed_role_log_stays_invalid():
    assert settle('solved', ['player'], 'invalid_infrastructure', 'rate_limit_wait') == 'invalid_infrastructure'
    assert settle('max_rounds', ['host'], 'valid', 'rate_limit_wait') == 'invalid_infrastructure'


def test_judge_prompt_states_resumed_pause_rule():
    prompt = br.judge_prompt(
        Path('/tmp/puzzle.json'), [Path(f'/tmp/trial-{i:02d}') for i in (1, 2, 3)],
        Path('/tmp/judge.json'), PLAYER,
    )
    for needle in ('infrastructure_pause', 'solved', 'max_rounds', '不得因该暂停记录判 invalid_infrastructure'):
        assert needle in prompt, needle
