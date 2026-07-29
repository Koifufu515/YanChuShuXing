(function (global) {
  "use strict";

  const REQUIRED_FIELDS = Object.freeze({
    value: "metric_value",
    unit: "metric_unit",
    metric: "metric_name",
    institution: "institution_name",
    date: "data_date",
  });

  const ANSWER_TYPE_LABELS = Object.freeze({
    direct_metric_values: "指标值",
    calculated_metric: "计算结果",
    trend: "趋势",
    ranking: "排名",
    benchmark_comparison: "跨期比较",
    main_metrics_overview: "综合分析",
    single_value: "单值",
  });

  const COLUMN_LABELS = Object.freeze({
    result: "结果",
    metric_id: "指标编号",
    metric_name: "指标",
    metric_value: "指标值",
    metric_unit: "单位",
    institution_id: "机构编号",
    institution_name: "机构",
    data_date: "数据日期",
    date: "日期",
    base_date: "基期",
    base_value: "基期值",
    current_date: "本期",
    current_value: "本期值",
    start_date: "开始日期",
    end_date: "结束日期",
    change: "变动值",
    difference: "差值",
    difference_unit: "差值单位",
    direction: "变动方向",
    relative_position: "相对位置",
    rank: "排名",
    value: "数值",
    count: "数量",
    record_count: "记录数",
    institution_count: "机构数",
    benchmark_name: "比较基准",
    benchmark_value: "基准值",
    target_value: "目标值",
    unit: "单位",
  });

  const HIDDEN_DISPLAY_FIELDS = new Set([
    "result",
    "operation",
    "institution_id",
    "metric_id",
  ]);

  function displayColumnName(value) {
    const name = String(value || "");
    return COLUMN_LABELS[name] || name.replaceAll("_", " ");
  }

  function displayTable(payload) {
    const rawColumns = Array.isArray(payload?.columns)
      ? payload.columns.map(String)
      : [];
    const rawRows = Array.isArray(payload?.rows)
      ? payload.rows.filter(Array.isArray)
      : [];

    const visibleIndexes = rawColumns
      .map((name, index) => ({ name, index }))
      .filter(item => !HIDDEN_DISPLAY_FIELDS.has(item.name));

    return {
      columns: visibleIndexes.map(
        item => displayColumnName(item.name)
      ),
      rows: rawRows.map(
        row => visibleIndexes.map(
          item => row[item.index]
        )
      ),
    };
  }

  function fieldIndexes(columns) {
    const names = Array.isArray(columns) ? columns.map(String) : [];
    return Object.fromEntries(
      Object.entries(REQUIRED_FIELDS).map(([role, name]) => [role, names.indexOf(name)])
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
    const missing = Object.entries(indexes).filter(([, index]) => index < 0).map(([role]) => REQUIRED_FIELDS[role]);
    return { columns, rows, indexes, missing };
  }

  function structuredAnswer(payload) {
    const answer = payload?.answer;
    if (!answer || typeof answer !== "object") return null;
    const keyMetrics = Array.isArray(answer.key_metrics)
      ? answer.key_metrics.filter(item => item && typeof item === "object")
      : [];
    const table = answer.table && Array.isArray(answer.table.columns) && Array.isArray(answer.table.rows)
      ? {
          columns: answer.table.columns.map(String),
          rows: answer.table.rows.filter(Array.isArray),
        }
      : null;
    const chartSpec = answer.chart_spec && ["bar", "line"].includes(answer.chart_spec.chart_type)
      ? answer.chart_spec
      : null;
    return {
      answerType: String(answer.answer_type || ""),
      resultType: ANSWER_TYPE_LABELS[answer.answer_type] || "综合分析",
      headline: answer.headline || "",
      summary: answer.summary || payload.summary || "当前结果暂无可用结论。",
      keyMetrics,
      table,
      chartSpec,
    };
  }

  function answerMetricText(metric) {
    const value = metric?.value;
    const unit = metric?.unit || "";
    if (typeof value === "number" && Number.isFinite(value)) {
      return `${formatNumber(value)}${unit}`;
    }
    return `${valueOrMissing(value)}${unit}`;
  }

  function valueOrMissing(value) {
    if (value === null || value === undefined || value === "") return "暂未提供";
    return String(value);
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

  function chartSpecOption(spec) {
    if (!spec || !["bar", "line"].includes(spec.chart_type)) return null;
    const categories = Array.isArray(spec.categories) ? spec.categories.map(String) : [];
    const series = Array.isArray(spec.series)
      ? spec.series.filter(item => item && Array.isArray(item.values))
      : [];
    if (!categories.length || !series.length) return null;
    const unit = spec.unit || "";
    const isLine = spec.chart_type === "line";
    return {
      animation: false,
      title: { text: spec.title || "", left: "center", textStyle: { color: "#172033", fontSize: 14 } },
      tooltip: { trigger: "axis", axisPointer: { type: isLine ? "line" : "shadow" }, ...tooltip, valueFormatter: value => `${formatNumber(value)}${unit}` },
      legend: { top: 28, textStyle: { color: "#667085", fontSize: 11 } },
      grid: { left: 62, right: 36, top: 68, bottom: 48, containLabel: false },
      xAxis: { type: "category", data: categories, axisLine, axisTick: { show: false }, axisLabel: { color: "#667085", fontSize: 10 } },
      yAxis: { type: "value", scale: isLine, name: unit ? `单位：${unit}` : "", nameTextStyle: { color: "#667085", fontSize: 10 }, axisLine, axisLabel: { color: "#667085", fontSize: 10, formatter: compactNumber }, splitLine },
      series: series.map(item => ({
        name: String(item.name || "指标值"),
        type: spec.chart_type,
        data: item.values,
        showSymbol: isLine,
        smooth: false,
        barMaxWidth: 32,
        itemStyle: { color: "#1577E0", borderRadius: isLine ? 0 : [4, 4, 0, 0] },
        lineStyle: { color: "#1577E0", width: 2 },
      })),
    };
  }

  function chartOption(view, model) {
    if (view.structured?.chartSpec) return chartSpecOption(view.structured.chartSpec);
    if (view.chart === "bar" && view.resultType === "排名") return rankingOption(model);
    if (view.chart === "line" && view.resultType === "趋势") return trendOption(model);
    return null;
  }

  global.YCSXResultAdapter = Object.freeze({
    REQUIRED_FIELDS,
    ANSWER_TYPE_LABELS,
    COLUMN_LABELS,
    displayColumnName,
    displayTable,
    adapt,
    structuredAnswer,
    answerMetricText,
    singleValue,
    ranking,
    trend,
    evenlySpacedLabels,
    rankingOption,
    trendOption,
    chartSpecOption,
    chartOption,
    paddedAxisMin,
    paddedAxisMax,
    formatNumber,
  });
})(window);
