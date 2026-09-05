# TurtleBench GitHub Pages Dashboard Design

**Date:** 2026-09-05
**Status:** Proposed for implementation

## 1. Goal

Publish finalized TurtleBench benchmark aggregates as a responsive GitHub Pages dashboard. The dashboard must remain readable on desktop and mobile, support chart/table switching, expose sortable resource metrics, and include a separate model-behavior table.

Raw conversations, prompts, puzzle answers, session IDs, local paths, credentials, invalid trial archives, and logs must not be published.

## 2. Selected architecture

Use a framework-free static site built with semantic HTML, CSS, JavaScript, and an SVG chart.

This keeps the `gh-pages` branch directly deployable, avoids a JavaScript build toolchain, and keeps later result publication to a deterministic Python export followed by a branch update.

Alternatives considered:

- React, Vite, and a chart package: richer component ecosystem with more dependencies and a build step.
- A Python-generated single HTML file: minimal file count with weaker separation between UI and historical result data.

## 3. Branch responsibilities

### `main`

Contains maintained source and tooling:

- dashboard exporter and pricing resolver
- models.dev model/provider mapping
- static asset source or templates
- tests
- publishing documentation

Benchmark results do not enter `main`.

### `gh-pages`

Contains deployable assets and sanitized aggregates:

```text
index.html
.nojekyll
assets/app.js
assets/styles.css
data/index.json
data/runs/<run-id>.json
```

`data/index.json` lists published runs and selects the newest run by default. Each run document is self-contained and includes metric aggregates, model identity, reasoning effort, and a price snapshot.

## 4. Publication flow

The repository provides a command with this shape:

```bash
python -m turtlebench.pages publish \
  --run-dir /path/to/completed-run \
  --repo /path/to/TurtleBench
```

The command performs these steps:

1. Require a completed run and read model summaries.
2. Read valid trial `score.json` and `player_totals.json` files.
3. Aggregate and validate the public metrics.
4. Fetch current models.dev pricing data and resolve each benchmark model through the maintained mapping.
5. Apply the pricing policy in section 6.
6. Produce a sanitized run JSON document.
7. Create or reuse a temporary `gh-pages` worktree.
8. Copy the static site, append or replace the matching run document, and rebuild `data/index.json`.
9. Run static-data validation and credential scanning.
10. Commit and push `gh-pages`.

Re-publishing the same `run_id` replaces that run document. Other historical runs remain available. Incomplete models are omitted until their summary and valid-game inputs are complete.

The first publication imports the currently finalized eight model summaries from `baseline-luna-max-host-20260903`. Later finalized models and runs use the same command.

## 5. Public run schema

Each model row stores:

```json
{
  "slug": "luna-max",
  "name": "GPT-5.6 Luna",
  "provider": "openai-codex",
  "model": "gpt-5.6-luna",
  "family": "gpt-5.6-luna",
  "reasoning_effort": "max",
  "overall_score": 85.9,
  "games": 36,
  "active_time_s": 15966.958,
  "tokens": {
    "total": 99964085,
    "input": 5887689,
    "output": 639468,
    "cache_read": 93436928,
    "cache_write": 0
  },
  "price_usd": {
    "total": 0,
    "input": 0,
    "output": 0,
    "cache_read": 0,
    "cache_write": 0
  },
  "behavior": {
    "solve_rate": 0.861,
    "rounds_median": 22,
    "hints_median": 1,
    "samples": 36
  },
  "pricing": {
    "source": "https://models.dev",
    "source_model_id": "openai/gpt-5.6-luna",
    "source_provider_id": "openai",
    "fetched_at": "ISO-8601 timestamp",
    "usd_per_million_tokens": {
      "input": 0,
      "output": 0,
      "cache_read": 0,
      "cache_write": 0
    }
  }
}
```

The numeric values above illustrate the schema. The exporter calculates published values from source files and fetched pricing.

`tokens.total` is the sum of input, output, cache-read, and cache-write tokens. Reasoning tokens remain part of model usage metadata but are not added again when already included in output usage.

`behavior.hints_median` is computed across valid trial `score.json` values at `metrics.hints_used`. Invalid and archived trials are excluded from all public aggregates.

## 6. Pricing policy

Prices are USD per million tokens and come from `https://models.dev/api.json`.

A versioned mapping connects each benchmark provider/model pair to a models.dev provider and model ID. Official provider records are preferred. A benchmark provider absent from models.dev maps to the canonical model provider; CommandCode DeepSeek V4 Flash maps to the DeepSeek model record.

Rules:

