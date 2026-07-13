# 来源失败修复批次实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对基线中 27 个最新内容探测未成功的来源完成确定性归因、官方获取方式复核、受控候选验证和中文可视化，并在不放开生产 HTML 抓取的前提下扩大可试用 RSS/API 来源。

**Architecture:** 从 PostgreSQL 按固定基线时间生成不可变失败清单，规则分类器只消费脱敏探测证据。候选验证复用现有研究探测器和安全 HTTP 客户端，通过独立 Worker 操作逐个执行；YAML 仍是人工审核真相，网页只读展示结论。

**Tech Stack:** Python 3.12、Pydantic 2、SQLAlchemy 2、Alembic、Typer、HTTPX、FastAPI/Jinja2、PostgreSQL、pytest、respx。

## 全局约束

- 不重新探测全部 166 个来源；固定基线中的 27 个目标必须全部保留在最终报告。
- 不使用登录态、Cookie、验证码绕过、代理轮换、IP 绕过、无头浏览器、JavaScript 或非官方私有接口。
- HTML 本批次仅作为研究候选，始终保持 `manual_only` 或 `catalog_only`，不能产生 RawItem。
- 候选验证必须使用 `new_safe_probe_client` / `safe_get`；不得使用自动跟随跳转的生产抓取客户端。
- 每次最多五条样本、20 秒超时、2 MB 响应上限、每主机并发 1、最多五次审核域跳转。
- 401、403、429、端点变化、字段不完整和未知错误不自动重试；网络临时失败只允许后续显式创建一次新操作。
- YAML 是人工审核真相，程序不得自动修改 YAML。
- MiniMax 不参与失败分类、访问批准、重试或来源启用；模型不可用不影响本阶段。
- 日志、数据库、报告和网页不得出现 API Key、Cookie、授权头、数据库连接串、代理详情或 URL 查询参数。

---

## 文件结构

- `src/newsradar/remediation/schema.py`：批次清单、失败分类和网页/报告投影类型。
- `src/newsradar/remediation/classifier.py`：从最新持久化探测证据生成确定性分类。
- `src/newsradar/remediation/repository.py`：按基线时间查询失败清单及原探测记录。
- `src/newsradar/remediation/reporting.py`：输出中文 Markdown 报告。
- `src/newsradar/remediation/runtime.py`：Worker 中执行单 Target、单候选研究探测。
- `src/newsradar/remediation/__init__.py`：稳定公开接口。
- `src/newsradar/sources/schema.py`：候选方式的显式审核跳转域。
- `src/newsradar/research/probes/safe_http.py`：逐跳审核域校验。
- `src/newsradar/operations/{schema.py,commands.py,retry_policy.py}`：修复操作的队列、串行门禁和不可自动重试语义。
- `src/newsradar/web/{viewmodels.py,queries.py,app.py}` 与模板：中文只读修复台。
- `migrations/versions/20260713_0011_source_remediation_redirect_hosts.py`：持久化 HTML selector 和审核跳转域。
- `reports/source-failure-remediation.md`：27 项真实审核与验证结果。

---

### Task 1：不可变失败清单、规则归因与报告骨架

**Files:**
- Create: `src/newsradar/remediation/__init__.py`
- Create: `src/newsradar/remediation/schema.py`
- Create: `src/newsradar/remediation/classifier.py`
- Create: `src/newsradar/remediation/repository.py`
- Create: `src/newsradar/remediation/reporting.py`
- Test: `tests/remediation/test_classifier.py`
- Test: `tests/remediation/test_repository.py`
- Test: `tests/remediation/test_reporting.py`

**Interfaces:**
- Produces: `FailureCategory`, `RemediationEntry`, `RemediationManifest`。
- Produces: `classify_probe(run: SourceProbeRunRecord) -> FailureCategory`。
- Produces: `RemediationRepository.manifest(baseline_at: datetime) -> RemediationManifest`。
- Produces: `render_remediation_report(manifest: RemediationManifest) -> str`。

