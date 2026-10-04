const LANGUAGE_STORAGE_KEY = "turtlebench-language";
const DATA_CACHE_BUSTER = "2score13";

const MESSAGES = {
  zh: {
    documentTitle: "TurtleBench · 海龟汤模型基准",
    description: "TurtleBench 海龟汤模型基准结果",
    subtitle: "海龟汤模型基准",
    loading: "正在读取结果…",
    resultBatch: "结果批次",
    language: "语言",
    autoLanguage: "自动",
    chinese: "中文",
    english: "English",
    performance: "综合表现",
    viewModes: "综合表现展示方式",
    view: "视图",
    chart: "图表",
    table: "表格",
    xAxis: "X 轴",
    averagePrice: "每局平均价格",
    averageTime: "每局平均耗时",
    score: "综合分",
    scoreMode: "评分模式",
    formulaScore: "公式得分",
    subjectiveScore: "主观评价分",

    behavior: "模型行为",
    puzzles: "{count} 道题",
    repeats: "每题 {count} 局",
    unknown: "未知",
    priceSource: "价格来源：各 provider 官方 API / models.dev 目录",
    chartRelation: "综合分与{metric}关系图",
    priceAxis: "每局平均价格（USD）",
    timeAxis: "每局平均耗时",
    priceTooltip: "每局平均价格",
    timeTooltip: "每局平均耗时",
    missingPrice: "当前结果缺少可计算的价格。",
    missingTime: "当前结果缺少耗时数据。",
    readError: "结果读取失败",
    httpReadError: "无法读取结果（{status}）",
    model: "模型",
    effort: "推理等级",
    games: "局数",
    totalTime: "总耗时",
    totalTokens: "总 Token",
    inputTokens: "输入",
    outputTokens: "输出",
    cacheRead: "Cache 读",
    cacheWrite: "Cache 写",
    averagePriceColumn: "每局平均价格",
    solveRate: "解出率",
    roundsMedian: "轮数中位数",
    hintsMedian: "提示数量中位数",
    samples: "样本数",
    inputShort: "入",
    outputShort: "出",
    cacheReadShort: "读",
    cacheWriteShort: "写",
    providers: "{count} 个运营商，点击查看详情",
    tooltipLine: "{provider} · {scoreLabel} {score} · {metricLabel} {metric} · {games} 局",
    effortNone: "none",
    effortMinimal: "minimal",
    effortLow: "low",
    effortMedium: "medium",
    effortHigh: "high",
    effortMax: "max",
    effortXhigh: "xhigh",
  },
  en: {
    documentTitle: "TurtleBench · Turtle Soup Model Benchmark",
    description: "TurtleBench turtle soup model benchmark results",
    subtitle: "Turtle Soup Model Benchmark",
    loading: "Loading results…",
    resultBatch: "Result batch",
    language: "Language",
    autoLanguage: "Auto",
    chinese: "中文",
    english: "English",
    performance: "Overall performance",
    viewModes: "Overall performance display mode",
    view: "View",
    chart: "Chart",
    table: "Table",
    xAxis: "X axis",
    averagePrice: "Average price per game",
    averageTime: "Average time per game",
    score: "Overall score",
    scoreMode: "Score mode",
    formulaScore: "Formula score",
    subjectiveScore: "Subjective score",

    behavior: "Model behavior",
    puzzles: "{count} puzzles",
    repeats: "{count} games per puzzle",
    unknown: "Unknown",
    priceSource: "Price source: provider API pricing / models.dev catalog",
    chartRelation: "Overall score vs. {metric}",
    priceAxis: "Average price per game (USD)",
    timeAxis: "Average time per game",
    priceTooltip: "Average price per game",
    timeTooltip: "Average time per game",
    missingPrice: "No computable prices in the current results.",
    missingTime: "No time data in the current results.",
    readError: "Failed to read results",
    httpReadError: "Unable to read results ({status})",
    model: "Model",
    effort: "Reasoning",
    games: "Games",
    totalTime: "Total time",
    totalTokens: "Total tokens",
    inputTokens: "Input",
    outputTokens: "Output",
    cacheRead: "Cache read",
    cacheWrite: "Cache write",
    averagePriceColumn: "Average price per game",
    solveRate: "Solve rate",
    roundsMedian: "Median rounds",
    hintsMedian: "Median hints",
    samples: "Samples",
    inputShort: "in",
    outputShort: "out",
    cacheReadShort: "read",
    cacheWriteShort: "write",
    providers: "{count} provider(s), click for details",
    tooltipLine: "{provider} · {scoreLabel} {score} · {metricLabel} {metric} · {games} games",
    effortNone: "none",
    effortMinimal: "minimal",
    effortLow: "low",
    effortMedium: "medium",
    effortHigh: "high",
    effortMax: "max",
    effortXhigh: "xhigh",
  },
};

