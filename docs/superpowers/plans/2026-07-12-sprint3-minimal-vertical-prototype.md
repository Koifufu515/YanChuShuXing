# BankInsight Sprint 3 Minimal Vertical Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD and execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a lightweight ports-and-adapters vertical slice where `POST /api/v1/query` answers three deterministic questions from a real SQLite database.

**Architecture:** Keep FastAPI as the driving adapter, place framework-free application models and orchestration in `application/`, define one Protocol per file in `ports/`, and place YAML, rule generation, SQLGlot, SQLite, formatting, and audit implementations in `adapters/`. A single composition root wires concrete adapters; the Pipeline imports only application models, errors, and Ports.

**Tech Stack:** Python 3.10, FastAPI, Pydantic v2, PyYAML, SQLGlot, SQLite, unittest, HTTPX TestClient.

---

## File Map

**Create application and seams**

- `backend/app/application/models.py`: framework-free dataclasses and JSON scalar type.
- `backend/app/application/errors.py`: stable application exceptions.
- `backend/app/application/pipeline.py`: orchestration only.
- `backend/app/ports/*.py`: one Protocol per replaceable capability.

**Create adapters**

- `backend/app/adapters/context/yaml_resolver.py`: keyword-based YAML context.
- `backend/app/adapters/generation/rule_generator.py`: three supported questions.
- `backend/app/adapters/safety/sqlglot_checker.py`: adapter over existing validator.
- `backend/app/adapters/database/sqlite_executor.py`: readonly execution.
- `backend/app/adapters/database/init_db.py`: atomic deterministic database initialization.
- `backend/app/adapters/formatting/template_formatter.py`: deterministic Chinese summaries.
- `backend/app/adapters/audit/noop_logger.py`: no-op audit seam.
- `backend/app/bootstrap/container.py`: sole production composition root.

**Modify integration surfaces**

- `backend/app/api/schemas.py`: external API v1 Pydantic DTOs.
- `backend/app/api/query.py`: `/api/v1/query` and compatibility `/api/v1/ask`.
- `backend/app/services/pipeline.py`: compatibility re-export only.
- `backend/requirements.txt`: add HTTPX for API tests.
- `README.md`, `task_plan.md`, `progress.md`: runnable instructions and evidence.
- `docs/Sprint3_架构实施与最小原型记录.md`: implementation record.

## Supported Questions and Gold Results

1. `查询有效客户数量` → `2` active customers.
2. `查询客户C001的账户余额` → `6,000,000` CNY across two active accounts.
3. `查询客户C001在2026年6月的交易汇总` → 3 successful transactions, inflow `100,000`, outflow `50,000`, net inflow `50,000`.

## Task 1: Pure Models, Errors, and Ports

**Files:** create `backend/app/application/models.py`, `backend/app/application/errors.py`, `backend/app/ports/*.py`; test `tests/test_architecture_contracts.py`.

- [x] Write a failing test that imports all pure models and Ports, and asserts Pipeline-related modules do not import FastAPI, SQLite, SQLGlot, or concrete adapters.
- [x] Run `PYTHONPATH=backend python3 -m unittest tests.test_architecture_contracts -v`; expect import failure.
- [x] Implement immutable dataclasses: `QueryCommand`, `QueryOutcome`, `QueryContext`, `GeneratedSQL`, `QueryResult`, `FormattedResult`, `UserContext`, `SafetyResult`, `ErrorDetail`, `AuditEvent`.
- [x] Implement stable exceptions: unsupported question, provider, SQL rejection, database unavailable/execution, query timeout.
- [x] Create one Protocol file each for ContextResolver, SQLGenerator, LLMProvider, SQLSafetyChecker, DatabaseExecutor, ResultFormatter, AuditLogger.
- [x] Re-run the test; expect pass.

## Task 2: Deterministic SQLite Initialization

**Files:** create `backend/app/adapters/database/init_db.py`; test `tests/test_database_init.py`.

- [x] Write a failing test that initializes a temporary database twice and asserts 10 tables, 3 customers, 4 accounts, and deterministic IDs without duplicate growth.
- [x] Run the single test; expect missing module failure.
- [x] Implement initialization by creating a temporary database, executing `sql/schema.sql`, inserting fixed branch/manager/customer/account/transaction records, and atomically replacing the target file.
- [x] Re-run; expect pass.

## Task 3: SQLite Executor

**Files:** create `backend/app/adapters/database/sqlite_executor.py`; test `tests/test_sqlite_executor.py`.