- [ ] **Step 1: 写归因模型和失败分类测试**

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict

class FailureCategory(StrEnum):
    NETWORK_TRANSIENT = "network_transient"
    RATE_LIMITED = "rate_limited"
    ENDPOINT_CHANGED = "endpoint_changed"
    CONTENT_INCOMPLETE = "content_incomplete"
    AUTHENTICATION_OR_POLICY = "authentication_or_policy"
    UNKNOWN = "unknown"

class RemediationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    source_name: str
    original_probe_id: int
    original_finished_at: datetime
    category: FailureCategory
    reason_zh: str
    next_action_zh: str
```

测试必须覆盖 401、403、404、429、500、超时、TLS/DNS、解析错误、零样本、缺字段和未知错误，并断言分类不调用网络或 MiniMax。

- [ ] **Step 2: 运行归因测试，确认因模块尚不存在而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/remediation/test_classifier.py -q`

Expected: FAIL，提示 `newsradar.remediation` 尚不存在。

- [ ] **Step 3: 实现确定性分类器**

```python
def classify_probe(run: SourceProbeRunRecord) -> FailureCategory:
    code = (run.error_code or "").lower()
    if run.http_status in {401, 403} or code in POLICY_CODES:
        return FailureCategory.AUTHENTICATION_OR_POLICY
    if run.http_status == 429 or code == "rate_limited":
        return FailureCategory.RATE_LIMITED
    if run.http_status == 404 or code in ENDPOINT_CODES:
        return FailureCategory.ENDPOINT_CHANGED
    if code in INCOMPLETE_CODES or _has_incomplete_metrics(run.metrics):
        return FailureCategory.CONTENT_INCOMPLETE
    if run.http_status is not None and 500 <= run.http_status <= 599:
        return FailureCategory.NETWORK_TRANSIENT
    if code in NETWORK_CODES:
        return FailureCategory.NETWORK_TRANSIENT
    return FailureCategory.UNKNOWN
```

中文说明使用固定映射；不得把 `run.reason` 原样作为 HTML 输出。

- [ ] **Step 4: 写清单查询和冻结语义测试**

构造同一来源在基线前失败、基线后成功的两条记录，断言清单仍选择基线前失败记录；构造基线前成功来源，断言不进入清单。按 `source_id` 排序并保存原 `probe_run_id`。

- [ ] **Step 5: 实现清单 Repository 和中文报告**

查询使用窗口函数：只选 `finished_at <= baseline_at` 的最新已完成探测，再筛选 `outcome != success`。报告包含基线时间、总数、六类数量、每个 Target 的原探测 ID、分类、中文原因、候选方式、验证结论和下一步动作；证据 URL 统一移除 query/fragment。

- [ ] **Step 6: 运行 Task 1 测试与静态检查**

Run: `.\.venv\Scripts\python.exe -m pytest tests/remediation -q`

Expected: PASS。

Run: `.\.venv\Scripts\ruff.exe check src/newsradar/remediation tests/remediation`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add src/newsradar/remediation tests/remediation
git commit -m "feat: classify failed source probes"
```

---

### Task 2：审核域跳转和 HTML 研究边界

**Files:**
- Modify: `src/newsradar/sources/schema.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `src/newsradar/sources/repository.py`
- Modify: `src/newsradar/research/probes/safe_http.py`
- Create: `migrations/versions/20260713_0011_source_remediation_redirect_hosts.py`
- Modify: `tests/test_research_schema.py`
- Modify: `tests/test_research_repository.py`
- Modify: `tests/research/probes/test_security.py`
- Modify: `tests/ingestion/test_trial.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces: `AcquisitionCandidate.allowed_redirect_hosts: tuple[str, ...]`。
- `safe_get()` 仅允许初始候选域及 `allowed_redirect_hosts` 中的跳转域。
- 保持 `evaluate_trial_eligibility()` 对所有 HTML 的拒绝。

- [ ] **Step 1: 写 Schema 和跳转安全失败测试**

```python
def test_candidate_rejects_url_shaped_redirect_host():
    with pytest.raises(ValidationError):
        candidate(allowed_redirect_hosts=("https://example.com/path",))

