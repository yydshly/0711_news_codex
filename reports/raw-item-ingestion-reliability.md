# RawItem Ingestion v1：可靠性与并发验收记录

更新日期：2026-07-12（本地自动化验收）

本报告只记录可复现的本地运行时证据；真实网络三轮抓取由 Milestone D 的现场验收报告单独记录，不能用本报告替代。

## 已验证的运行时边界

| 场景 | 证据 | 结论 |
| --- | --- | --- |
| Worker 进程丢失后的租约恢复 | `tests/acceptance/test_worker_recovery.py::test_expired_worker_lease_is_recovered_without_duplicate_item_or_snapshot` | 过期租约由新 Worker 重领；旧 Attempt 标记为 `interrupted`，同一 `(source_id, external_id)` RawItem 与内容快照均保持单条。 |
| 任务所有权与 Worker 心跳 | `tests/acceptance/test_worker_recovery.py::test_only_current_lease_owner_can_finish_an_operation_and_workers_expose_heartbeats` | 第二个 Worker 不能领取已有有效租约；非所有者不能结束 Attempt；领取、续租、结束均更新 Worker 心跳和当前任务。 |
| 网页不阻塞 | `tests/acceptance/test_nonblocking_web.py::test_web_enqueue_and_read_routes_return_while_worker_is_busy` | 网页 POST 只创建队列任务并返回 303；慢 Worker 执行时，任务详情与列表读取仍返回 200。 |
| 取消、最大尝试与错误脱敏 | `tests/operations/test_repository.py`、`tests/operations/test_worker.py`、`tests/web/test_security.py` | 取消任务不可再领取；失败最多三次后终止；异常内容会被脱敏；写入口限制为本机同源和一次性令牌。 |

## 本次可复现命令

```powershell
uv run pytest tests/acceptance tests/operations tests/web/test_security.py -q
uv run ruff check tests/acceptance src/newsradar/operations
```

验收测试不访问网络、不使用真实凭据，也不将任何 API Key 写入数据库、日志或报告。

## 运行时追踪与恢复

每次领取生成不可变 `operation_attempts` 记录。租约失效后，新 Worker 领取同一 `operation_runs` 任务会把前一次 Attempt 标记为 `interrupted`，并绑定新的 Attempt ID。Worker 记录保存最近心跳与当前操作；完成时清除当前操作，方便 `/system` 与诊断包定位停滞的 Worker。

## 限制与后续现场证据

- 本地验收使用 SQLite 验证状态机和所有权边界；生产 PostgreSQL 的 `FOR UPDATE SKIP LOCKED` 语义另由迁移与真实运行轮次验证。
- 本报告不虚构网络时延、第三方限流或真实来源成功率；这些指标应写入 `reports/raw-item-ingestion-live-acceptance.md`。
- 诊断 ZIP 的脱敏逻辑由既有 `tests/test_diagnostics_bundle.py` 覆盖。生成真实诊断包前，应在本地扫描压缩包和轮转日志，确认不存在测试或运行凭据。

## PostgreSQL 同一任务竞争证据

`tests/acceptance/test_postgres_operation_contention.py` 是真实 PostgreSQL 的双
Session 集成测试。它让第一个 Worker 在 `FOR UPDATE` 锁定一个 queued
`operation_runs` 行后暂停，再让第二个 Worker 对同一个 operation/source 调用生产
`lease_next`。第二个 Worker 必须被 `SKIP LOCKED` 跳过；释放第一个 Worker 后，数据库
只能保留一次 attempt 和一条关联的 fetch run。仅当项目本地 PostgreSQL 未配置或不可用时
测试会跳过；断言失败不会被当作跳过处理。
