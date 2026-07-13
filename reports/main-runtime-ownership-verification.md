# 主分支本地运行时归属迁移验收

日期：2026-07-12

## 结果

主分支已独立拥有本机 PostgreSQL 数据目录：

```text
D:\codex_project_work\news_codex\.local\postgres\data
```

端口 `55432` 当前由该目录启动的 PostgreSQL 监听。原先的两个运行工作树均保留，未删除、未移动：

- `feature/raw-item-ingestion`：保留原活跃数据目录，作为回滚副本；
- `feature/local-postgresql-runtime`：保留此前数据目录、`.env` 和未提交报告。

## 数据安全证据

停止活跃数据库后，对 `raw-item-ingestion/.local/postgres` 与
`main/.local/postgres` 生成稳定 SHA-256 清单；二者摘要一致：

```text
5F593DE9087569498CB280706EB358017627CC64DE8D7D1BE1ED1866844E7288
```

复制后的目录包含 1,470 个文件。`data/postmaster.pid` 作为运行期 PID
文件未参与稳定清单比较。

## 数据库验证

```text
alembic current  -> 20260712_0008 (head)
alembic check    -> No new upgrade operations detected.
```

切换前后计数一致：

| 数据对象 | 数量 |
| --- | ---: |
| 来源定义 | 166 |
| 运行任务 | 58 |
| RawItem | 211 |
| Event | 13 |

## 运行时验收

主分支从本机隔离端口 `8770` 启动网页和 Worker：

- `/`：HTTP 200；
- `/events`：HTTP 200；
- `/operations`：HTTP 200；
- Web 与 Worker 进程均存活；
- 本轮启动日志未包含 `Traceback`、`ERROR` 或 `CRITICAL`。

端口 `8765` 仍被保留工作树的旧网页占用，因此本验收不替换该进程。
首次合并后的运行验收使用的 Hacker News 抓取任务和事件构建任务，均在本次迁移前已完成；本次迁移没有发起网络抓取或 MiniMax 调用。

## 回滚方式

若需要回滚：停止主分支 PostgreSQL，然后在
`raw-item-ingestion` 工作树执行 `uv run newsradar db start`。原数据目录未被修改。
