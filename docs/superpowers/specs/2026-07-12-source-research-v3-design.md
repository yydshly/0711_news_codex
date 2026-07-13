# News Codex 来源研究与接入设计 v3

## 1. 背景

News Codex 已经具备 Provider/Target 目录、来源探测、RawItem、Worker、事件聚类和中文网页，但当前来源目录仍存在两个问题：

1. 一部分 Target 只是平台占位项，例如 `universe-*-1`、`universe-*-2`，并不代表已经确认的真实账号、频道、栏目或查询。
2. 当前流程过早按 RSS、API 或 HTML 分类，容易把“没有 API Key”“没有官方 API”和“完全无法获取”混为一谈。

v3 的设计中心改为“真实来源研究”。先确定需要哪些来源、希望获得哪些信息，再逐项研究所有候选获取方式，最后选择首选、备用和禁用方式。抓取器开发必须晚于来源研究结论。

## 2. 目标

第一阶段建立可审核、可复查、中文可读的来源研究体系，回答：

- 这个来源具体是谁、哪个频道、哪个栏目或哪个查询？
- 为什么 News Codex 需要它？
- 希望从它获得哪些信息和信号？
- 有哪些官方与非官方获取方式？
- 每种方式能提供哪些字段，缺少哪些字段？
- 是否需要 API Key、OAuth、审批、付费、登录或 Cookie？
- 获取频率、延迟、配额、稳定性和维护成本如何？
- robots、服务条款、内容权利和再利用风险如何？
- 哪种方式是首选、补充、备用、人工模式或禁止方式？
- 实际样本探测是否支持上述结论？

来源数量不设人为上限。当前 67 个 Provider 和 166 个 Target 只是审计起点，不是完成指标。

## 3. 非目标

本阶段不直接完成以下工作：

- 不先开发通用 HTML 抓取器。
- 不因为存在第三方库就自动接入生产抓取。
- 不使用登录 Cookie、浏览器会话、验证码破解、代理轮换或反爬绕过。
- 不抓取或保存视频、音频等大体积媒体文件。
- 不生成日报、推荐、推送或后台定时任务。
- 不让 MiniMax 决定来源合规性、启用状态或最佳获取方式。

## 4. 核心对象

### 4.1 Provider

Provider 表示平台或发布系统，例如 YouTube、GitHub、Reuters、Substack、Mastodon。它保存平台级能力、认证、计费、条款和通用限制。

### 4.2 Target

Target 表示真实的信息目标，例如：

- YouTube 的 No Priors 频道；
- Reuters 的 AI 栏目；
- GitHub 的 `openai/openai-python` Releases；
- Reddit 的 `r/LocalLLaMA`；
- Google News 的特定 AI 查询；
- 某公司的投资者关系公告页。

只有完成官方身份确认的目标才可进入正式研究目录。平台首页、无法确认身份的名称匹配和自动生成占位项不能冒充真实 Target。

### 4.3 WantedInformation

每个 Target 必须先声明希望获得的信息，而不是先声明抓取技术。字段按来源性质组合：

- 通用：标题、Canonical URL、发布时间、更新时间、作者、语言、摘要、正文。
- 社交：帖子正文、回复关系、转发、点赞、评论、删除状态、作者身份。
- 视频：频道、视频 ID、描述、时长、观看量、点赞量、评论量、字幕语言、文字稿可用性。
- 研究：论文 ID、作者、摘要、分类、版本、PDF、代码与数据集链接。
- 开发：仓库、Release、Tag、提交时间、依赖、下载量、Stars、维护状态。
- 商业监管：公司、文件类型、申报时间、融资、并购、投资者关系附件。

### 4.4 AcquisitionCandidate

每种候选获取方式独立记录：

```yaml
kind: atom
implementation: youtube-channel-feed
officiality: official
authentication: none
cost: free
fields:
  - video_id
  - title
  - published_at
  - channel
limitations:
  - no_engagement
  - no_transcript
stability: documented
terms_status: reviewed
sample_status: succeeded
```

固定维度包括：

- `kind`：`rss`、`atom`、`websub`、`public_api`、`api_key_api`、`oauth_api`、`sitemap`、`html`、`json_ld`、`embedded_json`、`library`、`aggregator`、`manual`。
- `officiality`：`official`、`documented_public`、`unofficial_library`、`third_party_service`。
- `authentication`：`none`、`api_key`、`oauth`、`approval`、`payment`、`login_cookie`。
- `role`：`discovery`、`metadata`、`content`、`engagement`、`transcript`、`evidence`。
- `decision`：`primary`、`supplement`、`fallback`、`manual_only`、`rejected`。

