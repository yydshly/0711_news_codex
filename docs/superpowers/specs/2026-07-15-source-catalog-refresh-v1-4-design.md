# 来源目录全量刷新 v1.4 设计

## 1. 背景与结论

News Codex 当前有 187 个 `current` 来源。2026-07-15 的数据库盘点结果为：

- 110 个来源最新内容探测成功；
- 63 个来源最新结果为阻塞；
- 7 个来源从未探测；
- 4 个来源降级；
- 3 个来源失败。

其中部分“阻塞”并非当前能力缺失，而是网页仍引用访问方式变更前的历史结果。例如 AP、Reuters、Bloomberg、Financial Times、WSJ 已从 HTML 占位改为 Google News RSS，但最新记录仍是旧 HTML 探测。使用当前 YAML 重新探测后，这 5 个入口均连续三轮成功，样本字段完整率均为 100%。

因此 v1.4 不再新增另一套来源架构，也不逐个平台深度改造。它建设一个能力感知、可恢复、可审计的全量刷新波次，让 187 个来源都获得与当前定义一致的最新结论。

## 2. 目标

v1.4 必须实现：

1. 冻结一次全目录盘点所使用的来源清单和关键定义。
2. 按来源可用性与覆盖模式选择正确的探测通道。
3. 对免费开放来源执行真实内容探测。
4. 对需要凭据、审批或付费的来源执行 Provider 能力探测，不冒充内容覆盖。
5. 对 `manual_only` 和 `catalog_only` 来源只校验目录资料，不发起内容抓取。
6. 识别访问方式变化造成的陈旧结果，避免网页继续显示旧结论。
7. 单个来源失败不阻塞整批任务；批次支持取消、租约恢复和安全重试。
8. 在中文网页中展示批次进度、来源结论、限制、解锁条件和证据时间。
9. MiniMax 完全不可用时，仍能完成盘点、探测和报告。

## 3. 非目标

本阶段不做：

- 新增新闻摘要、推荐、推送或定时日报；
- 自动启用来源或修改 YAML；
- 登录态、Cookie、验证码、代理绕过或非官方反爬；
- 自动回退到 HTML 正文抓取；
- 把 Google News、GDELT、社交讨论当成独立事实证据；
- 深度修复 GDELT、SEC EDGAR、No Priors 等单个平台问题；
- 要求所有受限来源都变成内容可读。

## 4. 总体架构

复用现有组件：

- YAML Provider 与 Source 注册表；
- `source_definitions`、`source_access_methods` 和版本快照；
- `ProbeFactory`、`ProbeRunner` 与各协议探测器；
- `ProviderProbe` 与 Provider 探测历史；
- `operation_runs`、租约、心跳、取消、恢复和 Worker Router；
- 现有中文 Web 查询层和操作详情页。

新增一个持久化操作类型：

```text
source_catalog_refresh
```

数据流：

```text
YAML 同步与严格校验
        ↓
冻结 187 个当前来源及定义摘要
        ↓
能力感知路由
  ├─ content：真实内容探测
  ├─ capability：Provider 能力探测
  └─ catalog：目录完整性校验
        ↓
逐成员持久化结果与证据链接
        ↓
operation_runs 汇总状态
        ↓
中文批次页、来源页和覆盖报告
```

网页请求只负责创建操作和读取状态，所有网络请求继续由 Worker 执行。

## 5. 冻结批次与数据对象

### 5.1 `operation_runs`

每个全量刷新批次使用现有 `operation_runs`，`operation_type` 为 `source_catalog_refresh`。

`requested_scope` 固定保存：

- `schema_version`；
- `catalog_digest`；
- `catalog_count`；
- `requested_lanes`；
- `global_concurrency`；
- `provider_concurrency`；
- `trigger`；
- `deadline_at`；
- 可选的 `retry_of_operation_id`。

`result_summary` 保存各通道和各结果的计数，不保存凭据、请求头或完整响应正文。

