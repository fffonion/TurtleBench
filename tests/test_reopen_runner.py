"""Runner-level reopen of games aborted by an idle-host timeout."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from turtlebench import benchmark_runner as br  # noqa: E402
from turtlebench import game_mailbox as mb  # noqa: E402

PUZZLE = {'id': 'SPB-A-H-02'}


def _state(events, status='error', revision=40):
    return {
        'format_version': 1, 'game_id': 'g', 'status': status, 'revision': revision,
        'round': 39, 'events': events, 'rate_limit_waits': [],
        'created_at': '2026-11-26T00:00:00+00:00', 'updated_at': '2026-11-26T00:00:00+00:00',
    }


def _trial_dir(tmp_path, exit_text, status='error', with_score=True):
    trial = tmp_path / 'games' / 'p' / 'SPB-A-H-02' / 'trial-01'
    trial.mkdir(parents=True)
    events = [
        {'seq': 1, 'actor': 'player', 'type': 'question', 'text': '丈夫在家吗？'},
        {'seq': 2, 'actor': 'host', 'type': 'response', 'text': '是'},
        {'seq': 3, 'actor': 'host', 'type': 'exit', 'text': exit_text},
    ]
    (trial / 'game.json').write_text(json.dumps(_state(events, status=status), ensure_ascii=False), encoding='utf-8')
    (trial / 'sessions.json').write_text('{"source": "turtle-bench"}', encoding='utf-8')
    if with_score:
        (trial / 'preliminary.json').write_text('{"status": "error", "validity": "pending"}', encoding='utf-8')
        (trial / 'score.json').write_text('{"validity": "invalid_infrastructure", "status": "error"}', encoding='utf-8')
    return trial


def _reopen(trial):
    return br.reopen_timeout_aborted_game(
        trial, trial / 'game.json', trial / 'score.json', trial / 'preliminary.json', PUZZLE, 1,
    )


def test_reopens_and_parks_stale_scoring_files(tmp_path):
    trial = _trial_dir(tmp_path, '等待超时')
    reopened = _reopen(trial)
    assert reopened is not None and reopened['status'] == 'player_turn'
    assert reopened['round'] == 39
    assert not (trial / 'score.json').exists()
    assert not (trial / 'preliminary.json').exists()
    parked = [p for p in trial.glob('aborted-*') if p.is_dir()]
    assert parked and (parked[0] / 'score.json').is_file()


def test_reopens_without_stale_files(tmp_path):
    trial = _trial_dir(tmp_path, '游戏因等待超时结束', with_score=False)
    reopened = _reopen(trial)
    assert reopened is not None and reopened['status'] == 'player_turn'


def test_keeps_real_error_and_its_files(tmp_path):
    trial = _trial_dir(tmp_path, '角色进程提前退出 host=1 player=124')
    assert _reopen(trial) is None
    assert (trial / 'score.json').exists()


def test_keeps_terminal_game(tmp_path):
    trial = _trial_dir(tmp_path, '等待超时', status='solved')
    assert _reopen(trial) is None
    assert (trial / 'score.json').exists()


def test_keeps_missing_game(tmp_path):
    trial = tmp_path / 'games' / 'p' / 'SPB-A-H-02' / 'trial-01'
    assert _reopen(trial) is None
