# News Codex v1.5 高价值真实热点波次最终验收报告

## 结论

v1.5 的工程能力已完成收口并通过验收：来源冻结、受控入队、并发 Worker、真实抓取、RawItem 幂等、事件快照、中文页面、MiniMax 规则降级、日志诊断和安全边界均可运行。

产品数据效果为“有条件通过”：最新波次能够产出 32 个真实早期信号和 7 天趋势，但当前没有事件达到严格的“官方一手或独立专业媒体证据”确认门槛。因此下一阶段应集中补足专业媒体与一手证据的交叉确认能力，不再重做来源注册表、Worker 或页面架构。

## 当前目录与波次范围

- Provider：67 个，严格 YAML 校验通过。
- Source/Target：187 个，严格 YAML 校验通过。
- v1.5 高价值 Profile：35 个固定目标。
- 最新真实波次 `#963`：24 个可抓取，11 个明确阻塞。
- 浏览器入口：`http://127.0.0.1:8766/`。

## 连续三轮稳定性证据

| Operation | MiniMax | 耗时 | 成功/阻塞 | Fetch 结果 | received | inserted | updated | unchanged | item failed | 事件快照 |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| #960 | 正常配置 | 20.3 秒 | 23 / 12 | 19 succeeded，4 no_change | 308 | 90 | 2 | 216 | 0 | 29 |
| #961 | 完全关闭 | 19.0 秒 | 23 / 12 | 19 succeeded，4 no_change | 309 | 101 | 0 | 208 | 0 | 29 |
| #962 | 正常配置 | 17.5 秒 | 23 / 12 | 18 succeeded，5 no_change | 293 | 90 | 0 | 203 | 0 | 29 |

三轮均只有一个 Worker attempt，完成度均为 35/35，没有重试、卡死或条目级失败。`partial` 是因为冻结清单内包含受限成员，并非 Worker 异常。

## YouTube 凭据与真实覆盖修复

验收期间发现两个实际缺陷：

1. 波次计划器对 `requires_credentials` 来源无条件阻塞，即使 `YOUTUBE_API_KEY` 已配置也无法解锁。
2. YouTube 探测器只读取频道对象，却用视频字段计算完整度，导致真实 API 响应被错误标记为 0%。

修复后，探测器按“频道 → uploads 播放列表 → 最近视频样本”执行，且不记录 Key。真实结果：

- OpenAI YouTube：5 个样本、字段完整率 100%，探测成功。
- Anthropic YouTube：5 个样本、字段完整率 83%，保持降级。
- Google DeepMind YouTube：5 个样本、字段完整率 77%，保持降级。
- Hugging Face YouTube：5 个样本、字段完整率 83%，保持降级。

最终回归 Operation `#963`：

- 24 succeeded，11 blocked，35/35 完成，1 个 attempt。
- 21 个 Fetch succeeded，3 个 no_change。
- 379 received，128 inserted，1 updated，250 unchanged，0 item failed。
- OpenAI YouTube 使用官方 REST API 成功生成 FetchRun `#983`。
- 32 个事件快照，32 个唯一 canonical event key。

其余 3 个 YouTube 频道能够访问官方 API，但没有越过 90% 字段完整率门槛，未伪装为成功。

## 幂等与并发可靠性

- 最新 24 个直接来源累计 1861 条 RawItem。
- Canonical URL 唯一数：1861。
- external_id 唯一数：1861。
- 没有来源出现 RawItem Canonical URL 或 external_id 重复。
- 最新波次 32 个事件快照对应 32 个唯一 canonical event key。
- 修复前 PostgreSQL 日志最后一次死锁发生在 `2026-07-15 19:58:34 PDT`；修复后的真实波次未出现新死锁。

死锁根因是锁顺序相反：成员完成事务按外键顺序锁定 `operation_attempts` 再锁定 `operation_runs`，续租事务原先反向锁定。现在续租与结束 attempt 均统一为“attempt → operation”，并增加真实 PostgreSQL 并发回归测试。

## MiniMax 降级验收

Operation `#961` 在不提供 `MINIMAX_API_KEY` 的独立 Worker 进程中执行：

- 23 个可抓取成员全部成功，12 个受限成员明确阻塞。
- 29 个事件版本全部生成。
- 29 个事件均标记为 `rule_fallback`。
- MiniMax 不可用没有阻断抓取、事件发布或网页读取。

当前波次事件均为低证据等级早期信号，没有达到模型增强调用门槛；因此 `model_degraded=false` 表示“没有失败的模型调用”，规则来源仍由事件版本中的 `rule_fallback` 明确展示。

## 浏览器验收

已在本地浏览器验证：

- `/`：读取完整 Operation `#962` 快照，展示 29 个新兴线索、早期信号和 7 天趋势。
- `/events`：只展示最新完整运行事件，并携带固定 operation/version 链接。
- `/events/407?operation=962&version=1`：展示固定快照、热度拆解、来源角色、缺失确认条件、证据时间线和模型运行摘要。
- `/events/274`：历史已确认事件能够展示中文摘要、确认依据、独立证据根和模型摘要。
- `/operations/962`：展示 `partial`、35/35、单次 attempt 和运行事件。
- `/system`：展示 Worker、MiniMax、凭据配置布尔值和脱敏错误分类。
- 浏览器控制台错误/警告：0。

截图证据保存在本机忽略目录：`.local/acceptance/home-962.png`。

## 当前 11 个阻塞目标

- 探测未达成功门槛：8 个。
  - Anthropic Bluesky、GDELT AI。
  - Anthropic、Google DeepMind、Hugging Face YouTube（可访问，但字段完整率不足 90%）。
  - 3 个 Reddit 社区（尚未配置 OAuth 凭据，或最新探测未成功）。
- 需要人工审批：Anthropic Newsroom HTML，1 个。
- 间接发现入口：Reuters、AP，2 个。

阻塞成员不会发起内容请求；网页、CLI、报告均保留具体阻塞原因。

## 自动化门禁

- `uv run pytest -q --maxfail=1`：通过。
- `uv run ruff check .`：通过。
- `newsradar providers validate`：67 个 Provider 通过。
- `newsradar sources validate`：187 个来源通过。
- `newsradar waves validate`：35 个 Profile 目标通过。
- Alembic：本地 PostgreSQL 与项目均为 `20260716_0022 (head)`。
- v1.5 真实 PostgreSQL acceptance：3 项全部通过。
- `git diff --check`：通过。

## 未完成的产品价值与下一阶段

最新 Operation `#963` 的 32 个事件全部是 `emerging`，没有当前 `confirmed` 事件。这说明系统已经能够真实发现热点，但专业媒体/一手证据的交叉聚合仍不足。

下一阶段只做“证据确认覆盖 v1”，不扩展新页面或新事件表：

1. 优先处理现有 11 个阻塞目标，不降低安全与字段质量门槛。
2. 为 Reuters、AP 等间接入口保存可核验原始 Publisher/Canonical URL，使媒体指针可以回到原文证据。
3. 增加少量高价值专业媒体 RSS/公开入口，并验证独立证据根归并。
4. 对 32 个早期信号抽查至多 20 个，确认哪些缺少第二媒体、哪些缺少官方一手材料。
5. 目标是至少产生一组可重复、可解释的当前 `confirmed` 事件，再考虑定时调度或日报。

## 推荐模型

- 下一步证据边界设计与最终审查：5.6 Sol + 高推理。
- 已确定方案后的常规来源接入、测试和报告实现：5.6 Terra + 中推理。

