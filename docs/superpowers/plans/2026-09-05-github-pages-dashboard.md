# GitHub Pages Benchmark Dashboard Implementation Plan

**Goal:** Publish existing and future TurtleBench aggregates on a responsive, sortable GitHub Pages dashboard with chart/table switching and models.dev price snapshots.

**Architecture:** Add a Python export/publish module on `main`, with pure aggregation and pricing functions covered by unit tests. Keep the deployable framework-free site and sanitized run JSON on `gh-pages`; use semantic HTML, CSS, JavaScript, and SVG. Publish through a temporary `gh-pages` worktree and verify both branch contents and the served page.

**Tech Stack:** Python 3.11 standard library, HTML5, CSS, browser JavaScript, SVG, Node.js built-in test runner, Git worktrees, GitHub Pages.

---

### Task 1: Add public-result aggregation

**Objective:** Convert a completed run into a sanitized public model dataset.

**Files:**
- Create: `src/turtlebench/pages.py`
- Create: `tests/test_pages.py`

**Steps:**
1. Write failing tests for model identity, score, game count, active time, token categories, token total, solve rate, round median, and hint median.
2. Run the focused tests and confirm failure because the exporter is absent.
3. Implement pure run/model aggregation over summaries and valid trial files.
4. Add failing tests that archived, retry-invalid, and nonterminal trials are excluded.
5. Implement strict valid-trial selection and public-field allowlisting.
6. Run the focused and full Python suites.
7. Commit with `Add public benchmark result exporter`.

### Task 2: Add models.dev pricing resolution

**Objective:** Resolve benchmark model identities to standard models.dev prices and calculate category totals.

**Files:**
- Create: `pricing/models-dev-mapping.json`
- Modify: `src/turtlebench/pages.py`
- Modify: `tests/test_pages.py`

**Steps:**
1. Write failing tests for official provider mapping, CommandCode fallback, promotional/free-plan rejection, off-peak selection, absent-rate behavior, and per-category USD totals.
2. Confirm focused tests fail for the missing resolver.
3. Implement resolver functions with injected catalog/fetch time for deterministic tests.
4. Fetch `https://models.dev/api.json` only in the CLI boundary and snapshot source IDs, rates, and timestamp.
5. Run focused and full suites.
6. Commit with `Add models.dev benchmark pricing`.

### Task 3: Build the static dashboard

**Objective:** Implement the accepted desktop/mobile dashboard and browser interactions.

**Files:**
- Create: `web/index.html`
- Create: `web/assets/styles.css`
- Create: `web/assets/app.js`
- Create: `tests/web/dashboard.test.mjs`
- Create: `tests/fixtures/public-run.json`

**Steps:**
1. Write failing Node tests for sorting, family grouping, line generation, metric formatting, and unavailable prices.
2. Confirm the Node tests fail because dashboard helpers are absent.
3. Implement the plain-white design system, semantic page shell, exclusive chart/table control, X-axis control, SVG scatter chart, resource table, and behavior table.
4. Keep reasoning-effort values as unboxed lowercase English text.
5. Implement complete header-cell sorting with `aria-sort` and accessible controls.
6. Implement mobile table scrolling, sticky headers/first columns, edge fade, and minimum touch targets.
7. Run Node and Python suites.
8. Commit with `Build responsive benchmark dashboard`.

### Task 4: Add gh-pages publication workflow

**Objective:** Update an orphan or existing `gh-pages` branch without committing results to `main`.

**Files:**
- Modify: `src/turtlebench/pages.py`
- Modify: `src/turtlebench/__main__.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_pages.py`
- Modify: `README.md`

**Steps:**
1. Write failing tests against temporary Git repositories for first publication, idempotent run replacement, preserved history, static-asset copy, index generation, and sensitive-field rejection.
2. Confirm focused failures.
3. Implement `python -m turtlebench.pages publish --run-dir ... --repo ...`, using a temporary worktree and explicit branch updates.
4. Add a dry build mode used by tests and local browser QA.
5. Document publication and models.dev price rules.
6. Run all tests and help commands.
7. Commit with `Add GitHub Pages publication command`.

### Task 5: Publish existing results

**Objective:** Create `gh-pages` and import the eight currently finalized model summaries.

**Files:**
- Branch only: `gh-pages/index.html`
- Branch only: `gh-pages/.nojekyll`
- Branch only: `gh-pages/assets/app.js`
- Branch only: `gh-pages/assets/styles.css`
- Branch only: `gh-pages/data/index.json`
- Branch only: `gh-pages/data/runs/baseline-luna-max-host-20260903.json`

**Steps:**
1. Run the publisher against the existing completed run.
2. Validate the public schema and confirm eight model rows.
3. Scan `gh-pages` tracked content for credentials, private paths, session IDs, prompts, answers, and raw logs.
4. Push `gh-pages` and verify local/remote hashes.
5. Confirm the GitHub Pages URL responds; if repository Pages settings block serving, report the exact remote state and retain the complete branch artifact.

### Task 6: Rendered browser QA and final merge

**Objective:** Verify the deployed or locally served site against the accepted visual direction and all interactions.

**Files:**
- Modify only files needed to fix verified defects.

**Steps:**
1. Serve the built `gh-pages` worktree locally.
2. Verify page identity, content, console health, desktop layout, mobile layout, and absence of page-level overflow with Browser tools.
3. Exercise chart/table switching, time/price axis switching, and ascending/descending sorting.
4. Capture desktop chart, desktop table, and mobile table screenshots outside the repository.
5. Inspect accepted concept and implementation screenshots with image analysis; record and repair material mismatches.
6. Run Python tests, Node tests, compile checks, diff checks, and credential scans.
7. Fast-forward the feature branch into `main`, push, and verify remote hashes.
8. Remove the feature worktree and branch after successful integration.
