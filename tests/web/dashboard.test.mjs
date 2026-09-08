import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  averageTimePerGame,
  averagePricePerGame,
  colorForFamily,
  formatBehaviorName,
  formatChartDetails,
  formatChartName,
  formatDuration,
  formatMoney,
  groupByFamily,
  groupByVariant,
  splitDisplayName,
  sortRows,
} from "../../web/assets/app.js";

const rows = [
  {
    name: "Luna",
    family: "gpt-5.6-luna",
    reasoning_effort: "max",
    overall_score: 85.9,
    active_time_s: 120,
    games: 3,
    price_usd: { total: 1.2 },
  },
  {
    name: "Luna",
    family: "gpt-5.6-luna",
    reasoning_effort: "high",
    overall_score: 78.1,
    active_time_s: 80,
    games: 2,
    price_usd: { total: 0.8 },
  },
  {
    name: "DeepSeek",
    family: "deepseek-v4-flash",
    reasoning_effort: "max",
    overall_score: 68.2,
    active_time_s: 30,
    games: 3,
    price_usd: null,
  },
];

test("sortRows sorts nested numeric values without mutating input", () => {
  const sorted = sortRows(rows, "price_usd.total", "asc");
  assert.deepEqual(sorted.map((row) => row.name), ["Luna", "Luna", "DeepSeek"]);
  assert.equal(rows[0].reasoning_effort, "max");
  assert.deepEqual(
    sortRows(rows, "overall_score", "desc").map((row) => row.overall_score),
    [85.9, 78.1, 68.2],
  );
});

test("groupByFamily orders reasoning levels for connected chart lines", () => {
  const groups = groupByFamily(rows);
  assert.deepEqual(
    groups.get("gpt-5.6-luna").map((row) => row.reasoning_effort),
    ["high", "max"],
  );
  assert.equal(groups.get("deepseek-v4-flash").length, 1);
});

test("groupByVariant merges providers for one model and reasoning level", () => {
  const groups = groupByVariant([
    { ...rows[2], provider: "commandcode", reasoning_effort: "max", overall_score: 81.6 },
    { ...rows[2], provider: "deepseek", reasoning_effort: "max", overall_score: 76.7 },
  ]);
  assert.equal(groups.size, 1);
  assert.deepEqual(
    groups.values().next().value.map((row) => row.provider),
    ["commandcode", "deepseek"],
  );
});

test("known model families keep stable distinct colors", () => {
  assert.equal(colorForFamily("gpt-5.6-luna"), colorForFamily("gpt-5.6-luna"));
  assert.notEqual(colorForFamily("gpt-5.6-luna"), colorForFamily("gpt-5.6-sol"));
  assert.notEqual(colorForFamily("gpt-5.6-sol"), colorForFamily("grok-4.6"));
});

test("chart time uses the per-game average", () => {
  assert.equal(averageTimePerGame({ active_time_s: 366, games: 3 }), 122);
  assert.equal(averageTimePerGame({ active_time_s: 366, games: 0 }), null);
});

test("chart price uses the per-game average", () => {
  assert.equal(Number(averagePricePerGame({ price_usd: { total: 1.2 }, games: 3 }).toFixed(12)), 0.4);
  assert.equal(averagePricePerGame({ price_usd: { total: 1.2 }, games: 0 }), null);
  assert.equal(averagePricePerGame({ price_usd: null, games: 3 }), null);
  assert.deepEqual(
    sortRows([
      { name: "two games", price_usd: { total: 2 }, games: 2 },
      { name: "one game", price_usd: { total: 1.5 }, games: 1 },
    ], "price_usd.total_per_game", "asc").map((row) => row.name),
    ["two games", "one game"],
  );
});

test("time is the default chart axis while price remains available", () => {
  const html = readFileSync(new URL("../../web/index.html", import.meta.url), "utf8");
  assert.ok(html.includes('data-axis data-value="price" aria-pressed="false">每局平均价格</button>'));
  assert.ok(html.includes('data-value="time" aria-pressed="true"'));
  const app = readFileSync(new URL("../../web/assets/app.js", import.meta.url), "utf8");
  assert.ok(app.includes('let axis = "time";'));
});

test("formatters keep resource values compact and explicit", () => {
  assert.equal(formatDuration(65), "1分 5秒");
  assert.equal(formatDuration(3661), "1时 1分");
  assert.equal(formatMoney(1.23456), "$1.2346");
  assert.equal(formatMoney(null), "—");
  assert.equal(formatBehaviorName(rows[0]), "Luna · max");
  assert.equal(formatChartName({ ...rows[0], name: "OpenAI Codex / GPT-5.6 Luna" }), "GPT-5.6 Luna · max");
  assert.deepEqual(splitDisplayName("OpenAI Codex / GPT-5.6 Luna"), {
    provider: "OpenAI Codex",
    model: "GPT-5.6 Luna",
  });
  assert.deepEqual(formatChartDetails({
    ...rows[2],
    name: "DeepSeek / DeepSeek V4 Flash",
    provider: "deepseek",
  }, "price", [
    { ...rows[2], provider: "deepseek", overall_score: 76.7 },
    { ...rows[2], provider: "commandcode", overall_score: 81.6 },
  ]), {
    model: "DeepSeek V4 Flash",
    reasoning_effort: "max",
    providers: [
      { provider: "deepseek", score: "76.7", metric: "—", games: "3" },
      { provider: "commandcode", score: "81.6", metric: "—", games: "3" },
    ],
  });
});