@pytest.mark.asyncio
async def test_safe_get_blocks_unreviewed_cross_domain_redirect():
    response = httpx.Response(302, headers={"location": "https://other.example/news"})
    with pytest.raises(UnsafeProbeUrl):
        await safe_get(policy(response), candidate(allowed_redirect_hosts=()), START_URL)
```

同时测试大小写归一化、重复域拒绝、HTTP URL 拒绝、同域跳转允许、显式跨域允许、敏感 query 拒绝和最多五次跳转。

- [ ] **Step 2: 运行相关测试并确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_schema.py tests/research/probes/test_security.py -q`

Expected: FAIL，缺少 `allowed_redirect_hosts` 与审核域判断。

- [ ] **Step 3: 实现严格审核域字段**

```python
allowed_redirect_hosts: tuple[str, ...] = ()

@field_validator("allowed_redirect_hosts")
@classmethod
def validate_redirect_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(value.rstrip(".").lower() for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("allowed_redirect_hosts must not contain duplicates")
    for value in normalized:
        if not re.fullmatch(r"[a-z0-9.-]+", value) or ".." in value:
            raise ValueError("allowed_redirect_hosts must contain hostnames only")
    return normalized
```

`safe_get` 在每次请求前比较 `urlsplit(current).hostname`；首个证据 URL 的 host 自动允许，其他 host 必须显式列入候选字段。禁止通配符和子域自动扩展。

- [ ] **Step 4: 持久化审核域并补迁移测试**

为 `source_acquisition_candidates` 新增可空字符串列 `selector` 和非空 JSON 列 `allowed_redirect_hosts`（默认 `[]`）；同步投影写入两个字段。迁移 downgrade 只删除这两列，不改历史探测。

- [ ] **Step 5: 固化 HTML 不进入试用抓取**

新增测试：即使 HTML 候选 `sample_status=succeeded`、`decision=primary` 且有审核域，`evaluate_trial_eligibility` 仍返回 `no_automatic_method`；FetcherFactory 仍不提供 HtmlFetcher。

- [ ] **Step 6: 运行 Task 2 测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_schema.py tests/test_research_repository.py tests/research/probes/test_security.py tests/ingestion/test_trial.py tests/test_migrations.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add src/newsradar/sources src/newsradar/db src/newsradar/research/probes migrations/versions tests
git commit -m "feat: enforce audited research redirects"
```

---

### Task 3：可恢复的单来源修复 Worker 操作

**Files:**
- Create: `src/newsradar/remediation/runtime.py`
- Modify: `src/newsradar/operations/schema.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/operations/retry_policy.py`
- Modify: `src/newsradar/cli.py`
- Test: `tests/remediation/test_runtime.py`
- Modify: `tests/operations/test_commands.py`
- Modify: `tests/operations/test_router.py`
- Modify: `tests/operations/test_repository.py`

**Interfaces:**
- Produces: `OperationType.SOURCE_REMEDIATION`。
- Produces: `OperationCommandService.enqueue_source_remediation(...) -> int`。
- Produces: `OperationCommandService.retry_source_remediation(operation_id: int, trigger: str) -> int`。
- Produces: `SourceRemediationHandler.production(sources, create_session) -> Handler`。

- [ ] **Step 1: 写操作门禁、运行和非重试测试**

测试应断言：

- 同一时间第二个 queued/running 修复操作被 `active_source_remediation_exists` 拒绝；
- scope 必须包含 `source_id`、`candidate_key`、`original_probe_id` 和 `baseline_at`；
- 通用 `operations retry` 永远拒绝修复操作；专用 retry 只允许 `network_transient` 且同一原始操作最多一次；
- 原探测不属于来源、候选不存在、候选要求凭据或候选为 rejected 时不发送网络请求；
- 401、403、429、404、字段不完整、未知错误均返回 `retryable=False`；
- HTML 成功只保存研究探测，不调用 IngestionService、不创建 RawItem；
- Worker 取消或租约丢失时结果不能覆盖现有操作状态。

- [ ] **Step 2: 运行测试并确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/remediation/test_runtime.py tests/operations/test_commands.py -q`

