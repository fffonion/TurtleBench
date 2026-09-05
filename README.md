# TurtleBench

TurtleBench runs a fixed situation-puzzle benchmark through [Hermes Agent](https://hermes-agent.nousresearch.com/docs). It includes the benchmark runner, mailbox protocol, tests, and the `fixed-v1` fixture suite. Benchmark results are intentionally excluded.

## Requirements

- Python 3.11 or newer
- A working `hermes` CLI configuration
- Git with submodule support

Provider credentials remain in Hermes configuration. TurtleBench does not require credential files in this repository.

## Install

```bash
git clone --recurse-submodules git@github.com:fffonion/TurtleBench.git
cd TurtleBench
python3 -m venv .venv
.venv/bin/pip install -e .
```

For an existing checkout:

```bash
git submodule update --init --recursive
```

The situation-puzzle skill is pinned at `skills/situation-puzzle` from <https://github.com/fffonion/situation-puzzle-skill>.

## Test

```bash
.venv/bin/python -m unittest discover -v
```

The tests validate the mailbox protocol, scoring helpers, model matrix, runner resume behavior, fixture schema, and all fixture SHA-256 values.

## Run

```bash
.venv/bin/python -m turtlebench \
  --fixtures fixtures/fixed-v1 \
  --runs-dir runs \
  --players gpt-5-6-sol-high \
  --repeats 3 \
  --concurrency 12
```

Use `python -m turtlebench --help` for all options. `--players` accepts comma-separated slugs from the model matrix in `src/turtlebench/benchmark_runner.py`.

Hermes session usage is read from `~/.hermes/state.db` by default. Override it with `--state-db PATH`.

## Fixtures

`fixtures/fixed-v1/manifest.json` declares 12 puzzles across two puzzle types and three difficulty levels. Every manifest entry records the puzzle path and SHA-256 digest. Puzzle JSON includes the private solution data required by the isolated host and judge.

## Output

Each run is written below `runs/<run-id>/` unless `--runs-dir` is changed. Run directories contain game mailboxes, process logs, per-trial scores, model summaries, and `REPORT.md`. The `runs/` and `results/` directories are ignored by Git.

## License

MIT
