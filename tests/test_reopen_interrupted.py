"""Reopen games that an idle host closed while its runner was down."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from turtlebench import game_mailbox as mb  # noqa: E402


def _game(events, status='error', revision=7):
    return {
        'format_version': 1,
        'game_id': 'g', 'status': status, 'revision': revision, 'round': 0,
        'events': events, 'rate_limit_waits': [], 'created_at': '2026-11-26T00:00:00+00:00',
        'updated_at': '2026-11-26T00:00:00+00:00',
    }


def _write(tmp_path, state):
    path = tmp_path / 'game.json'
    path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    return path


def _exit_event(text):
    return {'seq': 99, 'actor': 'host', 'type': 'exit', 'text': text, 'finish': None}


def _events(*items):
    """items: (actor, type, text) tuples in order."""
    return [
        {'seq': i + 1, 'actor': actor, 'type': kind, 'text': text, 'finish': None}
        for i, (actor, kind, text) in enumerate(items)
    ]


def test_reopens_player_turn_after_host_timeout(tmp_path):
    state = _game(_events(('host', 'surface', '妻子失踪后，丈夫收到了“到家了”'),
                          ('player', 'question', '丈夫当晚在家吗？'),
                          ('host', 'response', '是')) + [_exit_event('等待玩家输入超时。')])
    path = _write(tmp_path, state)
    reopened = mb.reopen_interrupted_game(path)
    assert reopened['status'] == 'player_turn'
    assert len(reopened['events']) == 3
    assert reopened['events'][-1]['type'] == 'response'
    assert reopened['infrastructure_pause']['reason'] == 'host_timeout_exit'
    assert reopened['revision'] > state['revision']
    assert reopened['rate_limit_waits'][-1]['source'] == 'infrastructure_pause'


def test_reopens_host_turn_when_player_asked_last(tmp_path):
    state = _game(_events(('host', 'surface', '开场'), ('player', 'question', '她去哪了？'))
                  + [_exit_event('等待主持输入超时。')])
    path = _write(tmp_path, state)
    reopened = mb.reopen_interrupted_game(path)
    assert reopened['status'] == 'host_turn'


def test_leaves_real_errors_alone(tmp_path):
    state = _game(_events(('host', 'surface', '开场')) + [_exit_event('角色进程提前退出 host=1 player=124')])
    path = _write(tmp_path, state)
    assert mb.reopen_interrupted_game(path)['status'] == 'error'


def test_leaves_terminal_states_alone(tmp_path):
    for status in ('solved', 'max_rounds', 'stopped'):
        state = _game(_events(('host', 'surface', '开场')) + [_exit_event('等待玩家输入超时。')], status=status)
        path = _write(tmp_path, state)
        assert mb.reopen_interrupted_game(path)['status'] == status


def test_leaves_game_without_events_alone(tmp_path):
    state = _game([], revision=1)
    path = _write(tmp_path, state)
    assert mb.reopen_interrupted_game(path)['status'] == 'error'
