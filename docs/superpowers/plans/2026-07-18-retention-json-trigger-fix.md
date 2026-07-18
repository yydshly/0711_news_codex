# 回收站 JSON 触发器修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 PostgreSQL 归档日报移入回收站时的 JSON 比较异常，并显示准确的中文失败信息。

**Architecture:** 以一次顺序 Alembic 迁移替换 PostgreSQL 触发器函数定义；保留现有归档保护和清理重挂关系。Web 层仅对回收站写入路由使用精确错误映射，不改变其他数据库错误页。

**Tech Stack:** Python、SQLAlchemy、Alembic、PostgreSQL、pytest、Starlette。

## Global Constraints

- 不读取、输出或写入 `.env` 密钥。
- 不改写现有日报及用户报告。
- 仅修改回收站触发器和诊断；不扩展功能范围。

---

### Task 1: PostgreSQL 触发器迁移

**Files:**
- Create: `migrations/versions/20260718_0030_fix_daily_report_retention_json_guard.py`
- Modify: `tests/daily_reports/test_automation_migration.py`

**Interfaces:**
- Consumes: `newsradar_guard_archived_daily_report()` PostgreSQL 触发器函数。
- Produces: 精确 JSON 文本比较的归档日报保护函数。

- [ ] **Step 1: Write the failing test**

```python
assert "NEW.generation_summary::text IS DISTINCT FROM OLD.generation_summary::text" in function_sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation_migration.py -q`

Expected: FAIL because the sequential fix migration does not yet exist.

- [ ] **Step 3: Write minimal implementation**

```sql
NEW.generation_summary::text IS DISTINCT FROM OLD.generation_summary::text
```

Keep every existing protected non-JSON field in the row comparison.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation_migration.py -q`

Expected: PASS.

### Task 2: Real PostgreSQL regression and web diagnostic

**Files:**
- Modify: `tests/test_migrations.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Consumes: repaired trigger and `database_error_response` boundary.
- Produces: successful archived-report retention update and a specific Chinese error path for unexpected retention writes.

- [ ] **Step 1: Write failing regression tests**

```python
connection.execute(text("UPDATE daily_reports SET deleted_at = CURRENT_TIMESTAMP WHERE id = 1"))
```

The PostgreSQL fixture must prove this no longer raises `UndefinedFunction`; a protected content update must still raise an integrity error.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run --extra dev pytest tests/test_migrations.py tests/web/test_daily_report_pages.py -q`

Expected: current database reproducer fails until migration is applied.

- [ ] **Step 3: Write minimal implementation**

Use the existing error-template mechanism with a retention-specific, non-secret Chinese diagnostic only for the affected write routes.

- [ ] **Step 4: Run focused and full verification**

Run: `uv run --extra dev --extra research pytest -q` and `uv run --extra dev ruff check .`

Expected: PASS.
