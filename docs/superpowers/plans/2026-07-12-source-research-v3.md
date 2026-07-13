# News Codex 来源研究与接入 v3 实施计划

> **面向代理执行者：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务执行。每个任务完成实现、测试、复审和提交后才能进入下一任务。

**目标：** 把当前以平台占位和访问方式为中心的来源目录，升级为以真实 Target、所需信息、候选获取方式、样本证据和人工结论为中心的来源研究系统。

**架构：** YAML 继续作为人工审核真相；严格 Pydantic Schema 表达 Target 研究档案和候选方式，PostgreSQL 保存当前投影、不可变版本和探测历史。研究探测与生产抓取严格分离，YouTube 作为首个完整样板，网页以中文展示研究进度、候选方法、字段、风险和缺口。

**技术栈：** Python 3.12、Pydantic 2、SQLAlchemy 2、Alembic、Typer、HTTPX、feedparser、FastAPI、Jinja2、pytest；研究可选依赖 `youtube-transcript-api==1.2.4`。

## 全局约束

- 所有新增设计、计划、报告、网页说明和用户错误使用中文。
- 当前 67 个 Provider、166 个 Target 是审计起点，不是来源数量上限或完成指标。
- 先声明来源和所需信息，再研究候选方式；不得先按 RSS、API、HTML 或第三方库决定来源范围。
- 不使用登录 Cookie、验证码破解、代理轮换、浏览器会话或反爬绕过。
- 不下载或保存视频、音频等大体积媒体。
- HTML、第三方库和能力探测不得自动变成生产抓取方式。
- MiniMax 不参与来源合规、候选方式选择、启用状态或风险结论。
- 旧 YAML 在迁移期间保持可加载；缺少 `research` 的旧目标默认为 `needs_research`，不得默认为 `verified`。
- 所有网络探测受现有超时、响应大小、并发、SSRF、防凭据泄漏和错误脱敏边界约束。
- 任何 `verified` Target 必须有明确用途、所需信息、首选方式、样本证据、风险结论和备用方式；无备用方式时必须写明原因。

---

## 任务 1：严格来源研究 Schema

**文件：**

- 修改：`src/newsradar/sources/schema.py`
- 修改：`src/newsradar/providers/schema.py`
- 创建：`tests/sources/test_research_schema.py`
- 修改：`tests/sources/test_schema.py`
- 修改：`tests/providers/test_schema.py`

**接口：**

- 输入：现有 `ProviderDefinition`、`SourceDefinition` YAML 数据。
- 输出：`ResearchStatus`、`AcquisitionKind`、`Officiality`、`AcquisitionAuth`、`AcquisitionRole`、`AcquisitionDecision`、`SampleStatus`、`AcquisitionCandidate`、`SourceResearchProfile`。
- 兼容：旧 YAML 不带 `research` 时生成 `SourceResearchProfile(status=needs_research)`。

- [ ] **步骤 1：先写 Schema 失败测试**

覆盖以下行为：

```python
def test_legacy_source_defaults_to_needs_research():
    source = SourceDefinition.model_validate(legacy_source_payload())
    assert source.research.status == ResearchStatus.NEEDS_RESEARCH


def test_verified_source_requires_wanted_information_primary_and_evidence():
    payload = legacy_source_payload() | {
        "research": {"status": "verified", "wanted_information": []}
    }
    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(payload)


def test_login_cookie_candidate_must_be_rejected():
    with pytest.raises(ValidationError):
        AcquisitionCandidate.model_validate({
            "key": "page-cookie",
            "kind": "html",
            "implementation": "browser-session",
            "officiality": "unofficial_library",
            "authentication": "login_cookie",
            "roles": ["content"],
            "fields": ["content"],
            "limitations": ["requires_login"],
            "evidence": ["https://example.test/terms"],
            "reviewed_at": "2026-07-12",
            "sample_status": "blocked",
            "decision": "primary",
        })
```

- [ ] **步骤 2：运行测试，确认缺少研究类型**

运行：

```powershell
uv run pytest tests/sources/test_research_schema.py tests/sources/test_schema.py tests/providers/test_schema.py -q
```

预期：失败，提示研究枚举和模型尚不存在。

- [ ] **步骤 3：实现严格模型与验证器**

