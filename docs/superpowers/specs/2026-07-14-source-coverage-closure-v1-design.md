# News Codex 来源覆盖收口 v1 设计

## 1. 目标

本阶段只处理当前来源目录中“已标记为就绪直连，但从未留下成功抓取记录”的目标，
不扩展来源宇宙，不开发摘要、推荐、调度器或新的抓取协议。

完成后应满足：

- 每个继续标记为 `availability=ready` 且 `coverage_mode=direct` 的 Target，至少存在一次
  `FetchRun.outcome` 为 `succeeded` 或 `no_change` 的真实抓取记录；或有本轮产生的明确失败证据。
- OpenAI YouTube 的公开 Atom 主路径按照它真实能提供的字段验收，不再被 API 才能提供的互动量阻塞。
- Qwen3 Releases 不因 HTTP 200 空数组而冒充可用新闻来源；它保留在来源地图中，但退出就绪抓取统计。
- `/sources` 自动反映新的真实覆盖结果，无需增加另一套页面或统计口径。
- 全部操作仍通过 PostgreSQL 队列和现有 Worker 执行，单个来源失败不阻塞其他来源。

## 2. 当前基线

截至 2026-07-14，YAML 目录有 43 个就绪直连 Target，其中 28 个已经存在成功或
`no_change` FetchRun，尚有 15 个缺口。

### 2.1 已探测成功、具备试用资格但尚未抓取的 13 项

| Target | Provider | 当前结论 |
| --- | --- | --- |
| `arxiv-cs-cl` | arXiv | 可直接进入受控试抓 |
| `arxiv-cs-lg` | arXiv | 可直接进入受控试抓 |
| `cuda-python-releases` | GitHub | 可直接进入受控试抓 |
| `gemini-cli-releases` | GitHub | 可直接进入受控试抓 |
| `microsoft-research` | independent | 可直接进入受控试抓 |
| `transformers-releases` | GitHub | 可直接进入受控试抓 |
| `universe-cnbc-1` | CNBC | 可直接进入受控试抓 |
| `universe-hard-fork-1` | Hard Fork | 可直接进入受控试抓 |
| `universe-import-ai-1` | Import AI | 可直接进入受控试抓 |
| `universe-interconnects-1` | Interconnects | 可直接进入受控试抓 |
| `universe-mit-tech-review-1` | MIT Technology Review | 可直接进入受控试抓 |
| `universe-techmeme-1` | Techmeme | 可直接进入受控试抓 |
| `universe-venturebeat-1` | VentureBeat | 可直接进入受控试抓 |

### 2.2 需要纠正目录口径的 2 项

`openai-youtube` 的官方 Atom 请求返回 HTTP 200、5 条样本和 80% 字段完整率。缺失的是
只有 YouTube Data API 才能补充的互动量；它不应阻塞 Atom 作为公开发现入口。

`qwen3-releases` 的 GitHub Releases API 返回 HTTP 200，但当前官方仓库没有 Release，
样本数为 0。该入口目前不能产生新闻信息，强行抓取只会制造“成功但无内容”的假覆盖。

## 3. 采用方案

采用“现有管线优先、目录口径纠正、证据驱动收口”的方案：

1. 对 13 个已合格缺口使用现有 FetchRun、OperationRun 和 Worker 进行最多 5 条的受控试抓。
2. 将 OpenAI YouTube 的 Target 级必需字段调整为 Atom 主路径实际提供的
   `title`、`canonical_url`、`published_at` 和 `summary`；`engagement` 继续保留在研究资料和
   YouTube API 补充能力中，不作为公开 Atom 的启用门槛。
3. 将 Qwen3 Releases 调整为 `availability=unavailable`、`status=degraded`，保留
   `coverage_mode=direct`、官方身份、接口和研究证据；解锁条件是官方仓库出现至少一个
   Release 且重新探测成功。
4. 重新同步目录、探测 OpenAI YouTube 和 Qwen3 Releases，再只对仍然缺失且符合 TrialDecision
   的就绪直连来源排队。
5. 从 PostgreSQL 生成中文收口报告，展示每个目标的探测、资格、操作、FetchRun、RawItem 和最终结论。

不采用以下方案：

- 不为 Qwen 临时改抓 commits 或 events。这是不同的信息类型，噪声更高，应作为未来独立 Target 审核。
- 不放宽全局 90% 探测成功阈值，也不允许 `degraded` 来源直接试抓。
- 不把 HTTP 200、空列表或队列成功当成内容覆盖成功。

## 4. 组件与边界

### 4.1 目录调整

只修改两个 YAML：

- `sources/universe/universe-youtube-1.yaml`
- `sources/github/qwen3-releases.yaml`

不新增 Provider、Target、访问方式、凭据或数据库迁移。YAML 仍是目录真相，数据库只保存同步版本与运行历史。

### 4.2 覆盖收口规划器

新增独立模块 `newsradar.ingestion.coverage_closure`，负责纯规则计算：

- 输入：当前 SourceDefinition、最新 ProbeSnapshot、已有 FetchRun 覆盖集合。
- 输出：`CoverageClosurePlan`，将 Target 分为：
  - `covered`：已有 succeeded/no_change FetchRun；
  - `queueable`：就绪直连、尚未覆盖、最新探测满足 TrialDecision；
  - `blocked`：尚未覆盖但不满足资格，并保留确定性错误代码和中文原因。
