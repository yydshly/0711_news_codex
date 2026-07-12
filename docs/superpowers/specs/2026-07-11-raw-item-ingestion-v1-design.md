# News Codex RawItem Ingestion v1 设计

## 1. 目标

RawItem Ingestion v1 在现有 Source Intelligence Registry、Source Universe v2、本地 PostgreSQL 与中文来源感知台之上，补齐“从已审核来源正式获取内容并可视化管理”的闭环。

本阶段不重建已有 Provider、Target、Probe、Coverage 或 A 风格中文页面。现有 YAML、探测器、查询层、诊断层、CLI 与 Web 基础设施继续复用。新增能力围绕正式抓取、幂等入库、内容版本、疑似重复、网页操作、后台任务、日志和故障恢复展开。

第一版不以“官网抓取器”为目标，而要验证五层新闻信号：官方证据、专业媒体、聚合发现、社交社区、研究开发。支持的接入类型包括：

- 官方与专业媒体 RSS/Atom
- Hacker News 官方 API
- GitHub Releases 官方 API
- arXiv Atom API
- Bluesky 公共 AppView API
- Mastodon 公共 API
- GDELT API
- Google News RSS 与原始发布者解析
- Reddit OAuth Data API
- YouTube Data API

所有正文只保存官方 RSS/API 直接返回的内容，不继续访问文章 HTML 抓取正文。

## 2. 已确认的产品边界

- 默认只抓取人工批准的白名单来源。
- CLI 和网页可以显式执行其他合规的 `ready + direct` 来源，但不能绕过凭据、审批、付费、HTML-only、`paused`、`disabled` 或条款硬阻塞。
- 同源通过 External ID 与 Canonical URL 幂等。
- 跨来源只建立重复候选关系，不自动合并或删除 RawItem。
- RawItem 保存最新状态；首次出现及内容哈希变化时保存不可变快照。
- 网页既提供流程指导，也能执行同步、探测、抓取、重试、停止和重复候选审核。
- 第一版仅本机单用户使用，绑定 `127.0.0.1`，不建设登录系统。
- Web 与 CLI 调用同一服务层。
- 执行使用 PostgreSQL 持久化队列和独立本地 Worker，不使用 Redis、Celery 或 Docker。
- 不建设后台定时调度、事件聚类、MiniMax 新闻摘要、推荐、日报或推送。
- X、Facebook、Instagram、Threads、TikTok 和 LinkedIn 继续登记并展示覆盖缺口；在没有官方权限或预算时不伪装成已覆盖，也不使用 Cookie、浏览器登录态或非官方绕过。

## 3. 总体架构

```text
现有 YAML Provider / Source 注册表
                ↓
       EligibilityService
                ↓
现有协议解析能力 + 新 Fetcher 编排
                ↓
      PostgreSQL Operation Queue
                ↓
       独立 newsradar worker
                ↓
规范化 → 幂等 → 快照 → 重复候选
                ↓
扩展 fetch_runs / raw_items 与新运行表
                ↓
现有中文感知台增加流程、操作和内容页面
```

Probe 与 Fetch 保持不同职责：Probe 读取少量样本并判断健康、字段与风险；Fetch 负责分页、条件请求、正式批次、持久化和增量状态。两者共享必要的请求与协议解析组件，但不共用结果模型或运行语义。

## 4. 数据模型

### 4.1 `operation_runs`

统一记录 Web 与 CLI 发起的 `provider_sync`、`source_sync`、`provider_probe`、`source_probe` 和 `fetch`。

主要字段：

- `id`
- `operation_type`
- `trigger`: `web` 或 `cli`
- `status`: `queued`、`running`、`succeeded`、`partial`、`failed`、`interrupted`、`cancelled`
- `requested_scope`
- `progress_current`、`progress_total`
- `result_summary`
- `worker_id`
- `attempt_count`
- `heartbeat_at`、`lease_expires_at`、`next_attempt_at`
- `cancel_requested_at`
- `started_at`、`finished_at`
- `error_code`、`error_message`

### 4.2 `operation_events`

保存经过清洗的用户可读过程记录：阶段、来源、结果、中文说明、内部错误代码、关联 ID 和时间。不得保存密钥、Cookie、Authorization Header 或完整敏感响应。