在 `sources/schema.py` 中增加：

```python
class ResearchStatus(StrEnum):
    VERIFIED = "verified"
    NEEDS_RESEARCH = "needs_research"
    PLACEHOLDER = "placeholder"
    DUPLICATE = "duplicate"
    RETIRED = "retired"


class AcquisitionKind(StrEnum):
    RSS = "rss"
    ATOM = "atom"
    WEBSUB = "websub"
    PUBLIC_API = "public_api"
    API_KEY_API = "api_key_api"
    OAUTH_API = "oauth_api"
    SITEMAP = "sitemap"
    HTML = "html"
    JSON_LD = "json_ld"
    EMBEDDED_JSON = "embedded_json"
    LIBRARY = "library"
    AGGREGATOR = "aggregator"
    MANUAL = "manual"


class Officiality(StrEnum):
    OFFICIAL = "official"
    DOCUMENTED_PUBLIC = "documented_public"
    UNOFFICIAL_LIBRARY = "unofficial_library"
    THIRD_PARTY_SERVICE = "third_party_service"


class AcquisitionAuth(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    APPROVAL = "approval"
    PAYMENT = "payment"
    LOGIN_COOKIE = "login_cookie"


class AcquisitionRole(StrEnum):
    DISCOVERY = "discovery"
    METADATA = "metadata"
    CONTENT = "content"
    ENGAGEMENT = "engagement"
    TRANSCRIPT = "transcript"
    EVIDENCE = "evidence"


class AcquisitionDecision(StrEnum):
    PRIMARY = "primary"
    SUPPLEMENT = "supplement"
    FALLBACK = "fallback"
    MANUAL_ONLY = "manual_only"
    REJECTED = "rejected"


class SampleStatus(StrEnum):
    NOT_RUN = "not_run"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
```

`AcquisitionCandidate` 必须使用严格字段，禁止 URL 内嵌凭据，`login_cookie` 只能搭配 `rejected`。`SourceResearchProfile` 包含：

```python
status: ResearchStatus = ResearchStatus.NEEDS_RESEARCH
wanted_information: tuple[str, ...] = ()
candidates: tuple[AcquisitionCandidate, ...] = ()
conclusion: str | None = None
no_fallback_reason: str | None = None
reviewed_at: date | None = None
```

`verified` 验证规则：至少一个 `primary`、至少一个成功或部分成功样本、至少一个证据 URL；没有 `fallback` 时要求 `no_fallback_reason`。

- [ ] **步骤 4：运行 Schema 全套测试**

运行：

```powershell
uv run pytest tests/sources tests/providers -q
```

预期：通过；旧 YAML 仍可加载，非法研究状态和凭据方式被拒绝。

- [ ] **步骤 5：提交任务 1**

```powershell
git add src/newsradar/sources/schema.py src/newsradar/providers/schema.py tests/sources tests/providers
git commit -m "feat: 增加严格来源研究模型"
```

---

## 任务 2：研究数据持久化、迁移与幂等同步

**文件：**

- 修改：`src/newsradar/db/models.py`
- 修改：`src/newsradar/sources/repository.py`
- 创建：`migrations/versions/20260712_0009_source_research_v3.py`
- 创建：`tests/sources/test_research_repository.py`
- 修改：`tests/test_migrations.py`
- 修改：`tests/sources/test_repository.py`

**接口：**

- 新表：`source_research_profiles`、`source_acquisition_candidates`、`source_acquisition_probe_runs`。
- 唯一键：`source_research_profiles.source_id`；`source_acquisition_candidates(source_id, candidate_key)`。
- `SourceRepository.sync_source()` 在同一短事务中同步研究投影；现有 `source_definition_versions` 继续保存完整 YAML 快照。

- [ ] **步骤 1：写迁移和幂等同步失败测试**

测试要求：

- 从 `20260712_0008` 升级后保留已有来源和 RawItem。
- 同一 YAML 同步两次不产生新版本或重复候选。
- 修改候选字段后产生新的来源版本，并更新当前研究投影。
- 删除 YAML 中的候选后只删除当前投影，不删除历史版本快照。
- 探测历史使用候选记录外键，候选更新时历史仍可读取。

- [ ] **步骤 2：运行测试确认表和模型缺失**

