# Task 6：波次事件阶段、完整快照与 MiniMax 降级

## 实现结果

- 高价值波次的全部成员进入终态后，Worker 在独立线程复用既有 `EventPipeline` 生成事件版本清单；事件阶段使用该 operation 持久化的 `window_hours` 与 `window_end`。
- 事件阶段成功时，结果记录 `event_version_snapshots`、`event_manifest_count`、`event_manifest_complete`、事件 ID 与 `model_degraded`。后者仅反映既有 EventPipeline 的规则降级次数；本任务没有新增 MiniMax 客户端或改变模型策略。
- 事件阶段异常或超时会保留成员抓取统计，但 operation 返回 `failed`，并记录 `error_stage=event_pipeline` 和 `event_manifest_complete=false`；因此不会成为网页可读快照。
- `event_pipeline` 仍只接受 `succeeded` 快照。`high_value_news_wave` 仅在 `succeeded` 或 `partial`、全部持久化成员终态、成员总数与完成数一致、事件 manifest 明确完整且计数匹配时可读。
- 事件阶段复用波次的持久化 deadline。成员已因超时进入终态时，不会再开始事件流水线；运行中的事件阶段也通过每个 checkpoint 继续检查 deadline。

## 测试证据

- RED：新增 partial 波次完整 manifest 可读测试，在选择器尚未支持该 operation type 时失败。
- RED：新增波次抓取完成后调用事件流水线测试，在事件阶段尚未接入时失败。
- RED：审阅发现 deadline 过期后仍会进入事件阶段；新增测试先失败（`event_pipeline_failed`），随后通过。
- 定向验证：`uv run pytest tests/waves/test_runtime.py tests/events/test_runtime.py tests/events/test_minimax.py tests/events/test_operation_snapshots.py -q`。
- 全量验证：`uv run pytest -q`。
- 静态验证：`uv run ruff check src/newsradar/events/operation_snapshots.py src/newsradar/waves/runtime.py tests/events/test_operation_snapshots.py tests/waves/test_runtime.py` 与 `git diff --check`。

## SQLite 测试说明

`EventPipeline` 在独立线程中需要新建短生命周期 session。SQLite `:memory:` 每个连接各自独立，测试夹具因此改为 `StaticPool + check_same_thread=False` 共享同一连接；生产 PostgreSQL 不依赖该测试兼容层。
