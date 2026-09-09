const LANGUAGE_STORAGE_KEY = "turtlebench-language";

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
    behavior: "模型行为",
    puzzles: "{count} 道题",
    repeats: "每题 {count} 局",
    unknown: "未知",
    priceSource: "价格来源：models.dev",
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
    pendingJudge: "待评分",
    inputShort: "入",
    outputShort: "出",
    cacheReadShort: "读",
    cacheWriteShort: "写",
    providers: "{count} 个运营商，点击查看详情",
    tooltipLine: "{provider} · 综合分 {score} · {metricLabel} {metric} · {games} 局",
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
    behavior: "Model behavior",
    puzzles: "{count} puzzles",
    repeats: "{count} games per puzzle",
    unknown: "Unknown",
    priceSource: "Price source: models.dev",
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
    pendingJudge: "Pending judge",
    inputShort: "in",
    outputShort: "out",
    cacheReadShort: "read",
    cacheWriteShort: "write",
    providers: "{count} provider(s), click for details",
    tooltipLine: "{provider} · score {score} · {metricLabel} {metric} · {games} games",
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

const FAMILY_COLORS = [
  "#173b63",
  "#0f766e",
  "#c2553d",
  "#6d4ca1",
  "#a06b13",
  "#2774a8",
  "#9c3f69",
  "#4f6b3d",
  "#80553f",
  "#50657a",
];

const FIXED_FAMILY_COLORS = new Map([
  ["gpt-5.6-luna", "#173b63"],
  ["minimax-m3", "#0f766e"],
  ["deepseek-v4-flash", "#c2553d"],
  ["claude-sonnet-5", "#6d4ca1"],
  ["gpt-5.6-sol", "#a06b13"],
  ["gpt-6-astra", "#2774a8"],
  ["grok-4.6", "#9c3f69"],
]);

export function colorForFamily(family) {
  if (FIXED_FAMILY_COLORS.has(family)) return FIXED_FAMILY_COLORS.get(family);
  let hash = 0;
  for (const character of family) hash = (hash * 31 + character.codePointAt(0)) >>> 0;
  return FAMILY_COLORS[hash % FAMILY_COLORS.length];
}

function nestedValue(row, path) {
  return path.split(".").reduce((value, key) => value?.[key], row);
}

function sortableValue(row, key) {
  if (key === "price_usd.total_per_game") return averagePricePerGame(row);
  return nestedValue(row, key);
}

