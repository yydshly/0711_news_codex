# 手动立即运行日报 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手动立即运行在上一轮成功后创建新自动日报，而定时调度保持安全去重。

**Architecture:** 在命令服务区分“复用成功任务”和“仅复用活动任务”；网页入口传递手动语义并把受控结果提示带到任务详情。现有 Worker、任务表和执行阶段不改变。

**Tech Stack:** Python 3.12、SQLAlchemy、FastAPI、Jinja、pytest。

## Global Constraints

- 不读取、输出或写入 `.env`。
- 所有网络任务继续仅由现有 Worker 执行。
- 不允许多个活动自动日报并发执行。
- 定时调度仍对相同当天波次幂等。

---

### Task 1: 命令服务手动重跑语义

**Files:**
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/daily_reports/autopilot_repository.py`
- Test: `tests/operations/test_commands.py`

- [ ] 写失败测试：同日成功任务在 `reuse_completed=False` 下创建新任务；活动任务始终返回已有任务。
- [ ] 运行定向测试，确认当前实现仍错误复用成功任务。
- [ ] 增加显式参数与返回原因，默认保持调度复用完成任务的行为。
- [ ] 运行定向测试并提交。

### Task 2: 网页提示与入口

**Files:**
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/daily_autopilot_detail.html`
- Test: `tests/web/test_daily_automation_pages.py`
- Test: `tests/web/test_daily_autopilot_pages.py`

- [ ] 写失败测试：手动入口在成功任务后重定向新任务；活动任务重定向当前任务；详情只显示允许的中文提示。
- [ ] 运行定向测试，确认当前入口复用成功任务且无提示。
- [ ] 让两个手动入口传入手动语义，并添加闭集提示。
- [ ] 运行网页测试并提交。

### Task 3: 验证与本机运行态收口

**Files:**
- Verify: `tests/operations/test_commands.py`
- Verify: `tests/web/test_daily_automation_pages.py`
- Verify: `tests/web/test_daily_autopilot_pages.py`

- [ ] 运行定向 pytest、完整 pytest 与 Ruff。
- [ ] 在本地网页确认“立即运行”新建任务或打开活动任务并显示中文原因。
- [ ] 在没有活动任务后停止旧 `8769` 服务；合并后重启 `8767` 当前服务。
