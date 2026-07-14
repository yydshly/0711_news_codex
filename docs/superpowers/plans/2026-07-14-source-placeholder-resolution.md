# 来源重复占位项收口实施计划

> **供执行代理使用：** 必须使用 `superpowers:executing-plans` 按任务逐项执行；每一步使用复选框跟踪。

**目标：** 将 19 组重复的 `universe-*-1/-2` 目录项收口为“19 条重复历史项 + 19 条待研究的间接发现入口”，并在中文网页中清楚解释。

**架构：** YAML 是来源目录真相。审计只依据 `research.status` 判断占位；`-1` 保留为 `duplicate` 历史项，`-2` 保留为 `needs_research` 的唯一间接发现入口。现有同步投影将状态和结论写入 PostgreSQL，网页直接显示，无需数据库迁移。

**技术栈：** Python 3.12、Pydantic 2、PyYAML、SQLAlchemy、FastAPI/Jinja2、pytest、Ruff。

## 全局约束

- 只处理 19 组重复目录记录，不新增抓取器、摘要、事件、推荐或调度。
- 166 个来源 ID 不变；54 个已启用来源的 `ingestion` 配置不变。
- 不执行网络探测或真实抓取；同步只更新既有记录。
- 所有网页文案和新增文档使用中文。
- 修改生产代码前必须先写失败测试并确认失败。

---

### 任务 1：修正审计的占位判断

**文件：**

- 修改：`src/newsradar/research/audit.py:120-143`
- 修改：`tests/research/test_audit.py`
- 修改：`tests/research/test_catalog_completion.py`

**接口：** `audit_source_catalog(providers, sources) -> ResearchAuditReport`。只有 `research.status == placeholder` 产生 `placeholder_target` 警告；ID 命名不改变审计结论。

- [ ] **步骤 1：写失败测试。**

```python
def test_audit_does_not_treat_universe_id_as_placeholder() -> None:
    report = audit_source_catalog((), (_source(id="universe-openai-2"),))
    assert not any(finding.code == "placeholder_target" for finding in report.findings)

def test_audit_flags_explicit_placeholder_status() -> None:
    report = audit_source_catalog(
        (), (_source(id="real-placeholder", research={"status": "placeholder"}),)
    )
    assert [finding.code for finding in report.findings] == ["placeholder_target"]
```

- [ ] **步骤 2：确认测试失败。**

运行：`uv run pytest tests/research/test_audit.py::test_audit_does_not_treat_universe_id_as_placeholder -q`

预期：失败，旧逻辑按 ID 后缀产生 `placeholder_target`。

- [ ] **步骤 3：最小实现。**

将基于 `source.id.startswith("universe-")` 的判断替换为：

```python
if source.research.status == ResearchStatus.PLACEHOLDER:
    findings.append(
        AuditFinding(
            code="placeholder_target",
            severity="warning",
            source_id=source.id,
            provider_id=source.provider_id,
            message_zh="该 Target 只是平台或概念占位，尚未确认可独立探测的具体入口。",
        )
    )
```

- [ ] **步骤 4：验证。**

运行：`uv run pytest tests/research/test_audit.py tests/research/test_catalog_completion.py -q`

预期：全部通过。

### 任务 2：收口 19 组 YAML 记录

**文件：**

- 修改：`sources/universe/universe-{anthropic,arxiv,bluesky,gdelt,github,google-ai,google-news,hackernews,huggingface-papers,mastodon,npm,nvidia,openai,openreview,polymarket,pypi,sec-edgar,semantic-scholar,the-batch}-{1,2}.yaml`
- 新建：`tests/research/test_placeholder_resolution_catalog.py`

**接口：** `load_source_tree(Path("sources")) -> list[SourceDefinition]`。每组 `-1` 是 `duplicate`，每组 `-2` 是 `needs_research`，两侧 `ingestion.enabled is False`。

- [ ] **步骤 1：写失败目录测试。**

```python
PAIR_BASES = (
    "anthropic", "arxiv", "bluesky", "gdelt", "github", "google-ai",
    "google-news", "hackernews", "huggingface-papers", "mastodon", "npm",
    "nvidia", "openai", "openreview", "polymarket", "pypi", "sec-edgar",
    "semantic-scholar", "the-batch",
)

def test_duplicate_placeholder_pairs_have_one_canonical_discovery_target() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    for base in PAIR_BASES:
        duplicate = sources[f"universe-{base}-1"]
        canonical = sources[f"universe-{base}-2"]
        assert duplicate.research.status.value == "duplicate"
        assert canonical.research.status.value == "needs_research"
        assert not duplicate.ingestion.enabled
        assert not canonical.ingestion.enabled
        assert str(duplicate.access_methods[0].url) == str(canonical.access_methods[0].url)

def test_placeholder_resolution_keeps_catalog_and_enabled_sources_unchanged() -> None:
    sources = list(load_source_tree(Path("sources")))
    assert len(sources) == 166
    assert sum(source.ingestion.enabled for source in sources) == 54
```