### 4.3 `workers`

保存 Worker 注册与健康状态：`worker_id`、主机、进程 ID、版本、启动时间、最后心跳、状态和当前 Operation。

### 4.4 `operation_attempts`

每次 Worker 领取或重新领取任务都创建独立 Attempt，保存 `operation_run_id`、`worker_id`、尝试序号、状态、领取时间、租约、心跳、结束时间和错误。FetchRun、操作事件与技术日志关联 `attempt_id`，使 Worker 崩溃和重领过程可以完整追踪，而不是只覆盖 OperationRun 上的最后一次状态。

### 4.5 扩展 `fetch_runs`

现有 FetchRun 增加：

- `operation_run_id`
- `access_method_id`
- `outcome`
- HTTP 状态、最终 URL、ETag、Last-Modified
- `items_received`、`items_inserted`、`items_updated`、`items_unchanged`、`items_skipped`、`items_failed`
- `next_cursor`
- `error_code`、`error_message`

单个来源使用独立 FetchRun 和事务，不影响同一 Operation 中的其他来源。

### 4.6 扩展 `raw_items`

RawItem 保存当前最新规范化状态：

- `source_id`、`external_id`
- `canonical_url`、`original_url`
- `title`、作者列表、`summary`、`content`
- `language`、`content_type`
- `published_at`、`source_updated_at`
- `discussion_url`、`engagement`
- `item_kind`
- `publisher_name`、`publisher_url`
- `discovery_url`、`origin_resolution_status`
- 社交账号 ID、Handle 与线程根 ID
- `raw_payload`
- `content_hash`、`title_fingerprint`、`canonical_url_hash`
- `first_seen_run_id`、`last_seen_run_id`
- `first_seen_at`、`last_seen_at`

现有 `payload` 数据必须无损兼容迁移，不得丢弃。

### 4.7 `raw_item_snapshots`

首次入库和内容哈希变化时保存不可变快照。`(raw_item_id, content_hash)` 唯一。内容不变时不产生快照；互动数据变化不计入内容哈希。

### 4.8 `fetch_run_items`

记录每个 FetchRun 对每条内容采取的 `inserted`、`updated`、`unchanged`、`skipped` 或 `failed` 动作，使页面可以解释批次统计。

### 4.9 `duplicate_candidates`

记录两条 RawItem 的匹配类型、分数、检测时间和 `pending`、`confirmed`、`dismissed` 审核状态。Canonical URL 相同为高置信候选；标题相似只作提示。

### 4.10 `source_fetch_states`

按 Source 与 AccessMethod 保存 ETag、Last-Modified、Cursor、最后成功时间和连续失败次数。不得保存凭据。

### 4.11 迁移策略

新增 Alembic 迁移必须从现有 `0002` 无损升级。新字段先允许为空，安全回填后再建立索引和约束。不修改 YAML，不删除旧表或旧 RawItem 数据。降级只撤销新增结构，不删除原有内容。

## 5. 白名单与资格规则

Source YAML 增加向后兼容的可选配置：

```yaml
ingestion:
  enabled: true
  approved_at: 2026-07-11
  max_items_per_run: 100
```

缺少该配置等同 `enabled: false`。程序不能自动修改 YAML。

默认批量抓取要求：

- `ingestion.enabled = true`
- `availability = ready`
- `coverage_mode = direct`
- Source 不是 `paused` 或 `disabled`
- 无条款硬阻塞
- 接入方式属于 v1 支持协议
- 所需环境变量已配置
- 不依赖 HTML 抓取

显式单次抓取允许非白名单的合规 `ready + direct` 来源，但必须展示风险和影响范围并二次确认。一次性操作不修改 YAML。付费、审批、人工、目录型、暂停、禁用或硬阻塞来源不得通过确认框绕过。

AccessMethod 按优先级选择。失败后只允许尝试另一个已审核 RSS/API 备用方式，绝不自动降级到 HTML。专业媒体 RSS 与聚合发现源必须保留来源归属；无法确认原始发布者时，只能作为发现信号，不能标记为已确认事实。

## 6. 规范化、幂等与重复候选