1. Use standard published token rates.
2. Ignore free plans, subscription-plan zero prices, trial prices, dated promotions, and limited-time discounts.
3. If a provider exposes peak and off-peak rates, use the lower off-peak rate.
4. Preserve distinct input, output, cache-read, and cache-write rates.
5. A missing cache rate contributes zero when that token category has zero usage or models.dev explicitly records zero. If usage is positive and the rate is absent, the price component and total price are marked unavailable instead of inferred.
6. Snapshot the resolved rates, source IDs, and fetch timestamp into every published run.
7. Context-size tiers are kept separate from peak/off-peak pricing. The base tier is used unless source usage gains enough per-request detail to select a context tier accurately.

The UI shows `—` for an unavailable price and excludes that point from the price-axis chart while retaining the row in tables.

## 7. Dashboard interaction

### Header

Display:

- TurtleBench
- 海龟汤模型基准
- suite version
- puzzle count
- repeat count
- selected run date

A run selector appears only after more than one run is published.

### Combined-performance section

A segmented control switches exclusively between:

- `图表`
- `表格`

The inactive view is hidden.

#### Chart view

- Y axis is always `综合分`.
- X axis switches between `总耗时` and `总价格`.
- One point represents one model and reasoning-effort combination.
- Model families have fixed, accessible colors.
- Multiple reasoning efforts in one family are connected by a thin same-color line.
- Point labels include model name and raw reasoning effort.
- Time values use seconds internally and human-readable labels.
- Price values use USD.
- SVG marks, labels, and axes resize to the container.

#### Resource table view

One row represents one model and reasoning-effort combination. Columns:

1. 模型
2. 推理等级
3. 综合分
4. 局数
5. 总耗时
6. 总 Token
7. 输入
8. 输出
9. Cache 读
10. Cache 写
11. 总价格

Reasoning-effort values use their original lowercase English text, such as `max`, `high`, `medium`, and `low`. They are plain text with no pill, badge, chip, border, or background.

Every complete header cell is clickable and keyboard-operable. The first click sorts descending for numeric metrics and ascending for text. Repeated clicks toggle direction. The active header exposes direction through both an icon and `aria-sort`.

The total-price cell includes a compact input/output/cache cost breakdown without adding more columns.

### Model-behavior table

This table remains visible below the combined-performance section and has no chart. Columns:

1. 名字
2. 综合分
3. 解出率
4. 轮数中位数
5. 提示数量中位数
6. 样本数

Its headers follow the same sorting behavior.

## 8. Responsive behavior

### Desktop

- Content width is capped for readable chart labels and table scanning.
- Chart uses the available width.
- Tables retain one-line numeric cells and dense row spacing.

### Mobile

- Controls wrap into full-width touch rows.
- The chart keeps a practical minimum height and shortens labels where necessary.
- Tables remain tables inside horizontal scroll containers.
- Header rows and first model/name columns are sticky.
- A right-edge fade and `左右滑动查看更多` hint communicate horizontal scrolling.
- Full header cells provide at least 44px touch targets.
- No data row is converted into a card.

The page uses a plain white canvas. Reasoning-effort values have no separate background treatment.

## 9. Accessibility

- Use native buttons for view and axis controls.
- Preserve visible focus indicators.
- Expose selected states with `aria-pressed`.
- Use real table headers with `scope="col"` and `aria-sort`.
- Do not rely on color alone; chart points include direct text labels and line grouping.
- Respect reduced-motion preferences.

## 10. Failure handling

Publishing stops before modifying `gh-pages` when:

- the run is incomplete
- summary/player metadata disagree
- required valid trial data is missing
- a metric contains a non-finite value
- duplicate model slugs occur
- the generated public document fails its schema checks
- credential patterns or private paths appear in generated output

Missing prices remain a valid publication state and display as unavailable, with the affected chart points omitted only from the price-axis view.

The browser shows a compact error message if `data/index.json` or the selected run document cannot load.

## 11. Tests and acceptance criteria

### Exporter tests

- imports existing eight finalized summaries
- ignores archived and invalid trials
- calculates token categories and total
- calculates hint median from valid scores
- validates model identity and reasoning effort
- resolves models.dev mappings and snapshots rates
- rejects promotional/free-plan pricing records
- chooses off-peak rates when present
- handles absent cache pricing without inventing a value
- emits no local paths, sessions, prompts, answers, logs, or credentials
- replaces a run idempotently without deleting other runs

### Frontend tests

- switches chart/table views exclusively
- switches chart X axis between time and price
- connects same-family reasoning levels
- assigns different family colors
- sorts every table column in both directions
- exposes accessible control and sort state
- renders unavailable prices safely

### Browser verification

Verify desktop and phone viewports with real exported data. Confirm no horizontal page overflow, tables scroll within their containers, sticky cells remain aligned, chart labels are readable, and all controls work by pointer and keyboard.

### Deployment acceptance

- `gh-pages` contains existing finalized aggregate results and no raw trial content.
- GitHub Pages loads over HTTPS.
- local and remote `gh-pages` hashes match after publication.
- the main branch test suite passes.
- a repository-wide credential scan reports no findings.
