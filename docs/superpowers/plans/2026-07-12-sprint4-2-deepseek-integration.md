# Sprint 4.2 DeepSeek Integration Plan

## Goal

Add a two-stage DeepSeek SQL generator and rule fallback behind the existing SQLGenerator Port without changing QueryPipeline responsibilities.

## Tasks

- [x] Add dotenv-backed settings, `.env.example`, and secret-safe `.gitignore`.
- [x] Implement and test the DeepSeek chat-completions adapter with normalized failures.
- [x] Implement and test strict business semantic parsing and SQL JSON parsing.
- [x] Implement and test HybridSQLGenerator fallback boundaries.
- [x] Select rule, llm, or hybrid only in the composition root.
- [x] Add the opt-in real smoke script and run it without exposing secrets.
- [x] Run all regression tests, update docs, and sync the verified project.

## Scope Guardrails

Do not modify QueryPipeline orchestration, database schema/data, RuleSQLGenerator behavior, query request contract, RAG, Agents, automatic SQL repair, or new business questions.
