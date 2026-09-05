# TurtleBench Initial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use codex-superpowers-subagent-driven-development (recommended) or codex-superpowers-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a portable TurtleBench Python project with the fixed-v1 fixture suite, automated tests, a situation-puzzle-skill submodule, and no benchmark results or credentials.

**Architecture:** Package the mailbox protocol and benchmark runner under `src/turtlebench`, with package-relative fixtures and configurable run/state paths. Keep the existing skill in its own repository and link it through a Git submodule. Use only the Python standard library at runtime; invoke Hermes through its CLI.

**Tech Stack:** Python 3.11+, `unittest`, `asyncio`, SQLite, Git submodules, Hermes CLI.

---

### Task 1: Project metadata and fixture verification

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/turtlebench/__init__.py`
- Create: `tests/test_fixtures.py`
- Create: `fixtures/fixed-v1/manifest.json`
- Create: `fixtures/fixed-v1/puzzles/*.json`

- [ ] **Step 1: Write the fixture tests**

Create tests that load `fixtures/fixed-v1/manifest.json`, require 12 unique IDs, require two entries in every type/difficulty stratum, and compare every declared SHA-256 value with the referenced file.

```python
def test_manifest_has_complete_strata(self):
    counts = Counter((item["type"], item["difficulty"]) for item in self.manifest["puzzles"])
    self.assertEqual(set(counts.values()), {2})
    self.assertEqual(len(counts), 6)

def test_manifest_hashes_match(self):
    for item in self.manifest["puzzles"]:
        path = self.fixture_root / item["path"]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
```

- [ ] **Step 2: Run the fixture test and confirm failure**

Run: `python3 -m unittest tests.test_fixtures -v`

Expected: failure because the fixture tree has not been checked in.

- [ ] **Step 3: Add package metadata, ignore rules, and fixtures**

Use a setuptools `src` layout with this script entry:

```toml
[project]
name = "turtlebench"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
turtlebench = "turtlebench.benchmark_runner:main"
```

Ignore `runs/`, `results/`, logs, local databases, virtual environments, dotenv files, private-key extensions, Python caches, and build output. Copy only the 13 fixed-v1 JSON files; do not copy any run directory.

- [ ] **Step 4: Run fixture tests**

Run: `python3 -m unittest tests.test_fixtures -v`

Expected: all fixture tests pass.

- [ ] **Step 5: Commit fixture foundation**

```bash
git add pyproject.toml .gitignore src/turtlebench/__init__.py fixtures tests/test_fixtures.py
git commit -m "Add TurtleBench fixtures and package metadata"
```

### Task 2: Mailbox protocol

**Files:**
- Create: `src/turtlebench/game_mailbox.py`
- Create: `tests/test_game_mailbox.py`

- [ ] **Step 1: Port mailbox tests before implementation**

Copy the protocol tests and change imports to:

```python
from turtlebench import game_mailbox as mailbox
```

Retain assertions for lock/revision concurrency, turn order, hint controls, solved exits, maximum rounds, stop wake-up, and CLI timeout exit codes.

- [ ] **Step 2: Run mailbox tests and confirm failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_game_mailbox -v`

Expected: import failure because `game_mailbox.py` is absent.

- [ ] **Step 3: Port the mailbox implementation**

Move the file-backed state machine into `src/turtlebench/game_mailbox.py`. Preserve the public Python functions and CLI subcommands. Replace script-path subprocess calls in tests with `python -m turtlebench.game_mailbox` where applicable.

- [ ] **Step 4: Run mailbox tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_game_mailbox -v`

Expected: all mailbox tests pass.

- [ ] **Step 5: Commit mailbox protocol**

```bash
git add src/turtlebench/game_mailbox.py tests/test_game_mailbox.py
git commit -m "Add file-backed game mailbox"
```

### Task 3: Portable benchmark runner and CLI

**Files:**
- Create: `src/turtlebench/benchmark_runner.py`
- Create: `src/turtlebench/__main__.py`
- Create: `tests/test_benchmark_runner.py`

- [ ] **Step 1: Port runner tests before implementation**

Change imports to `from turtlebench import benchmark_runner as runner`. Keep metric, aggregate, model matrix, usage, resume, API-failure, judge-retry, and invalid-archive tests. Add path configuration assertions:

```python
def test_parser_accepts_fixture_and_run_paths(self):
    args = runner.build_parser().parse_args([
        "--fixtures", "/tmp/fixtures",
        "--runs-dir", "/tmp/runs",
        "--state-db", "/tmp/state.db",
    ])
    self.assertEqual(args.fixtures, Path("/tmp/fixtures"))
    self.assertEqual(args.runs_dir, Path("/tmp/runs"))
    self.assertEqual(args.state_db, Path("/tmp/state.db"))
```

- [ ] **Step 2: Run runner tests and confirm failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_benchmark_runner -v`

Expected: import failure because `benchmark_runner.py` is absent.

- [ ] **Step 3: Port and parameterize the runner**

Replace fixed global paths with a runtime configuration object:

```python
@dataclass(frozen=True)
class RuntimePaths:
    fixtures: Path
    runs_dir: Path
    state_db: Path

DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "fixed-v1"
DEFAULT_RUNS = Path.cwd() / "runs"
DEFAULT_STATE_DB = Path.home() / ".hermes" / "state.db"
```

Invoke mailbox operations through:

```python
MAILBOX_COMMAND = [sys.executable, "-m", "turtlebench.game_mailbox"]
```

Add parser options `--fixtures`, `--runs-dir`, and `--state-db`. Thread `RuntimePaths` through suite verification, prompts, game execution, judging, and output creation. Preserve the nine current model configurations and all scoring formulas.

- [ ] **Step 4: Add package entry point**

`src/turtlebench/__main__.py` calls `benchmark_runner.main()` so both commands work:

```bash
python -m turtlebench --help
turtlebench --help
```

- [ ] **Step 5: Run runner and full tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -v
PYTHONPATH=src python3 -m turtlebench --help
```

Expected: all tests pass and CLI help lists fixture, runs, state database, player, repeat, concurrency, and timeout options.

- [ ] **Step 6: Commit benchmark runner**

```bash
git add src/turtlebench/benchmark_runner.py src/turtlebench/__main__.py tests/test_benchmark_runner.py
git commit -m "Add portable benchmark runner"
```

### Task 4: Skill submodule and documentation

**Files:**
- Create: `.gitmodules`
- Create: `skills/situation-puzzle` as submodule
- Create: `tests/test_skill_submodule.py`
- Create: `README.md`
- Create: `LICENSE`

- [ ] **Step 1: Write submodule declaration test**

```python
def test_skill_submodule_url(self):
    config = configparser.ConfigParser()
    config.read(ROOT / ".gitmodules")
    section = 'submodule "skills/situation-puzzle"'
    self.assertEqual(config[section]["url"], "https://github.com/fffonion/situation-puzzle-skill")
```

Also assert that `skills/situation-puzzle/SKILL.md` exists after recursive checkout.

- [ ] **Step 2: Run the submodule test and confirm failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_skill_submodule -v`

Expected: failure because `.gitmodules` and the submodule are absent.

- [ ] **Step 3: Add the existing skill repository as a submodule**

Run with the GitHub HTTPS rewrite disabled for this command:

```bash
GIT_CONFIG_GLOBAL=/dev/null git submodule add https://github.com/fffonion/situation-puzzle-skill skills/situation-puzzle
```

Keep the recorded URL exactly as supplied and pin the checked-out upstream commit.

- [ ] **Step 4: Write README and license**

README sections: purpose, requirements, recursive clone, editable install, unit tests, one benchmark command, fixture layout, output layout, and credential policy. Use this benchmark example:

```bash
python -m turtlebench \
  --fixtures fixtures/fixed-v1 \
  --runs-dir runs \
  --players gpt-5-6-sol-high \
  --repeats 3 \
  --concurrency 12
```

- [ ] **Step 5: Run submodule and full tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit submodule and docs**

```bash
git add .gitmodules skills/situation-puzzle README.md LICENSE tests/test_skill_submodule.py
git commit -m "Add situation puzzle skill submodule and usage docs"
```

### Task 5: Repository verification and publication

**Files:**
- Verify all tracked files
- Update: `docs/superpowers/plans/2026-09-05-turtlebench-initial.md` checkboxes

- [ ] **Step 1: Run final package checks**

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -v
.venv/bin/python -m turtlebench --help
```

Expected: installation succeeds, all tests pass, and CLI help exits with status 0.

- [ ] **Step 2: Verify fixture checksums independently**

Run the fixture test from the installed environment and confirm all 12 files match the manifest.

- [ ] **Step 3: Scan tracked content and staged changes**

List tracked files and confirm no path is under `runs/`, `results/`, caches, or local private storage. Search tracked text for private-key headers and credential assignments. Inspect `.gitmodules`, `git status --short`, and `git diff --check`.

- [ ] **Step 4: Commit completed plan state**

```bash
git add docs/superpowers/plans/2026-09-05-turtlebench-initial.md
git commit -m "Complete TurtleBench implementation plan"
```

- [ ] **Step 5: Verify branch and remote identities**

```bash
git branch --show-current
git branch -vv
git remote -v
git ls-remote --symref origin HEAD
```

Expected local branch: `main`. Expected origin: `git@github.com:fffonion/TurtleBench.git`.

- [ ] **Step 6: Push and verify the remote commit**

```bash
git push -u origin HEAD:main
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
```

The two hashes must match. If SSH authentication still fails, keep the tested local repository and report the exact authentication blocker without changing the requested origin URL.
