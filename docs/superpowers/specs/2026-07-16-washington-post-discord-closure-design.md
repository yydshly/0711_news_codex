# Washington Post 与 Discord 最终收口设计

日期：2026-07-16  
状态：用户已批准设计方向，等待书面设计复核

## 目标

完成当前来源可用性主线最后两个人工来源的明确结论：

- Washington Post Technology 使用官方 News Sitemap 作为公开发现路径，并通过现有通用 `SitemapFetcher` 做真实 Worker 验收。
- Discord Communities 保持 `manual_only + catalog_only`，补充可验证的中文原因和未来解锁条件，不把 Discord 公司博客误作社区内容。

本阶段不新增抓取器、不读取文章正文、不绕过付费墙、不创建 Discord Bot，也不删除任何 Target。

## Washington Post 官方路径

首选入口：

`https://www.washingtonpost.com/sitemaps/news-sitemap.xml.gz`

该入口由 Washington Post 官方 `robots.txt` 发布。虽然 URL 以 `.gz` 结尾，但服务器使用标准 HTTP 内容编码传输，现有 `httpx` 客户端会在受限响应读取过程中正常解码，交给 `SitemapFetcher` 的内容是标准 `urlset`，不需要实现 gzip 文件处理或 Sitemap Index 展开。

受控、无数据库写入的真实样本结果：

- HTTP 200；
- 20 条合格记录；
- 标题 20/20；
- URL 20/20；
- 发布时间 20/20；
- 20 条均为 News Sitemap 正式标题；
- warning 0；
- 正文 0。

旧 Technology RSS `https://feeds.washingtonpost.com/rss/business/technology` 继续保留为第二优先级备用路径。它当前仍返回 HTTP 200、0 条记录，不能作为成功依据。

## Washington Post 状态变化

Provider 调整为：

- `availability: ready`
- `auth_mode: none`
- 证据包含官方 robots、News Sitemap、RSS 列表和条款页。

主目标 `universe-washington-post-1` 调整为：

- `availability: ready`
- `coverage_mode: direct`
- 首选 `sitemap` News Sitemap；
- 第二优先级保留空 RSS；
- 第三优先级保留需要人工审批的 Technology HTML；
- `ingestion.enabled: true`
- `approved_at: '2026-07-16'`
- `max_items_per_run: 20`
- `research.status: verified`

News Sitemap 记录只作为发现线索。系统只保存公开标题、URL、发布时间和 Sitemap 元数据；`summary`、`content` 保持为空，不请求文章页面，也不绕过订阅或付费限制。

## Discord 最终人工边界

Discord 官方博客 RSS `https://discord.com/blog/rss.xml` 有公开内容，但它代表 Discord 公司新闻，不是 Discord Communities 社区消息，因此不能作为 `universe-discord-1` 的替代抓取路径。

读取具体 Discord 社区内容需要：

- 用户明确指定服务器与频道 Target；
- 创建并授权官方 Discord 应用/Bot；
- Bot 被服务器管理员加入目标服务器；
- 对目标频道具有查看与历史消息权限；
- 若读取消息正文，满足 Discord Gateway intents 与相关审批要求；
- 遵守服务器自身规则、成员隐私和内容使用边界。

当前 Target 只有泛化平台首页 `https://discord.com/`，没有具体服务器、频道或授权主体，因此保持：

- `availability: manual_only`
- `coverage_mode: catalog_only`
- `ingestion.enabled: false`
- `research.status: needs_research`

中文结论明确说明：当前只能人工查看；公司博客 RSS 不等于社区内容；未来只有用户指定具体服务器/频道并取得管理员授权后，才可为平台级 Discord API 能力另行设计。不得使用用户 Cookie、登录会话、非官方客户端、自助账号或绕过权限。

Discord Provider 保持 `manual_only`，并将 unlock requirements 更新为具体服务器、频道、Bot/OAuth 和管理员授权条件。

## 数据与证据规则

Washington Post Sitemap RawItem：

- `news:title` → `title`
- `<loc>` → `canonical_url`
- `news:publication_date` → `published_at`
- 不保存正文；不自动访问文章 URL。

这些记录可以参与去重、聚类和候选事件发现，但不得单独将事件提升为 `confirmed`。确认仍需要正文、公告、其他媒体或合格证据。

Discord 不产生 RawItem，不创建 FetchRun，不进入 Worker 队列。

## 网络与安全边界

- Washington Post 仅请求审核后的 News Sitemap URL。
- 复用现有 `HttpPolicy` 的超时、有限重试、并发限制和响应大小上限。
- 不发送 Cookie、Authorization 或登录状态。
- 不提高全局响应大小上限。
- 不展开 Washington Post 根 Sitemap Index。
- 不访问 Sitemap 中的文章正文。
- 不创建或授权 Discord Bot，不访问 Discord Gateway，不读取服务器消息。
- MiniMax 不参与来源合法性、启用或证据可信度判断。

## 测试与真实验收

### 测试驱动

先写失败测试，要求：

- Washington Post Provider 为 `ready + none`；
- 主 Target 为 `ready + direct + enabled`；
- 首选访问方式为准确的官方 News Sitemap；
- RSS 为第二优先级；
- 单次上限 20；
- research 明确发现线索与无正文边界；
- Discord 仍为 `manual_only + catalog_only + disabled`；
- Discord research 与 unlock requirements 包含具体 Target 和管理员授权要求。

测试失败后再更新 YAML。

### 真实 Worker 验收

1. 同步 Washington Post Provider 和 Target。
2. 使用当前分支代码、显式来源根目录的 Worker。
3. 只为 Washington Post 创建一条独立操作。
4. 检查 FetchRun 成功、RawItem 标题/URL/时间完整、正文为 0。
5. 检查副目标 `universe-washington-post-2` 自动显示“已由同一官方目标覆盖”。
6. Discord 不排队、不写入。

## 预期口径

若 Washington Post 真实 Worker 验收成功：

- Target 总数：187，不变；
- direct：77 → 78；
- indirect：57，不变；
- catalog_only：53 → 52；
- ingestion enabled：87 → 88；
- 实际成功：43 → 44；
- Discord 主目标继续显示“只能人工查看”；
- Discord 副目标继续显示“重复目录项”；
- Washington Post 副目标显示“已由同一官方目标覆盖”。

## 完成条件

- Washington Post 通过真实 Worker FetchRun，或保留逐项可验证的外部阻塞。
- 成功样本标题、URL、时间完整且正文为空。
- Discord 的人工状态和未来解锁条件在中文网页中可理解、可执行。
- 没有新增抓取器、Bot、Cookie、登录或付费墙行为。
- 完整 pytest、Ruff、67 Provider、187 Target 校验和真实网页验收通过。
- 不修改、暂存或提交用户报告与 `.env`。