### 5.2 `source_catalog_refresh_members`

新增成员表，每个批次和来源唯一一行：

- `operation_run_id`；
- `source_id`；
- `provider_id`；
- `definition_hash`；
- `availability_snapshot`；
- `coverage_mode_snapshot`；
- `access_kind_snapshot`；
- `lane`：`content`、`capability`、`catalog`；
- `state`：`pending`、`running`、`succeeded`、`blocked`、`degraded`、`failed`、`cancelled`；
- `result_code`；
- `conclusion`；
- `content_probe_run_ids`；
- `provider_probe_run_id`；
- `attempt_count`；
- `started_at`、`finished_at`。

这张表承担三个职责：

1. 固定本轮成员，避免运行期间 YAML 变化改变任务范围；
2. 支持 Worker 重新领取租约后跳过已完成成员；
3. 为网页提供稳定、可筛选的逐来源结果。

Worker 开始成员前必须比较当前目录的 `definition_hash` 与冻结值。若批次创建后定义已经变化，该成员以 `stale_result` 结束且不发起网络请求；操作者应使用新目录重新创建批次，不能把新配置偷偷带入旧批次。

### 5.3 探测记录关联

给以下表增加可空的 `operation_run_id` 外键：

- `source_probe_runs`；
- `source_provider_probe_runs`。

旧历史保持兼容。新波次产生的内容探测和能力探测必须关联所属操作，成员表再保存对应记录 ID。

## 6. 能力感知路由

路由必须是确定性规则，MiniMax 不参与。

### 6.1 内容通道 `content`

满足以下条件时进入内容通道：

- `availability: ready`；
- `coverage_mode` 为 `direct` 或 `indirect`；
- 首选方法不是需要人工批准的 HTML；
- 当前方法所需凭据均已配置；
- 来源未归档。

内容通道使用当前 YAML 的首选访问方式。若最新历史记录的 `access_kind` 与当前首选方式不同，成员先标记 `stale_result`，然后运行新探测；旧探测记录不被修改。

首次返回 `success` 后，对该来源再执行两轮，三轮必须串行，同一来源不能并发。三次连续执行用于证明当前入口可重复读取，不等同于跨小时或跨天的长期稳定性。若首轮为 `no_content`、`incomplete_fields`、阻塞或失败，不追加两轮。

### 6.2 能力通道 `capability`

以下来源不执行内容抓取，而是按 Provider 去重后执行一次能力探测：

- `requires_credentials`；
- `requires_approval`；
- `requires_payment`；
- `unavailable`；
- 当前方法需要未配置的凭据。

能力探测只确认：

- 官方文档是否可达；
- 当前认证或审批状态；
- 缺少的环境变量名称；
- 费用或审批要求；
- 推荐解锁方式和证据日期。

同一个 Provider 的一次能力结果可关联多个来源成员。能力探测成功不能把成员标记为内容成功。

### 6.3 目录通道 `catalog`

以下来源进入目录通道：

- `manual_only`；
- `catalog_only`；
- 只能使用需要人工批准的 HTML；
- 没有可自动执行的访问方式。

目录校验不发起目标内容请求，只检查：

- 官方身份地址；
- Provider 与 Target 类型；
- 用途、语言和主题；
- 获取方式和限制；
- 费用、权限和解锁说明；
- 风险证据链接；
- 审核日期；
- 中文结论或可读说明。

资料不完整时使用 `catalog_incomplete`，完整时使用 `catalog_verified`。两者都不代表内容覆盖。

## 7. 错误与状态语义

统一使用以下结果码：

