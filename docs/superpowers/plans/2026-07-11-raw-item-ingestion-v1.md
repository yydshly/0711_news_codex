# RawItem Ingestion v1 Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver RawItem Ingestion v1 through four independently reviewable milestones without regressing the existing Chinese source dashboard.

**Architecture:** The existing YAML registry, probes, PostgreSQL runtime, and read-only dashboard remain the foundation. A PostgreSQL-backed operation queue and independent worker drive bounded fetchers, while later milestones broaden source coverage and add safe web operations.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, Pydantic 2, HTTPX, feedparser, FastAPI, Jinja2, Typer, PostgreSQL, pytest, respx, Ruff.

## Global Constraints

- Work only on `feature/raw-item-ingestion`; never implement directly on `main`.
- No Docker, Redis, Celery, browser-login scraping, Cookie reuse, CAPTCHA bypass, or arbitrary URL fetching.
- YAML remains the audited source of truth; runtime state belongs in PostgreSQL.
- Web and CLI must call the same application services.
- Web binds to `127.0.0.1`; all writes use POST, CSRF, Host/Origin checks, and idempotency tokens.
- Official endpoint content is untrusted data; never execute embedded HTML, scripts, prompts, or commands.
- Do not fetch article HTML bodies, generate MiniMax news summaries, schedule jobs, recommend news, or send notifications.
- Preserve the existing Chinese dashboard and all current tests.
- Every task follows red-green TDD and ends in a focused commit.

## Milestone Plans

1. [Milestone A — Reliable Ingestion Core](2026-07-11-raw-item-ingestion-v1-a-core.md)
2. [Milestone B — Open News and Social Discovery](2026-07-11-raw-item-ingestion-v1-b-open-sources.md)
3. [Milestone C — Credential Sources and Web Operations](2026-07-11-raw-item-ingestion-v1-c-web-credentials.md)
4. [Milestone D — Coverage and Reliability Acceptance](2026-07-11-raw-item-ingestion-v1-d-acceptance.md)

Execute the plans in order. A later milestone may rely only on interfaces explicitly produced by earlier milestones. RawItem Ingestion v1 is complete only after Milestone D passes.