- 规划器不访问网络、不调用 MiniMax、不写数据库。

覆盖集合必须使用 Target ID 去重。历史失败、pending 或 cancelled FetchRun 不算已覆盖。

### 4.3 CLI 执行入口

新增：

```text
newsradar sources close-coverage
newsradar sources close-coverage --execute --wait --max-items 5
```

默认只输出计划，不写数据库。只有显式 `--execute` 才通过 `OperationCommandService` 为
`queueable` Target 创建 trial Fetch 操作。`--wait` 使用现有终态等待逻辑；不在 CLI 进程中直接请求外部网站。

重复执行时，已产生 succeeded/no_change FetchRun 的来源自动进入 `covered`，不会重复排队。

### 4.4 报告

生成 `reports/source-coverage-closure-v1.md`，包含：

- 收口前后就绪直连数量与实际抓取来源数量；
- 15 个基线缺口的逐项结论；
- OperationRun、FetchRun 和新增 RawItem 数量；
- 失败代码、是否可重试和下一步；
- OpenAI YouTube 字段口径说明；
- Qwen3 Releases 退出就绪统计的证据；
- 明确声明本轮未使用 Cookie、浏览器会话、代理绕过或 MiniMax 决策。

报告不包含 API Key、数据库连接串、请求头、Cookie、代理地址或带查询参数的敏感 URL。

## 5. 数据流

```text
YAML 校验与同步
  → 两个目标重新探测
  → 读取最新 ProbeSnapshot + 历史 FetchRun
  → CoverageClosurePlan
  → 仅 queueable 创建 trial OperationRun
  → Worker 串行/有界消费
  → FetchRun + RawItem + OperationEvent
  → 重新计算覆盖
  → 中文报告与 /sources 自动更新
```

Web 页面保持只读，不从浏览器直接启动本轮批处理。执行入口先保持 CLI 显式授权，避免误触发 14 个外部请求。

## 6. 错误、并发与可靠性

- 所有来源在排队前重新计算 TrialDecision，不能使用过期的人工名单绕过资格。
- 一次性创建全部 queueable 操作；Worker 对每个操作独立租约、心跳、超时、重试和取消。
- 单个来源出现 401、403、404、429、5xx、解析失败或超时，只影响自己的 OperationRun。
- `--wait` 返回时列出每个操作终态；任一操作为 failed/cancelled 时命令返回非零，但不回滚其他成功结果。
- 重复运行必须幂等地跳过已覆盖来源。
- 没有活跃 Worker 时操作保留 pending，页面和 CLI 均能观察，不在 Web 请求中阻塞。
- MiniMax 不参与资格、目录状态或失败处理决策。

## 7. 页面表现

不新建页面。现有 `/sources` 自动显示：

- YAML Target 与数据库 Target 漂移；
- 就绪直连数量；
- 实际抓取来源数量；
- RawItem 数量；
- 剩余抓取覆盖缺口。

若本轮只有部分成功，页面必须如实显示剩余差距，不能把已排队或 HTTP 200 当作已覆盖。

## 8. 测试与验收

### 8.1 规则测试

- succeeded/no_change 算 covered；failed/pending 不算。
- 只有 ready + direct + TrialDecision eligible + 未覆盖才 queueable。
- 间接、目录、受限、探测降级和无样本目标进入 blocked 或不在收口范围。
- 重复执行不会为已覆盖 Target 新建操作。
- OpenAI YouTube 固定 Atom 样本在新字段口径下达到 success。
- Qwen3 Releases 不再计入 ready direct。

### 8.2 CLI 与 Worker 测试

- 默认 close-coverage 只读，不创建 OperationRun。
- `--execute` 只为 queueable 创建 trial 操作，每个 `max_items <= 5`。
- 一个操作失败不阻止其他操作创建和完成。
- `--wait` 正确返回终态和退出码。
- 页面与报告不泄露敏感配置。

### 8.3 真实验收

1. 使用本地 PostgreSQL 同步 YAML。
2. 对 OpenAI YouTube、Qwen3 Releases 执行真实内容探测并持久化结果。
3. 运行 `close-coverage --execute --wait --max-items 5`。
4. 验证继续处于 ready direct 的 Target 全部具有 succeeded/no_change FetchRun，或报告列出本轮真实失败。
5. 生成中文报告并在浏览器验收 `/sources`。
6. 运行完整 Ruff、pytest 和 `git diff --check`。

## 9. 非目标

- 不新增 Qwen commits/events Target。
- 不增加 YouTube Transcript 或 yt-dlp 自动执行。
- 不启用登录 Cookie、浏览器会话或反爬绕过。
- 不调整全局探测阈值和 TrialDecision 安全规则。
- 不修改事件聚合、摘要、推荐、MiniMax、调度器或通知功能。
- 不自动把来源状态升级为 active。

## 10. 完成标准

本阶段完成时：

1. 15 个基线缺口均有明确结论；
2. 13 个已有资格来源和修正后的 OpenAI YouTube 均完成受控试抓，或留下本轮可定位失败；
3. Qwen3 Releases 诚实退出就绪统计但仍保留目录与解锁条件；
4. 没有已覆盖来源被重复排队；
5. `/sources` 和中文报告使用真实运行数据；
6. 完整测试、真实数据库验收和最终代码审查通过。