Fetcher 输出严格 Pydantic `NormalizedRawItem`。未知字段只能进入 `raw_payload`。所有外部内容视为不可信数据，不执行 HTML、脚本、提示或指令。

规范化规则：

- 标题解码 HTML Entity、执行 Unicode 规范化并合并空白。
- 作者统一为去重列表。
- 时间统一为 UTC；无法解析时保持为空，不伪造时间。
- Summary 与 Content 分开保存。
- Host 小写，移除 Fragment、默认端口和已知跟踪参数，保留业务参数。
- URL 规范化不发起额外网络请求。
- 保存 `original_url` 供排查。
- 聚合源的 Feed/结果链接保存为 `discovery_url`；只有受控重定向解析确认原始发布者后，原始报道 URL 才进入 `canonical_url`。
- 受控重定向解析只读取跳转链与响应头，不下载或解析文章正文；跨域、循环、超长跳转或归属不明时保留聚合 URL 并标记解析状态。

同源写入顺序：

1. 查找 `(source_id, external_id)`。
2. 未命中时检查同源 `canonical_url_hash`。
3. 未命中则新增 RawItem 和初始快照。
4. 命中后比较内容哈希。
5. 内容相同则更新最后观测、互动数据和批次关联。
6. 内容变化则更新当前状态并新增快照。
7. External ID 与 URL 分别命中不同记录时记录冲突，不自动合并。

内容哈希只包含标题、作者、摘要、正文、Canonical URL、发布时间和来源更新时间，不包含抓取时间、互动数、Header 或分页信息。

标题指纹进行 Unicode 规范化、转小写、去标点与站点尾缀，保留数字、版本号和实体。完全相同指纹直接生成候选；轻微差异只在发布时间相差不超过七天且标题足够长时，以固定的保守 Token 相似度阈值（默认 0.9）生成候选。模型不参与判断。

## 7. Fetcher 设计

统一接口：

```text
fetch(source, access_method, fetch_state, limit) -> FetchResult
```

Fetcher 不写数据库。FetchResult 返回规范化条目、请求元数据、游标、计数、限流和错误信息。

### RSS/Atom

- 复用现有解析能力。
- 支持 ETag、Last-Modified 和 304。
- GUID 优先作为 External ID，缺失时使用 Canonical URL 哈希。
- 保存 Feed 自带 Summary/Content，不访问文章 HTML。
- 单条解析失败不影响其他条目。

### Hacker News

- Story ID 为 External ID。
- 从 Top/New/Best 列表读取 Story，再请求官方 Item API。
- 无外部 URL 的 Ask HN 使用 HN Item URL。
- Deleted/Dead 跳过。
- 不抓评论树。
- Item 请求默认最多并发 5 个。

### GitHub Releases

- 官方 Release ID 为 External ID。
- Body 作为官方正文。
- Draft 跳过，Pre-release 保留并标记。
- 支持 Token、匿名限流、ETag 和分页。
- 只操作已登记仓库，不接受任意仓库 URL。

### arXiv

- 标准 arXiv ID 为 External ID。
- Abstract 为 Summary，不下载 PDF。
- 支持分页、版本更新和请求频率限制。
- 页面标记预印本未经同行评审。

### Bluesky

- 使用公共 AppView API，只操作已审核账号、Feed 或查询目标。
- AT URI 或 CID 组成稳定 External ID。
- 保存作者 DID、Handle、正文、发布时间、回复/转发/点赞数和线程根。
- 删除、屏蔽或不可用内容更新为观测状态，不把缺失自动解释为事实撤回。
- 固定账号 Feed 优先于全局搜索；搜索能力变化时准确降级或阻塞，不回退网页抓取。

### Mastodon

- 使用已审核实例的公共 API，只抓取已登记账号或明确允许的公共时间线目标。
- Status ID 与实例域名组成 External ID。
- 保存账号、正文、发布时间、回复/转发/收藏和线程关系。
- 尊重实例级速率限制与本地政策；某实例失败不影响其他实例。
- 不对所有 Mastodon 实例进行自动发现或无界抓取。

### GDELT