export function sortRows(rows, key, direction = "asc") {
  const sign = direction === "desc" ? -1 : 1;
  return [...rows].sort((left, right) => {
    const a = sortableValue(left, key);
    const b = sortableValue(right, key);
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
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

export function groupByVariant(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const family = row.family || row.model;
    const key = `${family}|${row.reasoning_effort || ""}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  return groups;
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

export function formatBehaviorName(row) {
  const status = row.score_status === "pending_judge" ? ` · ${translate("pendingJudge")}` : "";
  return `${row.name} · ${formatEffort(row.reasoning_effort)}${status}`;
}

export function formatChartName(row) {
  const status = row.score_status === "pending_judge" ? ` · ${translate("pendingJudge")}` : "";
  return `${splitDisplayName(row.name).model} · ${formatEffort(row.reasoning_effort)}${status}`;
}

export function formatTableModelName(row, behavior = false) {
  const status = behavior && row.score_status === "pending_judge"
    ? ` · ${translate("pendingJudge")}`
    : "";
  return `${splitDisplayName(row.name).model}${status}`;
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
  return value == null ? "—" : Number(value).toFixed(1);
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
  const families = [...new Set(models.map((model) => model.family || model.model))];
  return new Map(families.map((family) => [family, colorForFamily(family)]));
}

function chartMetric(model, axis) {
  return axis === "price" ? averagePricePerGame(model) : averageTimePerGame(model);
}

export function isPlottable(model, axis) {
  return Number.isFinite(model.overall_score) && Number.isFinite(chartMetric(model, axis));
}

function chartLabel(value, axis) {
  return axis === "price" ? formatMoney(value) : formatDuration(value);
}

export function formatChartDetails(row, axis, providers = [row]) {
  const parts = splitDisplayName(row.name);
  return {
    model: parts.model,
    reasoning_effort: row.reasoning_effort,
    providers: providers.map((providerRow) => {
      const providerParts = splitDisplayName(providerRow.name);
      return {
        provider: providerRow.provider || providerParts.provider,
        score: formatScore(providerRow.overall_score),
        metric: chartLabel(chartMetric(providerRow, axis), axis),
        games: formatNumber(providerRow.games),
      };
    }),
  };
}

function renderChartTooltip(host, row, axis, providers = [row]) {
  let tooltip = host.querySelector(".chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    tooltip.setAttribute("role", "status");
    host.append(tooltip);
  }
  const details = formatChartDetails(row, axis, providers);
  tooltip.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = `${details.model} · ${details.reasoning_effort}`;
  tooltip.append(title);
  details.providers.forEach((provider) => {
    const line = document.createElement("span");
    line.className = "chart-tooltip-provider";
    line.textContent = translate("tooltipLine", {
      provider: provider.provider || translate("unknown"),
      score: provider.score,
      metricLabel: axis === "price" ? translate("priceTooltip") : translate("timeTooltip"),
      metric: provider.metric,
      games: provider.games,
    });
    tooltip.append(line);
  });
  tooltip.hidden = false;
}

function hideChartTooltip(host) {
  const tooltip = host.querySelector(".chart-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function renderChart(models, axis) {
  const host = document.querySelector("#chart");
  host.replaceChildren();
  const candidates = models.filter((model) => isPlottable(model, axis));
  const plotted = [...groupByVariant(candidates).values()].map((providers) => ({
    model: providers.reduce((highest, row) => (
      row.overall_score > highest.overall_score ? row : highest
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

  const width = 1000;
  const height = 500;
  const margin = { top: 42, right: 170, bottom: 72, left: 72 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xValues = plotted.map(({ model }) => chartMetric(model, axis));
  const maxX = Math.max(...xValues, 1) * 1.12;
  const minScore = Math.min(...plotted.map(({ model }) => model.overall_score));
  const maxScore = Math.max(...plotted.map(({ model }) => model.overall_score));
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
  yTitle.textContent = translate("score");
  svg.append(yTitle);
  const xTitle = svgElement("text", { x: margin.left + plotWidth / 2, y: height - 16, class: "axis-title", "text-anchor": "middle" });
  xTitle.textContent = axis === "price" ? translate("priceAxis") : translate("timeAxis");
  svg.append(xTitle);

  const colors = colorMap(models);
  groupByFamily(plotted.map(({ model }) => model)).forEach((items) => {
    const family = items[0].family || items[0].model;
    const points = items.map((model) => `${x(chartMetric(model, axis))},${y(model.overall_score)}`).join(" ");
    if (items.length > 1) {
      svg.append(svgElement("polyline", { points, class: "series-line", stroke: colors.get(family) }));
    }
  });

  let pinnedModel = null;
  plotted.forEach(({ model, providers }, index) => {
    const family = model.family || model.model;
    const xPosition = x(chartMetric(model, axis));
    const yPosition = y(model.overall_score);
    const point = svgElement("circle", {
      cx: xPosition,
      cy: yPosition,
      r: 6.5,
      fill: colors.get(family),
      class: "chart-point",
      tabindex: 0,
      role: "button",
      "aria-label": `${formatChartName(model)} · ${translate("providers", { count: providers.length })}`,
    });
    point.addEventListener("pointerenter", () => renderChartTooltip(host, model, axis, providers));
    point.addEventListener("focus", () => renderChartTooltip(host, model, axis, providers));
    point.addEventListener("pointerleave", () => {
      if (pinnedModel !== model) hideChartTooltip(host);
    });
    point.addEventListener("blur", () => {
      if (pinnedModel !== model) hideChartTooltip(host);
    });
    point.addEventListener("click", () => {
      pinnedModel = pinnedModel === model ? null : model;
      if (pinnedModel) renderChartTooltip(host, model, axis, providers);
      else hideChartTooltip(host);
    });
    point.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        point.dispatchEvent(new MouseEvent("click"));
      }
    });
    svg.append(point);
    const nearRight = xPosition > margin.left + plotWidth * 0.76;
    const label = svgElement("text", {
      x: xPosition + (nearRight ? -11 : 11),
      y: yPosition + (index % 2 ? 18 : -11),
      class: "point-label",
      fill: colors.get(family),
      "text-anchor": nearRight ? "end" : "start",
    });
    label.textContent = formatChartName(model);
    svg.append(label);
  });
  host.append(svg);
}

const RESOURCE_COLUMNS = [
  ["model", "name", (row) => row.name],
  ["effort", "reasoning_effort", (row) => row.reasoning_effort],
  ["score", "overall_score", (row) => formatScore(row.overall_score)],
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
  ["score", "overall_score", (row) => formatScore(row.overall_score)],
  ["solveRate", "behavior.solve_rate", (row) => formatPercent(row.behavior.solve_rate)],
  ["roundsMedian", "behavior.rounds_median", (row) => formatNumber(row.behavior.rounds_median)],
  ["hintsMedian", "behavior.hints_median", (row) => formatNumber(row.behavior.hints_median)],
  ["samples", "behavior.samples", (row) => formatNumber(row.behavior.samples)],
];

function renderTable(table, rows, columns, state) {
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
    button.textContent = translate(labelKey);
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
      renderTable(table, sortRows(rows, state.key, state.direction), columns, state);
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
        primary.textContent = formatTableModelName(row, columns === BEHAVIOR_COLUMNS);
        td.append(primary);
        if (parts.provider) {
          const provider = document.createElement("small");
          provider.className = "provider-subtitle";
          provider.textContent = columns === BEHAVIOR_COLUMNS
            ? `${parts.provider} · ${row.reasoning_effort}`
            : parts.provider;
          td.append(provider);
        }
      } else {
        if (key === "reasoning_effort") td.classList.add("effort-cell");
        td.textContent = formatter(row);
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
  const response = await fetch(file, { cache: "no-store" });
  if (!response.ok) throw new Error(translate("httpReadError", { status: response.status }));
  return response.json();
}

async function startDashboard() {
  const status = document.querySelector("#status");
  const languageSelect = document.querySelector("#language-select");
  const languagePreference = readLanguagePreference();
  languageSelect.value = languagePreference;
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
    const resourceSort = { key: "overall_score", direction: "desc" };
    const behaviorSort = { key: "overall_score", direction: "desc" };

    const render = () => {
      document.querySelector("#suite-meta").textContent = [
        data.suite_version,
        translate("puzzles", { count: data.puzzle_count }),
        translate("repeats", { count: data.repeats }),
      ].filter(Boolean).join(" · ");
      renderChart(data.models, axis);
      renderTable(
        document.querySelector("#resource-table"),
        sortRows(data.models, resourceSort.key, resourceSort.direction),
        RESOURCE_COLUMNS,
        resourceSort,
      );
      renderTable(
        document.querySelector("#behavior-table"),
        sortRows(data.models, behaviorSort.key, behaviorSort.direction),
        BEHAVIOR_COLUMNS,
        behaviorSort,
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
      renderChart(data.models, axis);
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