`login_cookie` 候选只能记录为 `rejected`，不能进入 Worker。

## 5. 研究流程

### 步骤 1：Provider 审计

逐个审查当前 67 个 Provider：平台身份、官方文档、服务条款、认证、计费、公开数据能力和适用地区。允许新增、合并或删除 Provider。

### 步骤 2：Target 清理与扩展

逐项审计当前 166 个 Target：

- 确认真实身份；
- 删除或降级占位目标；
- 补充真实频道、账号、栏目、社区、Newsletter 和查询；
- 记录语言、主题、国家/地区、来源性质和用途。

### 步骤 3：声明所需信息

每个 Target 明确 News Codex 想获取的字段和用途。没有明确用途的 Target 不进入方法研究。

### 步骤 4：穷举候选方式

研究官方主页、`<link rel="alternate">`、robots、Sitemap、官方 API 文档、平台开发者文档、页面 JSON-LD、公开 HTML、开源库和合规聚合入口。

候选方式不能只写名称，必须记录实现、字段、凭据、配额、成本、风险、证据链接和更新时间。

### 步骤 5：样本探测

每种可行方式最多探测五条样本，记录：

- HTTP/TLS、最终 URL、内容类型和响应大小；
- 字段完整率、最新发布时间和重复率；
- 分页、游标、ETag、Last-Modified、限流与配额；
- 结构指纹和动态渲染依赖；
- 是否出现登录墙、Cookie、验证码、地区限制或付费墙；
- 样本是否真的是所声明 Target 的内容。

能力探测和内容探测必须分开。确认“存在某个 API”不能冒充已经获取到目标内容。

### 步骤 6：选择组合方案

每个 Target 独立选择组合方式，不设全局固定优先级：

- `primary` 负责稳定发现；
- `supplement` 补充主方式缺失的字段；
- `fallback` 在主方式异常时降级；
- `manual_only` 只供人工查看；
- `rejected` 记录明确禁用原因。

### 步骤 7：人工审核

只有来源身份、用途、方法、样本、字段、风险和结论全部完成，Target 才能进入实现计划。程序不得自行把研究结论改成启用状态。

## 6. YouTube 完整样板

YouTube 作为第一份完整研究样板，不把“是否有 Key”当作唯一判断。

### 6.1 固定频道发现

官方 Atom/WebSub Feed：

- 无 API Key；
- 提供视频 ID、频道 ID、标题、链接、发布时间和更新时间；
- 适合持续监控已经确认的频道；
- 不提供完整互动量和文字稿。