let currentLanguage = "zh";

function interpolate(template, values = {}) {
  return template.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ""));
}

export function translate(key, values = {}) {
  const template = MESSAGES[currentLanguage][key] ?? MESSAGES.zh[key] ?? key;
  return interpolate(template, values);
}

export function detectLanguage(preference = "auto", languages = []) {
  if (preference === "zh" || preference === "en") return preference;
  const candidates = languages.length
    ? languages
    : (typeof navigator !== "undefined" ? navigator.languages || [navigator.language] : []);
  return candidates.some((language) => String(language).toLowerCase().startsWith("zh")) ? "zh" : "en";
}

export function applyLanguage(language) {
  currentLanguage = language === "zh" ? "zh" : "en";
  if (typeof document === "undefined") return currentLanguage;
  document.documentElement.lang = currentLanguage === "zh" ? "zh-CN" : "en";
  document.title = translate("documentTitle");
  const description = document.querySelector('meta[name="description"]');
  if (description) description.setAttribute("content", translate("description"));
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = translate(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((element) => {
    element.setAttribute("aria-label", translate(element.dataset.i18nAriaLabel));
  });
  return currentLanguage;
}

function readLanguagePreference() {
  try {
    const value = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return value === "zh" || value === "en" ? value : "auto";
  } catch {
    return "auto";
  }
}

function saveLanguagePreference(value) {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, value);
  } catch {
    // Ignore storage restrictions and keep the current page language.
  }
}

const EFFORT_ORDER = new Map([
  ["none", 0],
  ["minimal", 1],
  ["low", 2],
  ["medium", 3],
  ["high", 4],
  ["max", 5],
  ["xhigh", 6],
]);

const FAMILY_GROUP_COLORS = new Map([
  ["gpt-luna", "#173b63"],
  ["gpt-sol", "#a06b13"],
  ["gpt-astra", "#2774a8"],
  ["deepseek", "#c2553d"],
  ["claude", "#6d4ca1"],
  ["grok", "#9c3f69"],
  ["minimax", "#0f766e"],
  ["mimo", "#0b7f8c"],
  ["glm", "#4f6b3d"],
  ["qwen", "#80553f"],
  ["step", "#b14b32"],
  ["union", "#50657a"],
]);

const FAMILY_VARIANT_COLORS = new Map([
  ["gpt-5.6-luna", "#173b63"],
  ["gpt-6-luna", "#2c5d89"],
  ["gpt-5.6-sol", "#a06b13"],
  ["gpt-6-sol", "#c18a25"],
  ["gpt-6.1-sol", "#81510a"],
  ["gpt-6-astra", "#2774a8"],
  ["deepseek-v4-flash", "#c2553d"],
  ["deepseek-v4.1-flash", "#dc7257"],
  ["claude-sonnet-5", "#6d4ca1"],
  ["grok-4.6", "#9c3f69"],
  ["grok-4.7", "#b85a80"],
  ["minimax-m3", "#0f766e"],
  ["minimax-m3.1-flash-preview", "#2b9988"],
  ["mimo-v2.6-flash", "#0b7f8c"],
  ["mimo-v2.6-pro", "#3a9ca7"],
  ["glm-5.3", "#4f6b3d"],
  ["glm-5.3-flash", "#729352"],
  ["qwen3.8-flash", "#80553f"],
  ["step-5-preview", "#b14b32"],
  ["union-alpha", "#50657a"],
]);

const FALLBACK_FAMILY_COLORS = [
  "#265d91",
  "#8b5a9b",
  "#a36a1d",
  "#287d69",
  "#b2475d",
  "#526c35",
  "#725b96",
  "#2f7183",
];

