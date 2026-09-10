import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  averageTimePerGame,
  averagePricePerGame,
  colorForFamily,
  detectLanguage,
  formatBehaviorName,
  formatChartDetails,
  formatChartName,
  formatDuration,
  formatMoney,
  formatTableModelName,
  groupByFamily,
  groupByVariant,
  isDisplayableModel,
  isPlottable,
  splitDisplayName,
  sortRows,
  translate,
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

test("language detection supports browser preference and explicit overrides", () => {
  assert.equal(detectLanguage("auto", ["en-US", "en"]), "en");
  assert.equal(detectLanguage("auto", ["zh-CN", "en-US"]), "zh");
  assert.equal(detectLanguage("en", ["zh-CN"]), "en");
  assert.equal(detectLanguage("zh", ["en-US"]), "zh");
  assert.equal(translate("performance"), "综合表现");
});

test("price is the default chart axis while time remains available", () => {
  const html = readFileSync(new URL("../../web/index.html", import.meta.url), "utf8");
  assert.ok(html.includes('data-value="price"'));
  assert.ok(html.includes('>每局平均价格</button>'));
  assert.ok(html.includes('data-value="price" aria-pressed="true"'));
  assert.ok(html.includes('data-value="time" aria-pressed="false"'));
  const app = readFileSync(new URL("../../web/assets/app.js", import.meta.url), "utf8");
  assert.ok(app.includes('let axis = "price";'));
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

test("partial result rows remain available without status annotation", () => {
  const partial = {
    ...rows[0],
    overall_score: 65.4,
    status: "stopped",
    partial: true,
    score_status: "partial_judged",
  };
  assert.equal(formatBehaviorName(partial), "Luna · max");
  assert.equal(formatTableModelName(partial, true), "Luna");
  assert.equal(formatChartName({
    ...partial,
    name: "OpenAI Codex / GPT-5.6 Luna",
  }), "GPT-5.6 Luna · max");
  assert.equal(isDisplayableModel(partial), false);
  assert.equal(isPlottable(partial, "price"), false);
  assert.deepEqual(sortRows([partial, rows[0]], "overall_score", "desc"), [rows[0], partial]);
  assert.equal(isDisplayableModel(rows[0]), true);
  assert.equal(isPlottable(rows[0], "price"), true);
});

test("all partial rows stay out of the public model view even with a score", () => {
  assert.equal(isDisplayableModel({ ...rows[0], partial: true, overall_score: 81.5 }), false);
  assert.equal(isDisplayableModel({ ...rows[0], score_status: "pending_judge" }), false);
  assert.equal(isDisplayableModel({ ...rows[0], status: "stopped" }), false);
  assert.equal(isDisplayableModel({ ...rows[0], overall_score: null }), false);
});
