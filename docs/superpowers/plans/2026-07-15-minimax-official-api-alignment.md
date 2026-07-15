# MiniMax 官网接口对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 MiniMax-M2.7/M3 按官网当前 Chat Completions 协议稳定提供可校验的辅助结果，并在失败时给出安全、准确的诊断后回退规则流程。

**Architecture:** 保持 `MiniMaxClient.structured` 作为唯一通用入口，在内部拆分响应元数据检查、最终内容提取和结构校验。事件适配器不改变职责，只继承通用客户端的新协议与错误分类。

**Tech Stack:** Python 3.12、HTTPX、Pydantic 2、pytest、pytest-asyncio、Ruff。

## Global Constraints

- 使用 MiniMax 官网当前 `/v1/chat/completions` 接口。
- M2.7/M3 不使用 `response_format`，启用 `reasoning_split: true`。
- 模型失败不得阻塞规则流程，只允许一次结构修复重试。
- 日志和数据库不得记录 API Key、完整提示词、完整模型响应或互联网原文。
- 真实 API 验证先 1 个请求，成功后最多扩大到 3 个固定样本。
- 不开发摘要、推荐、推送或新的来源抓取功能。

---

### Task 1: 当前协议与响应诊断

**Files:**
- Modify: `tests/test_minimax.py`
- Modify: `src/newsradar/ai/minimax.py`

**Interfaces:**
- Consumes: `MiniMaxClient.structured(...) -> T`
- Produces: `_provider_error(payload) -> str | None`、`_completion_content(payload) -> str`

- [ ] **Step 1: 写失败测试**

新增测试，断言请求路径是 `/v1/chat/completions`，请求包含 `reasoning_split=true`、
`max_completion_tokens` 和 `temperature=1.0`，且不包含 `response_format`。

- [ ] **Step 2: 验证测试因旧端点和旧参数失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimax.py::test_classification_uses_current_chat_api_and_validates_json -q`

Expected: FAIL，显示路径仍为 `/v1/text/chatcompletion_v2` 或缺少新参数。

- [ ] **Step 3: 实现最小请求迁移**

在 `structured` 中使用当前端点和参数；保留 Bearer 认证、总超时和一次修复循环。

- [ ] **Step 4: 验证新请求测试通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimax.py::test_classification_uses_current_chat_api_and_validates_json -q`

Expected: PASS。

### Task 2: 精细响应错误分类

**Files:**
- Modify: `tests/test_minimax.py`
- Modify: `src/newsradar/ai/minimax.py`
- Modify: `tests/events/test_minimax.py`

**Interfaces:**
- Consumes: MiniMax OpenAI 兼容响应中的 `base_resp`、`choices[0].finish_reason`、`message.content`
- Produces: `provider_business_error`、`completion_truncated`、`response_shape_invalid`、`json_syntax_invalid`、`schema_validation_failed`

- [ ] **Step 1: 分别写五类失败测试**

用 `httpx.MockTransport` 返回业务错误、`finish_reason=length`、缺失内容、非 JSON、字段不匹配；
断言 `ModelUsage.error` 精确分类，只有后两类发生一次修复重试。

- [ ] **Step 2: 运行并确认旧实现统一报 `invalid_response`**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimax.py -q`

Expected: FAIL，错误分类不符合新设计。

- [ ] **Step 3: 添加有界内部异常和响应校验函数**

使用不携带原文的内部异常表达错误码；先校验 provider/finish reason/shape，再分别执行
`json.loads` 和 `response_type.model_validate`。修复响应只截取首轮内容的既有 2000 字符上限，
不进入持久化日志。

- [ ] **Step 4: 更新事件测试中的预期错误分类**

将确属 JSON 语法或 Schema 校验的断言从 `invalid_response` 更新为对应新代码，不修改历史
快照对旧运行的展示语义。

- [ ] **Step 5: 运行 MiniMax 测试集**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minimax.py tests/events/test_minimax.py -q`

Expected: PASS。

### Task 3: 回归验证与真实单请求验收

**Files:**
- Modify: `docs/superpowers/specs/2026-07-15-minimax-official-api-alignment-design.md`（仅在验证发现官方差异时）

**Interfaces:**
- Consumes: 本地环境变量 `MINIMAX_API_KEY`、`MINIMAX_BASE_URL`、模型配置
- Produces: 不含敏感内容的验证结论

- [ ] **Step 1: 静态与全量回归测试**

Run: `.venv/Scripts/python.exe -m ruff check src tests`

Expected: PASS。

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: PASS。

- [ ] **Step 2: 执行一个真实最小请求**

通过本地未跟踪环境配置注入 Key，调用 `infer_source_topics("Agent research")` 一次，仅输出
结果类型、置信度、调用 outcome/error 和 token 数，不输出 Key、提示词或模型正文。

- [ ] **Step 3: 按结果决定是否扩大**

单请求成功时最多追加两个固定样本；失败时停止调用，并根据精细错误码报告阻塞点。

- [ ] **Step 4: 复核差异并提交**

Run: `git diff --check && git status --short`

Expected: 只有本计划范围内文件变化；提交消息使用 `fix: align minimax client with official chat api`。

