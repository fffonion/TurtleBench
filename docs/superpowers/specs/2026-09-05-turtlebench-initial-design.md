# TurtleBench Initial Project Design

Date: 2026-09-05

## Goal

Create a portable Python project for running the existing situation-puzzle model benchmark with Hermes Agent. The first revision includes the benchmark framework, the fixed-v1 fixtures, tests, a short README, and the existing situation-puzzle skill as a Git submodule. Benchmark results and credentials remain outside version control.

## Repository layout

```text
TurtleBench/
├── README.md
├── LICENSE
├── pyproject.toml
├── .gitignore
├── src/turtlebench/
│   ├── __init__.py
│   ├── __main__.py
│   ├── benchmark_runner.py
│   └── game_mailbox.py
├── fixtures/fixed-v1/
│   ├── manifest.json
│   └── puzzles/*.json
├── skills/situation-puzzle/       # Git submodule
└── tests/
    ├── test_benchmark_runner.py
    ├── test_game_mailbox.py
    ├── test_fixtures.py
    └── test_skill_submodule.py
```

## Components

### Python package

`src/turtlebench` owns the portable benchmark implementation:

- `game_mailbox.py`: file-backed host/player protocol, revision checks, locking, turn validation, hint limits, and terminal states.
- `benchmark_runner.py`: fixture verification, model configuration, process orchestration through the `hermes` CLI, scoring, resource accounting, invalid-trial archival, resume support, and report generation.
- `__main__.py`: command-line entry point for `python -m turtlebench`.

Paths that currently point into `~/.hermes` or `~/.cache` become command-line options or package-relative defaults. The external `hermes` executable remains the model transport.

### Fixtures

`fixtures/fixed-v1` checks in the existing 12-puzzle suite:

- two puzzle types: concentrated and absurd;
- three difficulty levels: easy, medium, and hard;
- two puzzles per type/difficulty stratum;
- SHA-256 values in `manifest.json` verified before a run.

Fixture files include the private fields required by the host and judge. They are benchmark data, not generated run results.

### Skill submodule

`skills/situation-puzzle` is a Git submodule with this URL:

```text
https://github.com/fffonion/situation-puzzle-skill
```

The initial submodule commit is the current upstream `master` HEAD. TurtleBench does not copy the local skill worktree or its uncommitted files into the main repository.

### Tests

The test suite uses Python `unittest` and covers:

- mailbox state transitions, locking, revision fences, hint limits, and terminal states;
- metric calculation, model selection, CLI construction, session resource loading, invalid-trial archival, resume behavior, and aggregate scoring;
- fixture schema, ID uniqueness, file existence, hash verification, and complete six-stratum coverage;
- submodule declaration and expected skill entry point.

Tests mock external model calls. Normal unit tests do not require provider credentials.

## Runtime flow

1. Load and verify the fixture manifest.
2. Create a run directory outside tracked source.
3. Start isolated host and player Hermes sessions for each trial.
4. Record game events through the mailbox protocol.
5. Calculate preliminary metrics and player-only active time.
6. Judge terminal games and aggregate scores by six strata.
7. Write JSON summaries and a Markdown report under the selected run directory.

## Repository hygiene

The repository ignores run outputs, logs, caches, virtual environments, dotenv files, private keys, local session databases, and private puzzle storage. Before commit, staged files are scanned for private-key headers, common credential assignments, and accidental result paths.

No provider token, API key, SSH private key, Hermes state database, player log, host log, or benchmark result is part of the initial commit.

## README scope

The README contains only:

- project purpose;
- prerequisites: Python 3.11+ and a configured Hermes CLI;
- editable installation;
- submodule checkout;
- unit-test command;
- one benchmark command;
- fixture and output locations;
- a note that provider credentials are managed by Hermes.

## Git delivery

The local repository uses branch `main` and origin:

```text
git@github.com:fffonion/TurtleBench.git
```

Implementation is committed after tests and staged-content checks pass. Push is attempted through the configured remote. The current machine needs valid GitHub authentication before that push can succeed.
