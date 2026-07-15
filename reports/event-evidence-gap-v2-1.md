# Event Intelligence v2.1 来源归因与证据缺口报告

生成日期：2026-07-15

## 本轮目标

本轮没有增加摘要、推荐或推送功能，只收口两个问题：

1. 聚合源能否保留原始发布者和原始报道身份；
2. 普通科技标题是否会因摘要偶然出现 AI 词而进入事件流。

## 已完成

### Techmeme 原始报道解析

- 新增 Techmeme 专用 RSS 抓取器，不再把聚合页当作报道正文身份。
- 从 Techmeme RSS 摘要中的首个外部 HTTPS 链接提取原始报道 URL。
- 从标题归因后缀提取媒体名称，并保留 Techmeme 页面作为发现入口。
- 聚合内容继续只承担发现和上下文角色，不会被升级为独立事实证据。
- 当前数据库中已有 20 条 Techmeme 条目解析到原始媒体文章，涉及 Reuters、Financial Times、New York Times、Wall Street Journal、Axios、TechCrunch、Wired、CNBC 等媒体。

### Google News 发布者归因

- 当 Google News 跳转无法解析到文章 URL 时，保留 RSS `source` 提供的媒体名称和媒体主页。
- 这类条目仍标记为 `unresolved`，Canonical URL 仍是 Google News 发现地址，不会伪装成已获得原文。
- 本轮刷新目标中，数据库已有 77 条 Google News/间接入口条目带有媒体归因信息。

### 新闻价值精度

- 新增 `newsworthiness-v2`，与旧规则审计记录明确分离。
- 普通媒体和社交内容不能再把摘要中的 AI 词与标题中的普通价格、发布等动作拼接成 AI 新闻。
- 研究来源允许标题与摘要共同构成研究事件，避免误伤 arXiv 论文。
- AI 原生公司标题支持定价事件，例如 DeepSeek 降价。
- 已覆盖 SpaceX 股价误报、普通科技报道误报、研究论文保留和 AI 公司定价四类回归场景。

## 真实运行证据

### 定向抓取 Operations 770–777

8 个来源任务全部成功：

| Operation | 来源 | 收到 | 新增 | 更新 | 未变化 | 失败 |
|---:|---|---:|---:|---:|---:|---:|
| 770 | techmeme-feed | 5 | 5 | 0 | 0 | 0 |
| 771 | google-news-ai | 5 | 5 | 0 | 0 | 0 |
| 772 | google-news-business | 20 | 19 | 0 | 1 | 0 |
| 773 | google-news-chips-compute | 0 | 0 | 0 | 0 | 0 |
| 774 | google-news-policy-safety | 20 | 19 | 1 | 0 | 0 |
| 775 | google-news-research | 20 | 15 | 0 | 5 | 0 |
| 776 | universe-techmeme-2 | 12 | 7 | 0 | 5 | 0 |
| 777 | universe-techmeme-1 | 15 | 15 | 0 | 0 | 0 |

### 最终事件 Operation 781

- 72 小时窗口 RawItem：482
- 有新闻价值：95
- 事件候选：86
- 单成员事件：77
- 多成员事件：9
- 无独立证据根：68
- 一个独立证据根：18
- 两个及以上独立证据根：0
- 热点：0
- 新兴线索：78
- 仅审计：8
- `event_action_not_ai_focused` 排除：9

相较于同一轮抓取后、旧规则执行的 Operation 778：

- 有新闻价值内容由 82 增至 95；
- 有一个独立证据根的事件由 8 增至 18；
- 标题不聚焦 AI 的排除由 21 降至 9，主要恢复了研究内容和 DeepSeek 定价新闻；
- SpaceX 股价和普通科技报道等已知误报仍保持排除。

## 当前结论

来源归因能力已经改善，但 v2.1 仍未达到“热点验收”终点：

- 20 条已解析 Techmeme 原文目前只与另一个 Techmeme 目标重复，没有与直连专业媒体 RSS 命中同一文章；因此不能构造第二个独立证据根。
- Google News 能确认媒体身份，但多数条目仍无法仅靠 RSS 获得最终文章 URL，只能作为发现线索。
- 当前 86 个事件中没有两个及以上独立证据根，所以热点层仍为空。
- MiniMax 不负责弥补证据缺失，也不参与来源合规或启用决策。

### 网页 Operation 快照口径已收口

- 首页、`/events`、`/emerging` 和带 `operation/version` 参数的事件详情现在默认使用同一个最新完整 Operation 快照。
- 真实数据库验收选中 Operation 781：不可变引用 86 个，网页投影 86 个，热点 0、新兴信号 78、仅审计 8，与质量报告完全一致。
- 全局 current 目录共有 225 条记录，已作为 `/events?scope=current_catalog` 的独立排查入口，不再冒充最新运行结果。
- 59 个早期不可变版本没有 `publication` 字段；网页沿用报告层的保守兼容规则，将其显示为“新兴信号”，不读取可变 `EventRecord` 补值。
- 较新的损坏或不完整 Operation 会被跳过；无合法快照时网页显示中文阻塞说明，不静默回退。
- 固定详情页已抽查 5 个事件，均显示 Operation 781 上下文、准确版本证据，并隐藏可能误操作当前事件的受控按钮。
- 本轮没有修改、删除或自动退役任何历史事件，也没有触发抓取或 MiniMax 调用。

## 下一步

下一阶段只做“证据覆盖波次”，不重新设计架构：

1. 刷新 Reuters、TechCrunch、The Verge、Wired、Ars Technica、Guardian、BBC、CNBC、VentureBeat、MIT Technology Review 等已审核直连媒体入口；
2. 以 Techmeme/Google News 的媒体名称和原始 URL 为线索，检查直连媒体是否存在相同报道；
3. 对同一事件形成至少两个独立事实根后，再验收热点分层和 Top 20 人工审阅；
4. 仍未获得第二证据根的内容继续显示为“新兴线索”或“仅审计”，不提高事实确定性。

本报告不包含 API Key、数据库连接串、Cookie、登录态或带敏感查询参数的 URL。
