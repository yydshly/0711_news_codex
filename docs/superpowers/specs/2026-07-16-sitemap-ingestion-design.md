# Sitemap 发现线索抓取设计

日期：2026-07-16  
状态：已获用户原则批准，等待书面设计复核

## 目标

在现有 News Codex 架构中增加一个平台级、可复用的标准 Sitemap 抓取能力。首批用于验收 Ben’s Bites 和 TLDR AI 的官方公开 Sitemap，将其中合格的文章目录元数据作为“发现线索”写入 RawItem。

该能力不抓取文章正文，Sitemap 记录不能单独作为事件确认依据。

## 范围

首批目标：

- `universe-bens-bites-1`：`https://www.bensbites.com/sitemap.xml`
- `universe-tldr-ai-1`：`https://ai.tldr.tech/sitemap.xml`

本阶段不启用 Washington Post RSS。其公开 Feed 已返回 HTTP 200，但受控样本没有条目，继续保持“待验收”。

本阶段不处理需要登录、Cookie、验证码、代理规避、反爬绕过或文章 HTML 抽取的来源。

## 架构

新增一个通用 `SitemapFetcher`，通过现有 `FetcherFactory` 按 `AccessKind.SITEMAP` 选择。它复用项目当前的 `HttpPolicy`，因此沿用统一的请求超时、连接限制、有限重试、响应大小上限和公开响应头处理。

抓取器只负责：

1. 请求已经审核并登记的 Sitemap URL。
2. 解析标准 `urlset` 和 Sitemap Index。
3. 从条目读取文章 URL、`lastmod`、News Sitemap 标题和新闻发布时间。
4. 生成 `NormalizedRawItem`，交给现有服务、仓储、去重和日志链路处理。

不为每个媒体编写专用抓取器。站点差异只能通过审核后的目标配置表达。

## 数据规则

每条 Sitemap 记录按以下顺序生成字段：

- `external_id`：规范化文章 URL 的稳定哈希。
- `canonical_url`：Sitemap 条目的公开文章 URL；不得包含用户名、密码或敏感查询参数。
- `title`：优先使用 News Sitemap 的 `news:title`；没有时从 URL 最后一个有效 slug 生成可读标题。
- `published_at`：优先使用 `news:publication_date`，否则使用 `lastmod`。
- `source_updated_at`：使用 `lastmod`；缺失时为空。
- `summary`：为空，不访问文章页面补齐。
- `raw_payload`：仅保存当前 Sitemap 条目的结构化元数据，不保存认证信息或完整响应。

普通 Sitemap 缺少标题时，slug 标题只是发现标签，不能被解释为媒体正式标题。

## Sitemap Index

Sitemap Index 只能展开同一审核站点体系内的公开子 Sitemap：

- 子 Sitemap URL 必须是 HTTP 或 HTTPS。
- 不允许嵌入用户名、密码。
- 默认要求与登记入口同主机；跨主机子 Sitemap 必须预先登记为独立访问方法，本阶段不自动跟随。
- 展开数量、总条目数和响应体大小必须有上限。
- 子 Sitemap 单个失败只形成结构化警告，不阻塞其他子 Sitemap。

抓取过程中所有网络请求仍通过同一 `HttpPolicy`，并在每个子请求之间执行现有取消检查能够覆盖的批次边界。若现有 Fetcher 接口不足以在子请求间检查取消，首版只处理单个 `urlset`，Sitemap Index 保持明确不支持，不能静默降级。

## 合规和安全边界

- 仅请求配置中已经审核的 Sitemap URL。
- 不请求 Sitemap 列出的文章正文。
- 不使用 Cookie、登录状态、验证码绕过、代理或非公开接口。
- 不携带认证请求头。
- MiniMax 不参与判断来源是否合法、是否启用或字段是否可信。
- 响应必须受到超时、有限重试、并发限制和最大字节数约束。
- XML 使用禁止外部实体和外部资源解析的安全解析方式。
- 单条无效 URL、日期或标题不得中断整批；记录中文可定位警告。

## 来源状态变化

只有在真实 Worker 验收满足以下条件后，目标才能从 `manual_only + catalog_only` 改为 `ready + direct`：

- 官方 Sitemap 请求成功。
- 至少获得一条合格记录。
- 每条入库记录具有 `canonical_url` 和非空发现标题。
- 样本具备可解析的 `published_at` 或明确记录时间缺失。
- Worker 日志能用中文定位 XML、HTTP、域名和字段错误。
- 写入 RawItem 后现有重复检测和事件管线不受影响。

配置启用与真实验收应放在同一实现里完成，但如果真实网络结果不合格，则保留原状态，只提交抓取能力和逐项外部阻塞证据。

## 事件与证据规则

Sitemap RawItem 的角色是 `discovery`：

- 可以进入去重、聚类和候选事件发现。
- 不得仅凭 Sitemap 条目把事件提升为 `confirmed`。
- 后续确认仍需要官方正文、独立媒体、公告、论文或其他合格证据。
- slug 生成标题需要在 payload 或来源元数据中可识别，防止被误当作正式标题。

## 错误处理和诊断

结构化错误至少区分：

- HTTP 超时或连接失败。
- HTTP 非成功状态。
- 响应超过大小上限。
- XML 无效或不支持的根元素。
- Sitemap Index 暂不支持或子 Sitemap 越界。
- 条目 URL 无效或包含凭据。
- 条目缺少可用标题。
- 日期格式无效。
- 合格条目为零。

单条问题写入 warnings；整个响应不可用或零合格条目时，FetchRun 明确失败或部分失败，并在网页和日志中提供中文原因与下一步动作。

## 测试策略

严格按测试驱动实现：

1. 抓取器单元测试：标准 Sitemap、News Sitemap、slug 标题、日期、无效 XML、超大响应、单条容错和零合格条目。
2. 工厂和安全测试：`AccessKind.SITEMAP` 选择通用抓取器，试用模式明确无凭据，不发送敏感请求头。
3. 服务与仓储测试：多条记录规范化、幂等写入、单条失败不阻塞整批。
4. 目录测试：两个目标共用同一个平台能力，不新增专用实现。
5. 真实验收：通过持久队列和 Worker 分别抓取两个来源，检查 FetchRun、RawItem 字段、中文诊断和网页结论。
6. 回归验证：完整 pytest、ruff、来源校验与真实网页验收。

## 验收标准

- 通用 Sitemap 抓取器不包含 Ben’s Bites 或 TLDR AI 的站点专用分支。
- 两个来源各自单独失败时不会阻塞另一个来源或整批任务。
- 网络行为满足超时、有限重试、大小限制和安全请求头要求。
- 合格 Sitemap 记录能够幂等写入 RawItem。
- Sitemap 记录明确属于发现线索，不能单独确认事件。
- 若两个真实来源均验收成功，则目录 direct 增加 2、catalog_only 减少 2；否则保持未通过目标的原状态并输出可验证原因。

