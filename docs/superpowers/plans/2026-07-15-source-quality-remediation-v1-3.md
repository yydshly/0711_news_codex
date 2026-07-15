# 来源质量修复 v1.3 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精准修复 10 个当前降级来源，使内容完整、空内容、字段不足和访问失败拥有可审计且中文可读的不同结论。

**Architecture:** 保留现有 `ProbeOutcome` 和数据库结构，在通用质量分类函数中产生稳定错误码，由 RSS、JSON、Bluesky 和 Mastodon 协议探测器共享；网页查询层根据错误码生成中文解释。来源 YAML 只调整已经验证的真实入口和可读文案，不降低 90% 完整率门槛。

**Tech Stack:** Python 3.12、HTTPX、feedparser、Pydantic 2、SQLAlchemy 2、Typer、FastAPI/Jinja2、pytest、ruff。

## 全局约束

- 只处理设计文档列出的 10 个降级来源，不扩展来源宇宙。
- 不降低全局 90% 字段完整率标准。
- 不新增数据库迁移或 `ProbeOutcome` 枚举值。
- 空内容使用 `degraded` + `no_content`，字段不足使用 `degraded` + `incomplete_fields`。
- 空内容不能计为内容探测成功，也不能满足连续三次成功条件。
- 不启用 HTML 自动回退、登录 Cookie、验证码处理、代理绕过或非官方抓取。
- 所有行为修改必须先写失败测试并确认 RED，再写最小实现。
- 中文来源配置、报告和网页文案使用 UTF-8。
- 不触碰主工作区中用户未提交的报告文件。

---

## 文件结构

- 修改 `src/newsradar/sources/probes/base.py`：提供统一样本质量分类函数。
- 修改 `src/newsradar/sources/probes/json_api.py`：为通用 JSON 空内容和字段不足设置稳定错误码。
- 修改 `src/newsradar/sources/probes/rss.py`：完善 feed 字段回退并设置稳定错误码。
- 修改 `src/newsradar/sources/probes/protocols.py`：完善 Bluesky，并新增 Mastodon 专用规范化。
- 修改 `src/newsradar/sources/probes/factory.py`：将审核过的 Mastodon API 路由到专用探测器。
- 修改 `src/newsradar/web/i18n.py`：将稳定错误码映射成中文诊断。
- 修改受影响的 10 个 `sources/**/*.yaml`：修复乱码并校准已确认入口。
- 修改 `tests/test_probes.py`、`tests/test_protocol_probes.py`、`tests/web/test_i18n.py`：固定协议、状态和中文诊断行为。
- 新建 `reports/source-quality-remediation-v1-3.md`：记录真实探测结果与剩余限制。

### Task 1：统一空内容与字段不足分类

**Files:**
- Modify: `src/newsradar/sources/probes/base.py`
- Modify: `src/newsradar/sources/probes/json_api.py`
- Modify: `src/newsradar/sources/probes/rss.py`
- Test: `tests/test_probes.py`

**Interfaces:**
- Produces: `classify_sample_quality(sample_count: int, field_completeness: float) -> tuple[ProbeOutcome, SourceStatus, str | None]`
- Consumes: `ProbeOutcome`、`SourceStatus` 和现有 90% 成功阈值。

- [ ] **Step 1: 写 JSON 与 RSS 空内容的失败测试**

在 `tests/test_probes.py` 增加两个异步测试，使用 `MockTransport` 分别返回 `[]` 和合法空 RSS，断言：

```python
assert result.outcome is ProbeOutcome.DEGRADED
assert result.sample_count == 0
assert result.error_code == "no_content"
assert result.suggested_status.value == "degraded"
```

- [ ] **Step 2: 写字段不足的失败测试**

使用只包含 `title` 的 JSON 样本和 `expected_fields=["title", "canonical_url"]`，断言：

```python
assert result.outcome is ProbeOutcome.DEGRADED
assert result.sample_count == 1
assert result.error_code == "incomplete_fields"
```

- [ ] **Step 3: 运行测试并确认 RED**

Run: `uv run pytest tests/test_probes.py -k "empty or incomplete_fields" -v`

Expected: FAIL，因为当前探测器没有设置 `no_content` 或 `incomplete_fields`。

- [ ] **Step 4: 实现统一分类函数并接入两个通用探测器**

在 `base.py` 增加：