```powershell
uv run pytest tests/sources/test_research_repository.py tests/test_migrations.py -q
```

预期：失败，提示研究表、模型和同步逻辑不存在。

- [ ] **步骤 3：实现数据库对象**

新增记录：

```python
class SourceResearchProfileRecord(Base):
    __tablename__ = "source_research_profiles"
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str]
    wanted_information: Mapped[list[str]] = mapped_column(JSON)
    conclusion: Mapped[str | None]
    no_fallback_reason: Mapped[str | None]
    reviewed_at: Mapped[date | None]


class SourceAcquisitionCandidateRecord(Base):
    __tablename__ = "source_acquisition_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_definitions.id", ondelete="CASCADE"), index=True
    )
    candidate_key: Mapped[str]
    kind: Mapped[str]
    implementation: Mapped[str]
    officiality: Mapped[str]
    authentication: Mapped[str]
    roles: Mapped[list[str]] = mapped_column(JSON)
    fields: Mapped[list[str]] = mapped_column(JSON)
    limitations: Mapped[list[str]] = mapped_column(JSON)
    evidence: Mapped[list[str]] = mapped_column(JSON)
    sample_status: Mapped[str]
    decision: Mapped[str]
    reviewed_at: Mapped[date]
```

探测记录保存 `started_at`、`completed_at`、`outcome`、`http_status`、`latency_ms`、`fields_present`、`sample_count`、`latest_published_at`、`schema_fingerprint`、`error_code` 和经过脱敏的 `details`。

- [ ] **步骤 4：实现幂等同步和版本兼容**

Repository 用 `(source_id, candidate_key)` 更新当前投影；同一规范化 YAML Hash 不新增版本。程序不得修改 YAML 或自动改变 `research.status`。

- [ ] **步骤 5：执行迁移与仓储测试**

```powershell
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run pytest tests/sources/test_research_repository.py tests/sources/test_repository.py tests/test_migrations.py -q
```

预期：`20260712_0009 (head)`，无遗漏迁移，测试通过。

- [ ] **步骤 6：提交任务 2**

```powershell
git add src/newsradar/db/models.py src/newsradar/sources/repository.py migrations/versions/20260712_0009_source_research_v3.py tests
git commit -m "feat: 持久化来源研究结论"
```

---

## 任务 3：目录审计引擎、CLI 与中文报告

**文件：**

- 创建：`src/newsradar/research/__init__.py`
- 创建：`src/newsradar/research/audit.py`
- 创建：`src/newsradar/research/reporting.py`
- 修改：`src/newsradar/cli.py`
- 创建：`tests/research/test_audit.py`
- 创建：`tests/research/test_reporting.py`
- 修改：`tests/test_cli.py`

**接口：**

```python
def audit_source_catalog(
    providers: tuple[ProviderDefinition, ...],
    sources: tuple[SourceDefinition, ...],
) -> ResearchAuditReport: ...

def render_research_report(report: ResearchAuditReport) -> str: ...
```

新增命令：

```text
newsradar sources research validate
newsradar sources research audit
newsradar sources research report --output reports/source-research-v3.md
```

- [ ] **步骤 1：写审计规则失败测试**

覆盖：

- `universe-*-1/2` 仅作为占位提示，不被程序自动改状态。
- Provider 首页作为 Target URL 时产生 `generic_platform_target`。
- 同一 `official_identity_url` 的同 Provider 目标产生重复候选。
- `verified` 缺用途、首选方式、样本或备用说明时为错误。
- `needs_research` 可合法存在，但计入未完成研究。
- `placeholder`、`duplicate`、`retired` 不计入真实覆盖。
- API、HTML、第三方库和聚合发现分别计数。

- [ ] **步骤 2：实现不可变审计结果**

```python
@dataclass(frozen=True)
class AuditFinding:
    code: str
    severity: Literal["error", "warning", "info"]
    source_id: str | None
    provider_id: str | None
    message_zh: str


@dataclass(frozen=True)
class ResearchAuditReport:
    provider_count: int
    target_count: int
    status_counts: Mapping[str, int]
    method_counts: Mapping[str, int]
    findings: tuple[AuditFinding, ...]
```

审计只读 YAML，不写入配置、不启用来源、不调用模型。

