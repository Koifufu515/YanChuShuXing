# 正式数据库 Schema 与数据字典

Real 业务库包含 `institutions`、`metrics`、`metric_facts`、`derived_dimensions` 和 `import_manifest`。

- `institutions`：机构编号主键与机构名称。
- `metrics`：指标编号主键、名称、定义、单位和 `value_scale`。
- `metric_facts`：机构、指标、日期组合主键；指标值保存为 `metric_value_scaled` 整数。
- `derived_dimensions`：官方衍生维度原始描述，不定义业务公式。
- `import_manifest`：run_id、源文件 SHA-256、Schema 版本、导入时间和各表行数。

日期统一为 `YYYY-MM-DD`。展示值为 `metric_value_scaled / 10 ^ value_scale`。评测题库独立存储，不属于业务库。
