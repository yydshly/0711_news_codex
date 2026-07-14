# Event Intelligence v2 事件质量验收报告

生成时间：2026-07-14T17:17:20.748899+00:00
统计窗口：最近 72 小时 RawItem（含上界，不读取未来数据）

## 输入与处理结论

- 72 小时 RawItem：428
- 已形成 relevance-v2 唯一结论：428
- included：213
- excluded：215
- 规则处理覆盖率：100.0%

### 排除原因

- 其他规则原因（no_ai_signal）：149
- 泛科技且无明确 AI 事实：22
- 仅命中歧义词：17
- 其他规则原因（ai_entity_without_event_context）：15
- 广告、促销或订阅引导：11
- 游戏或娱乐内容：10
- 其他规则原因（technology_entity_without_ai_context）：4

## 候选与事件

- 候选簇（cluster-v2）：199
- current：199
- legacy：74
- 状态 confirmed：4
- 状态 emerging：195

## current 事件六项平均评分

评分快照：199
- AI 相关性：69.3
- 来源覆盖：7.0
- 来源权威性：16.1
- 时效：56.7
- 互动热度：6.5
- 新颖性：99.7

## Worker 与 MiniMax

- 最近 72 小时 event_pipeline Operation：751
- Operation 终态：succeeded
- MiniMax 成功：0
- MiniMax 降级：72
- 失败尝试错误码 invalid_response：144

## 剩余问题

- 存在 MiniMax 降级；规则管线已继续完成。
- 当前窗口没有 MiniMax 成功记录。

> 本报告为数据库只读投影；不触发抓取、事件构建或模型调用，且不输出连接串、凭据、原始错误或带查询参数的 URL。
