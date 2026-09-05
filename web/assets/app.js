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

function nestedValue(row, path) {
  return path.split(".").reduce((value, key) => value?.[key], row);
}

export function sortRows(rows, key, direction = "asc") {
  const sign = direction === "desc" ? -1 : 1;
  return [...rows].sort((left, right) => {
    const a = nestedValue(left, key);
    const b = nestedValue(right, key);
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

export function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const value = Math.max(0, Math.round(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const remainder = value % 60;
  if (hours) return `${hours}时 ${minutes}分`;
  if (minutes) return `${minutes}分 ${remainder}秒`;
  return `${remainder}秒`;
}

export function formatMoney(value) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `$${value.toFixed(4)}`;
}

function formatNumber(value) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("zh-CN").format(value);
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
  return new Map(families.map((family, index) => [family, FAMILY_COLORS[index % FAMILY_COLORS.length]]));
}

function chartMetric(model, axis) {
  return axis === "price" ? model.price_usd?.total : model.active_time_s;
}

function chartLabel(value, axis) {
  return axis === "price" ? formatMoney(value) : formatDuration(value);
}

function renderChart(models, axis) {
  const host = document.querySelector("#chart");
  host.replaceChildren();
  const plotted = models.filter((model) => Number.isFinite(chartMetric(model, axis)));
  if (!plotted.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = axis === "price" ? "当前结果缺少可计算的价格。" : "当前结果缺少耗时数据。";
    host.append(empty);
    return;
  }

  const width = 1000;
  const height = 500;
  const margin = { top: 42, right: 170, bottom: 72, left: 72 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xValues = plotted.map((model) => chartMetric(model, axis));
  const maxX = Math.max(...xValues, 1);
  const minScore = Math.min(...plotted.map((model) => model.overall_score));
  const maxScore = Math.max(...plotted.map((model) => model.overall_score));
  const yMin = Math.max(0, Math.floor((minScore - 8) / 10) * 10);
  const yMax = Math.min(100, Math.max(yMin + 10, Math.ceil((maxScore + 5) / 10) * 10));
  const x = (value) => margin.left + (value / maxX) * plotWidth;
  const y = (value) => margin.top + (1 - (value - yMin) / (yMax - yMin)) * plotHeight;

  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `综合分与${axis === "price" ? "总价格" : "总耗时"}关系图`,
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
  yTitle.textContent = "综合分";
  svg.append(yTitle);
  const xTitle = svgElement("text", { x: margin.left + plotWidth / 2, y: height - 16, class: "axis-title", "text-anchor": "middle" });
  xTitle.textContent = axis === "price" ? "总价格（USD）" : "总耗时";
  svg.append(xTitle);

  const colors = colorMap(models);
  groupByFamily(plotted).forEach((items, family) => {
    const points = items.map((model) => `${x(chartMetric(model, axis))},${y(model.overall_score)}`).join(" ");
    if (items.length > 1) {
      svg.append(svgElement("polyline", { points, class: "series-line", stroke: colors.get(family) }));
    }
  });

  plotted.forEach((model, index) => {
    const family = model.family || model.model;
    const xPosition = x(chartMetric(model, axis));
    const yPosition = y(model.overall_score);
    svg.append(svgElement("circle", { cx: xPosition, cy: yPosition, r: 6.5, fill: colors.get(family), class: "chart-point" }));
    const label = svgElement("text", {
      x: xPosition + 11,
      y: yPosition + (index % 2 ? 18 : -11),
      class: "point-label",
      fill: colors.get(family),
    });
    label.textContent = `${model.name} ${model.reasoning_effort}`;
    svg.append(label);
  });
  host.append(svg);
}

const RESOURCE_COLUMNS = [
  ["模型", "name", (row) => row.name],
  ["推理等级", "reasoning_effort", (row) => row.reasoning_effort],
  ["综合分", "overall_score", (row) => formatScore(row.overall_score)],
  ["局数", "games", (row) => formatNumber(row.games)],
  ["总耗时", "active_time_s", (row) => formatDuration(row.active_time_s)],
  ["总 Token", "tokens.total", (row) => formatNumber(row.tokens.total)],
  ["输入", "tokens.input", (row) => formatNumber(row.tokens.input)],
  ["输出", "tokens.output", (row) => formatNumber(row.tokens.output)],
  ["Cache 读", "tokens.cache_read", (row) => formatNumber(row.tokens.cache_read)],
  ["Cache 写", "tokens.cache_write", (row) => formatNumber(row.tokens.cache_write)],
  ["总价格", "price_usd.total", (row) => formatMoney(row.price_usd?.total)],
];

const BEHAVIOR_COLUMNS = [
  ["名字", "name", (row) => row.name],
  ["综合分", "overall_score", (row) => formatScore(row.overall_score)],
  ["解出率", "behavior.solve_rate", (row) => formatPercent(row.behavior.solve_rate)],
  ["轮数中位数", "behavior.rounds_median", (row) => formatNumber(row.behavior.rounds_median)],
  ["提示数量中位数", "behavior.hints_median", (row) => formatNumber(row.behavior.hints_median)],
  ["样本数", "behavior.samples", (row) => formatNumber(row.behavior.samples)],
];

function renderTable(table, rows, columns, state) {
  const headRow = table.querySelector("thead tr");
  const body = table.querySelector("tbody");
  headRow.replaceChildren();
  body.replaceChildren();

  columns.forEach(([label, key]) => {
    const th = document.createElement("th");
    th.scope = "col";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sort-button";
    button.dataset.sortKey = key;
    button.textContent = label;
    if (state.key === key) {
      th.setAttribute("aria-sort", state.direction === "asc" ? "ascending" : "descending");
      const mark = document.createElement("span");
      mark.className = "sort-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = state.direction === "asc" ? "↑" : "↓";
      button.append(mark);
    } else {
      th.setAttribute("aria-sort", "none");
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
      if (key === "reasoning_effort") td.classList.add("effort-cell");
      td.textContent = formatter(row);
      if (key === "price_usd.total" && row.price_usd) {
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
  if (!response.ok) throw new Error(`无法读取结果（${response.status}）`);
  return response.json();
}

async function startDashboard() {
  const status = document.querySelector("#status");
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
    let axis = "time";
    const resourceSort = { key: "overall_score", direction: "desc" };
    const behaviorSort = { key: "overall_score", direction: "desc" };

    const render = () => {
      document.querySelector("#suite-meta").textContent = [
        data.suite_version,
        `${data.puzzle_count} 道题`,
        `每题 ${data.repeats} 局`,
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
    });
    bindSegmentedControl("[data-axis]", (value) => {
      axis = value;
      renderChart(data.models, axis);
    });
    runSelect.addEventListener("change", async () => {
      status.hidden = false;
      status.textContent = "正在读取结果…";
      data = await loadRun(runSelect.value);
      render();
    });
    render();
  } catch (error) {
    status.hidden = false;
    status.classList.add("error");
    status.textContent = error instanceof Error ? error.message : "结果读取失败";
  }
}

if (typeof document !== "undefined") {
  startDashboard();
}