- [ ] **步骤 3：实现中文 Markdown 报告**

报告包含：Provider 总数、真实 Target、占位、重复、退役、待研究、已验证；按来源类别和候选方式统计；逐来源列出用途、所需信息、首选/补充/备用、样本、风险和未完成项。

- [ ] **步骤 4：接入嵌套 Typer 命令并测试**

```powershell
uv run newsradar sources research validate --root sources --provider-root providers
uv run newsradar sources research audit --root sources --provider-root providers
uv run pytest tests/research tests/test_cli.py -q
```

预期：命令输出中文；审计错误返回非零，警告不阻止生成报告。

- [ ] **步骤 5：提交任务 3**

```powershell
git add src/newsradar/research src/newsradar/cli.py tests/research tests/test_cli.py
git commit -m "feat: 增加来源研究审计工具"
```

---

## 任务 4：YouTube 多路径研究样板

**文件：**

- 修改：`pyproject.toml`
- 修改：`uv.lock`
- 创建：`src/newsradar/research/probes/__init__.py`
- 创建：`src/newsradar/research/probes/schema.py`
- 创建：`src/newsradar/research/probes/youtube.py`
- 修改：`src/newsradar/cli.py`
- 修改：`providers/youtube.yaml`
- 修改：`sources/universe/universe-youtube-1.yaml`
- 修改：`sources/universe/universe-no-priors-1.yaml`
- 创建：`tests/research/probes/test_youtube.py`
- 修改：`tests/test_cli.py`
- 创建：`tests/fixtures/research/youtube_atom.xml`
- 创建：`tests/fixtures/research/youtube_api.json`
- 创建：`tests/fixtures/research/youtube_transcript.json`

**接口：**

```python
class ResearchProbe(Protocol):
    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ) -> AcquisitionProbeResult: ...


class YouTubeResearchProbe:
    async def probe_atom(...): ...
    async def probe_data_api(...): ...
    async def probe_transcript(...): ...
    def inspect_ytdlp_metadata(...): ...
```

- [ ] **步骤 1：写四路径固定样本测试**

测试 Atom 提取视频 ID、标题、频道和时间；Data API 无 Key 返回 `blocked/missing_credential`，有 Key 时提取详情和互动；字幕库提取语言、生成类型和文本可用性；yt-dlp 仅记录版本、许可证和候选能力，不执行媒体下载。

- [ ] **步骤 2：增加研究可选依赖**

```toml
[project.optional-dependencies]
research = [
    "youtube-transcript-api==1.2.4",
]
```

不得增加代理依赖，不配置 Cookie。字幕库的 `RequestBlocked`、`IpBlocked`、`TranscriptsDisabled`、`NoTranscriptFound` 均映射为可读、可降级的研究结果。

- [ ] **步骤 3：实现 YouTube 研究 Probe**

Atom 使用现有 `HttpPolicy` 和 `feedparser`；Data API 使用现有凭据提供器但只读取 `YOUTUBE_API_KEY`；字幕库通过线程边界执行并设置总超时；所有结果限制文本长度，不保存完整视频或音频。此任务先为 `sources research probe` 接入 YouTube Probe，任务 5 再将命令扩展到通用 Probe Factory。

`yt-dlp` 初始不加入依赖，只通过官方 GitHub/PyPI 元数据记录维护状态、许可证和用途，结论固定为 `manual_only`，不执行下载命令。

- [ ] **步骤 4：把 OpenAI YouTube 和 No Priors 改成真实研究档案**

OpenAI YouTube 的候选组合：

- `youtube-atom`：`primary`、官方、无认证、负责发现；
- `youtube-data-api`：`supplement`、官方、API Key、负责描述与互动；
- `youtube-transcript-api`：`supplement`、非官方库、无认证、负责重点视频文字稿；
- `yt-dlp-metadata`：`manual_only`、非官方库、不下载媒体；
- 无登录 Cookie 候选。

No Priors 使用同一模型，但只有确认频道 ID 后 Atom 候选才能标记成功；未确认字段保持 `needs_research`，不能伪造 `verified`。

- [ ] **步骤 5：运行固定样本和一次真实 Atom 探测**