function familyColorGroup(family) {
  const value = String(family).toLowerCase();
  if (/^gpt-[0-9.]+-luna$/.test(value)) return "gpt-luna";
  if (/^gpt-[0-9.]+-sol$/.test(value)) return "gpt-sol";
  if (/^gpt-[0-9.]+-astra$/.test(value)) return "gpt-astra";
  if (value.startsWith("deepseek-")) return "deepseek";
  if (value.startsWith("claude-")) return "claude";
  if (value.startsWith("grok-")) return "grok";
  if (value.startsWith("minimax-")) return "minimax";
  if (value.startsWith("mimo-")) return "mimo";
  if (value.startsWith("glm-")) return "glm";
  if (value.startsWith("qwen")) return "qwen";
  if (value.startsWith("step-")) return "step";
  if (value.startsWith("union-")) return "union";
  return value;
}

export function colorForFamily(family) {
  const value = String(family).toLowerCase();
  if (FAMILY_VARIANT_COLORS.has(value)) return FAMILY_VARIANT_COLORS.get(value);
  const group = familyColorGroup(value);
  if (FAMILY_GROUP_COLORS.has(group)) return FAMILY_GROUP_COLORS.get(group);
  let hash = 0;
  for (const character of group) hash = (hash * 31 + character.codePointAt(0)) >>> 0;
  return FALLBACK_FAMILY_COLORS[hash % FALLBACK_FAMILY_COLORS.length];
}

export function reasoningOpacity(rows, row) {
  const levels = rows
    .map((item) => EFFORT_ORDER.get(item.reasoning_effort))
    .filter((value) => Number.isFinite(value));
  const level = EFFORT_ORDER.get(row?.reasoning_effort);
  if (!Number.isFinite(level) || !levels.length) return 1;
  const minimum = Math.min(...levels);
  const maximum = Math.max(...levels);
  if (minimum === maximum) return 1;
  return Number((0.65 + ((level - minimum) / (maximum - minimum)) * 0.35).toFixed(3));
}

function nestedValue(row, path) {
  return path.split(".").reduce((value, key) => value?.[key], row);
}

export function scoreForRow(row, mode = "subjective") {
  if (!row) return null;
  const value = mode === "formula" ? row.formula_score : (row.subjective_score ?? row.overall_score);
  return Number.isFinite(value) ? Number(value) : null;
}

export function scoreLabel(mode = "subjective") {
  return mode === "formula" ? translate("formulaScore") : translate("subjectiveScore");
}

function sortableValue(row, key, scoreMode = "subjective") {
  if (key === "price_usd.total_per_game") return averagePricePerGame(row);
  if (key === "overall_score") return scoreForRow(row, scoreMode);
  return nestedValue(row, key);
}

export function sortRows(rows, key, direction = "asc", scoreMode = "subjective") {
  const sign = direction === "desc" ? -1 : 1;
  return [...rows].sort((left, right) => {
    const a = sortableValue(left, key, scoreMode);
    const b = sortableValue(right, key, scoreMode);
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    if (scoreMode === "formula" && key === "overall_score") {
      const leftProvisional = left.formula_provisional === true;
      const rightProvisional = right.formula_provisional === true;
      if (leftProvisional !== rightProvisional) return leftProvisional ? 1 : -1;
    }
    if (typeof a === "number" && typeof b === "number") return (a - b) * sign;
    return String(a).localeCompare(String(b), "zh-CN", { numeric: true }) * sign;
  });
}

export function groupByFamily(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const family = row.family || row.model;
    if (!groups.has(family)) groups.set(family, []);
    groups.get(family).push(row);
  });
  groups.forEach((items) => {
    items.sort(
      (a, b) =>
        (EFFORT_ORDER.get(a.reasoning_effort) ?? 99) -
        (EFFORT_ORDER.get(b.reasoning_effort) ?? 99),
    );
  });
  return groups;
}

