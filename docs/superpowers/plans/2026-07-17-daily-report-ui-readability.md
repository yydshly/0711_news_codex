# Daily Report UI Readability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将日报详情页改造成数量口径清晰、条目分卡换行、决策版与情报全览易于快速浏览的中文界面。

**Architecture:** 在现有 `DailyReportQueryService` 中投影只读审核统计，模板使用现有日报条目与全览分组渲染结构化卡片，CSS 仅新增日报专用布局。数据库、生成、归档和音频数据流不变。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Jinja2、原生 CSS、pytest、ruff。

## Global Constraints

- 日报确认与线索栏目仍各最多 20 条，不增加或降低生成上限。
- 决策收录按 `included=True` 统计；待补证可以同时属于决策收录。
- 情报全览只读取日报绑定的事件运行快照。
- 不触发抓取、聚类或 MiniMax，不修改数据库结构。
- 保留现有归档、修订、审核、排序、证据链接和音频操作。

---

### Task 1: 审核统计视图

**Files:**
- Modify: `src/newsradar/web/daily_report_queries.py`
- Test: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Consumes: `tuple[DailyReportItemView, ...]` 与最新 `DailyReportEditorialReviewView.decision`
- Produces: `DailyReportEditorialSummaryView`，字段为 `total_count`、`included_count`、`needs_evidence_count`、`excluded_count`、`duplicate_count`、`unreviewed_count`

- [ ] **Step 1: Write the failing test**

新增查询测试，保存 `needs_evidence` 审核后断言：总条目 2、决策收录 2、待补证 1、排除 0、重复 0、未审核 1。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_daily_report_pages.py::test_detail_projects_editorial_summary_counts -q`

Expected: FAIL，因为 `DailyReportDetailView` 尚无 `editorial_summary`。

- [ ] **Step 3: Write minimal implementation**

新增冻结 dataclass，并在 `detail()` 根据 `views` 和最新审核结论构建统计；所有计数均由固定日报条目投影，不发起额外网络或写操作。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_daily_report_pages.py::test_detail_projects_editorial_summary_counts -q`

Expected: PASS。

### Task 2: 结构化日报模板

**Files:**
- Modify: `src/newsradar/web/templates/daily_report_detail.html`
- Test: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Consumes: `daily_report.editorial_summary`、`daily_report.confirmed`、`daily_report.emerging`、`daily_report.overview.confirmed/hotspots/signals`
- Produces: `.daily-report-metrics`、`.decision-item-card`、`.overview-group` 与折叠播报稿

- [ ] **Step 1: Write the failing page tests**

断言页面包含“本期条目”“决策收录”“待补证”“未收录”，包含逐条卡片标记；为绑定快照的确认、热点和信号分别断言分组标题和卡片内容。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/web/test_daily_report_pages.py -k "readable_summary or grouped_overview" -q`

Expected: FAIL，因为当前模板只输出连续播报文本和单一列表。

- [ ] **Step 3: Write minimal template implementation**

顶部增加统计区；决策简报遍历所有 `included` 条目并展示结构化字段；情报全览使用三个分组逐条渲染；两段播报稿放入 `<details>`；保留原有音频与完整审核明细。

- [ ] **Step 4: Run focused page tests**

Run: `python -m pytest tests/web/test_daily_report_pages.py -q`

Expected: 现有及新增日报页面测试全部 PASS。

### Task 3: 响应式视觉样式与验收

**Files:**
- Modify: `src/newsradar/web/static/styles.css`
- Test: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Consumes: Task 2 的日报专用 class
- Produces: 最大 1600px 页面容器、响应式指标网格、卡片间距、长中文自然换行、窄屏单列布局

- [ ] **Step 1: Add a failing CSS contract assertion**

新增测试读取页面并断言日报容器和卡片 class 已挂载；该测试与 Task 2 页面行为共同保护样式选择器契约。

- [ ] **Step 2: Add minimal responsive CSS**

仅增加 `.daily-report-page`、`.daily-report-metrics`、`.decision-item-grid`、`.decision-item-card`、`.overview-grid`、`.overview-item-card`、`.report-transcript` 等专用规则，并在 760px 媒体查询中切换为单列。

- [ ] **Step 3: Run automated verification**

Run: `python -m pytest tests/web/test_daily_report_pages.py -q`

Run: `python -m ruff check .`

Run: `python -m pytest -q`

Expected: 全部 PASS，仅允许仓库已有的依赖弃用警告。

- [ ] **Step 4: Run real browser acceptance**

启动隔离工作树版本的本地服务，在日报 1 页面验证指标为 5/3/1/2、决策三张卡片、全览五条分组显示，并检查窄屏换行；保存前后截图作为验收证据。

- [ ] **Step 5: Commit**

Stage only the spec、plan、query、template、CSS 和测试文件，提交信息：`feat: improve daily report readability`。不暂存或提交任何 `reports/` 文件。
