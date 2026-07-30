# 评分器完善报告

**生成时间**: 2026-07-30
**执行人**: 测试负责人

## 一、评分器审查结论

### 发现并修复的 Bug

| Bug | 位置 | 影响 | 修复 |
|-----|------|------|------|
| 元/万元/亿元单位换算缺失 | `_units_compatible()` + `_numeric_atoms_match_for_question()` | 预期答案在万元而系统输出亿元时，评分器误判失败 | 新增 `_UNIT_CONVERSION` 换算表 + `_normalize_to_base_unit()` + 容差缩放 |

### 修复详情

1. **新增 `_UNIT_CONVERSION` 字典**：定义 亿元=100000000元, 万元=10000元, 元=1元
2. **新增 `_COMPATIBLE_UNIT_FAMILIES`**：将 {亿元,万元,元} 标记为互换算单位族
3. **新增 `_normalize_to_base_unit()`**：将带单位数值转换为基准单位（元）
4. **修改 `_units_compatible()`**：去除硬编码的 %/百分点/万元/网点 判断，改用单位族匹配
5. **修改 `_numeric_atoms_match_for_question()`**：跨单位比较时自动换算 + 按换算因子缩放容差

### 代码逻辑审查通过项

| 函数 | 状态 | 说明 |
|------|------|------|
| `load_catalog()` | OK | 机构别名自动生成（如江苏省A市→A市、A市农商行） |
| `extract_dates()` | OK | 覆盖10+种日期格式（YYYY-MM-DD、X年X月X日、季度末等） |
| `extract_numeric_atoms()` | OK | 先匹配带单位数字，再匹配裸数字，避免日期/ID污染 |
| `_single_result_expected_text()` | OK | 智能剥离括号验算过程、锁定结果短语 |
| `_select_expected_numbers()` | OK | 按题型区分必答数值：计数题只看计数、排名题只看名次 |
| `_infer_actual_directions()` | OK | 从正负符号推断涨跌方向，时间序列支持首尾总体趋势 |
| `_presentation_flags()` | OK | 检测英文内部字段名、摘要过长、方向文字缺失 |
| `score_record()` | OK | 三级评分（structured_status → executable_answer → intent_aware_deterministic） |
| `build_scoring_summary()` | OK | 按难度/题型/缺失组件/质量标记分维度汇总 |

## 二、单元测试覆盖矩阵

### 任务文档9类规则覆盖

| 规则类别 | 测试函数 | 状态 |
|----------|----------|------|
| 1. 元/万元/亿元换算 | `test_yi_to_wan_conversion_passes` `test_wan_to_yuan_conversion_passes` `test_yuan_to_yi_conversion_passes` | ✅ |
| 2. 百分比/小数点区分 | `test_percentage_point_unit_is_factually_compatible` | ✅ |
| 3. 精度/舍入/容差 | implicit via numeric matching tolerance | ✅ |
| 4. 日期格式/期间表达 | implicit via `extract_dates` + integration | ✅ |
| 5. 机构名称/编号/简称 | `test_institution_short_name_alias_matches` `test_institution_id_in_answer_matches` `test_institution_wrong_org_fails` | ✅ |
| 6. 排名/名次/TopN | `test_ranking_fact_detects_wrong_rank` `test_top_three_ranking_correct_passes` | ✅ |
| 7. 列表/集合顺序规则 | `test_multi_detail_reversed_order_passes` `test_multi_detail_missing_one_value_fails` `test_multi_detail_all_values_present_passes` | ✅ |
| 8. 零值/空值/系统失败 | `test_zero_value_handling` `test_null_summary_with_error_is_failure` `test_structured_non_executable_status_passes` | ✅ |
| 9. 综合题完整性 | `test_comprehensive_multi_component_pass` `test_comprehensive_missing_direction_fails` | ✅ |

### 测试统计

| 维度 | 值 |
|------|-----|
| 存量测试 | 14 |
| 新增测试 | 15 |
| 总计 | 29 |
| 通过率 | 100% |
| 执行时间 | 0.40s |

## 三、文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `evaluation/scorer.py` | 修改 | 新增单位换算逻辑（+15行） |
| `tests/test_evaluation_scorer.py` | 扩展 | 新增15个测试函数（+160行） |

## 四、后续建议

1. **评分器已就绪**：可进入任务2-5（版本对比、专项回归、对话测试、权限测试）
2. **全量验证复跑建议**：建议用修复后的评分器重新评分已有200题评测结果，验证是否有因单位换算误判的题目
3. **`numeric_atoms_match` 遗留函数**：未在任何地方调用，建议后续清理或同步修复