export function chartFamilyKey(row) {
  const parts = splitDisplayName(String(row.name ?? ""));
  const displayModel = parts.model || row.family || row.model || "";
  return String(displayModel)
    .toLowerCase()
    .replace(/\bexpires-on-\d{4}\b/g, "")
    .replace(/[^a-z0-9.-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function groupByVariant(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const key = `${chartFamilyKey(row)}|${row.reasoning_effort || ""}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  return groups;
}

function groupByChartFamily(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const key = chartFamilyKey(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  groups.forEach((items) => {
    items.sort(
      (a, b) =>
        (EFFORT_ORDER.get(a.reasoning_effort) ?? 99) -
        (EFFORT_ORDER.get(b.reasoning_effort) ?? 99),
    );
  });
  return groups;
}

export function chartLegendEntries(models) {
  return [...groupByChartFamily(models).entries()]
    .map(([family, items]) => ({
      family,
      label: splitDisplayName(items[0].name).model,
      reasoning: items.map((item) => item.reasoning_effort),
    }))
    .sort((left, right) => left.label.localeCompare(right.label, undefined, {
      numeric: true,
      sensitivity: "base",
    }));
}

export function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const value = Math.max(0, Math.round(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const remainder = value % 60;
  if (currentLanguage === "en") {
    if (hours) return `${hours}h ${minutes}m`;
    if (minutes) return `${minutes}m ${remainder}s`;
    return `${remainder}s`;
  }
  if (hours) return `${hours}时 ${minutes}分`;
  if (minutes) return `${minutes}分 ${remainder}秒`;
  return `${remainder}秒`;
}

export function formatMoney(value) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `$${value.toFixed(4)}`;
}

export function splitDisplayName(name) {
  const separator = " / ";
  if (!name.includes(separator)) return { provider: "", model: name };
  const [provider, ...modelParts] = name.split(separator);
  return { provider, model: modelParts.join(separator) };
}

export function isDisplayableModel(row, scoreMode = "subjective") {
  return Boolean(
    row
      && row.partial !== true
      && row.status !== "stopped"
      && row.score_status == null
      && scoreForRow(row, scoreMode) != null,
  );
}

export function formatBehaviorName(row) {
  return `${row.name} · ${formatEffort(row.reasoning_effort)}`;
}

export function formatChartName(row) {
  return `${splitDisplayName(row.name).model} · ${formatEffort(row.reasoning_effort)}`;
}

export function formatTableModelName(row, behavior = false, scoreMode = "subjective") {
  const model = splitDisplayName(row.name).model;
  return model;
}

export function formatTableProviderName(row) {
  const provider = row?.provider || splitDisplayName(row?.name || "").provider;
  if (!provider) return "";
  const effort = row?.reasoning_effort;
  return effort ? `${provider} · ${formatEffort(effort)}` : provider;
}

function formatEffort(effort) {
  const value = String(effort ?? "");
  const effortKey = `effort${value.replace(/^./, (letter) => letter.toUpperCase())}`;
  return translate(effortKey) === effortKey ? value : translate(effortKey);
}

export function averageTimePerGame(model) {
  if (!Number.isFinite(model.active_time_s) || !Number.isFinite(model.games) || model.games <= 0) return null;
  return model.active_time_s / model.games;
}

export function averagePricePerGame(model) {
  if (!Number.isFinite(model.price_usd?.total) || !Number.isFinite(model.games) || model.games <= 0) return null;
  return model.price_usd.total / model.games;
}

function formatNumber(value) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(currentLanguage === "en" ? "en-US" : "zh-CN").format(value);
}

function formatScore(value) {
  return Number.isFinite(value) ? Number(value).toFixed(1) : "—";
}

function formatPercent(value) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function colorMap(models) {
  const families = [...new Set(models.map((model) => chartFamilyKey(model)))];
  return new Map(families.map((family) => [family, colorForFamily(family)]));
}

function chartMetric(model, axis) {
  return axis === "price" ? averagePricePerGame(model) : averageTimePerGame(model);
}

export function isPlottable(model, axis, scoreMode = "subjective") {
  return isDisplayableModel(model, scoreMode) && Number.isFinite(chartMetric(model, axis));
}

function chartLabel(value, axis) {
  return axis === "price" ? formatMoney(value) : formatDuration(value);
}

export function formatChartDetails(row, axis, providers = [row], scoreMode = "subjective") {
  const parts = splitDisplayName(row.name);
  return {
    model: parts.model,
    reasoning_effort: row.reasoning_effort,
    providers: providers.map((providerRow) => {
      const providerParts = splitDisplayName(providerRow.name);
      return {
        provider: providerRow.provider || providerParts.provider,
        score: formatScore(scoreForRow(providerRow, scoreMode)),
        metric: chartLabel(chartMetric(providerRow, axis), axis),
        games: formatNumber(providerRow.games),
      };
    }),
  };
}

function positionChartTooltip(host, tooltip, clientX, clientY) {
  const hostRect = host.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();
  const padding = 10;
  const offset = 14;
  const preferredLeft = clientX - hostRect.left + offset;
  const preferredTop = clientY - hostRect.top + offset;
  const left = Math.min(
    Math.max(padding, preferredLeft),
    Math.max(padding, hostRect.width - tooltipRect.width - padding),
  );
  const top = Math.min(
    Math.max(padding, preferredTop),
    Math.max(padding, hostRect.height - tooltipRect.height - padding),
  );
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
  tooltip.style.right = "auto";
}

function renderChartTooltip(
  host,
  row,
  axis,
  providers = [row],
  scoreMode = "subjective",
  pointerEvent = null,
  anchorElement = null,
) {
  let tooltip = host.querySelector(".chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    tooltip.setAttribute("role", "status");
    host.append(tooltip);
  }
  const details = formatChartDetails(row, axis, providers, scoreMode);
  tooltip.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = `${details.model} · ${details.reasoning_effort}`;
  tooltip.append(title);
  details.providers.forEach((provider) => {
    const line = document.createElement("span");
    line.className = "chart-tooltip-provider";
    line.textContent = translate("tooltipLine", {
      provider: provider.provider || translate("unknown"),
      scoreLabel: scoreLabel(scoreMode),
      score: provider.score,
      metricLabel: axis === "price" ? translate("priceTooltip") : translate("timeTooltip"),
      metric: provider.metric,
      games: provider.games,
    });
    tooltip.append(line);
  });
  tooltip.hidden = false;
  if (pointerEvent && Number.isFinite(pointerEvent.clientX) && Number.isFinite(pointerEvent.clientY)) {
    positionChartTooltip(host, tooltip, pointerEvent.clientX, pointerEvent.clientY);
  } else if (anchorElement) {
    const anchorRect = anchorElement.getBoundingClientRect();
    positionChartTooltip(
      host,
      tooltip,
      anchorRect.left + anchorRect.width / 2,
      anchorRect.top + anchorRect.height / 2,
    );
  }
}

function hideChartTooltip(host) {
  const tooltip = host.querySelector(".chart-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function setChartFamilyState(svg, legendHost, family = null) {
  [svg, legendHost].forEach((container) => {
    container.querySelectorAll("[data-chart-family]").forEach((element) => {
      const active = family != null && element.dataset.chartFamily === family;
      element.classList.toggle("is-active", active);
    });
  });
}

function renderChartLegend(legendHost, svg, models, colors) {
  const entries = chartLegendEntries(models);
  const title = document.createElement("h3");
  title.className = "chart-legend-title";
  title.textContent = translate("model");
  legendHost.append(title);

  entries.forEach((entry) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "chart-legend-item";
    item.dataset.chartFamily = entry.family;
    item.setAttribute("aria-label", `${entry.label} · ${entry.reasoning.join(", ")}`);
    item.title = `${entry.label} · ${entry.reasoning.join(", ")}`;

    const swatch = document.createElement("span");
    swatch.className = "chart-legend-swatch";
    swatch.style.backgroundColor = colors.get(entry.family);
    swatch.setAttribute("aria-hidden", "true");
    item.append(swatch);

    const label = document.createElement("span");
    label.className = "chart-legend-label";
    label.textContent = entry.label;
    item.append(label);

    item.addEventListener("pointerenter", () => setChartFamilyState(svg, legendHost, entry.family));
    item.addEventListener("pointerleave", () => setChartFamilyState(svg, legendHost));
    item.addEventListener("focus", () => setChartFamilyState(svg, legendHost, entry.family));
    item.addEventListener("blur", () => setChartFamilyState(svg, legendHost));
    legendHost.append(item);
  });
}

function renderChart(models, axis, scoreMode = "subjective") {
  const host = document.querySelector("#chart");
  host.replaceChildren();
  const candidates = models.filter((model) => isPlottable(model, axis, scoreMode));
  const plotted = [...groupByVariant(candidates).values()].map((providers) => ({
    model: providers.reduce((highest, row) => (
      scoreForRow(row, scoreMode) > scoreForRow(highest, scoreMode) ? row : highest
    )),
    providers,
  }));
  if (!plotted.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = axis === "price" ? translate("missingPrice") : translate("missingTime");
    host.append(empty);
    return;
  }

  const width = 900;
  const height = 500;
  const margin = { top: 42, right: 30, bottom: 72, left: 72 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xValues = plotted.map(({ model }) => chartMetric(model, axis));
  const maxX = Math.max(...xValues, 1) * 1.12;
  const minScore = Math.min(...plotted.map(({ model }) => scoreForRow(model, scoreMode)));
  const maxScore = Math.max(...plotted.map(({ model }) => scoreForRow(model, scoreMode)));
  const yMin = Math.max(0, Math.floor((minScore - 8) / 10) * 10);
  const yMax = Math.min(100, Math.max(yMin + 10, Math.ceil((maxScore + 5) / 10) * 10));
  const x = (value) => margin.left + (value / maxX) * plotWidth;
  const y = (value) => margin.top + (1 - (value - yMin) / (yMax - yMin)) * plotHeight;

  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": translate("chartRelation", {
      metric: axis === "price" ? translate("priceAxis") : translate("timeAxis"),
    }),
  });
  svg.classList.add("score-chart");

  for (let index = 0; index <= 5; index += 1) {
    const yValue = yMin + ((yMax - yMin) * index) / 5;
    const yPosition = y(yValue);
    svg.append(svgElement("line", { x1: margin.left, y1: yPosition, x2: width - margin.right, y2: yPosition, class: "grid-line" }));
    const label = svgElement("text", { x: margin.left - 14, y: yPosition + 4, class: "axis-tick", "text-anchor": "end" });
    label.textContent = yValue.toFixed(0);
    svg.append(label);
  }
  for (let index = 0; index <= 4; index += 1) {
    const value = (maxX * index) / 4;
    const xPosition = x(value);
    svg.append(svgElement("line", { x1: xPosition, y1: margin.top, x2: xPosition, y2: height - margin.bottom, class: "grid-line vertical" }));
    const label = svgElement("text", { x: xPosition, y: height - margin.bottom + 30, class: "axis-tick", "text-anchor": "middle" });
    label.textContent = chartLabel(value, axis);
    svg.append(label);
  }

  const yTitle = svgElement("text", { x: margin.left, y: 22, class: "axis-title" });
  yTitle.textContent = scoreLabel(scoreMode);
  svg.append(yTitle);
  const xTitle = svgElement("text", { x: margin.left + plotWidth / 2, y: height - 16, class: "axis-title", "text-anchor": "middle" });
  xTitle.textContent = axis === "price" ? translate("priceAxis") : translate("timeAxis");
  svg.append(xTitle);

  const colors = colorMap(models);
  const chartFamilies = groupByChartFamily(plotted.map(({ model }) => model));
  chartFamilies.forEach((items) => {
    const family = chartFamilyKey(items[0]);
    for (let index = 0; index < items.length - 1; index += 1) {
      const from = items[index];
      const to = items[index + 1];
      svg.append(svgElement("line", {
        x1: x(chartMetric(from, axis)),
        y1: y(scoreForRow(from, scoreMode)),
        x2: x(chartMetric(to, axis)),
        y2: y(scoreForRow(to, scoreMode)),
        class: "series-line",
        "data-chart-family": family,
        stroke: colors.get(family),
        "stroke-opacity": reasoningOpacity(items, to),
      }));
    }
  });

  let pinnedModel = null;
  plotted.forEach(({ model, providers }) => {
    const family = chartFamilyKey(model);
    const familyItems = chartFamilies.get(family) || [model];
    const xPosition = x(chartMetric(model, axis));
    const yPosition = y(scoreForRow(model, scoreMode));
    const point = svgElement("circle", {
      cx: xPosition,
      cy: yPosition,
      r: 6.5,
      fill: colors.get(family),
      opacity: reasoningOpacity(familyItems, model),
      class: "chart-point",
      "data-chart-family": family,
      tabindex: 0,
      role: "button",
      "aria-label": `${formatChartName(model)} · ${translate("providers", { count: providers.length })}`,
    });
    point.addEventListener("pointerenter", (event) => renderChartTooltip(host, model, axis, providers, scoreMode, event, point));
    point.addEventListener("pointermove", (event) => renderChartTooltip(host, model, axis, providers, scoreMode, event, point));
    point.addEventListener("focus", () => renderChartTooltip(host, model, axis, providers, scoreMode, null, point));
    point.addEventListener("pointerleave", () => {
      if (pinnedModel !== model) hideChartTooltip(host);
    });
    point.addEventListener("blur", () => {
      if (pinnedModel !== model) hideChartTooltip(host);
    });
    point.addEventListener("click", (event) => {
      pinnedModel = pinnedModel === model ? null : model;
      if (pinnedModel) {
        const clickPosition = event.detail > 0 ? event : null;
        renderChartTooltip(host, model, axis, providers, scoreMode, clickPosition, point);
      } else hideChartTooltip(host);
    });
    point.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        point.dispatchEvent(new MouseEvent("click"));
      }
    });
    svg.append(point);
  });
  const layout = document.createElement("div");
  layout.className = "chart-layout";
  const plot = document.createElement("div");
  plot.className = "chart-plot";
  plot.append(svg);
  const legendHost = document.createElement("aside");
  legendHost.className = "chart-legend";
  legendHost.setAttribute("role", "list");
  legendHost.setAttribute("aria-label", translate("model"));
  renderChartLegend(legendHost, svg, plotted.map(({ model }) => model), colors);
  layout.append(plot, legendHost);
  host.append(layout);
}

const RESOURCE_COLUMNS = [
  ["model", "name", (row) => row.name],
  ["score", "overall_score", (row, scoreMode) => formatScore(scoreForRow(row, scoreMode))],
  ["games", "games", (row) => formatNumber(row.games)],
  ["totalTime", "active_time_s", (row) => formatDuration(row.active_time_s)],
  ["totalTokens", "tokens.total", (row) => formatNumber(row.tokens.total)],
  ["inputTokens", "tokens.input", (row) => formatNumber(row.tokens.input)],
  ["outputTokens", "tokens.output", (row) => formatNumber(row.tokens.output)],
  ["cacheRead", "tokens.cache_read", (row) => formatNumber(row.tokens.cache_read)],
  ["cacheWrite", "tokens.cache_write", (row) => formatNumber(row.tokens.cache_write)],
  ["averagePriceColumn", "price_usd.total_per_game", (row) => formatMoney(averagePricePerGame(row))],
];

const BEHAVIOR_COLUMNS = [
  ["model", "name", (row) => formatBehaviorName(row)],
  ["score", "overall_score", (row, scoreMode) => formatScore(scoreForRow(row, scoreMode))],
  ["solveRate", "behavior.solve_rate", (row) => formatPercent(row.behavior.solve_rate)],
  ["roundsMedian", "behavior.rounds_median", (row) => formatNumber(row.behavior.rounds_median)],
  ["hintsMedian", "behavior.hints_median", (row) => formatNumber(row.behavior.hints_median)],
  ["samples", "behavior.samples", (row) => formatNumber(row.behavior.samples)],
];

function renderTable(table, rows, columns, state, scoreMode = "subjective") {
  const headRow = table.querySelector("thead tr");
  const body = table.querySelector("tbody");
  headRow.replaceChildren();
  body.replaceChildren();

  columns.forEach(([labelKey, key]) => {
    const th = document.createElement("th");
    th.scope = "col";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sort-button";
    button.dataset.sortKey = key;
    button.textContent = labelKey === "score" ? scoreLabel(scoreMode) : translate(labelKey);
    if (state.key === key) {
      th.setAttribute("aria-sort", state.direction === "asc" ? "ascending" : "descending");
      const mark = document.createElement("span");
      mark.className = "sort-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = state.direction === "asc" ? "↑" : "↓";
      button.append(mark);
    } else {
      th.setAttribute("aria-sort", "none");
      const mark = document.createElement("span");
      mark.className = "sort-mark inactive";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "↕";
      button.append(mark);
    }
    button.addEventListener("click", () => {
      state.direction = state.key === key && state.direction === "desc" ? "asc" : "desc";
      state.key = key;
      renderTable(table, sortRows(rows, state.key, state.direction, scoreMode), columns, state, scoreMode);
    });
    th.append(button);
    headRow.append(th);
  });

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach(([, key, formatter], columnIndex) => {
      const td = document.createElement("td");
      if (columnIndex === 0) td.className = "sticky-cell model-cell";
      if (key === "name") {
        const parts = splitDisplayName(row.name);
        const primary = document.createElement("span");
        primary.className = "model-primary";
        primary.textContent = formatTableModelName(row, columns === BEHAVIOR_COLUMNS, scoreMode);
        td.append(primary);
        const providerName = formatTableProviderName(row) || parts.provider;
        if (providerName) {
          const provider = document.createElement("small");
          provider.className = "provider-subtitle";
          provider.textContent = columns === BEHAVIOR_COLUMNS
            ? providerName
            : providerName;
          td.append(provider);
        }
      } else {
        if (key === "reasoning_effort") td.classList.add("effort-cell");
        td.textContent = formatter(row, scoreMode);
      }
      if (key === "price_usd.total_per_game" && row.price_usd) {
        const detail = document.createElement("small");
        detail.className = "price-detail";
        detail.textContent = [
          `入 ${formatMoney(row.price_usd.input)}`,
          `出 ${formatMoney(row.price_usd.output)}`,
          `读 ${formatMoney(row.price_usd.cache_read)}`,
          `写 ${formatMoney(row.price_usd.cache_write)}`,
        ].join(" · ");
        td.append(detail);
      }
      tr.append(td);
    });
    body.append(tr);
  });
}

function bindSegmentedControl(selector, onChange) {
  document.querySelectorAll(selector).forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(selector).forEach((item) => {
        const selected = item === button;
        item.classList.toggle("selected", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
      onChange(button.dataset.value);
    });
  });
}

async function loadRun(file) {
  const separator = file.includes("?") ? "&" : "?";
  const response = await fetch(`${file}${separator}v=${DATA_CACHE_BUSTER}`, { cache: "no-store" });
  if (!response.ok) throw new Error(translate("httpReadError", { status: response.status }));
  return response.json();
}

async function startDashboard() {
  const status = document.querySelector("#status");
  const languageSelect = document.querySelector("#language-select");
  const scoreSelect = document.querySelector("#score-select");
  const languagePreference = readLanguagePreference();
  languageSelect.value = languagePreference;
  scoreSelect.value = "subjective";
  applyLanguage(detectLanguage(languagePreference));
  try {
    const index = await loadRun("data/index.json");
    const runSelect = document.querySelector("#run-select");
    index.runs.forEach((run) => {
      const option = document.createElement("option");
      option.value = run.file;
      option.textContent = run.title || run.id;
      option.selected = run.id === index.default_run;
      runSelect.append(option);
    });
    if (index.runs.length > 1) document.querySelector("#run-picker").hidden = false;

    let data = await loadRun(runSelect.value || index.runs[0].file);
    let axis = "price";
    let scoreMode = scoreSelect.value || "subjective";
    const resourceSort = { key: "overall_score", direction: "desc" };
    const behaviorSort = { key: "overall_score", direction: "desc" };

    const render = () => {
      const tableModels = data.models;
      const chartModels = data.models.filter((model) => isDisplayableModel(model, scoreMode));
      document.querySelector("#suite-meta").textContent = [
        data.suite_version,
        translate("puzzles", { count: data.puzzle_count }),
        translate("repeats", { count: data.repeats }),
      ].filter(Boolean).join(" · ");
      renderChart(chartModels, axis, scoreMode);
      renderTable(
        document.querySelector("#resource-table"),
        sortRows(tableModels, resourceSort.key, resourceSort.direction, scoreMode),
        RESOURCE_COLUMNS,
        resourceSort,
        scoreMode,
      );
      renderTable(
        document.querySelector("#behavior-table"),
        sortRows(tableModels, behaviorSort.key, behaviorSort.direction, scoreMode),
        BEHAVIOR_COLUMNS,
        behaviorSort,
        scoreMode,
      );
      status.hidden = true;
    };

    bindSegmentedControl("[data-view]", (value) => {
      const chartView = value === "chart";
      document.querySelector("#chart-view").hidden = !chartView;
      document.querySelector("#table-view").hidden = chartView;
      document.querySelector("#axis-control").hidden = !chartView;
    });
    bindSegmentedControl("[data-axis]", (value) => {
      axis = value;
      renderChart(data.models, axis, scoreMode);
    });
    scoreSelect.addEventListener("change", () => {
      scoreMode = scoreSelect.value === "subjective" ? "subjective" : "formula";
      render();
    });
    languageSelect.addEventListener("change", () => {
      saveLanguagePreference(languageSelect.value);
      applyLanguage(detectLanguage(languageSelect.value));
      render();
    });
    runSelect.addEventListener("change", async () => {
      status.hidden = false;
      status.textContent = translate("loading");
      data = await loadRun(runSelect.value);
      render();
    });
    render();
  } catch (error) {
    status.hidden = false;
    status.classList.add("error");
    status.textContent = error instanceof Error ? error.message : translate("readError");
  }
}

if (typeof document !== "undefined") {
  startDashboard();
}