Expected: FAIL，缺少修复操作类型和 Handler。

- [ ] **Step 3: 实现串行入队门禁**

```python
def enqueue_source_remediation(self, *, source_id: str, candidate_key: str,
                               original_probe_id: int, baseline_at: datetime,
                               trigger: str) -> int:
    self.session.execute(text(
        "SELECT pg_advisory_xact_lock(hashtext('newsradar:source-remediation-enqueue'))"
    ))
    active = self.session.scalar(select(OperationRunRecord.id).where(
        OperationRunRecord.operation_type == OperationType.SOURCE_REMEDIATION.value,
        OperationRunRecord.status.in_(["queued", "running"]),
    ))
    if active is not None:
        raise ValueError("active_source_remediation_exists")
    # enqueue with deadline and immutable baseline evidence
```

SQLite 单元测试路径使用进程内锁替身；PostgreSQL 验收验证真实 advisory transaction lock。门禁只覆盖短入队事务，不在网络期间占用数据库事务。

实现 `retry_source_remediation`：读取原操作的终态和 `result_summary["category"]`，仅当类别为 `network_transient`、没有已有 `retry_of_operation_id` 且数据库中不存在指向该操作的修复操作时，复制不可变 scope 并写入 `retry_of_operation_id`。其他情况抛出 `source_remediation_retry_not_allowed`。

- [ ] **Step 4: 实现 Worker Handler**

Handler 从当前 YAML 重新加载 source/candidate，核对原探测记录，调用 `research_probe_for(source, candidate)`，网络调用发生在数据库事务外；完成后在新事务中调用 `save_acquisition_probe_run`。所有结果均 `retryable=False`，网络临时失败的再次验证必须由显式新命令创建。

```python
return OperationResult(
    status=OperationStatus.SUCCEEDED if result.outcome == "succeeded" else OperationStatus.PARTIAL,
    error_code=result.error_code,
    error_message=result.reason_zh,
    result_summary={
        "source_id": source.id,
        "candidate_key": candidate.key,
        "outcome": result.outcome.value,
        "sample_count": result.sample_count,
    },
    retryable=False,
)
```

- [ ] **Step 5: 注册路由并封闭通用 retry**

Worker Router 注册 `source_remediation`。把所有修复错误码加入 `NONRETRYABLE_ERROR_CODES`，并在 `OperationCommandService.retry` 中拒绝 `SOURCE_REMEDIATION`，避免通用命令复制请求；唯一入口是受次数约束的 `retry_source_remediation`。

- [ ] **Step 6: 运行 Task 3 测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/remediation/test_runtime.py tests/operations -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add src/newsradar/remediation/runtime.py src/newsradar/operations src/newsradar/cli.py tests/remediation tests/operations
git commit -m "feat: run bounded source remediation operations"
```

---

### Task 4：中文 CLI、修复台和来源下钻

**Files:**
- Modify: `src/newsradar/cli.py`
- Modify: `src/newsradar/web/viewmodels.py`
- Modify: `src/newsradar/web/queries.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/base.html`
- Create: `src/newsradar/web/templates/remediation.html`
- Modify: `src/newsradar/web/templates/target_detail.html`
- Test: `tests/remediation/test_cli.py`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_queries.py`
- Modify: `tests/web/test_security.py`

**Interfaces:**
- Produces CLI：`newsradar sources remediate snapshot`、`queue`、`retry`、`report`。
- Produces Web：`GET /remediation`，以及 Target 详情中的修复结论。

- [ ] **Step 1: 写 CLI 和网页失败测试**

