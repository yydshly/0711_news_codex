# 高价值 AI/技术新闻波次 v1.5 验收报告

验收时间：2026-07-16（Asia/Shanghai）

## 本次结论

v1.5 的代码、Profile 和本地离线验收已完成；三轮真实 PostgreSQL 抓取验收未执行成功，原因是项目本机 PostgreSQL 当前无法监听其既有本地地址。该状态不能被标记为来源抓取成功，也不会通过更换协议、使用登录态或绕过网络限制来伪造结果。

## 已完成的能力

- 冻结 Profile：`high-value-ai-tech`，共 35 个已审核目标；命令校验通过。
- `waves enqueue-due`：只在到期且没有同 Profile 活跃/近期波次时创建一个持久化任务；命令本身不会触发 Worker、来源请求或模型调用。
- 任务入队仍由既有 PostgreSQL advisory lock 与 `active_high_value_wave_exists` 保护；并发点击会得到不入队结果。
- 中文报告将事件分为“已确认热点”“早期信号”“7 天趋势”，并使用冻结成员、不可变事件版本和热度快照。
- 社区、社交和聚合内容不会越权成为已确认新闻；确认仍需官方一手材料或两条独立专业媒体证据根。
- MiniMax 不可用时保留规则快照；该降级状态会写入报告，模型不参与合规或确认判定。
- 报告只读取已持久化元数据，不携带请求头、正文或本地凭据。

## 三轮真实抓取验收

| 轮次 | 状态 | 结果 | 原因 |
| --- | --- | --- | --- |
| 第 1 轮 | 未开始 | 无 Operation | 本机数据库端口拒绝连接，无法安全创建持久化波次。 |
| 第 2 轮 | 未开始 | 无 Operation | 必须等待第 1 轮终态；前置数据库不可用。 |
| 第 3 轮 | 未开始 | 无 Operation | 必须等待第 2 轮终态；前置数据库不可用。 |
| MiniMax 离线轮 | 未开始 | 无 Operation | 与三轮相同的数据库前置条件未满足；代码级离线降级测试已通过。 |

### 已验证的数据库阻塞证据

- 项目根目录已有本机数据库配置，但该配置没有复制到当前功能工作树，也未展示或写入报告。
- 在仅注入该本地配置的临时进程中，TCP 探测返回 `ConnectionRefusedError`。
- 尝试通过项目自己的 `newsradar db start` 启动本地运行时失败；运行日志记录为无法绑定既有 `127.0.0.1` 监听地址（操作系统拒绝）。
- 因此 `alembic upgrade head` 被中止，避免在不可达数据库上无限等待或误报迁移成功。

恢复条件：由本机运行环境释放/允许项目数据库的既有监听地址后，先执行 `newsradar db start`，再运行迁移与三轮波次。恢复后不得删除 `.local/postgres`、不得更换为未知外部数据库、不得修改来源协议以规避阻塞。

## 离线质量门禁

| 检查 | 结果 |
| --- | --- |
| `pytest tests/waves/test_scheduling.py tests/waves/test_reporting.py tests/waves/test_runtime.py tests/acceptance/test_high_value_news_wave_v1_5.py -q` | 通过：15 项通过、1 项 PostgreSQL 前置条件跳过。 |
| Profile 冻结验收 | 通过：35 个目标、无网络请求。 |
| `newsradar providers validate` | 通过：67 个平台。 |
| `newsradar sources validate` | 通过：187 个来源。 |
| `newsradar waves validate --profile wave_profiles/high-value-ai-tech.yaml` | 通过：35 个目标。 |
| 定向 Ruff 与 `git diff --check` | 通过。 |
| 本地浏览器页面验收 | 未执行：当前 Codex 浏览器连接没有可用浏览器绑定；未以截图或手工观察替代真实验收。 |

## 尚待恢复后执行的操作

1. 启动项目本机 PostgreSQL，并确认它处于当前 Alembic head。
2. 使用 `waves enqueue` 创建第 1 轮，使用 Worker 消费至终态；同样完成第 2、3 轮。
3. 为每轮记录 RawItem inserted/updated/unchanged、成员状态、事件版本与最多 20 个事件抽样结果。
4. 暂时移除 MiniMax 配置再运行一次，确认规则快照、中文页面和报告仍完整。
5. 在本地浏览器检查 `/`、`/events`、`/emerging`、已确认详情、早期信号详情和失败诊断页面。

## 安全边界

- 没有创建 Windows Task Scheduler 或任何无人值守计划任务。
- `enqueue-due` 只是人工/外部调度器可调用的到期判定接口，不自行循环或重复抓取。
- 没有使用浏览器会话、登录态、代理绕过、验证码破解或非官方网页回退。
- 报告中未包含 API Key、数据库连接串、请求头或抓取正文。
