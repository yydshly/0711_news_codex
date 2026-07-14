# 凭据来源长期启用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 OpenAI YouTube 与 7 个 GitHub Release 来源从单次抓取候选收口为可由 Worker 正常消费的已审核来源，同时准确保留凭据依赖和失败诊断。

**Architecture:** 长期启用继续使用现有 `SourceDefinition.ingestion`，YAML 只声明审核启用和官方 API，既有 CLI、Worker 与持久化抓取管线负责运行、去重、重试与记录。

**Tech Stack:** Python 3.12、Pydantic 2、Typer、SQLAlchemy 2、pytest、YAML。

## Global Constraints

- API Key / Token 仅从本地环境变量读取，绝不写入 YAML、数据库、报告、日志或网页。
- YouTube 仅使用 YouTube Data API v3；GitHub 仅使用官方 REST API。
- 不使用 Cookie、网页登录抓取、代理绕过或第三方镜像。
- `requires_credentials` 代表真实权限要求，不得因长期启用而改成 `ready`。
- 不新增来源、定时调度、摘要、推荐、邮件或推送功能。

---

### Task 1: 为 8 个来源建立长期启用矩阵测试

**Files:**
- Create: `tests/ingestion/test_credential_source_activation.py`
- Read: `src/newsradar/sources/loader.py`
- Read: `src/newsradar/sources/schema.py`

**Interfaces:**
- Consumes: `load_source_tree(root: Path) -> list[SourceDefinition]` 与 `SourceDefinition.ingestion`。
- Produces: `CREDENTIAL_SOURCE_IDS` 与配置验收测试。

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from newsradar.sources.yaml_loader import load_source_tree

CREDENTIAL_SOURCE_IDS = {
    "openai-youtube", "anthropic-sdk-releases", "cuda-python-releases",
    "deepseek-v3-releases", "gemini-cli-releases", "mistral-common-releases",
    "openai-python-releases", "transformers-releases",
}

def test_credential_sources_are_explicitly_approved_for_ingestion() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    enabled = {source_id for source_id in CREDENTIAL_SOURCE_IDS if sources[source_id].ingestion.enabled}
    assert enabled == CREDENTIAL_SOURCE_IDS
    assert all(sources[source_id].ingestion.approved_at is not None for source_id in CREDENTIAL_SOURCE_IDS)
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/ingestion/test_credential_source_activation.py::test_credential_sources_are_explicitly_approved_for_ingestion -q`

Expected: FAIL because the eight definitions do not all have `ingestion.enabled: true`.

- [ ] **Step 3: Add the official-authentication boundary test**

```python
def test_credential_source_access_methods_keep_official_auth_requirements() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    youtube = sources["openai-youtube"]
    github = [sources[source_id] for source_id in CREDENTIAL_SOURCE_IDS - {"openai-youtube"}]
    assert youtube.availability.value == "requires_credentials"
    assert youtube.access_methods[1].auth_envs == ("YOUTUBE_API_KEY",)
    assert all(source.availability.value == "requires_credentials" for source in github)
    assert all(source.access_methods[0].auth_envs == ("GITHUB_TOKEN",) for source in github)
```

- [ ] **Step 4: Run both tests**

Run: `uv run pytest tests/ingestion/test_credential_source_activation.py -q`

Expected: only the explicit approval assertion fails; the authentication boundary already passes.

- [ ] **Step 5: Commit the red checkpoint**

```bash
git add tests/ingestion/test_credential_source_activation.py
git commit -m "test: define credential source activation matrix"
```

### Task 2: 启用经验证的官方 API 来源

**Files:**
- Modify: `sources/universe/universe-youtube-1.yaml`
- Modify: `sources/github/anthropic-sdk-releases.yaml`
- Modify: `sources/github/cuda-python-releases.yaml`
- Modify: `sources/github/deepseek-v3-releases.yaml`
- Modify: `sources/github/gemini-cli-releases.yaml`
- Modify: `sources/github/mistral-common-releases.yaml`
- Modify: `sources/github/openai-python-releases.yaml`
- Modify: `sources/github/transformers-releases.yaml`
- Test: `tests/ingestion/test_credential_source_activation.py`

**Interfaces:**
- Consumes: `IngestionConfig(enabled: bool, approved_at: date)`.
- Produces: 8 个启用且有审核日期的 `SourceDefinition`。

- [ ] **Step 1: Add the minimal ingestion block to every source**

直接在 8 个 YAML 的 `poll_interval_minutes` 后加入：

```yaml
ingestion:
  enabled: true
  approved_at: 2026-07-14