```powershell
uv sync --extra dev --extra research
uv run pytest tests/research/probes/test_youtube.py -q
uv run newsradar sources research probe openai-youtube --candidate youtube-atom --limit 5
```

预期：固定测试通过；真实 Atom 最多返回五条公开视频元数据。没有 YouTube Key 时 Data API 明确阻塞，但不影响 Atom 结论。

- [ ] **步骤 6：提交任务 4**

```powershell
git add pyproject.toml uv.lock src/newsradar/research/probes src/newsradar/cli.py providers/youtube.yaml sources/universe/universe-youtube-1.yaml sources/universe/universe-no-priors-1.yaml tests
git commit -m "feat: 建立 YouTube 多路径研究样板"
```

---

## 任务 5：通用候选方式研究探测框架

**文件：**

- 创建：`src/newsradar/research/probes/feed.py`
- 创建：`src/newsradar/research/probes/api.py`
- 创建：`src/newsradar/research/probes/sitemap.py`
- 创建：`src/newsradar/research/probes/html.py`
- 创建：`src/newsradar/research/probes/library.py`
- 创建：`src/newsradar/research/probes/factory.py`
- 修改：`src/newsradar/research/probes/schema.py`
- 创建：`tests/research/probes/test_feed.py`
- 创建：`tests/research/probes/test_api.py`
- 创建：`tests/research/probes/test_sitemap.py`
- 创建：`tests/research/probes/test_html.py`
- 创建：`tests/research/probes/test_library.py`
- 修改：`src/newsradar/cli.py`

**接口：**

```python
def research_probe_for(candidate: AcquisitionCandidate) -> ResearchProbe: ...
```

CLI：

```text
newsradar sources research probe <source-id> --candidate <candidate-key> --limit 5
```

- [ ] **步骤 1：先写协议边界测试**

覆盖：RSS/Atom/WebSub、公开/API Key/OAuth 能力、Sitemap 索引、静态 HTML、JSON-LD、OpenGraph、内嵌 JSON 和第三方库元数据。验证：

- HTML Probe 不执行 JavaScript；
- 不发送 Cookie、Authorization 或 YAML 中未审核的敏感 Header；
- robots 5xx 按不可达处理并阻止自动内容探测；
- robots 允许不等于条款批准，结果保留 `terms_review_required`；
- 登录墙、验证码、付费墙和需要浏览器会话时返回 `blocked`；
- 单响应不超过 2 MB，最多五条样本；
- Probe 不修改 `ingestion.enabled`、`research.status` 或 YAML。

- [ ] **步骤 2：实现统一结果和字段矩阵**

`AcquisitionProbeResult` 输出：成功状态、候选 Key、能力或内容探测类型、HTTP 信息、样本数、最新时间、字段完整率、分页、缓存、限流、结构指纹、阻塞条件、可读中文原因和脱敏详情。

- [ ] **步骤 3：实现 HTML 研究边界**

HTML 只解析：

- `<link rel="canonical">`；
- `<link rel="alternate">`；
- `application/ld+json`；
- OpenGraph；
- 语义化 `article` 元数据；
- 经 YAML 明确审核的站点选择器。

不在本任务实现生产 HTML Fetcher。动态渲染、登录 Cookie、Cloudflare 挑战和验证码统一阻塞。

- [ ] **步骤 4：持久化探测历史并接入 CLI**

单来源失败不得中断其他候选；数据库不可用时允许 `--no-persist` 输出内存报告。所有上游错误 URL、Query 和 Header 必须脱敏。

- [ ] **步骤 5：运行研究 Probe 全套测试**

```powershell
uv run pytest tests/research/probes tests/acceptance/test_nonblocking_web.py -q
```

预期：通过；研究 Probe 不触发生产抓取、事件发布或模型调用。

- [ ] **步骤 6：提交任务 5**

```powershell
git add src/newsradar/research/probes src/newsradar/cli.py tests/research/probes
git commit -m "feat: 增加候选方式研究探测"
```

---

## 任务 6：审计当前 Provider/Target 并扩展真实来源矩阵

**文件：**

- 修改：`providers/*.yaml`
- 修改：`sources/**/*.yaml`
- 创建：`reports/source-research-v3-audit.md`
- 创建：`reports/source-research-v3-matrix.md`
- 创建：`tests/research/test_catalog_completion.py`

