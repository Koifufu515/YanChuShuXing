(function (global) {
  "use strict";

  const REQUIRED_FIELDS = Object.freeze({
    value: ["metric_value", "value"],
    unit: ["metric_unit", "unit"],
    metric: ["metric_name"],
    institution: ["institution_name"],
    date: ["data_date"],
  });

  function fieldIndexes(columns) {
    const names = Array.isArray(columns) ? columns.map(String) : [];
    return Object.fromEntries(
      Object.entries(REQUIRED_FIELDS).map(([role, aliases]) => [role, aliases.map(name => names.indexOf(name)).find(index => index >= 0) ?? -1])
    );
  }

  function numberValue(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
    return null;
  }

  function formatNumber(value, minimumFractionDigits = 2, maximumFractionDigits = 2) {
    const numeric = numberValue(value);
    if (numeric === null) return "暂未提供";
    return numeric.toLocaleString("zh-CN", { minimumFractionDigits, maximumFractionDigits });
  }

  function compactNumber(value) {
    const numeric = numberValue(value);
    if (numeric === null) return "—";
    const absolute = Math.abs(numeric);
    if (absolute >= 100000000) return `${formatNumber(numeric / 100000000, 0, 2)}亿`;
    if (absolute >= 10000) return `${formatNumber(numeric / 10000, 0, 2)}万`;
    return formatNumber(numeric, 0, 2);
  }

  function cell(row, index) {
    return index >= 0 && Array.isArray(row) ? row[index] : null;
  }

  function adapt(payload) {
    const columns = Array.isArray(payload?.columns) ? payload.columns.map(String) : [];
    const rows = Array.isArray(payload?.rows) ? payload.rows.filter(Array.isArray) : [];
    const indexes = fieldIndexes(columns);
    const missing = Object.entries(indexes).filter(([, index]) => index < 0).map(([role]) => REQUIRED_FIELDS[role].join("/"));
    return { columns, rows, indexes, missing };
  }

  function singleValue(model) {
    const row = model.rows[0];
    if (!row || model.indexes.value < 0) return null;
    const value = numberValue(cell(row, model.indexes.value));
    if (value === null) return null;
    const unit = cell(row, model.indexes.unit);
    return {
      metricName: cell(row, model.indexes.metric) || "指标值",
      value,
      unit: unit == null || unit === "" ? "暂未提供" : String(unit),
      valueText: `${formatNumber(value)}${unit ? ` ${unit}` : ""}`,
    };
  }

  function ranking(model) {
    if (model.indexes.institution < 0 || model.indexes.value < 0) return [];
    return model.rows.map(row => ({
      institution: String(cell(row, model.indexes.institution) ?? "暂未提供"),
      value: numberValue(cell(row, model.indexes.value)),
      unit: String(cell(row, model.indexes.unit) ?? ""),
    })).filter(item => item.value !== null).sort((left, right) => right.value - left.value);
  }

  function trend(model) {
    if (model.indexes.date < 0 || model.indexes.value < 0) return [];
    return model.rows.map(row => ({
      date: String(cell(row, model.indexes.date) ?? ""),
      value: numberValue(cell(row, model.indexes.value)),
      unit: String(cell(row, model.indexes.unit) ?? ""),
    })).filter(item => item.date && item.value !== null).sort((left, right) => left.date.localeCompare(right.date));
  }

  function evenlySpacedLabels(values, maximum = 8) {
    const unique = [...new Set((values || []).map(String))];
    if (unique.length <= maximum) return unique;
    const indexes = new Set([0, unique.length - 1]);
    for (let step = 1; step < maximum - 1; step += 1) {
      indexes.add(Math.round(step * (unique.length - 1) / (maximum - 1)));
    }
    return [...indexes].sort((a, b) => a - b).map(index => unique[index]);
  }

  const axisLine = { lineStyle: { color: "#D2D7E0" } };
  const splitLine = { show: true, lineStyle: { color: "#E5E8EE", type: "dashed" } };
  const tooltip = { backgroundColor: "#fff", borderColor: "#E5E8EE", textStyle: { color: "#172033", fontSize: 12 }, extraCssText: "box-shadow:0 4px 16px rgba(16,24,40,.1);border-radius:8px;" };

  function paddedAxisMin(value) {
    if (value.min === 0) return 0;
    const span = value.max - value.min || Math.abs(value.max) * 0.1 || 1;
    return value.min - span * 0.08;
  }

  function paddedAxisMax(value) {
    if (value.max === 0) return 0;
    const span = value.max - value.min || Math.abs(value.max) * 0.1 || 1;
    return value.max + span * 0.08;
  }

  function rankingOption(model) {
    const items = ranking(model);
    const unit = items[0]?.unit || "";
    const displayed = items.slice().reverse();
    const minimum = items.length ? Math.min(0, ...items.map(item => item.value)) : 0;
    return {
      animation: false,
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltip, valueFormatter: value => `${formatNumber(value)}${unit ? ` ${unit}` : ""}` },
      grid: { left: 142, right: 36, top: 18, bottom: 42, containLabel: false },
      xAxis: { type: "value", min: minimum, splitNumber: 5, name: unit ? `单位：${unit}` : "", nameLocation: "middle", nameGap: 28, axisLine, axisLabel: { color: "#667085", fontSize: 10, formatter: compactNumber }, splitLine },
      yAxis: { type: "category", data: displayed.map(item => item.institution), axisLine, axisTick: { show: false }, axisLabel: { color: "#475467", fontSize: 10 } },
      series: [{ type: "bar", barMaxWidth: 18, data: displayed.map((item, index) => ({ value: item.value, itemStyle: { color: index === displayed.length - 1 ? "#1577E0" : "#77AFE9", borderRadius: [0, 4, 4, 0] } })) }],
    };
  }

  function trendOption(model) {
    const items = trend(model);
    const dates = items.map(item => item.date);
    const labels = evenlySpacedLabels(dates, 8);
    const labelSet = new Set(labels);
    const unit = items[0]?.unit || "";
    return {
      animation: false,
      tooltip: { trigger: "axis", ...tooltip, valueFormatter: value => `${formatNumber(value)}${unit ? ` ${unit}` : ""}` },
      grid: { left: 62, right: 62, top: 24, bottom: 48, containLabel: false },
      xAxis: { type: "category", boundaryGap: false, data: dates, axisLine, axisTick: { show: false }, axisLabel: { color: "#667085", fontSize: 10, interval: 0, formatter: value => labelSet.has(value) ? value : "", hideOverlap: true } },
      yAxis: { type: "value", splitNumber: 5, scale: true, name: unit ? `单位：${unit}` : "", nameTextStyle: { color: "#667085", fontSize: 10, align: "left" }, min: paddedAxisMin, max: paddedAxisMax, axisLine, axisLabel: { color: "#667085", fontSize: 10, formatter: compactNumber }, splitLine },
      series: [{ type: "line", showSymbol: false, smooth: false, connectNulls: false, data: items.map(item => item.value), lineStyle: { color: "#1577E0", width: 2 }, itemStyle: { color: "#1577E0" }, areaStyle: { color: "rgba(21,119,224,.08)" } }],
      __audit: { pointCount: items.length, axisLabels: labels, firstDate: dates[0] || null, lastDate: dates.at(-1) || null },
    };
  }

  function chartOption(view, model) {
    if (view.chart === "bar" && view.resultType === "排名") return rankingOption(model);
    if (view.chart === "line" && view.resultType === "趋势") return trendOption(model);
    return null;
  }

  global.YCSXResultAdapter = Object.freeze({
    REQUIRED_FIELDS,
    adapt,
    singleValue,
    ranking,
    trend,
    evenlySpacedLabels,
    rankingOption,
    trendOption,
    chartOption,
    paddedAxisMin,
    paddedAxisMax,
    formatNumber,
  });
})(window);
