import assert from "node:assert/strict";
import test from "node:test";

import {
  colorForFamily,
  formatBehaviorName,
  formatChartName,
  formatDuration,
  formatMoney,
  groupByFamily,
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
    price_usd: { total: 1.2 },
  },
  {
    name: "Luna",
    family: "gpt-5.6-luna",
    reasoning_effort: "high",
    overall_score: 78.1,
    active_time_s: 80,
    price_usd: { total: 0.8 },
  },
  {
    name: "DeepSeek",
    family: "deepseek-v4-flash",
    reasoning_effort: "max",
    overall_score: 68.2,
    active_time_s: 30,
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

test("known model families keep stable distinct colors", () => {
  assert.equal(colorForFamily("gpt-5.6-luna"), colorForFamily("gpt-5.6-luna"));
  assert.notEqual(colorForFamily("gpt-5.6-luna"), colorForFamily("gpt-5.6-sol"));
  assert.notEqual(colorForFamily("gpt-5.6-sol"), colorForFamily("grok-4.6"));
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
});