CLI 测试固定 `--baseline-at` 为 ISO UTC 时间，断言 snapshot/report 输出 27 项结构；queue 必须显式提供 source/candidate/original probe，不提供 `--all`。网页测试断言中文分类、原探测 ID、候选状态、下一步和 HTML 研究标签存在，且页面没有写操作按钮。

- [ ] **Step 2: 运行测试并确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/remediation/test_cli.py tests/web/test_routes.py tests/web/test_queries.py -q`

Expected: FAIL，缺少命令和路由。

- [ ] **Step 3: 实现四个 CLI 命令**

```text
newsradar sources remediate snapshot --baseline-at <UTC> --output reports/source-failure-remediation.md
newsradar sources remediate queue <source-id> <candidate-key> --original-probe-id <id> --baseline-at <UTC> --wait
newsradar sources remediate retry <operation-id> --wait
newsradar sources remediate report --baseline-at <UTC> --output reports/source-failure-remediation.md
```

snapshot 显式持久化并冻结不可变批次；report 只读取已经冻结的批次，不得隐式写库。
queue 只创建单 Target 操作；retry 只接受一次网络临时失败。`--wait` 超时只退出等待，
不取消 Worker 操作。

- [ ] **Step 4: 实现 `/remediation` 只读页面**

页面显示：基线总数、六类数量、已复核、RSS/API 可验证、HTML 研究候选、政策阻塞和未知；表格支持分类/Provider/结论筛选。Target 详情显示原失败探测、候选方式、静态 selector、审核域、最近研究结果和中文下一步。

- [ ] **Step 5: 补网页安全断言**

对包含敏感 query、Authorization、Cookie、数据库 URL 和代理值的测试数据发起页面请求，断言响应中不存在原值；证据 URL 只保留 scheme/host/path。

- [ ] **Step 6: 运行 Task 4 测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/remediation tests/web -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add src/newsradar/cli.py src/newsradar/web tests/remediation tests/web
git commit -m "feat: add Chinese source remediation console"
```

---

### Task 5：逐项审核基线失败来源并登记官方候选

**Files:**
- Modify: `sources/*.yaml`（仅本批清单中经证据确认的 Target）
- Modify: `reports/source-failure-remediation.md`
- Test: `tests/research/test_catalog_completion.py`
- Test: `tests/ingestion/test_open_source_matrix.py`

**Interfaces:**
- Consumes: Task 1 的不可变清单和分类。
- Produces: 每个 Target 的首选方式、备用方式或无合规自动方式结论。

- [ ] **Step 1: 生成本批不可变清单**

运行 snapshot，记录精确 `baseline_at` 和 27 个原探测 ID。确认数量为 27；若实际数量不同，保留数据库事实并在报告解释与旧基线的差异，禁止手工补齐或删除。

- [ ] **Step 2: 按失败类别分组审核官方证据**

对每个 Target 只使用官方主页、官方 RSS/API 文档、官方 Sitemap/robots 和可核实条款。依次检查 RSS/Atom、公开 API、静态 HTML 研究候选；记录官方身份、证据 URL、字段、成本、权限、更新时间和备用方式。

- [ ] **Step 3: 更新 YAML 研究档案**

RSS/API 候选使用 `authentication: none` 和明确 decision；HTML 候选使用 `decision: manual_only`，提供静态 selector、审核域、限制、证据和审核日期。登录 Cookie 候选只能 `rejected`。不得修改 `ingestion.enabled`。

- [ ] **Step 4: 校验和同步**

Run: `.\.venv\Scripts\newsradar.exe sources validate --root sources`

Expected: 全部 YAML 通过，无未知字段、凭据、Cookie、HTTP URL 或重复 ID。

Run: `.\.venv\Scripts\newsradar.exe sources sync --root sources`

Expected: 同步成功且相同定义重复同步不产生新版本。

