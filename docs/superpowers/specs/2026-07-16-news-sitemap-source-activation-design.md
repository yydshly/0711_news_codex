# 官方 News Sitemap 来源启用设计

日期：2026-07-16  
状态：用户已批准设计方向，等待书面设计复核

## 目标

复用现有通用 `SitemapFetcher`，将 Axios Technology、Forbes Innovation、Fortune Technology 和 Semafor Technology 的官方 News Sitemap 从人工目录目标提升为可直接抓取的发现来源。

本阶段不新增站点专用抓取器，不访问文章正文，不绕过付费墙；Sitemap 条目只能作为发现线索，不能单独确认事件。

## 官方路径与已观察结果

受控、无数据库写入的真实探针已得到以下结果：

- Axios：`https://www.axios.com/sitemaps/news.xml`，20 条样本全部具有 News Sitemap 标题、URL 和发布时间。
- Forbes：`https://www.forbes.com/news_sitemap.xml`，20 条样本全部具有 News Sitemap 标题、URL 和发布时间。
- Fortune：`https://fortune.com/feed/googlenews/articles.xml`，20 条样本全部具有 News Sitemap 标题、URL 和发布时间。
- Semafor：`https://www.semafor.com/sitemap-news.xml`，20 条样本全部具有 News Sitemap 标题、URL 和发布时间。

这些入口均由对应站点公开 `robots.txt` 发布。抓取器只请求上述审核入口，不请求 Sitemap 中列出的文章页面。

## 范围

需要更新的主目标：

- `universe-axios-1`
- `universe-forbes-1`
- `universe-fortune-1`
- `universe-semafor-1`

每个目标从：

- `availability: manual_only`
- `coverage_mode: catalog_only`
- `ingestion.enabled: false`

调整为：

- `availability: ready`
- `coverage_mode: direct`
- `ingestion.enabled: true`
- `approved_at: '2026-07-16'`
- `max_items_per_run: 20`

Provider 的 `availability` 和 `auth_mode` 同步调整为 `ready` 与 `none`，但只表示官方公开 Sitemap 能力可用，不表示免费阅读全文。

## 明确不在范围内

- Discord Communities：官方博客 RSS 不能代表 Discord 社区内容，保持人工状态。
- Washington Post：现有公开 RSS 返回零条目；官方新闻 Sitemap 是 gzip 索引路径，当前安全抓取器不展开 Sitemap Index，本阶段保持“已有公开路径待验收”。
- 不开发 Sitemap Index、gzip 索引展开、HTML 抽取或付费墙处理。
- 不修改四个 `AI discovery` 副目标。主目标真实成功后，现有同身份覆盖规则会自动把副目标显示为“已由同一官方目标覆盖”。

## 数据与证据规则

四个来源均使用 News Sitemap 自带字段：

- `news:title` → RawItem `title`
- `<loc>` → RawItem `canonical_url`
- `news:publication_date` → RawItem `published_at`
- Sitemap 元数据 → `raw_payload`

RawItem 的 `summary` 和 `content` 保持为空，不访问文章页面补齐。付费文章只保存公开 Sitemap 中的标题、URL 和发布时间。

这些 RawItem 可以参与去重、聚类和候选事件发现，但不能单独把事件提升为 `confirmed`。事件确认仍需要正文、公告、独立媒体或其他合格证据。

## 网络与安全边界

- 所有网络请求继续使用现有 `HttpPolicy`。
- 保留统一超时、有限重试、每主机并发限制和最大响应体限制。
- 不发送 Cookie、Authorization 或其他认证请求头。
- 不使用登录、验证码、代理规避或浏览器会话。
- 单条无效记录写入结构化 warning，不阻塞同一 Sitemap 的其他记录。
- 一个来源失败不得阻塞其他三个独立操作。
- MiniMax 不参与来源合法性、启用与字段可信度判断。

## 测试驱动与验收

### 目录测试

先把测试改为期望四个主目标：

- Provider 为 `ready + none`；
- Target 为 `ready + direct`；
- 首选协议为 `sitemap`；
- URL 与官方 robots 发布入口完全一致；
- 无凭据、无人工审批；
- ingestion 已批准且单次上限 20；
- research 状态为 `verified`，并明确“发现线索、无正文、不能独立确认”。

测试先失败，再更新 YAML 使其通过。

### 受控探针

使用现有 `SitemapFetcher` 分别读取四个入口，限制 20 条，只输出状态、数量和字段覆盖率，不输出响应正文。

### 真实 Worker 验收

1. 同步审核后的 Provider 和 Target YAML。
2. 为四个目标分别创建独立持久操作。
3. 由当前 main/分支代码 Worker 执行。
4. 分别检查 FetchRun、RawItem 和中文诊断。
5. 验收标题、URL、发布时间完整，正文为空。
6. 验证任一操作失败不会阻塞其余操作。

只有真实 FetchRun 成功的目标才在网页计入“已真实抓取成功”。受控探针成功但 Worker 失败时，保留可修复状态并给出可验证原因。

## 预期目录口径

如果四个目标全部验收成功：

- Target 总数：187，不变。
- direct：73 → 77。
- indirect：57，不变。
- catalog_only：53。
- ingestion enabled：83 → 87。
- 四个对应副目标从“重复目录项”转为现有“已由同一官方目标覆盖”。

实际成功数只根据真实数据库 FetchRun 更新，不在设计中预先写死。

## 完成条件

- 四个主目标均通过真实 Worker FetchRun，或分别留下可验证的外部阻塞。
- 成功目标具有 RawItem 标题、URL、发布时间，且无正文。
- 不新增站点专用代码分支。
- Discord 和 Washington Post 状态保持正确。
- 完整 pytest、Ruff、来源/Provider 校验和真实网页验收通过。
- 不修改、暂存或提交用户报告与 `.env`。

