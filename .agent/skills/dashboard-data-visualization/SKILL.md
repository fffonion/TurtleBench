---
name: dashboard-data-visualization
description: Use when fixing dashboard charts, axes, or metric displays.
version: 1.1.0
author: Hermes Agent
tags: [dashboard, charts, visualization, testing]
---

# Dashboard Data Visualization

Use this for dashboard UI work where operational metrics are graphed, summarized, or visually compared. The goal is legible charts backed by real data and verified in a browser, not only syntactic changes.

## Core Principles

- Match chart scale to the metric. If series magnitudes differ by orders of magnitude, separate their axes or split the chart.
- Keep axis ownership in series metadata so desktop and mobile renderers cannot drift.
- Treat zero-heavy operational data carefully: repeated rounded tick labels make charts look broken.
- Verify rendered charts visually after code tests pass. Canvas/SVG bugs often pass unit tests while still looking wrong.
- For service dashboards, activation is separate from installation. If the user says not to restart, use a temporary preview process with copied state instead of touching the live service.

## Reference-Driven Area Chart Pattern

When a user supplies a chart screenshot as the accepted visual direction, preserve the chart's real data and axis semantics while adopting its visual language:

- extract surface, stroke, fill, grid, label-density, and interaction tokens from the reference;
- render high-volume context series first as a low-opacity background area;
- render foreground activity series with restrained gradient fills and thin monotone strokes;
- remove persistent point markers and show markers only at the active hover/touch index;
- keep separate axes for unrelated magnitudes even when the reference visually de-emphasizes axis labels;
- verify with representative non-zero data at explicit desktop and phone viewports.

See [references/layered-area-chart-visual-language.md](references/layered-area-chart-visual-language.md) for Canvas ordering, suggested opacity ranges, and screenshot-verification pitfalls.

## Multi-Axis Chart Pattern

When one chart mixes high-volume counters with low-volume activity counters:

1. Give every series explicit metadata: `{ key, label, color, axis: 'left' | 'right' }`.
2. Compute `leftMax` from only left-axis series and `rightMax` from only right-axis series.
3. Render each line using the max for its own axis.
4. Draw grid lines once, normally from the left axis.
5. Reserve label margin on both sides at desktop and phone widths.
6. Suppress consecutive duplicate tick labels after rounding.
7. Skip the right-axis `0` label, and hide the right axis entirely when all right-axis series are zero.

See [references/canvas-dashboard-charts.md](references/canvas-dashboard-charts.md) for a condensed implementation/verification checklist.

## Regression Tests

Prefer behavior-focused checks that lock the visible contract:

- Series metadata includes explicit axis ownership.
- Per-axis scale helpers exist.
- The renderer calculates left and right maxima separately.
- Line drawing chooses the scale by `series.axis`.
- Right-axis rendering is gated by positive right-axis data.
- Right-side label margin and label placement exist.

String assertions are acceptable for embedded static assets, but pair them with real browser preview when chart legibility was the failure.

## Browser Verification

After tests and release build:

1. Start the built dashboard artifact on a loopback-only temporary port.
2. Use a copied database or fixture data so the preview cannot mutate live state.
3. Open the temp URL with the browser tool.
4. Capture/inspect the chart and confirm the scale, axis labels, line visibility, and zero-label behavior.
5. Kill the temporary process.

If a Browser screenshot's pixel width does not match `window.innerWidth`, do not infer layout overflow from the cropped image. Inspect `document.documentElement.scrollWidth` and element bounding rectangles first; when screenshot evidence remains cropped, use the existing Playwright installation with an explicit desktop/mobile viewport and record that Browser screenshot limitation.

Do not claim chart quality from code inspection alone when the user complained about visual output.

## Commit / Deployment Discipline

- Keep commit subjects concise and descriptive; do not add a verification prefix.
- Install the verified artifact when that is part of the repo workflow.
- Do not restart a service after a UI-only fix unless the user explicitly asks for activation.