- `stale_result`：历史结果使用的访问方式已不是当前首选方式；
- `no_content`：入口可达但当前没有内容；
- `incomplete_fields`：获得内容但必要字段不足；
- `missing_credentials`：缺少 API Key 或 OAuth；
- `requires_approval`：需要平台或人工审批；
- `requires_payment`：需要付费；
- `manual_only`：只允许人工处理；
- `catalog_verified`：目录资料完整，但没有内容探测；
- `catalog_incomplete`：目录资料缺失；
- `timeout`；
- `connection_error`；
- `rate_limited`；
- `unsupported_access_kind`；
- `cancelled`；
- `deadline_exceeded`；
- `internal_error`。

成员状态与内容覆盖必须分开解释。例如：

- `capability + blocked + missing_credentials` 表示能力边界已确认，不是执行故障；
- `catalog + succeeded + catalog_verified` 表示目录审核成功，不是内容成功；
- `content + degraded + no_content` 表示接口正常但没有样本；
- `content + failed + timeout` 才是运行故障。

批次最终状态：

- 所有成员完成且没有运行故障：`succeeded`；
- 部分成员出现真实运行故障，但其余成员完成：`partial`；
- 批次初始化、数据库或 Worker 级故障导致无法继续：`failed`；
- 用户取消：`cancelled`。

真实权限阻塞、目录人工边界和空内容不会单独导致整个批次失败。

## 8. 并发、重试、取消与恢复

- 默认全局并发为 8，可配置范围为 1–16；
- 同一 Provider 默认最多并发 2 个请求；
- 同一来源的三轮内容探测严格串行；
- 单请求使用现有 HTTP 超时边界；
- 429 必须遵守 `Retry-After`，没有该响应头时使用有上限的退避；
- `timeout` 和 `connection_error` 允许一次受控重试；
- 认证、审批、付费、无内容、字段不足和目录缺失不自动重试；
- 每完成一个成员更新进度和心跳；
- Worker 每次网络边界前后检查租约、取消和总截止时间；
- 租约恢复时读取成员表，仅继续 `pending` 和失效的 `running`；已结束的失败成员只有在操作者明确创建重试批次时才复制到新操作；
- 已完成成员及已保存的探测记录不得重复创建。

单个来源异常被转换成成员结果，不能中断其他成员。

## 9. CLI 与网页

### 9.1 CLI

新增命令：

```text
newsradar sources refresh-plan
newsradar sources refresh-enqueue
newsradar sources refresh-status <operation-id>
newsradar sources refresh-report <operation-id> --output <path>
```

`refresh-plan` 只输出各通道数量和目标清单，不写数据库、不发起网络请求。

`refresh-enqueue` 先同步并严格校验目录，再在一个事务中创建操作和冻结成员。若已有活动中的全量刷新，拒绝重复创建。

### 9.2 网页

新增导航入口“全量盘点”：

- `/source-waves`：批次列表与最近一次总体摘要；
- `/source-waves/{operation_id}`：批次详情和逐来源成员；
- POST `/source-waves`：创建批次，只写队列；
- POST `/source-waves/{operation_id}/cancel`：请求取消；
- POST `/source-waves/{operation_id}/retry`：只重试允许重试的失败成员。

详情页支持按以下字段筛选：

- 通道；
- Provider；
- availability；
- coverage mode；
- 成员状态；
- 结果码。

每个来源行显示：

- 来源中文名称；
- 当前处理通道；
- 最新结论；
- 内容样本和字段完整率，或能力/目录结论；
- 探测时间；
- 解锁要求；
- 跳转到现有来源详情页的入口。

页面必须显式区分“内容成功”“能力已确认”“目录已确认”和“运行失败”。

## 10. MiniMax 边界

MiniMax 只允许在确定性结果生成后，按需提供：

- 中文错误解释；
- 中文解锁步骤改写；
- 报告中的简短可读说明。

要求：

- 不参与通道路由；
- 不决定来源合规、启用或成员状态；
- 不接收 API Key、Authorization、Cookie、请求头或完整响应正文；
- 结构化输出必须经过 Pydantic 校验；
- 超时、限流或非法 JSON 时回退到规则文案；
- MiniMax 离线不能阻塞批次完成。

