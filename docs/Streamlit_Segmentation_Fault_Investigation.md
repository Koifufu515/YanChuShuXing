# Streamlit Segmentation Fault 排查记录

## 结论

本次崩溃不是普通 Python 异常，也不是 FastAPI、SQLite、DeepSeek 或业务 Pipeline 抛出的错误。6份 macOS Crash Report 均显示 Python 因 `EXC_BAD_ACCESS / SIGSEGV` 被系统终止，触发线程的共同调用链为：

```text
mi_heap_main
-> mi_thread_init
-> _mi_malloc_generic
-> arrow::MimallocAllocator::AllocateAligned
-> Arrow Buffer Resize / IPC Writer / Python Sequence to Arrow
```

证据将直接故障点定位到 Streamlit 结果表格使用 PyArrow 序列化时触发的 Mimalloc 原生内存分配路径。项目代码与虚拟环境来自不同目录是严重的环境管理风险，但不是6份原生崩溃栈中的直接调用原因。该原生问题具有间歇性，不能仅凭一次未复现判断修复成功。

## 复现现象

原运行方式从桌面项目读取代码，却使用另一工程的 Python：

```text
代码：当前 BankInsight 项目根目录
Python：曾错误引用另一工程的 `.venv/bin/python`
```

连续查询后，浏览器显示 `Streamlit server is not responding`，macOS 提示 Python 意外退出，终端只留下 `zsh: segmentation fault`，没有常规 Traceback。

## 原始环境与新环境

两套环境均为 Python 3.10.11、arm64。旧环境的关键组合为 Streamlit 1.59.1、PyArrow 25.0.0、NumPy 2.2.6、Pandas 2.3.3，并使用 Arrow 默认 Mimalloc 内存池。

新环境建立在桌面项目根目录 `.venv`，通过项目自己的依赖文件安装。最终验证版本如下：

| 组件 | 版本 |
|---|---|
| macOS | 26.5.1 |
| Python | 3.10.11 arm64 |
| Streamlit | 1.59.1 |
| FastAPI | 0.139.0 |
| Uvicorn | 0.51.0 |
| Pandas | 2.3.3 |
| PyArrow | 25.0.0 |
| NumPy | 2.2.6 |
| Certifi | 2026.6.17 |
| Protobuf | 7.35.1 |

`pip check` 返回 `No broken requirements found`。旧、新 PyArrow 扩展和 `libarrow.2500.dylib` 均为 arm64，未发现 x86_64 与 Apple Silicon 二进制混装。

## 排查过程

1. 收集6份崩溃报告，确认每次均进入 PyArrow Mimalloc 分配路径。
2. 在桌面项目建立独立 `.venv`，排除跨工程环境继续污染运行结果。
3. 静态页面与普通 API 请求未触发进程级错误；HTTP 客户端没有保存全局连接或未关闭 Response。
4. 检查 Session State，原结果对象可能跨 Streamlit rerun 保留；现已转换为普通字典、列表和标量。
5. 直接 PyArrow 多线程压力测试未稳定复现，说明故障依赖 Streamlit 表格序列化上下文，且具有间歇性。
6. 移除 `st.dataframe` 后，页面结果不再进入 Arrow 表格转换与 IPC Writer 路径。
7. 将 Arrow 默认内存池切换为 `system`，实测 `pyarrow.default_memory_pool().backend_name == "system"`。

## 实施修复

- `frontend/app.py`
  - 在导入 Streamlit 前设置 `ARROW_DEFAULT_MEMORY_POOL=system`。
  - 结果表格使用 HTML 转义和稳定 CSS 尺寸渲染，不再调用 `st.dataframe`。
  - Session State 只保存可序列化的 `payload` 字典与整数耗时。
  - 连接失败时清除旧结果，Loading 正常结束，页面可继续使用。
- `frontend/requirements.txt`
  - 固定 Streamlit、NumPy、Pandas、PyArrow 的已验证版本。
- `tests/test_streamlit_stability.py`
  - 验证没有 `st.dataframe`、HTML 会转义、状态为普通字典、失败后可被成功结果替换。
- `tests/test_query_stability.py`
  - 覆盖20次交替查询、三问题重复查询和失败后恢复。
- `tests/test_frontend_api_client.py`
  - 覆盖同一客户端在连接失败后的恢复。
- `tests/test_hybrid_generator.py`
  - 覆盖 DeepSeek 超时回退后下一次查询仍可成功。
- `scripts/stability_check.py`
  - 对真实 `/api/v1/query` 循环执行三个固定问题。

## 回归测试

| 检查 | 结果 |
|---|---|
| `pip check` | 通过 |
| Python `compileall` | 通过 |
| 全量自动化测试 | 69项通过 |
| Arrow 内存池 | `system` |
| API 三问题循环 | 60/60通过 |
| 浏览器双问题交替 | 20/20通过 |
| 浏览器三问题循环 | 30/30通过，逐次核对业务结果 |
| 不支持问题后正常查询 | 通过 |
| 后端断开时页面存活 | 通过 |
| Hybrid 超时后恢复 | 自动化测试通过 |
| 新增 macOS Crash Report | 0 |

## 连续查询结果

稳定性脚本按以下顺序循环60次：有效客户数量、C001账户余额、C001在2026年6月交易汇总。每次均通过真实后端、Pipeline、安全层和SQLite返回结果，未出现结构漂移、连接残留或进程退出。

真实浏览器额外执行20次双问题交替和30次三问题循环。后者每次分别核对“2户”“客户C001”和“2026年6月”对应结果，避免把旧页面内容误判为成功。

## 当前风险

1. 无法证明 PyArrow 25 与 macOS 26.5.1 的上游精确缺陷机制，只能根据一致的原生崩溃栈将故障明确定位到该组件路径。
2. 原问题具有间歇性；当前通过双重措施规避：移除 Arrow 表格序列化入口，并切换系统内存池。
3. HTML 表格适合当前小规模 Demo；未来若展示大数据量，需要分页或重新评估稳定的表格组件。
4. 后端断开时当前用户提示较通用，但不会暴露底层异常，也不会导致前端进程退出。

## 运行要求

只允许使用桌面项目根目录 `.venv`：

```bash
cd BankInsight
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
PYTHONPATH=. .venv/bin/python -X faulthandler -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501 --server.fileWatcherType none --browser.gatherUsageStats false
```

不得再使用其他项目目录中的 `.venv` 启动 BankInsight。