```python
def classify_sample_quality(
    sample_count: int, field_completeness: float
) -> tuple[ProbeOutcome, SourceStatus, str | None]:
    if sample_count == 0:
        return ProbeOutcome.DEGRADED, SourceStatus.DEGRADED, "no_content"
    if field_completeness < 0.9:
        return ProbeOutcome.DEGRADED, SourceStatus.DEGRADED, "incomplete_fields"
    return ProbeOutcome.SUCCESS, SourceStatus.CANDIDATE, None
```

在 `JsonApiProbe.parse()` 与 `RssProbe.parse()` 中使用该函数，并把 `error_code` 写入 `_result(...)`。原因文本分别明确为“Parsed 0 ...; endpoint reachable but no content”或现有完整率说明。

- [ ] **Step 5: 运行定向测试并确认 GREEN**

Run: `uv run pytest tests/test_probes.py -v`

Expected: PASS。

- [ ] **Step 6: 提交 Task 1**

```powershell
git add src/newsradar/sources/probes/base.py src/newsradar/sources/probes/json_api.py src/newsradar/sources/probes/rss.py tests/test_probes.py
git commit -m "fix: distinguish empty and incomplete source probes"
```

### Task 2：完善 Bluesky 与 Mastodon 原生字段映射

**Files:**
- Modify: `src/newsradar/sources/probes/protocols.py`
- Modify: `src/newsradar/sources/probes/factory.py`
- Test: `tests/test_protocol_probes.py`

**Interfaces:**
- Consumes: Task 1 的 `classify_sample_quality`（通过父类 `JsonApiProbe.parse()` 间接使用）。
- Produces: `MastodonProbe(JsonApiProbe)`；Bluesky 和 Mastodon 都输出标准 `ProbeSample` 字段。

- [ ] **Step 1: 写 Bluesky 互动总量失败测试**

扩展 Bluesky 固定样本，加入 `likeCount=9`、`repostCount=3`、`replyCount=2`，断言：

```python
assert result.samples[0].engagement == 14
assert result.samples[0].content == "New model"
```

- [ ] **Step 2: 写 Mastodon 规范化失败测试**

固定响应包含一条公开状态：

```python
{
    "id": "100",
    "url": "https://mastodon.social/@alice/100",
    "created_at": "2026-07-10T12:00:00Z",
    "account": {"display_name": "Alice", "acct": "alice"},
    "content": "<p>New open model</p>",
    "replies_count": 2,
    "reblogs_count": 3,
    "favourites_count": 5,
}
```

断言标题和正文为 `New open model`，作者为 `Alice`，链接和时间存在，互动量为 `10`，探测结果为 `success`。

- [ ] **Step 3: 运行测试并确认 RED**

Run: `uv run pytest tests/test_protocol_probes.py -k "bluesky or mastodon" -v`

Expected: Bluesky 互动量仍为 9，Mastodon 由通用 JSON 探测器处理而缺少作者和正文映射。

- [ ] **Step 4: 实现最小协议适配**

在 `protocols.py`：

```python
def engagement_total(*values: object) -> int:
    return sum(value for value in values if isinstance(value, int))
```

Bluesky 的 `likes` 改为点赞、转发和回复总量。新增 `MastodonProbe`，将状态数组扁平化为：

```python
{
    "id": status.get("id"),
    "title": plain_text,
    "content": plain_text,
    "published_at": status.get("created_at"),
    "author": display_name or acct or username,
    "url": status.get("url") or status.get("uri"),
    "likes": engagement_total(
        status.get("replies_count"),
        status.get("reblogs_count"),
        status.get("favourites_count"),
    ),
}
```

使用标准库 `html.parser.HTMLParser` 或项目已有纯文本辅助函数去除标签，不能增加网络请求。在 `factory.py` 中仅将 `mastodon.social` 的 `/api/v1/` 路径交给 `MastodonProbe`。

- [ ] **Step 5: 运行定向测试并确认 GREEN**

Run: `uv run pytest tests/test_protocol_probes.py -v`

Expected: PASS。

- [ ] **Step 6: 提交 Task 2**

```powershell
git add src/newsradar/sources/probes/protocols.py src/newsradar/sources/probes/factory.py tests/test_protocol_probes.py
git commit -m "fix: normalize bluesky and mastodon probe samples"
```

### Task 3：完善 RSS 字段回退