**接口：**

- 输入：任务 3 的审计结果和任务 5 的研究探测结果。
- 输出：每个当前 Provider/Target 的明确研究状态，以及逐来源候选方式矩阵。

- [ ] **步骤 1：生成完整审计队列**

```powershell
uv run newsradar sources research audit --root sources --provider-root providers --output reports/source-research-v3-audit.md
```

报告列出全部 Provider 和 Target，不允许仅抽样。每项包含真实身份、占位/重复提示、所需信息缺口和候选方式缺口。

- [ ] **步骤 2：按来源类别完成 Provider 复核**

依次复核：官方机构、专业媒体、社区社交、聚合搜索、研究开发、Newsletter/播客、趋势商业监管。每个 Provider 使用官方主页、开发文档、条款和至少一个能力证据；允许合并、新增和退役。

- [ ] **步骤 3：逐项给当前 Target 明确状态**

全部当前 Target 必须得到以下之一：

- `verified`：完整研究档案；
- `needs_research`：真实目标存在但证据或样本未完成；
- `placeholder`：仅平台占位；
- `duplicate`：记录替代 Target ID；
- `retired`：记录退役原因。

不得根据文件名自动做最终结论；审计提示必须经过人工证据复核后写入 YAML。

- [ ] **步骤 4：扩展真实目标**

根据 AI/技术新闻用途补充真实频道、账号、栏目、Newsletter、Podcast、研究查询、开发项目和商业监管入口。新增数量由研究价值决定，不设置 15、50 或 166 的上限。

- [ ] **步骤 5：生成逐来源方法矩阵**

```powershell
uv run newsradar sources research report --root sources --provider-root providers --output reports/source-research-v3-matrix.md
```

矩阵逐项显示所需信息、全部候选方式、字段、样本、首选、补充、备用、禁用、凭据、成本和风险。

- [ ] **步骤 6：增加目录完成度测试**

```python
def test_every_catalog_target_has_explicit_research_status(source_yaml_documents):
    assert all("research" in document for document in source_yaml_documents)


def test_placeholder_targets_do_not_count_as_real_coverage(audit_report):
    assert audit_report.real_target_count == sum(
        count for status, count in audit_report.status_counts.items()
        if status in {"verified", "needs_research"}
    )
```

并验证所有 `verified` 项满足任务 1 的严格条件。

- [ ] **步骤 7：提交任务 6**

```powershell
git add providers sources reports/source-research-v3-audit.md reports/source-research-v3-matrix.md tests/research/test_catalog_completion.py
git commit -m "data: 完成来源目录 v3 审计"
```

---

## 任务 7：中文来源研究网页

**文件：**

- 修改：`src/newsradar/web/viewmodels.py`
- 修改：`src/newsradar/web/queries.py`
- 修改：`src/newsradar/web/app.py`
- 修改：`src/newsradar/web/i18n.py`
- 修改：`src/newsradar/web/templates/base.html`
- 创建：`src/newsradar/web/templates/research_dashboard.html`
- 创建：`src/newsradar/web/templates/research_target.html`
- 修改：`src/newsradar/web/static/styles.css`
- 创建：`tests/web/test_research_queries.py`
- 创建：`tests/web/test_research_routes.py`

**接口：**

- `GET /research`：研究总览、状态、类别、方法和缺口。
- `GET /research/targets/{source_id}`：单 Target 的所需信息和候选方式矩阵。
- 页面只读，不执行网络探测、不修改 YAML、不调用 MiniMax。

- [ ] **步骤 1：先写查询和路由失败测试**

验证：

- 总览区分 Provider、目录 Target、真实 Target、已验证、待研究、占位、重复和退役；
- 第三方库不显示为官方 API；
- 能力探测不显示为已经抓取；
- Target 详情展示所需信息、候选方式、字段、限制、证据、样本和结论；
- API Key、OAuth、审批、付费、HTML、库和人工模式使用不同中文标签；
- 未知枚举安全回退，不泄漏凭据、Header、Query 或堆栈。

- [ ] **步骤 2：实现查询层和不可变 ViewModel**

查询使用 SQLAlchemy 一次批量加载研究 Profile、候选和最近探测，禁止每 Target N+1 查询。详情页只投影公开字段。