```

YouTube 保持 `availability: requires_credentials`、`status: degraded`、现有 `auth_envs` 与官方 URL 不变。7 个 GitHub YAML 的 REST API 方法增加 `auth_envs: [GITHUB_TOKEN]`，并将 `availability` 设为 `requires_credentials`；这保留 GitHub 未认证 API 的公开性质，但明确长期 Worker 运行使用 Token 以避免低配额限流。

- [ ] **Step 2: Verify GREEN**

Run: `uv run pytest tests/ingestion/test_credential_source_activation.py -q`

Expected: `2 passed`.

- [ ] **Step 3: Validate all source definitions**

Run: `uv run newsradar sources validate --root sources`

Expected: 166 个来源通过校验，无凭据泄漏或 Schema 错误。

- [ ] **Step 4: Commit configuration activation**

```bash
git add sources/universe/universe-youtube-1.yaml sources/github/anthropic-sdk-releases.yaml sources/github/cuda-python-releases.yaml sources/github/deepseek-v3-releases.yaml sources/github/gemini-cli-releases.yaml sources/github/mistral-common-releases.yaml sources/github/openai-python-releases.yaml sources/github/transformers-releases.yaml tests/ingestion/test_credential_source_activation.py
git commit -m "feat: enable verified credential sources"
```

### Task 3: 验证长期抓取与中文可观察性

**Files:**
- Read: `src/newsradar/cli.py`
- Read: `src/newsradar/operations/fetch_runtime.py`
- Read: `src/newsradar/web/app.py`
- Test: `tests/test_cli.py::test_fetch_enqueues_without_direct_network_work`
- Test: `tests/operations/test_fetch_runtime.py::test_worker_keeps_policy_blocked_fetch_terminal_without_retry`

**Interfaces:**
- Consumes: 已启用 YAML、`newsradar fetch --approved`、`OperationRunRecord` / `FetchRunRecord`。
- Produces: 可审计队列任务与现有抓取运行页中的中文诊断。

- [ ] **Step 1: Run approval and blocked-credential regression tests**

```bash
uv run pytest tests/test_cli.py::test_fetch_enqueues_without_direct_network_work tests/operations/test_fetch_runtime.py::test_worker_keeps_policy_blocked_fetch_terminal_without_retry -q
```

Expected: both pass;已启用来源由 Worker 消费，缺失凭据是终态可诊断阻塞而不是网页回退或无限重试。

- [ ] **Step 2: Queue only enabled sources through the approved path**

Run: `uv run newsradar fetch --approved --max-items 5 --no-wait`

Expected: CLI 无 one-off 确认地创建已批准任务，并且不打印环境变量值。

- [ ] **Step 3: Read persisted results**

使用只读 SQLAlchemy 脚本输出 operation ID、source ID、终态、outcome、received、inserted 和 error code。

Expected: 每个来源均终态；`succeeded` 与 `no_change` 都健康；缺失凭据只会是带代码的 `blocked`。

- [ ] **Step 4: Verify Chinese UI endpoints**

```powershell
Invoke-WebRequest http://127.0.0.1:8766/fetch-runs -UseBasicParsing | Select-Object -ExpandProperty StatusCode
Invoke-WebRequest http://127.0.0.1:8766/items -UseBasicParsing | Select-Object -ExpandProperty StatusCode
```

Expected: 本地 Web 运行时两个端点均为 `200`；否则记录运行前置条件，不误报为代码故障。

### Task 4: 将 GitHub 凭据真正传递到官方 API

**Files:**
- Modify: `src/newsradar/ingestion/fetchers/github.py`
- Modify: `src/newsradar/ingestion/fetchers/base.py`
- Modify: `tests/ingestion/fetchers/test_github.py`

**Interfaces:**
- Consumes: `AccessMethod.auth_envs` 与 `CredentialProvider.require("GITHUB_TOKEN")`。
- Produces: 仅对显式声明 `GITHUB_TOKEN` 的 GitHub REST API 请求附加 `Authorization: Bearer ...`；缺失凭据时返回 `blocked/missing_credential`。

- [ ] **Step 1: Write the failing HTTP-header and missing-credential tests**

Use an injected fake credential provider and `respx` route. Assert the request contains `Authorization: Bearer test-github-token`; assert missing credentials returns `FetchOutcome.BLOCKED` and `missing_credential` before network I/O.

- [ ] **Step 2: Verify RED**

Run: `uv run python -m pytest tests/ingestion/fetchers/test_github.py -q`

Expected: the two new tests fail because the previous constructor had no credential provider and never set an authorization header.

- [ ] **Step 3: Implement the minimal credential propagation**

Keep the existing public-fetch constructor compatible. When `method.auth_envs` contains `GITHUB_TOKEN`, obtain it from the injected provider, put it only in the in-memory request header, and return a blocked result if absent. Have `FetcherFactory` inject its existing credential provider for GitHub.

- [ ] **Step 4: Verify GREEN and lint**

```bash
uv run python -m pytest tests/ingestion/fetchers/test_github.py tests/ingestion/test_credential_source_activation.py -q
uv run ruff check src/newsradar/ingestion/fetchers/github.py tests/ingestion/fetchers/test_github.py
```

Expected: all tests and lint checks pass.

### Task 5: 完整验收与合并前审查

**Files:**
- Read: `docs/superpowers/specs/2026-07-14-credential-source-activation-design.md`
- Read: `docs/superpowers/plans/2026-07-14-credential-source-activation.md`

**Interfaces:**
- Consumes: Task 1–3 的提交和真实运行证据。
- Produces: 可合并分支与不含秘密的验证报告。

- [ ] **Step 1: Run full verification**

```bash
uv run ruff check .
uv run pytest -q
git diff --check
```

Expected: all exit 0.

- [ ] **Step 2: Review final diff**

Run: `git diff main...HEAD --check; git diff --stat main...HEAD; git log --oneline main..HEAD`

Expected: only activation YAML, focused tests and Chinese design/plan docs; no `.env`, token or generated local reports.

- [ ] **Step 3: Request final review and integrate only on user request**

Use the branch completion workflow after reporting fresh evidence; do not merge or push without user instruction.