- 作为聚合发现源，不作为唯一事实证据。
- 保存 GDELT 结果 ID、报道标题、原始发布者、报道 URL、语言、时间及可用元数据。
- 对实体歧义、重复 URL 和来源归属缺失产生明确警告。
- 同一报道被多次发现时幂等更新，不因查询批次不同制造新 RawItem。

### Google News RSS

- 支持已审核主题、关键词和媒体聚合 Feed。
- 聚合链接保存为 `discovery_url`，受控解析原始发布者和原始 URL。
- 不抓取目标文章正文，不将 Google News 视为原始发布者。
- 无法解析原始 URL 时仍可保存发现记录，但 `origin_resolution_status` 必须标记为未解析。

### Reddit

- 只使用官方 OAuth Data API，支持已审核 Subreddit 的 Hot/New 目标。
- Post ID 为 External ID，保存作者、正文、外链、发布时间、Score 和评论数。
- 缺少 OAuth 凭据、应用未批准或权限不足时准确标记 `blocked`，不得回退到网页或 Cookie。
- 删除内容、匿名作者和社区偏差在页面中明确提示。

### YouTube

- 只使用官方 YouTube Data API，优先固定频道与已审核查询。
- Video ID 为 External ID，保存频道、标题、描述、发布时间和可用互动指标。
- v1 不承诺字幕；没有官方字幕能力时不抓取或推断完整视频正文。
- 缺少 API Key、配额耗尽或权限不足时准确阻塞，不回退网页抓取。

所有来源均受最大 Item、最大分页、响应体大小、单来源时限和 Operation 总时限约束。社交与聚合内容默认承担 `discovery` 或 `engagement` 角色，不能单独升级为已确认新闻事实。

## 8. 服务层与持久化任务队列

Web 与 CLI 只负责参数解析和响应，业务逻辑统一进入：

- `OperationService`
- `EligibilityService`
- 现有 Sync/Probe 服务
- 新 `IngestionService`
- 独立 Repository

Repository 不发起 HTTP，不决定合规。

Web 提交后写入 PostgreSQL Operation Queue 并立即返回。独立 `newsradar worker` 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 领取任务，写入 Worker、租约和心跳。执行语义为“至少一次”，依靠幂等约束保证安全重领。

提供：

```text
newsradar serve   # 推荐：启动 Web 和独立 Worker 子进程
newsradar web     # 仅网页
newsradar worker  # 仅 Worker
```

Worker 离线时网页仍可查询，写任务保持排队并显示原因。服务重启后，失去租约的任务可以重领；超过最大尝试次数则失败并等待人工重试。

## 9. 并发、超时与防卡死

默认限制：

- 同时执行 Operation：1
- 单 Operation 并发来源：4
- 同 Host 并发请求：2
- HN Item 并发：5
- 同 Source 同时最多一个 FetchRun
- Catalog Sync 使用全局独占锁

网络请求期间不持有数据库事务；按来源使用独立短事务。PostgreSQL Advisory Lock 防止不同 Web/CLI/Worker 重复处理同一 Source。

默认上限：

- 建立连接 10 秒
- 单次读取 30 秒
- 单次 HTTP 请求 45 秒
- 单来源 2 分钟
- 数据库锁等待 5 秒
- Operation 30 分钟
- Worker 租约 60 秒
- Worker 心跳 10 秒

临时连接错误、502/503/504 和合理 Retry-After 的 429 最多自动重试两次，并使用退避与抖动。400、401、403、404、410、Schema 失败、资格阻塞和数据冲突不自动重试。

停止请求只在请求、分页或来源边界生效，不强杀事务。重试创建新 OperationRun，保留原历史。

## 10. 日志、错误与诊断

建立三层日志：

1. 网页操作日志：中文阶段、进度、错误编号和恢复建议。
2. PostgreSQL 审计：Operation、Attempt、FetchRun、Source、RawItem 动作、状态、心跳和租约。
3. `.local/logs/newsradar.log`：JSON Lines 结构化技术日志，10 MB 轮转，默认保留 5 个文件。

所有层通过 `operation_id`、`worker_id`、`attempt_id`、`fetch_run_id`、`source_id` 和 `request_id` 关联。

