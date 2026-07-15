# MiniMax 官网接口对齐设计

## 背景与根因

News Codex 当前通过 `MiniMaxClient` 调用 `/v1/text/chatcompletion_v2`，并要求
`MiniMax-M2.7-highspeed` 与 `MiniMax-M3` 仅靠提示词返回严格 JSON。MiniMax 官网已将
该原生接口标记为弃用；官网同时说明 `response_format` 仅支持 `MiniMax-Text-01`，不能
把它当作 M2.7/M3 的 JSON Schema 保证。最近一次事件处理因此出现模型调用有响应、但
72 个候选全部未通过本地 Pydantic 结构校验并回退规则结果的现象。

## 目标

- 将通用适配器迁移到官网当前的 `/v1/chat/completions`。
- 对 M2.7/M3 显式启用 `reasoning_split`，只解析最终回答，不把推理内容当 JSON。
- 保留提示词 JSON Schema 与一次修复重试，不声称模型具备官网未承诺的 JSON Mode。
- 检查 HTTP 状态、MiniMax `base_resp`、`finish_reason`、响应结构、JSON 语法和 Pydantic
  Schema，并记录可审计、无敏感内容的分类错误。
- MiniMax 不可用或响应不合格时继续使用规则结果，不阻塞抓取、事件聚合与发布规则。
- 真实验证从单个请求开始；未通过前不运行 72 个候选的批量调用。

## 非目标

- 不改变 MiniMax 在系统中的辅助定位。
- 不让模型决定来源合规、新闻事实确认或发布资格。
- 不新增摘要、推荐、推送或来源抓取功能。
- 不记录 API Key、原始提示词、模型完整回答或互联网原文。
- 本轮不切换到 `MiniMax-Text-01`，也不依赖未确认可强制调用的 Function Tool。

## 请求设计

请求发送到 `${MINIMAX_BASE_URL}/v1/chat/completions`，包含：

- 国际区 Key 使用 `https://api.minimax.io`；中国区 Token Plan Key 使用
  `https://api.minimaxi.com`。区域配置错误会返回 HTTP 401，不能据此误判 Key 无效。

- `model`：继续使用现有配置中的快速模型或深度模型。
- `messages`：单条用户消息，继续带不可信数据安全前言和目标 Pydantic Schema。
- `reasoning_split: true`：将推理和最终回答分离。
- `temperature: 1.0`：遵循 MiniMax 对 M2 系列的推荐值。
- `max_completion_tokens`：设置有界输出预算，防止无限增长。

不发送 `response_format`，因为官网没有承诺 M2.7/M3 支持该参数。首轮也不发送工具定义，
避免把 `tool_choice=auto` 误当作强制结构化输出。

## 响应与错误分类

适配器按以下顺序验证响应：

1. HTTP 成功；否则保留 `http_4xx`、`http_429`、`http_5xx`、`timeout`、
   `transport_error`。
2. `base_resp.status_code` 必须为 `0`；否则记录 `provider_business_error`。
3. `choices[0].finish_reason` 若为 `length`，记录 `completion_truncated`。
4. `choices[0].message.content` 必须为字符串；否则记录 `response_shape_invalid`。
5. 去除 Markdown JSON 围栏和兼容性 `<think>` 块后解析 JSON；语法失败记录
   `json_syntax_invalid`。
6. Pydantic 字段校验失败记录 `schema_validation_failed`。

上述错误只进入 `ModelUsage.error`，不包含服务端消息、模型正文、密钥或提示词。只有 JSON
语法和 Schema 错误允许一次修复重试；业务错误、截断和响应结构错误直接回退，避免无意义
重复调用。

## 测试与验收

- 单元测试先验证新端点、`reasoning_split`、参数和响应解析。
- 覆盖业务错误、截断、结构错误、JSON 错误、Schema 错误以及一次修复重试。
- 保持无 Key 回退、总超时、用量记录失败隔离和 token 边界测试。
- 运行全部 MiniMax 与事件适配器测试，再运行全量测试和 Ruff。
- 使用真实 Key 只执行一个最小主题推断请求；成功后最多扩大到 3 个固定样本。
- 如果真实请求仍失败，停止扩大调用并根据新的细分错误继续定位。

## 真实验收结果

- 当前 `sk-cp` Token Plan Key 在国际区额度接口返回业务状态 `2049`，在中国区返回状态
  `0`，确认属于中国区。
- 本地未跟踪配置已切换为 `https://api.minimaxi.com`，Key 未写入源码、Git、日志或报告。
- 3 个固定主题推断样本均一次成功，无重试、无规则回退，置信度分别为 0.85、0.90、
  0.90。

## 官方依据

- MiniMax 原生文本接口（已标记 deprecated）：
  https://platform.minimax.io/docs/api-reference/text-post
- MiniMax OpenAI 兼容 Chat Completions：
  https://platform.minimax.io/docs/api-reference/text-chat-openai
