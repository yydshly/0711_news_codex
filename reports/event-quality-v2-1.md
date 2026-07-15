# Event Intelligence v2.1 事件质量验收报告

生成时间：2026-07-15T06:02:24.142994+00:00
Operation 完成快照时间：2026-07-15T06:02:07.428671+00:00
统计窗口：Operation 请求窗口末端前 72 小时 RawItem（含上下界）

## 输入与处理结论

- 72 小时 RawItem：482
- 已形成 relevance-v2 唯一结论：482
- 进入候选处理：95
- included：95
- excluded：387
- 规则处理覆盖率：100.0%

### 排除原因

- 其他规则原因（no_event_action）：164
- 其他规则原因（no_ai_signal）：146
- 泛科技且无明确 AI 事实：21
- 仅命中歧义词：16
- 广告、促销或订阅引导：15
- 其他规则原因（ai_entity_without_event_context）：15
- 游戏或娱乐内容：10
- 其他规则原因（event_action_not_ai_focused）：9
- 其他规则原因（technology_entity_without_ai_context）：4

## 新闻价值覆盖

- 有新闻价值：95
- 无新闻动作或价值不足：173
- 新闻价值排除原因 no_event_action：164
- 新闻价值排除原因 event_action_not_ai_focused：9

## 本次 Operation 候选与事件

- 候选簇（cluster-v2）：86
- current：86
- legacy：0
- 热点：0
- 新兴线索：78
- 仅审计：8
- 单成员事件：77
- 多成员事件：9
- 无独立证据根：68
- 一个独立证据根：18
- 两个及以上独立证据根：0
- 状态 confirmed：1
- 状态 emerging：85
- 分类 company：8
- 分类 developer_tool：5
- 分类 product_model：56
- 分类 research：17

## 本次 current 事件六项平均评分

合法 score-v2 快照：86
- AI 相关性：75.3
- 来源覆盖：7.3
- 来源权威性：17.0
- 时效：67.7
- 互动热度：2.1
- 新颖性：100.0

## Worker 与 MiniMax

- 匹配的 event_pipeline Operation：781
- Operation 终态：succeeded
- 规则直接合并：0
- 模型辅助合并：0
- 明确分开：41
- 候选对缓存命中：844
- MiniMax 成功：0
- MiniMax 降级：0
- 输入 token：0
- 输出 token：0

## 剩余问题

- 本次 Operation 没有 MiniMax 成功记录。

> 本报告为数据库只读投影；不触发抓取、事件构建或模型调用，且不输出连接串、凭据、原始错误或带查询参数的 URL。
