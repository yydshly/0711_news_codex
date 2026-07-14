# Event Intelligence v2 Task 4 实施报告

日期：2026-07-14

范围：仅完成候选级 MiniMax 有界增强、模型降级审计、Pipeline/Worker 统计，以及 Task 3 遗留的 canonical Event 首建竞争闭环；未进入网页或 Task 5。

## 实施结果

- 新增候选级 `EventEnrichmentBatch` / `EventEnrichmentResult`，只处理规则 included 且确需发布新版本的候选；单候选失败只降级该候选。
- MiniMax 快速模型执行候选编辑增强；M3 深度模型只允许 `metadata.disputed is True` 的规则争议候选。
- Prompt 仅包含不可信候选标题和最多 5 个证据标题，每个标题最多 500 字符；不发送正文、payload、metadata、环境变量或 URL 查询参数。
- 非法 JSON 最多修复一次，每次尝试独立写入安全 usage；无 Key 不发 HTTP，只写 0-token `fallback/no_api_key`。
- 所有候选网络工作均在发布短事务和 Event lease 之前完成；模型 usage 与最终 Event 通过 `event_model_runs` 原子关联。
- Pipeline/Worker 输出 selected、included、excluded、候选数、版本数以及模型成功/降级计数；操作 scope 与幂等键共享固定 `window_end` 和四项 v2 版本。
- PostgreSQL canonical 首建竞争使用 savepoint 收敛：相同快照 loser 返回 winner，不同快照返回 retryable publication conflict。

## 独立审查 8 项闭环

1. 取得已有 Event lease 后重新读取 active membership。A/B 同快照竞争时，B 原子关联自身 attempts、释放 lease、返回 `created=0`，不再创建重复版本。
2. Batch 与生产 adapter 的有效并发硬上限为 2，即使配置请求 5。
3. 两次模型尝试共享一个 monotonic deadline；repair 只获得剩余预算，预算耗尽不再发 HTTP，并写入 `fallback/timeout`。
4. canonical 首建 loser 在同 membership 时把自身 usages 原子关联到 winner；审计失败仍为显式 retryable。
5. malformed、negative、NaN、无穷或超大 token count 安全归零，不再导致合法 success usage 丢失。
6. M3 只接受 `candidate.metadata.get("disputed") is True`，reason 文本不能授权。
7. 标题清洗覆盖 `http`、`https`、协议相对和 `www` URL 的 query/fragment，继续保持 500 字符上限。
8. Pipeline 新增 enrichment 前和候选级 checkpoint。候选 checkpoint 位于 semaphore 获取后、adapter try 外；异常会终止 batch、取消 started/pending async HTTP 并快速返回。生产模型 HTTP 已移除 `asyncio.to_thread`，改为同一 event loop 的直接 async 调用。

## TDD 与验证证据

- 第一批 1/2/4/5/6/7 均先建立最小 RED，再转 GREEN；确定性 A/B 测试验证只新增一个版本且 B usage 被审计。
- 第二批 total-timeout RED 证明旧实现给 repair 完整 0.1 秒且过期仍发第二请求；取消 RED 证明旧实现会让后续候选抢占刚释放的 semaphore。
- 聚焦 enrichment/pipeline/provenance：70 passed。
- 真实 PostgreSQL canonical 首建 contention：passed；唯一 event、唯一 version，winner/loser 两次 usage 均关联。
- 全量（安全注入项目本地 PostgreSQL 配置）：916 collected，全部 passed。
- `python -m ruff check src tests`：passed。
- `git diff --check`：passed。
- `.env` 未修改、未提交。

## 边界

- 本任务未修改网页、来源 YAML、来源合规或启用状态，也未执行 Task 5。
- 共享 `.superpowers/sdd` 中其他未跟踪任务/审查文件未纳入提交。
