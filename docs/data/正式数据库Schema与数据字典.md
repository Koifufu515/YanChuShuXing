# 正式数据库 Schema 与数据字典

Real 业务库包含 `institutions`、`metrics`、`metric_facts`、`derived_dimensions` 和 `import_manifest`。

- `institutions`：机构编号主键与机构名称。
- `metrics`：指标编号主键、名称、定义、单位和 `value_scale`。
- `metric_facts`：机构、指标、日期组合主键；指标值保存为 `metric_value_scaled` 整数。
- `derived_dimensions`：官方衍生维度原始描述，不定义业务公式。
- `import_manifest`：run_id、源文件 SHA-256、Schema 版本、导入时间和各表行数。

运行时问数上下文只开放前三张业务表，不开放 `derived_dimensions` 和 `import_manifest`。日期统一为 `YYYY-MM-DD`，业务值统一通过只读连接注册的 `scaled_value(metric_value_scaled, value_scale)` 恢复。中间计算保持原精度，最终展示再按单位保留两位小数。

“较年初”使用查询年份上一年的12月31日作为动态基期。`derived_dimensions` 仅保存官方原始描述，不直接充当可执行计算规则。评测题库位于独立数据库，不属于业务查询 Schema。