## 11. 安全与隐私

- 凭据只从环境变量读取；
- 成员表、操作事件、探测历史、日志和报告不得保存凭据值；
- 受限来源无凭据时不得回退网页抓取；
- 不新增 Cookie、登录态、验证码或浏览器自动化；
- 不修改现有 URL 安全策略；
- 能力探测只访问 Provider 已审核文档地址；
- 报告不得保存完整响应正文；
- Google News 等聚合来源继续保留间接发现身份和原始媒体归属要求。

## 12. 测试设计

### 12.1 选择与冻结

- 187 个来源按 availability 和 coverage mode 路由到唯一通道；
- 归档来源不进入批次；
- 当前方法变化能识别 `stale_result`；
- 冻结后修改 YAML 不改变已创建成员；
- 同一批次和来源不能重复创建成员；
- 活动批次存在时拒绝重复入队。

### 12.2 内容探测

- 首轮成功追加两轮，并保存三个关联探测记录；
- 首轮空内容、字段不足或失败不追加；
- 同一来源串行、不同来源受全局和 Provider 并发限制；
- 401、403、404、429、5xx、超时、连接错误和字段漂移准确分类；
- 一个来源失败不影响其他来源。

### 12.3 能力与目录通道

- 缺凭据时不发起内容请求；
- 审批和付费来源只执行能力探测；
- 同 Provider 只执行一次能力请求；
- `manual_only` 和 `catalog_only` 不发起网络内容请求；
- 目录缺失字段产生 `catalog_incomplete`。

### 12.4 Worker 可靠性

- 心跳持续更新；
- 取消能在下一个网络边界生效；
- 租约过期后可恢复未完成成员；
- 恢复不重复成功成员和探测记录；
- 截止时间终止后续请求；
- 重试只包含允许重试的失败成员。

### 12.5 网页与安全

- 网页创建操作时不执行网络；
- 列表、筛选、分页和中文解释准确；
- 能力成功不显示为内容成功；
- 陈旧记录显示当前配置与旧证据的差异；
- API Key、Authorization、Cookie 和数据库密码不会出现在 HTML、日志、操作事件或报告中；
- MiniMax 离线、超时、限流和非法 JSON 均能规则降级。

## 13. 真实验收

在本机 PostgreSQL 和现有 Worker 上执行：

1. 同步并校验 187 个来源；
2. 创建一个冻结全量刷新批次；
3. 验证 7 个此前未探测来源获得最新结论；
4. 验证当前 `ready` 来源不再引用访问方式变更前的旧结果；
5. 对首轮成功来源补齐三轮连续执行证据；
6. 验证受限来源只产生能力或目录结论；
7. 在运行中验证一次取消和一次租约恢复；
8. 生成中文批次报告；
9. 在网页中验收总体摘要、筛选、来源下钻和阻塞说明；
10. 运行完整测试、Ruff、迁移、差异检查和敏感信息扫描。

本阶段完成不要求 187 个来源全部内容成功。完成条件是每个当前来源都进入冻结盘点，并获得与当前定义、权限和真实运行结果一致的可解释结论。

## 14. 当前已知事实

- AP、Reuters、Bloomberg、Financial Times、WSJ 的 Google News RSS 间接发现入口已经连续三轮成功，完整率为 100%；
- GDELT 当前重新探测仍为 `timeout`，本阶段只准确记录该失败，不在全量刷新中顺带重构 GDELT；
- DeepMind 与 Hugging Face 的 RSS 原生字段不足继续显示 `incomplete_fields`；
- Anthropic Bluesky 与 Qwen3 Releases 当前无内容继续显示 `no_content`；
- SEC EDGAR 保持 `requires_approval`，未完成专项政策审核前只走能力通道；
- No Priors 未确认官方频道 ID 前只走目录通道；
- 真实凭据平台即使凭据已经配置，也必须根据来源 availability 和当前方法决定是否允许内容探测。