官方依据：[YouTube Push Notifications / Atom Feed](https://developers.google.com/youtube/v3/guides/push_notifications)。

### 6.2 元数据、搜索和互动量

YouTube Data API v3：

- 公开数据读取使用 API Key；私有用户数据与写操作才需要 OAuth；
- 可获取视频描述、频道信息、观看量、点赞量和评论量；
- 关键词搜索、频道枚举和互动量补全受配额约束；
- 固定频道应优先用上传列表或 Feed，避免高成本全局搜索。

官方依据：[YouTube Data API Overview](https://developers.google.com/youtube/v3/getting-started)。

### 6.3 字幕与文字稿

`youtube-transcript-api`：

- 无 API Key，可读取公开视频可用的人工或自动字幕；
- 属于非官方库，依赖平台内部接口；
- 可能遇到无字幕、IP 限制、接口变化或平台封锁；
- 只作为重点视频的可选内容补充，不承担频道发现，也不能阻塞事件发布。

项目依据：[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)。

### 6.4 元数据诊断备用

`yt-dlp`：

- 可提取丰富的平台元数据，维护活跃；
- 属于非官方解析器，YouTube 适配变化频繁；
- News Codex 不使用其下载视频，不提供 Cookie，不绕过登录或地区限制；
- 初始仅列为人工诊断或受控实验候选，不作为定时生产主路径。

项目依据：[yt-dlp](https://github.com/yt-dlp/yt-dlp)。

### 6.5 推荐组合

```text
固定频道发现：官方 Atom Feed
元数据补全：YouTube Data API（有 Key 时）
关键词发现：YouTube Data API（有 Key 且有配额时）
重点视频文字稿：youtube-transcript-api（可选、非官方、可降级）
人工诊断：yt-dlp（不下载、不使用 Cookie）
```

## 7. HTML 方法边界

HTML 是逐来源候选方式，不是全局启用开关。

允许研究的 HTML 类型：

- 公司新闻、博客、更新日志和投资者关系页面；
- 专业媒体公开文章与公开栏目；
- Newsletter 公开归档；
- 研究机构、会议和项目公开页面。

每个 HTML Target 分开研究：

1. 列表页、Sitemap 或聚合入口负责发现 URL；
2. 详情页使用 JSON-LD、OpenGraph、语义化 `article` 或经审核的站点选择器获取字段；
3. 记录 Canonical URL、结构指纹、正文完整率和字段漂移；
4. 遵循 robots 规则，同时单独审核服务条款；robots 不是内容使用授权；
5. 无登录、无 Cookie、无验证码、无反爬绕过；
6. 单站点低并发、有限响应大小、条件请求和明确 User-Agent；
7. 页面结构变化时自动降级，不能把错误页或空正文写成新闻。

社交平台的登录态 HTML 默认 `rejected`。公开嵌入或公开静态页可以作为独立候选研究，但不能因为浏览器能打开就自动批准抓取。

## 8. 第三方库研究标准

第三方库与官方 API 平行记录，但不能混称为“公开 API”。研究时必须记录：

- 仓库、许可证、维护者和最新版本；
- 最近发布与平台适配频率；
- 是否调用官方接口、公开 Feed、内部接口或解析网页；
- 是否要求 Cookie、代理、浏览器模拟或验证码；
- 能获取的字段与失败模式；
- 平台条款、版权与再利用风险；
- 运行成本、依赖大小、并发与超时；
- 无该库时的降级方式。

任何要求登录 Cookie、规避访问限制或批量下载媒体的默认方案均被拒绝。

## 9. 当前来源目录的处理

v3 不把当前 YAML 全部删除重建，而是保留审计轨迹：

- `verified`：真实身份与方法证据完整；
- `needs_research`：真实目标存在，但方法或字段未研究完；
- `placeholder`：平台占位，不代表真实内容目标；
- `duplicate`：与其他 Target 重复；
- `retired`：无价值、失效或不符合项目范围。

占位项不得计入“真实来源数量”“可抓取覆盖”或“已验证覆盖”。

## 10. 网页呈现

来源能力页面需要从“平台是否登记”升级为“研究结论是否完成”，展示：

- 真实 Target 与占位项数量；
- 每个 Target 想获取的信息；
- 候选方式对比；
- 首选、补充、备用和禁用方式；
- 实际样本和字段完整率；
- 凭据、审批、付费与条款阻塞；
- 最近审核时间和证据链接；
- 尚未研究或需要用户决策的内容。

网页不得把第三方库标成官方 API，也不得把能力目录标成已经抓取的数据。

## 11. 实施顺序

1. 扩展研究 Schema，使 Target 能声明所需信息和多种候选方式。
2. 为现有 Provider/Target 生成审计报告，识别真实、占位、重复和缺失项。
3. 完成 YouTube 样板，包括 Atom、Data API、字幕库和诊断备用的样本探测。
4. 按来源类别研究媒体、公司官网、社区、研究、开发、Newsletter、播客、商业监管和受限社交平台。
5. 形成逐来源推荐方式矩阵并人工审核。
6. 依据矩阵编写独立抓取器实施计划；优先复用通用协议，HTML 使用站点级配置与审批。
7. 最后更新中文网页，让用户能看到来源研究进度、结论和缺口。

## 12. 验收条件

- 当前 67 个 Provider 全部完成平台级复核，允许合并、新增或退役。
- 当前 166 个 Target 全部得到 `verified`、`needs_research`、`placeholder`、`duplicate` 或 `retired` 结论。
- 所有 `verified` Target 都有明确用途、所需信息、首选方式、备用方式、字段清单、样本证据和风险结论。
- YouTube 样板完整覆盖官方 Feed、官方 API、无 Key 字幕库和人工诊断候选。
- HTML、第三方库、API Key、OAuth、审批和付费在数据结构与网页中明确区分。
- 占位项不计入真实覆盖或可抓取覆盖。
- 没有凭据或第三方库时，来源健康、目录报告和事件规则流程仍可运行。
- 所有研究说明、计划、报告和用户页面默认使用中文。