统一清洗 Authorization、Cookie、API Key、Token、数据库密码、敏感查询参数和环境变量值。Raw Payload 不写入普通日志；异常堆栈只进入本地技术日志。

错误分类：`validation`、`eligibility`、`authentication`、`transport`、`http`、`parsing`、`persistence`、`conflict`、`limit_exceeded` 和 `internal`。一个来源失败不影响其他来源，Operation 可以是 `partial`。

`newsradar diagnostics create` 生成本地脱敏诊断包，包含版本、迁移、Worker 健康、任务摘要、脱敏错误、定义哈希及环境变量是否配置，不包含值，也不自动上传。

## 11. Web 增量设计

现有 A 风格页面和导航全部保留。新增：

- 首页流程指导：初始化、同步、探测、审核、抓取、查看内容、处理问题。
- `/operations`：任务列表、确认、进度、事件、停止和重试。
- `/fetch-runs`：按来源展示请求与入库计数。
- `/items` 与 `/items/{id}`：内容列表、详情、版本、来源性质和原始 Payload。
- `/duplicates`：并排审核疑似重复。
- `/system`：数据库、迁移、Worker、队列、当前任务、最近错误和诊断入口。

所有写操作使用 POST，提交前展示影响范围、资格、方法、上限、风险和不会执行的动作。使用 Host/Origin 校验、CSRF Token、SameSite=Strict Cookie 和一次性幂等令牌。请求只能引用已登记 ID，不能传入任意 URL、Header、Shell 命令、环境变量或 Python 模块。

页面轮询轻量状态接口，任务结束后停止轮询。Worker 离线不阻塞页面，后台抓取运行时只读页面保持响应。

## 12. CLI

新增：

```text
newsradar fetch --approved
newsradar fetch <source-id>
newsradar fetch --provider github
newsradar fetch --approved --max-items 20
newsradar fetch <source-id> --dry-run

newsradar operations list
newsradar operations show <operation-id>
newsradar operations retry <operation-id>
```

`--max-items` 只能降低 YAML 上限。`--dry-run` 执行资格、请求与规范化但不写 RawItem、快照或游标。正常 Fetch 必须持久化，不提供 `--no-persist`。CLI 默认同步等待，并创建与网页相同的 OperationRun。

## 13. 首批来源矩阵

先完成官方身份、端点、字段、新鲜度、条款与三轮探测审核，再登记至少 20 个 Ingestion 目标。首批矩阵必须覆盖五层信号，不能只由官网和论文组成：

| 信息层 | 最低目标数 | 候选范围 | 主要作用 |
|---|---:|---|---|
| 官方/开发 | 4 | NVIDIA、Google AI/DeepMind、OpenAI/Anthropic GitHub Releases、Hugging Face | 事实确认与产品变化 |
| 专业媒体 | 5 | TechCrunch、The Verge、BBC、Guardian、WIRED、MIT Technology Review 等官方 RSS | 独立报道与背景 |
| 聚合发现 | 3 | Google News RSS、Techmeme、GDELT | 扩大召回并定位原始报道 |
| 社交/社区 | 4 | Hacker News、Bluesky、Mastodon，以及凭据可用时的 Reddit/YouTube | 早期动态、讨论和热度 |
| 研究/开发 | 4 | arXiv、GitHub Releases、OpenReview 或其他已有开放目标 | 论文与开发活动 |

至少 15 个免费可用目标必须完成连续三轮正式 Fetch。其余目标可以是 Reddit、YouTube 等凭据阻塞目标，但必须完成适配器能力验证并在网页准确说明解锁条件，不能冒充内容已覆盖。

X、Facebook、Instagram、Threads、TikTok、LinkedIn 即使无法免费读取，也继续出现在 Provider/Target/Gap/System 页面中。它们不计入成功抓取数量，只计入覆盖缺口与未来解锁路线。

实际端点、字段完整度、新鲜度和风险未通过时不得写入 `ingestion.enabled: true`。

## 14. 测试与验收

自动化测试必须覆盖：