**Files:**
- Modify: `src/newsradar/sources/probes/rss.py`
- Test: `tests/test_probes.py`

**Interfaces:**
- Consumes: feedparser `FeedParserDict` 和 Task 1 的质量分类。
- Produces: `feed_summary(entry) -> str | None`、`feed_content(entry) -> str | None`。

- [ ] **Step 1: 写 RSS 正文回退失败测试**

创建 Atom 固定样本，只提供 `<content>Full article body</content>`，来源预期字段包含 `summary` 和 `content`，断言两者均得到可用文本，完整率达到 100%。再创建只有 `<description>` 的 RSS 样本，断言 `content` 能从摘要回退。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `uv run pytest tests/test_probes.py -k "rss_content_fallback" -v`

Expected: FAIL，因为当前 `summary` 不会从 content 回退，content 也不会从 description 回退。

- [ ] **Step 3: 实现两个纯函数**

```python
def feed_summary(entry: dict) -> str | None:
    content = entry.get("content") or []
    return entry.get("summary") or entry.get("description") or (
        content[0].get("value") if content else None
    )


def feed_content(entry: dict) -> str | None:
    content = entry.get("content") or []
    return (
        content[0].get("value") if content else None
    ) or entry.get("summary") or entry.get("description")
```

在 `ProbeSample` 构造处调用两个函数，不请求文章 HTML。

- [ ] **Step 4: 运行定向测试并确认 GREEN**

Run: `uv run pytest tests/test_probes.py -v`

Expected: PASS。

- [ ] **Step 5: 提交 Task 3**

```powershell
git add src/newsradar/sources/probes/rss.py tests/test_probes.py
git commit -m "fix: normalize rss summary and content fields"
```

### Task 4：校准 10 个来源配置与中文诊断

**Files:**
- Modify: `src/newsradar/web/i18n.py`
- Modify: `tests/web/test_i18n.py`
- Modify: `sources/community/anthropic-bluesky.yaml`
- Modify: `sources/community/mastodon-ai-tag.yaml`
- Modify: `sources/community/mastodon-artificialintelligence-tag.yaml`
- Modify: `sources/community/mastodon-llm-tag.yaml`
- Modify: `sources/community/mastodon-machinelearning-tag.yaml`
- Modify: `sources/community/mastodon-mastodon.yaml`
- Modify: `sources/official/deepmind-blog.yaml`
- Modify: `sources/official/huggingface-blog.yaml`
- Modify: `sources/github/qwen3-releases.yaml`
- Modify: `sources/universe/universe-latent-space-2.yaml`

**Interfaces:**
- Consumes: `explain_failure(reason, http_status, error_code)`。
- Produces: `no_content` 和 `incomplete_fields` 的稳定中文解释；10 个 UTF-8 可读来源定义。

- [ ] **Step 1: 写中文诊断失败测试**

在 `tests/web/test_i18n.py` 增加：

```python
assert explain_failure("", 200, "no_content") == "入口正常，当前没有可用内容"
assert explain_failure("", 200, "incomplete_fields") == "已获取内容，但缺少必要字段"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `uv run pytest tests/web/test_i18n.py -v`

Expected: FAIL，当前会返回通用结构变化或探测失败文案。

- [ ] **Step 3: 按错误码优先级实现中文解释**

在 `explain_failure()` 最前面增加精确判断：

```python
if error_code == "no_content":
    return "入口正常，当前没有可用内容"
if error_code == "incomplete_fields":
    return "已获取内容，但缺少必要字段"
```

- [ ] **Step 4: 修复来源中文乱码并校准入口**

用 `apply_patch` 将 10 个 YAML 中不可读的 `name`、`purpose`、`conclusion`、`risk_conclusion`、`limitations` 和 `notes` 改为准确中文。保留所有凭据为空间环境变量，YAML 中不得出现密钥或 Cookie。

将 `universe-latent-space-2` 的首选访问方式明确改为：

```yaml
target_type: publisher_feed
coverage_mode: direct
access_methods:
  - kind: rss
    url: https://www.latent.space/feed
    priority: 1