- [ ] **Step 5: 运行来源矩阵测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/research/test_catalog_completion.py tests/ingestion/test_open_source_matrix.py -q`

Expected: PASS。

- [ ] **Step 6: 提交审核目录**

```powershell
git add sources reports/source-failure-remediation.md tests/research/test_catalog_completion.py tests/ingestion/test_open_source_matrix.py
git commit -m "docs: audit failed source acquisition paths"
```

---

### Task 6：受控真实验证、资格重算与报告收口

**Files:**
- Modify: `sources/*.yaml`（仅真实验证后需要修正的候选结论）
- Modify: `reports/source-failure-remediation.md`
- Modify: `reports/source-trial-baseline.md`
- Test: `tests/acceptance/test_source_remediation.py`

**Interfaces:**
- Consumes: Task 5 中已审核且无凭据的候选。
- Produces: 27 项最终分类、实际验证结果和新的试用资格数量。

- [ ] **Step 1: 对已审核候选逐个排队验证**

每次只 queue 一个 Target，等待终态后再提交下一个。HTML 只产生研究探测记录；RSS/API 成功后再执行现有内容探测，不能直接更改试用资格。

- [ ] **Step 2: 验证错误停止策略**

至少保留并检查一条 401/403/政策阻塞、一条 429 或固定样本模拟、一条网络临时失败和一条字段不完整记录。确认操作没有自动重排三次，Worker 心跳和取消仍正常。

- [ ] **Step 3: 重新计算试用资格**

仅对最新内容探测成功、样本大于零、完整度至少 60% 且含标题/规范 URL 的非 HTML 来源执行 `fetch --trial` 小批量验证。不得启用长期 ingestion。

- [ ] **Step 4: 生成最终中文报告**

报告必须列出不可变清单的全部 Target，并给出：原失败证据、最终分类、官方方式、验证结果、字段完整度、是否新增试用资格、HTML 研究状态、阻塞原因和后续复查条件。报告首页同时显示修复前 16 个试用来源和修复后的实际数量。

- [ ] **Step 5: 运行 PostgreSQL 与网页验收**

Run: `.\.venv\Scripts\python.exe -m pytest tests/acceptance/test_source_remediation.py -q`

Expected: PASS。

浏览器检查 `/remediation`、`/probes`、`/targets` 和至少一个失败 Target 详情；确认中文说明与数据库记录一致。

- [ ] **Step 6: 提交真实证据**

```powershell
git add sources reports/source-failure-remediation.md reports/source-trial-baseline.md tests/acceptance/test_source_remediation.py
git commit -m "test: verify failed source remediation batch"
```

---

### Task 7：最终回归、安全审查与合并准备

**Files:**
- Modify: `README.md`
- Modify: `reports/source-failure-remediation.md`（仅修正验收中发现的描述问题）

- [ ] **Step 1: 补中文操作说明**

README 说明基线清单、分类、单来源 queue、报告入口、HTML 研究边界、网络继承和受限平台停止条件；不放任何真实凭据或代理配置。

- [ ] **Step 2: 执行完整测试和静态检查**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS，允许既有明确 skip，无新增失败。

Run: `.\.venv\Scripts\ruff.exe check src tests migrations`

Expected: PASS。

Run: `git diff --check`

Expected: PASS。

- [ ] **Step 3: 执行安全断言检查**

检查报告、测试快照、日志和网页响应不含 `Authorization`、`Cookie`、数据库 URL、API Key、代理详情或带 query 的证据 URL；确认代码中没有 HtmlFetcher、浏览器自动化或凭据回退。

- [ ] **Step 4: 审查需求覆盖**

逐条核对设计文档的非目标、分类、官方优先级、HTML 白名单、有界验证、YAML 真相、可观测性、重试和完成定义；任何未满足项必须在合并前修复或明确记为阻塞。

- [ ] **Step 5: 提交文档并进入代码审查**

```powershell
git add README.md reports/source-failure-remediation.md
git commit -m "docs: explain source remediation operations"
```

完成后进行独立代码审查；只有无 Critical/Important 问题、完整测试通过且 27 项报告齐全时，才允许合并到 `main`。
