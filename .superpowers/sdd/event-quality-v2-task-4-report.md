# Event Intelligence v2 Task 4 实施报告

日期：2026-07-14

范围：仅实现 MiniMax 候选级有界增强、模型降级审计、Pipeline/Worker 统计，以及 Task 3 遗留的 canonical Event 首次创建竞争修复；未进入网页或 Task 5。

## 实施结果

- 新增 `EventEnrichmentBatch.enrich(candidates)` 和候选级 `EventEnrichmentResult`。默认并发为 2，可通过 `event_model_max_concurrency` 配置；一个候选异常或返回非法适配器结果只降级该候选。
- Pipeline 只把规则 included 后形成、且确实需要发布 current 新版本的候选交给模型。excluded 项和同成员 replay 不调用模型。
- MiniMax 快速模型固定使用 `MiniMax-M2.7-highspeed`；M3 冲突解释增加 rule-disputed 硬门，非 disputed 候选不能调用。
- 模型上下文只含明确标注为不可信的候选标题和最多 5 条证据标题，每个标题最多 500 字符。不发送正文、摘要、payload、metadata、环境变量、publisher、实体、candidate URL/key 或 URL 查询参数。
- 非法 JSON 最多修复一次。首次非法响应记录 `retry/invalid_response`，修复尝试再独立记录 success 或 fallback；429、timeout、5xx 和意外异常使用稳定安全错误码。
- 无 Key 不创建 HTTP 请求，每个待发布候选只产生一条 0-token `fallback/no_api_key` 审计；不写日志、Key、原文或 URL query。
- Pipeline 先完成所有候选增强，再逐候选打开短事务发布。模型 HTTP 期间没有打开的数据库 Session、事务或 Event lease。
- 每次模型尝试分别写入 `model_usage`，并通过 `event_model_runs` 关联最终 Event。审计与候选版本在同一原子事务中写入；审计失败会回滚本次候选版本并返回可重试错误，Worker 不会静默宣告成功。
- `PipelineResult` 新增 `model_success_count`，并保留 `model_fallback_count`。Worker `result_summary` 已包含 selected/included/excluded、排除原因、候选、版本、模型成功/降级等完整字段。
- 检查点覆盖 `after_event_selection`、`after_event_relevance`、`after_event_cluster`、`after_event_enrichment`、`after_event_publish`。
- `enqueue_event_pipeline()` 的 scope 与幂等键共享四项 v2 版本，并使用同一个精确固定 `window_end`。

## Task 3 可靠性遗留关闭

真实 PostgreSQL 用两个独立 Session 和 flush barrier 重现了 `SELECT none -> INSERT` 的 canonical 唯一键竞争。修复使用短 savepoint，并且只识别 PostgreSQL `events_canonical_key_key`（SQLite 使用精确 canonical 唯一错误文本）：

- winner 已发布相同成员快照时，loser 读取并锁定既有 Event，幂等返回，不创建第二版本。
- winner 快照不同时，返回显式 `event_publication_conflict`，标记为 retryable。
- 其他 `IntegrityError` 原样抛出，不吞掉真实数据库错误。
- `created_event_versions` 只在本 Operation 实际创建新版本时增加。

本地 PostgreSQL 可连接。首次真实测试发现数据库尚停在迁移 0013，因此先应用仓库已有的追加式 0014 迁移，再完成 contention 验证；未修改或提交 `.env`。

## TDD 与验证证据

关键 RED 证据包括：缺少 batch 接口、并发最大值为 1、必需检查点缺失、Worker 汇总字段缺失、幂等键使用小时桶、prompt 泄露 candidate query、非法适配器结果破坏整个 batch，以及真实 PostgreSQL canonical `UniqueViolation`。每项均在最小实现后转为 GREEN。

最终 fresh 验证：

- 指定 Task 4 聚焦套件（含安全注入配置后的两个真实 PostgreSQL contention 测试）：69 项通过。
- 全套 pytest：905 项收集，901 项通过，4 项环境条件跳过；仅有既有依赖弃用警告。
- `uv run ruff check .`：通过。
- `git diff --check`：通过。

## 剩余注意事项

- 模型审计写入失败使用 `event_model_audit_failed` 显式标记为可重试；非审计验证错误不改变原有非重试语义。
- 真实 PostgreSQL worker-claim 测试保留竞争者 5 秒快速返回约束，同时允许 winner 在真实数据集上最多 60 秒完成管线。
- 本任务没有修改网页、来源 YAML、来源合规/启用状态，也没有执行 Task 5。
