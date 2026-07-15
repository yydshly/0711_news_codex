# Event Intelligence v2.1 事件质量验收报告

生成时间：2026-07-15T05:27:09.747363+00:00
Operation 完成快照时间：2026-07-15T05:26:45.832244+00:00
统计窗口：Operation 请求窗口末端前 72 小时 RawItem（含上下界）

## 输入与处理结论

- 72 小时 RawItem：407
- 已形成 relevance-v2 唯一结论：407
- 进入候选处理：76
- included：76
- excluded：331
- 规则处理覆盖率：100.0%

### 排除原因

- 其他规则原因（no_ai_signal）：137
- 其他规则原因（no_event_action）：130
- 泛科技且无明确 AI 事实：21
- 仅命中歧义词：17
- 其他规则原因（ai_entity_without_event_context）：14
- 游戏或娱乐内容：10
- 广告、促销或订阅引导：9
- 其他规则原因（technology_entity_without_ai_context）：4

## 新闻价值覆盖

- 有新闻价值：76
- 无新闻动作或价值不足：130
- 新闻价值排除原因 no_event_action：130

## 本次 Operation 候选与事件

- 候选簇（cluster-v2）：67
- current：67
- legacy：0
- 热点：0
- 新兴线索：67
- 仅审计：0
- 单成员事件：58
- 多成员事件：9
- 无独立证据根：46
- 一个独立证据根：20
- 两个及以上独立证据根：1
- 状态 confirmed：2
- 状态 emerging：65
- 分类 company：4
- 分类 developer_tool：4
- 分类 product_model：45
- 分类 research：14

## 本次 current 事件六项平均评分

合法 score-v2 快照：67
- AI 相关性：75.8
- 来源覆盖：11.5
- 来源权威性：25.7
- 时效：59.6
- 互动热度：3.3
- 新颖性：99.3

## Worker 与 MiniMax

- 匹配的 event_pipeline Operation：767
- Operation 终态：succeeded
- 规则直接合并：9
- 模型辅助合并：0
- 明确分开：251
- 候选对缓存命中：0
- MiniMax 成功：0
- MiniMax 降级：0
- 输入 token：0
- 输出 token：0
- 候选对模型错误码 no_api_key：2

## 剩余问题

- 本次 Operation 没有 MiniMax 成功记录。

## 补充真实验收

- 事件管线 Operation 767：一次成功完成，407 条 RawItem 的相关性与新闻价值结论覆盖率为 100%。
- 离线人工标注回归集：50 组正例、50 组反例；正例直接合并召回率 100%，反例误合并 0。
- MiniMax 事件增强 Operation 769：成功；高价值研究线索事件 100 生成中文增强，记录 350 输入 token、885 输出 token。
- 网页验收：`/`、`/events?tier=signal` 与 `/events/100` 可显示中文分层、排名、展示依据和模型运行摘要。
- 本轮热点人工抽检：无法执行。当前 67 个事件全部为 `signal`，主要原因是 46 个没有独立证据根，只有 1 个达到两个及以上独立证据根；系统没有为了通过验收而降低热点门槛。
- 验收中发现并修复：手动“补充摘要”曾把事件排名重置为 0；修复后会保留现有分层和排名，事件 100 已通过追加版本恢复，历史错误版本未删除。

> 本报告为数据库只读投影；不触发抓取、事件构建或模型调用，且不输出连接串、凭据、原始错误或带查询参数的 URL。