```

保留 `qwen3-releases` 的官方 API、`availability: unavailable` 和“等待官方 Release”的解锁条件，不用 commits/events 冒充 Release。

- [ ] **Step 5: 运行 YAML 与网页测试**

Run: `uv run newsradar sources validate --root sources`

Expected: `Validated 187 sources from sources`（若当前目录数量发生已提交变化，以命令实际输出为准，但必须为零校验错误）。

Run: `uv run pytest tests/web/test_i18n.py tests/test_source_schema.py tests/test_source_universe_catalog.py tests/research/test_failure_remediation_catalog.py -v`

Expected: PASS。

- [ ] **Step 6: 提交 Task 4**

```powershell
git add src/newsradar/web/i18n.py tests/web/test_i18n.py sources/community sources/official/deepmind-blog.yaml sources/official/huggingface-blog.yaml sources/github/qwen3-releases.yaml sources/universe/universe-latent-space-2.yaml
git commit -m "fix: clarify degraded source diagnostics"
```

### Task 5：真实探测、报告与合并前审查

**Files:**
- Create: `reports/source-quality-remediation-v1-3.md`
- Verify only: all changed source and test files.

**Interfaces:**
- Consumes: Tasks 1–4 的探测器、来源 YAML 和中文诊断。
- Produces: 可提交的真实来源质量验收报告。

- [ ] **Step 1: 确认数据库和运行环境状态**

Run: `uv run alembic current`

Expected: 输出当前 Alembic revision 且退出码为 0，证明项目可连接本机 PostgreSQL。探测继续使用项目现有 HTTPX 环境继承策略，不新增代理参数或代理绕过，也不打印任何凭据值。

- [ ] **Step 2: 同步修复后的来源定义**

Run: `uv run newsradar sources sync --root sources`

Expected: 10 个目标至多产生必要版本更新；重复执行一次时 `updated=0`，证明同步幂等。

- [ ] **Step 3: 对 10 个目标执行第一轮真实探测**

逐一运行：

```powershell
uv run newsradar sources probe anthropic-bluesky
uv run newsradar sources probe deepmind-blog
uv run newsradar sources probe huggingface-blog
uv run newsradar sources probe mastodon-ai-tag
uv run newsradar sources probe mastodon-artificialintelligence-tag
uv run newsradar sources probe mastodon-llm-tag
uv run newsradar sources probe mastodon-machinelearning-tag
uv run newsradar sources probe mastodon-mastodon
uv run newsradar sources probe qwen3-releases
uv run newsradar sources probe universe-latent-space-2
```

Expected: 所有来源都有明确 `success`、`no_content`、`incomplete_fields`、`blocked` 或 `failed` 证据，不能只显示无解释的 0%。

- [ ] **Step 4: 对第一轮成功的目标再执行两轮**

只重跑 Step 3 中实际返回内容且 `success` 的目标两次。`no_content` 不进入三轮成功统计，不因验收目标而伪造内容。

- [ ] **Step 5: 生成中文质量报告**

使用 `apply_patch` 新建 `reports/source-quality-remediation-v1-3.md`，每个目标记录：修复前结果、修复后结果、样本数、完整率、错误码、最新内容时间、剩余限制和是否建议继续启用。报告不得包含请求头、密钥、Cookie 或完整响应正文。

- [ ] **Step 6: 运行完整验证**

Run: `uv run pytest -q`

Expected: PASS，无失败。

Run: `uv run ruff check .`

Expected: `All checks passed!`

Run: `git diff --check`

Expected: 无输出且退出码为 0。

Run: `git status --short`

Expected: 只包含本计划内报告或已明确的待提交文件。

- [ ] **Step 7: 提交验收报告**

```powershell
git add reports/source-quality-remediation-v1-3.md
git commit -m "docs: accept source quality remediation v1.3"
```

- [ ] **Step 8: 合并前代码审查**

审查 `main..HEAD`，重点确认：全局阈值未降低、空内容未计为成功、Mastodon 只匹配审核 API、没有 HTML/登录态回退、没有敏感信息进入代码或报告。若发现问题，先补失败测试再修复并单独提交。

## 最终完成判定

- 10 个目标均有清晰中文结论和可审计原始证据。
- 返回内容的 Bluesky、Mastodon、RSS 来源必要字段完整率达到 90% 或明确说明剩余缺字段。
- GitHub Release 与其他空内容入口显示 `no_content`，且不满足成功晋级。
- YAML 校验、完整测试、ruff、差异检查和敏感信息检查全部通过。
- 中文质量报告已提交，分支可以安全进入合并流程。
