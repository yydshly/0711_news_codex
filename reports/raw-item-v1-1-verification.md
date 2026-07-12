# RawItem v1.1 收口验证报告

验证日期：2026-07-12
分支：`feature/raw-item-v1-1-closure`

## 结论

RawItem v1.1 的本地运行闭环已通过本轮验收：PostgreSQL 迁移与目录同步、Web 入队到 Worker 消费、三轮真实开放来源抓取、中文运行边界和凭据状态展示均有实际证据。当前闭环不依赖 MiniMax，也未加入摘要或推荐功能。

## 数据库与目录

- PostgreSQL 实际迁移版本：`20260712_0006 (head)`。
- Provider YAML 校验：67 个通过。
- Source YAML 校验：164 个通过。
- Provider 实库同步：67 个全部 unchanged。
- Source 实库首次同步：1 created、163 updated；紧接着第二次同步为 164 unchanged。
- 实库验收发现并修复了历史 `fetch_runs` 引用接入方式时的同步外键冲突。同步器现在保留相同优先级接入方式的数据库 ID，避免无条件全删全建。

数据库内页面统计会包含此前遗留的验收数据，因此页面显示的 68 个 Provider 和 166 个 Target 高于当前 YAML 目录数量；YAML 目录数量仍以上述校验结果为准。

## Web → Worker 端到端

真实 PostgreSQL 验收测试覆盖：

1. Web POST 创建 fetch 操作；
2. 操作持久化到 PostgreSQL；
3. 真实 Worker 领取并执行操作；
4. fetch run 写回并显示 succeeded；
5. PostgreSQL 竞争领取测试确认同一操作不会被两个 Worker 重复领取。

结果：2 个 PostgreSQL acceptance tests 全部通过。

## 三轮真实抓取

选取三个不需要凭据的代表来源，每轮各抓取一次，每次最多取得 5 条：

| 轮次 | Hacker News | arXiv cs.AI | OpenAI News |
|---|---|---|---|
| 1 | 操作 30，succeeded，收到 5，新增 3 | 操作 31，succeeded，收到 5 | 操作 32，succeeded，收到 5 |
| 2 | 操作 33，succeeded，收到 5 | 操作 34，succeeded，收到 5 | 操作 35，succeeded，收到 5 |
| 3 | 操作 36，succeeded，收到 5 | 操作 37，succeeded，收到 5 | 操作 38，succeeded，收到 5 |

九次 operation 和对应 fetch run 均为 `succeeded`，无 error code。第一轮 Hacker News 新增 3 条，其余条目因已存在而正确计为 unchanged，证明重复抓取没有重复插入。

## 中文网页验收

在 `http://127.0.0.1:8766/` 实际检查：

- 首页明确说明“浏览页面不会发起网络抓取”。
- 首页明确说明抓取、取消、重试和重复候选裁决会写入数据库，网络任务只由 Worker 执行。
- 系统健康页只展示 `GITHUB_TOKEN`、`REDDIT_CLIENT_ID`、`REDDIT_CLIENT_SECRET`、`YOUTUBE_API_KEY` 的变量名与已配置/未配置状态，没有展示值。
- 运行任务页实际显示操作 30–38 全部 succeeded。
- 页面可查看来源能力、探测记录、目标目录、阻塞解锁、任务、抓取批次、RawItem 和重复候选。

## 口径与剩余限制

- 首页“连续三轮成功”仍严格统计内容探测记录，不统计本报告中的正式抓取运行，因此本轮抓取成功不会把该指标从 0 自动改为 3。
- 本轮三轮抓取是三个代表性开放来源的运行闭环验收，不等于 164 个目录来源全部稳定。
- 需要 GitHub、Reddit、YouTube 等凭据的来源仍保持阻塞，不会回退到 Cookie 或登录网页抓取。
- GDELT 仍为 degraded/one-off 发现源，不进入常规抓取。
- MiniMax 适配器尚未接入 RawItem v1.1；来源健康、资格判断、抓取和任务控制均使用确定性逻辑。

## 本轮验证命令

```powershell
uv run alembic current
uv run newsradar providers validate --root providers
uv run newsradar sources validate --root sources
uv run newsradar providers sync --root providers
uv run newsradar sources sync --root sources
uv run pytest tests/acceptance/test_cli_web_worker_flow.py tests/acceptance/test_postgres_operation_contention.py -q
uv run newsradar fetch <source-id> --no-wait
uv run newsradar worker --once
```

## 最终质量门

- `uv run ruff check .`：通过。
- `uv run pytest -q`：347 项通过，0 项失败，0 项跳过；仅有已知依赖弃用警告。
- PostgreSQL 迁移 `0006 → 0005 → 0006` 往返通过，修订后的历史接入方式外键策略已在实库应用。
- 跟踪文件和诊断包脱敏扫描未发现真实凭据；诊断包仅包含 `manifest.json` 和 `snapshot.json`。

## 最终审查修复

- CLI `operations retry` 已改用与 Web 相同的 `OperationCommandService`，新任务保留 `retry_of_operation_id` 和 `trigger=cli` 审计信息。
- 受监控的 Worker 后台执行线程不再访问拥有者线程的 SQLAlchemy Session；取消状态由独立监控 Session 传播。
- URL 查询参数 `key=` 纳入统一脱敏，fetch failure 在写入 `fetch_runs` 前再次脱敏。
- `IngestionService` 现在使用注入的 Settings 计算凭据状态，测试与生产配置口径一致。
- 删除已被历史抓取引用的接入方式时，fetch run 外键安全置空、对应游标状态清理；普通定义更新仍保留接入方式 ID 和抓取状态。
