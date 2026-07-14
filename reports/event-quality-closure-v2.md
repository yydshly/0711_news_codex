# Event Intelligence v2 事件质量验收报告

生成时间：2026-07-14T17:40:11.513364+00:00
Operation 快照时间：2026-07-14T17:11:51.881776+00:00
统计窗口：快照前 72 小时 RawItem（含上下界）

## 输入与处理结论

- 72 小时 RawItem：428
- 已形成 relevance-v2 唯一结论：428
- 进入候选处理：213
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

## 本次 Operation 候选与事件

- 候选簇（cluster-v2）：198
- current：198
- legacy：0
- 状态 confirmed：3
- 状态 emerging：195

## 本次 current 事件六项平均评分

合法 score-v2 快照：198
- AI 相关性：69.2
- 来源覆盖：6.9
- 来源权威性：15.7
- 时效：56.7
- 互动热度：6.6
- 新颖性：99.7

## Worker 与 MiniMax

- 匹配的 event_pipeline Operation：751
- Operation 终态：succeeded
- MiniMax 成功：0
- MiniMax 降级：72
- Operation 模型错误码 error_attribution_unavailable：72

## 剩余问题

- 存在 MiniMax 降级；规则管线已继续完成。
- 本次 Operation 没有 MiniMax 成功记录。
- 旧 Operation 未保存模型错误聚合，无法把并发模型记录归因到本次运行。

> 本报告为数据库只读投影；不触发抓取、事件构建或模型调用，且不输出连接串、凭据、原始错误或带查询参数的 URL。