- [ ] **步骤 2：确认测试失败。**

运行：`uv run pytest tests/research/test_placeholder_resolution_catalog.py -q`

预期：失败，当前记录仍为 `placeholder`。

- [ ] **步骤 3：更新 YAML。**

每个 `-1` 使用：

```yaml
research:
  status: duplicate
  conclusion: 此记录与 universe-<provider>-2 使用相同入口；保留为目录审计历史，不参与探测或抓取。
  reviewed_at: '2026-07-14'
```

每个 `-2` 使用：

```yaml
research:
  status: needs_research
  purpose: 通过间接聚合查询发现与该 Provider 相关的 AI/技术新闻线索。
  wanted_information: [title, canonical_url, published_at, summary]
  conclusion: 这是唯一保留的间接发现入口；聚合结果只能用于发现，事实必须回到官方或独立专业媒体确认。
  risk_conclusion: 不使用登录 Cookie、代理绕过或页面抓取；在完成样本、字段、条款和备用方式审核前保持未启用。
  reviewed_at: '2026-07-14'
```

- [ ] **步骤 4：验证目录与 schema。**

运行：`uv run pytest tests/research/test_placeholder_resolution_catalog.py tests/test_source_schema.py tests/research/test_catalog_completion.py -q`

预期：全部通过。

### 任务 3：网页中文解释、同步与验收

**文件：**

- 修改：`src/newsradar/web/templates/research_target.html`
- 修改：`tests/web/test_research_routes.py`
- 新建：`reports/source-placeholder-resolution.md`

**接口：** `ResearchQueryService.research_target(source_id) -> ResearchTargetView | None` 和 `newsradar sources sync`。详情页解释重复、待研究、占位；同步后数据库中这 38 条为 19 条 `duplicate` 和 19 条 `needs_research`。

- [ ] **步骤 1：写失败网页测试。**

```python
def test_research_target_explains_duplicate_and_needs_research_status(client) -> None:
    duplicate = client.get("/research/targets/universe-openai-1")
    canonical = client.get("/research/targets/universe-openai-2")
    assert "历史目录项" in duplicate.text
    assert "不会参与抓取" in duplicate.text
    assert "尚未完成样本、字段、条款和备用方式验证" in canonical.text
```

- [ ] **步骤 2：确认测试失败。**

运行：`uv run pytest tests/web/test_research_routes.py::test_research_target_explains_duplicate_and_needs_research_status -q`

预期：失败，模板尚未按研究状态渲染解释。

- [ ] **步骤 3：最小模板实现。**

在研究状态段落之后加入：

```jinja2
{% if target.research_status == 'duplicate' %}
<p class="metric-note">重复：这是保留的历史目录项，已由研究结论中的规范入口替代，不会参与探测或抓取。</p>
{% elif target.research_status == 'needs_research' %}
<p class="metric-note">待研究：入口已登记，但尚未完成样本、字段、条款和备用方式验证，当前不会自动启用。</p>
{% elif target.research_status == 'placeholder' %}
<p class="metric-note">占位：只有平台或概念登记，尚未形成可独立探测的具体目标。</p>
{% endif %}
```

- [ ] **步骤 4：网页与静态验证。**

运行：`uv run pytest tests/web/test_research_routes.py -q && uv run ruff check src tests`

预期：全部通过。

- [ ] **步骤 5：同步数据库并做只读验证。**

运行：`$env:DATABASE_URL=(Get-Content ..\\..\\.env | Select-String '^DATABASE_URL=' | ForEach-Object { $_.Line.Substring(13) }); uv run newsradar sources sync`

随后运行：

```powershell
$env:DATABASE_URL=(Get-Content ..\\..\\.env | Select-String '^DATABASE_URL=' | ForEach-Object { $_.Line.Substring(13) })
uv run python -c "from sqlalchemy import create_engine,text; import os; e=create_engine(os.environ['DATABASE_URL']); print(e.connect().execute(text(\"select status,count(*) from source_research_profiles where source_id like 'universe-%' group by status order by status\")).all())"
```

预期：本次记录中 19 条 `duplicate` 和 19 条 `needs_research`；启用来源仍为 54。

- [ ] **步骤 6：写验收报告并完整回归。**

报告记录处理的 19 组、启用来源数、目录总数、同步结果和网页验证结果。

运行：`uv run pytest -q && uv run ruff check src tests`

预期：完整测试通过，Ruff 无错误。

- [ ] **步骤 7：提交实现。**

```powershell
git add src/newsradar/research/audit.py src/newsradar/web/templates/research_target.html sources/universe tests/research tests/web reports/source-placeholder-resolution.md
git commit -m "fix: resolve duplicate source placeholders"
```

## 计划自检

- 规格中的目录、审计、网页、同步和验收均有对应任务。
- 计划没有新增抓取器、删除历史或修改 54 个已启用来源。
- 每个生产代码改动先定义失败测试和精确验证命令。
