# BankInsight 产品页面

当前前端使用 Streamlit 展示 BankInsight 的 Rule First Hybrid 查询链路。页面不访问 SQLite、不实现 SQL 规则，只通过 `POST /api/v1/query` 调用 FastAPI，因此后端生成器、SQL 安全层和数据库执行器都可以独立替换。

## 页面能力

- 六类银行业务场景在同一页面切换，并动态更新说明、输入提示和推荐问题；
- 经营分析场景提供三个已验证标准问题，未开放场景会显示产品演示提示；
- 展示业务结论、关键指标、结果表格、生成 SQL 和默认折叠的技术详情；
- 技术详情展示运行模式、实际执行器、规则命中、查询路径、模型信息和结构化失败原因；
- 查询期间显示分析状态，失败后可以继续发起查询；
- API 地址可通过 `BANKINSIGHT_API_URL` 环境变量替换。

## 启动

在项目根目录分别打开两个终端：

```bash
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
PYTHONPATH=. .venv/bin/python -X faulthandler -m streamlit run frontend/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false
```

浏览器打开 `http://127.0.0.1:8501`。
