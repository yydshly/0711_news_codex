# Task 5 报告：可解释热度、七天趋势与 P1 修复

## 原任务完成内容

- 已实现确定性的 `HeatSnapshot`、`TrendDirection` 和 `TrendAssessment`：从过去七天内、至少早于当前快照 24 小时的持久化快照中选取基线。
- 每个事件版本 payload 已保存版本级 `heat_breakdown`：全部评分维度、传播速度输入、独立证据根数量、允许的互动字段与可信度原因。
- 每个事件版本 payload 已保存版本级 `trend`：方向、变化量、比较热度及比较快照时间。读页面只读取不可变版本数据，不按当前墙上时间重新计算趋势。
- Pipeline 将本轮逻辑快照时间传入发布流程；仅社区且高互动的事件仍保持 `signal`，不会被提升为已确认热点。

## P1 结论

已修复 P1。趋势计算现在将事件评分的不可变逻辑快照时间
`observed_at` 与数据库实际写入时间 `created_at` 分离；补跑或重试造成的迟写入不再让真实的历史快照被排除。

## 根因

发布路径以 Operation 的 `snapshot_at` 构造当前 `HeatSnapshot`，但 `heat_history()` 以
`EventScoreRecord.created_at` 作为历史快照的筛选和排序时间。`created_at` 是数据库写入时间，可能晚于该评分代表的逻辑窗口结束时间，因此迟写入的历史版本会被误判为不存在，产生 `trend:first_snapshot`。

## 修复内容

- 为 `event_scores` 新增可空 `observed_at`，迁移版本为 `20260716_0021`。
- `PublishedEvent` 现在保存 `snapshot_at`，因此版本 payload 同时固定该逻辑快照时间。
- 发布评分时，将 `snapshot_at` 写入 `EventScoreRecord.observed_at`；未显式传入时才采用发布时刻。
- `heat_history()` 按 `coalesce(observed_at, created_at)` 过滤、排序并构造 `HeatSnapshot`。旧数据没有 `observed_at` 时保持兼容，回退使用原 `created_at`。
- 新增迟写入回归测试：首个逻辑快照虽在后续窗口结束后才写入数据库，第二个版本仍正确取得其 24 小时基线。
- 新增迁移回归测试：从 `20260716_0020` 升级后已有评分仍保留，且新增 `observed_at` 字段。

## TDD 证据

1. 先新增 `test_publish_snapshot_uses_logical_snapshot_time_for_delayed_history`。
2. 在修复前运行，得到预期失败：`trend:first_snapshot`，而非 `trend:24h_persisted_snapshot`。
3. 先新增迁移测试；修复前运行，预期失败：`event_scores` 缺少 `observed_at`。
4. 完成最小持久化、查询和迁移修复后，两条测试通过。

## 验证

```text
uv run pytest tests/events/test_trends.py tests/events/test_quality.py tests/events/test_ranking.py tests/events/test_publishing.py tests/test_migrations.py -q
49 passed

uv run ruff check src/newsradar/db/models.py src/newsradar/events/schema.py src/newsradar/events/publishing.py src/newsradar/events/repository.py tests/events/test_publishing.py tests/test_migrations.py migrations/versions/20260716_0021_event_score_observed_at.py
All checks passed!

git diff --check
通过
```

迁移测试仍会输出 Alembic 的 `path_separator` 弃用警告；这是既有工具配置警告，与本次 P1 无关。
