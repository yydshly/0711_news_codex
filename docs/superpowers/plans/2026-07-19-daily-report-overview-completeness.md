# 日报全览完整性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全览和完整报告不再静默遗漏事件，并提供逐项中文降级原因与最新任务入口。

**Architecture:** 扩展日报快照草稿模型，用安全的降级快照替代 `_overview_drafts` 的跳过行为。决策简报继续只使用完整快照；全览、完整报告使用全部草稿。页面读取已持久化的降级原因，不触发网络抓取。

**Tech Stack:** Python 3.12、SQLAlchemy、FastAPI、Jinja2、pytest。

## Global Constraints

- 不读取、输出或写入 `.env` 密钥。
- 不重新抓取来源；只复用固定事件快照。
- 外部 URL 继续经过 `_public_url` 安全清洗。

---

### Task 1: 持久化降级快照

**Files:**
- Modify: `src/newsradar/daily_reports/service.py`
- Test: `tests/daily_reports/test_service.py`

- [ ] 写失败测试：构造一个 `get_operation_event` 返回 `None` 的可见事件，断言报告全览数量包含该事件，快照含 `display_degradation_reason="event_detail_unavailable"`。
- [ ] 运行 `uv run --extra dev pytest tests/daily_reports/test_service.py -q`，确认测试因当前跳过逻辑失败。
- [ ] 实现 `_degraded_overview_item(row, version_number, reason)`，生成含事件 ID、版本、空证据和中文原因的安全快照；`_overview_drafts` 捕获详情/字段异常时追加降级草稿而非 `continue`。
- [ ] 再次运行同一测试，确认通过。

### Task 2: 网页显示降级原因

**Files:**
- Modify: `src/newsradar/web/templates/daily_report_detail.html`
- Test: `tests/web/test_daily_report_pages.py`

- [ ] 写失败页面测试，断言降级项目显示“待补齐展示数据”和中文原因。
- [ ] 实现降级徽标与原因字段；决策简报跳过降级项目，全览与完整报告保留。
- [ ] 运行页面测试，确认通过。

### Task 3: 最新任务入口

**Files:**
- Modify: `src/newsradar/web/templates/daily_reports.html`
- Test: `tests/web/test_daily_automation_pages.py`

- [ ] 写失败测试，断言最近自动任务区包含“打开最新任务”链接；成功任务同时显示“打开最新日报”。
- [ ] 实现链接，复用现有 `automation.last_run` 和 `autopilot_runs` 数据。
- [ ] 运行页面测试，确认通过。

### Task 4: 回归验证

- [ ] 运行日报聚焦测试、Web 聚焦测试与 Ruff。
- [ ] 运行 `uv run --extra dev --extra research pytest -q` 和 `uv run --extra dev --extra research ruff check .`。
- [ ] 从本机网页确认报告 #17 的修订版能展示全部 11 个事件，不重跑来源。