- [ ] **步骤 3：实现中文页面和流程引导**

总览按“先看来源—再看所需信息—比较候选方式—检查样本—阅读结论”的流程展示。Target 页面明确：

- 这是目录、能力还是已获取内容；
- 当前首选与备用方式；
- 还需要用户提供什么凭据、审批或决策；
- 哪些方式因为 Cookie、条款或付费被禁止。

- [ ] **步骤 4：执行网页测试和浏览器验收**

```powershell
uv run pytest tests/web/test_research_queries.py tests/web/test_research_routes.py tests/web -q
uv run newsradar web --port 8771
```

浏览器验收 `/research`、OpenAI YouTube、No Priors、一个 HTML 媒体、一个受限社交平台和一个占位 Target。

- [ ] **步骤 5：提交任务 7**

```powershell
git add src/newsradar/web tests/web
git commit -m "feat: 增加中文来源研究台"
```

---

## 任务 8：真实探测、完整验收与中文交付

**文件：**

- 修改：`README.md`
- 创建：`reports/source-research-v3-acceptance.md`
- 创建：`tests/acceptance/test_source_research_v3.py`

**接口：**

- 验收报告汇总 Schema、目录、YouTube、研究 Probe、网页、迁移和已知限制。
- 不把未提供凭据的平台写成已覆盖。

- [ ] **步骤 1：运行离线完整门禁**

```powershell
uv run pytest -q
uv run ruff check src tests migrations
uv run alembic current
uv run alembic check
git diff --check
```

预期：全部通过，迁移头为 `20260712_0009 (head)`。

- [ ] **步骤 2：运行真实网络研究探测**

至少覆盖：

- YouTube OpenAI 官方 Atom；
- YouTube Data API 无 Key 的明确阻塞；有 Key 时补充一轮详情探测；
- `youtube-transcript-api` 对一个确认有字幕的公开视频，仅记录文字稿可用性和有界样本；
- 一个 RSS/Atom 媒体；
- 一个 Sitemap；
- 一个经人工批准的静态 HTML 文章；
- 一个 Bluesky 或 Mastodon 公开 API；
- X、LinkedIn、TikTok 等受限平台的能力阻塞结论。

不使用代理、Cookie、验证码或浏览器登录态。

- [ ] **步骤 3：验证目录完整性**

```powershell
uv run newsradar sources research validate --root sources --provider-root providers
uv run newsradar sources research report --root sources --provider-root providers --output reports/source-research-v3-matrix.md
```

预期：全部当前 Provider/Target 有明确研究状态；`verified` 项无 Schema 错误；占位项不计入真实覆盖。

- [ ] **步骤 4：写中文 README 和验收报告**

README 说明：

- 如何理解 Provider、Target、WantedInformation 和候选方式；
- 如何运行审计、探测和报告；
- YouTube Atom、Data API、字幕库和 yt-dlp 的区别；
- HTML 研究与生产抓取的边界；
- 如何读取中文网页并提供 Key 或审批；
- 所有凭据的最小权限和风险。

验收报告记录实际成功、部分、阻塞、失败和未运行，不隐瞒覆盖缺口。

- [ ] **步骤 5：最终代码审查**

使用 5.6 Sol + 高推理进行全分支只读审查，修复所有 Critical 和 Important 问题后重新运行步骤 1–4。

- [ ] **步骤 6：提交任务 8**

```powershell
git add README.md reports tests/acceptance/test_source_research_v3.py
git commit -m "docs: 完成来源研究 v3 验收"
```

## 完成定义

- 研究数据结构、数据库、审计 CLI、YouTube 样板、通用研究 Probe、目录审计和中文网页全部通过测试。
- 当前全部 Provider/Target 得到明确研究状态；数量可以增长，不受原 166 项限制。
- YouTube 不再因为没有 Key 被误判为完全不可用，Atom、API、字幕库和人工诊断边界清晰。
- HTML 被作为逐来源研究候选，而不是全局启用或全局禁止。
- 第三方库与官方 API 在 Schema、报告和网页中明确区分。
- 没有凭据、第三方库或 MiniMax 时，现有抓取、事件、来源健康和网页仍可工作。
- 所有禁用或受限方式都有中文原因、证据和解锁条件。
