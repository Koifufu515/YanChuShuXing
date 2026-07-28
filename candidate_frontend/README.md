# 言出数行候选独立前端

本目录是“受控分阶段迁移”中的候选版本。它已接入真实 `POST /api/v1/query`，但在团队完成验收前，不替代 `frontend/app.py`；原 Streamlit 页面仍是回退入口。

## 启动

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_candidate_frontend.ps1
```

然后打开 `http://127.0.0.1:8512/candidate`。脚本强制使用正式数据环境，默认采用已审计的 `rule` 查询模式；可通过 `-GeneratorMode hybrid` 切换，但外部大模型不可用时会返回结构化错误。

首次运行前，需要在受控本机安装 `scripts/data/requirements.txt`，并用下面的命令导入官方工作簿：

```powershell
$env:PYTHONPATH = "."
python -m scripts.data.init_real_database --source "<本机受控目录中的官方工作簿.xlsx>"
python -m scripts.data.validate_real_database
```

导入后的业务库位于 Git 忽略的 `data/real/`，评测题目与答案位于 Git 忽略的 `data/private/`。候选前端、规则生成器和业务查询只连接业务库。

候选页和查询接口由同一个本地服务提供，因此浏览器不需要跨域访问，也没有开放任意来源的 CORS。

## 当前边界

- 历史会话保存在浏览器 `localStorage`。刷新和重启服务后仍可恢复，但它只是单机候选过渡存储；清理浏览器数据或更换浏览器后不会保留，也不能多人共享。
- 七类结果名称和默认图表来自 `result_contract.json`；自动测试固定检查七类契约和三类已接通的真实规则。
- 右栏只展示后端实际返回的内容；缺失项显示“暂未提供”，SQL 默认折叠。
- 数据看板只统计当前浏览器真实保存的会话与查询，不展示或虚构银行经营数据。
- `?fixture=...` 只用于截图验收，页面顶部会明确说明数值不是银行真实数据。比赛真实演示不得带该参数。

## 验证

```powershell
$env:PYTHONPATH = "backend;."
$env:TMP = "$PWD\.test_tmp"
$env:TEMP = $env:TMP
.\.venv\Scripts\python.exe -m unittest tests.test_candidate_frontend -v
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## 当前真实查询范围

候选版目前只开放三类经过参数化和安全检查的正式规则：单值、机构排名、趋势。机构、指标和日期示例由当前正式业务目录自动生成；不读取评测答案，也不把结果写死在代码里。其他问法会返回“暂不支持”。

## 回退

停止候选服务后，仍可按照仓库原说明启动 `frontend/app.py` 的 Streamlit 页面。候选版通过验收并由负责人确认前，不删除 Streamlit 回退版，也不把两个入口同时称作正式版。