- [x] Write a failing test that uses a real temporary initialized database and verifies parameter binding, JSON scalar rows, row count, truncation, and duration.
- [x] Add a failing test that invalid SQL becomes `QueryExecutionError` without exposing raw SQLite exceptions through the interface.
- [x] Implement readonly URI connections, `max_rows + 1` fetch, type conversion, automatic closure, and stable exception conversion.
- [x] Re-run the executor tests; expect pass.

## Task 4: Rule Generator and YAML Resolver

**Files:** create `backend/app/adapters/generation/rule_generator.py`, `backend/app/adapters/context/yaml_resolver.py`; test `tests/test_rule_sql_generator.py`.

- [x] Write one failing public-interface test for each supported question and one unsupported question.
- [x] Implement exact/regex parsing for the three questions, returning parameterized `GeneratedSQL` matching the existing schema.
- [x] Implement keyword-based context resolution that loads `schema.yml` and `metrics.yml`, returns relevant context and table allowlists, and never performs vector retrieval.
- [x] Verify unsupported input raises `UnsupportedQuestionError`.

## Task 5: Safety Adapter

**Files:** create `backend/app/adapters/safety/sqlglot_checker.py`; test `tests/test_sql_safety_adapter.py`.

- [x] Write failing tests for legal SELECT, DELETE, multiple statements, unknown tables, and denied columns.
- [x] Implement translation between pure `UserContext`/`SafetyResult` and the existing `SqlSafetyValidator`.
- [x] Verify rejected SQL returns `allowed=False` and stable error metadata.

## Task 6: Formatter and Audit

**Files:** create `backend/app/adapters/formatting/template_formatter.py`, `backend/app/adapters/audit/noop_logger.py`; test `tests/test_result_formatter.py`.

- [x] Write failing tests for the three Gold summaries and empty results.
- [x] Implement summaries based on result column names, not on Pipeline conditionals.
- [x] Implement NoOp logger satisfying the audit Port.
- [x] Re-run; expect pass.

## Task 7: Pipeline Orchestration

**Files:** create `backend/app/application/pipeline.py`; modify `backend/app/services/pipeline.py`; test `tests/test_pipeline.py`.

- [x] Write a tracer-bullet test using fake Ports: supported query produces a successful outcome.
- [x] Implement orchestration in the required order: resolve, generate, validate, execute, format, return.
- [x] Add a test where safety rejects SQL and a fail-fast executor proves it was not called.
- [x] Add tests for unsupported questions and database errors becoming structured outcomes.
- [x] Add audit event assertions for started, succeeded, rejected, and failed.
- [x] Ensure Pipeline imports no concrete adapter or infrastructure library.

## Task 8: Composition Root and HTTP API

**Files:** create `backend/app/bootstrap/container.py`, `backend/app/api/schemas.py`; modify `backend/app/api/query.py`, `backend/app/main.py`; test `tests/test_api.py`.

- [x] Add HTTPX and write a failing TestClient test for `/health` and `/api/v1/query` using a temporary initialized database and dependency override.
- [x] Implement API v1 DTOs and conversion between DTO, `QueryCommand`, and `QueryOutcome`.
- [x] Map error codes to HTTP 400/403/500/503/504 while preserving the common response body.
- [x] Implement one cached composition root; API must not instantiate adapters.
- [x] Keep `/api/v1/ask` as a compatibility alias using the same DTO and handler.
- [x] Test three successful questions, unsupported question, safety rejection through a fake Pipeline, and structured database error.

## Task 9: Real Database, Documentation, and Full Verification

**Files:** generate `data/processed/bankinsight.db`; modify `README.md`, `task_plan.md`, `progress.md`; create `docs/Sprint3_架构实施与最小原型记录.md`.

- [x] Run the initializer against the project database path twice and verify stable row counts.
- [x] Run all tests with `/tmp/bankinsight-audit-venv/bin/python -m unittest discover -s tests -v`.
- [x] Start Uvicorn and verify `/health` and all three questions with real HTTP requests.
- [x] Inspect imports to confirm Pipeline depends only on Ports and application models/errors.
- [x] Document actual files, directory tree, results, rule limitations, reserved interfaces, known issues, and next recommendation.
- [x] Run review skill; resolve blocking findings and rerun the full suite.
- [x] Sync the verified project to the desktop `农行杯金融科技` directory without deleting unrelated files.

## Self-Review

- Spec coverage: directory migration, pure models, seven Ports, six minimal adapters, deterministic DB, Pipeline, composition root, API v1, tests, docs, and prohibited-scope checks are assigned above.
- YAGNI: no real LLM, frontend, RAG, vector database, Agent framework, Docker, persistent audit, or full permission system.
- Type consistency: `GeneratedSQL.parameters` and `DatabaseExecutor.execute_query` share `dict[str, JsonScalar]`; `QueryResult` is the sole database result; external DTOs remain separate from application dataclasses.