- `0002` 到新迁移的无损升级、回填、索引与约束。
- 白名单、显式操作和所有禁止绕过规则。
- URL、时间、External ID、内容哈希、快照和重复候选。
- RSS/Atom、HN、GitHub、arXiv、Bluesky、Mastodon、GDELT、Google News、Reddit、YouTube 固定样本及协议边界。
- 聚合链接解析、原始发布者归属、无法解析和跨域跳转限制。
- 社交账号身份、删除状态、互动字段、线程关系和社区内容风险标记。
- Reddit/YouTube 缺少凭据、权限不足和配额耗尽时的阻塞语义。
- DNS、TLS、超时、响应过大、401/403/404/410/429/5xx、非法 XML/JSON、Schema 漂移和数据库锁。
- Worker 租约、双 Worker 竞争、心跳丢失、崩溃重领、最大尝试、停止和短事务。
- 日志关联、敏感信息清洗、轮转和诊断包。
- CSRF、Origin、Host、幂等令牌、内容转义和只允许已登记 ID。
- 首页指导、操作确认、进度、批次、内容、版本、重复审核和系统状态。

浏览器验收覆盖桌面、移动端、键盘焦点、长内容、Worker 离线、任务刷新和后台抓取时的页面响应。

真实网络验收要求：至少 20 个目标完成审核，其中至少 15 个免费可用目标完成三轮 Probe 和三轮 Fetch，并覆盖五层信息信号与至少 8 种接入方式；验证一次条件请求、一次聚合原始 URL 解析、一次 Worker 重启恢复、一次来源失败隔离和一次凭据阻塞，并检查 RawItem、快照、FetchRun、操作事件和日志。

## 15. 完成标准

- 现有 147 项基线测试和中文来源感知台无回归。
- PostgreSQL 队列与独立 Worker 可运行且不会永久卡住任务。
- 网页具有流程指导和真实操作入口。
- RSS/Atom、HN、GitHub、arXiv、Bluesky、Mastodon、GDELT、Google News、Reddit、YouTube 适配器具有明确可用或阻塞结果。
- 至少 20 个目标完成审核，至少 15 个免费可用目标连续三轮正式抓取成功。
- 官方、专业媒体、聚合发现、社交社区、研究开发五层均有真实内容或准确阻塞证据。
- 聚合和社交内容不会被错误标记为独立事实证据。
- RawItem 幂等、快照和疑似重复有效。
- 错误可在网页、数据库和本地日志中关联定位。
- Worker 崩溃不会造成重复内容或永久 `running`。
- 后台抓取不阻塞网页查询。
- 日志和诊断包不泄露凭据。
- 不抓文章 HTML，不调用 MiniMax 生成新闻，不加入调度、推荐、日报或推送。
- 完整 pytest、Ruff、真实网络和浏览器验收通过。

## 16. 实施顺序

扩展后的 v1 涉及运行时、开放来源、凭据来源和 Web 四个边界，实施计划必须按里程碑拆分，不能作为一次大改提交：

### 里程碑 A：可靠 Ingestion 内核

1. 数据模型、迁移、日志与错误契约。
2. Operation Queue、Worker 租约、心跳和并发保护。
3. Eligibility、规范化、幂等、快照和重复候选。
4. RSS、HN、GitHub、arXiv Fetcher。
5. CLI Fetch/Operations/Worker/Serve。

完成后只能说明 Ingestion 内核可用，不能宣称全域来源覆盖完成。

### 里程碑 B：开放新闻与社交发现

1. 专业媒体 RSS 目标审核。
2. Bluesky、Mastodon、GDELT、Google News Fetcher。
3. 聚合原始发布者与受控重定向解析。
4. 五层来源角色和证据边界展示。

### 里程碑 C：凭据型来源与 Web 操作

1. Reddit、YouTube 凭据型 Fetcher 与阻塞语义。
2. Web 流程、操作、批次、内容、重复和系统状态。
3. Worker 离线、排队、重试、停止和诊断体验。

### 里程碑 D：覆盖与可靠性验收

1. 至少 20 个五层来源目标审核。
2. 至少 15 个免费目标完成真实网络三轮探测与抓取。
3. 完整 pytest、Ruff、浏览器验收、日志脱敏、Worker 恢复和可靠性演练。

只有 A 至 D 全部通过，RawItem Ingestion v1 才算完成。
