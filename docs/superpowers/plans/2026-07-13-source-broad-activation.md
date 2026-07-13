# 广覆盖来源试用实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对全部来源建立一次真实探索记录，并让公开直连且首次探测合格的来源以可追踪的“试用”资格进入受控抓取，而不等待深度审计。

**Architecture:** 新增纯规则的试用资格判定器，输入 YAML `SourceDefinition` 与最新持久化 `SourceProbeRunRecord`，输出可解释的资格结论。CLI 和 Worker 使用同一规则；页面从数据库查询试用/发现/受限三类数量和来源原因，YAML 仍是人工审核的真相，程序不自动修改它。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、Pydantic 2、Typer、HTTPX、FastAPI/Jinja、PostgreSQL、pytest、ruff。

## 全局约束

- 对 166 个 Target 批量探测时，单个来源失败不得中断批次。
- 禁止邮件收取、邮件转 RSS、Cookie、登录态、代理绕过、验证码绕过、付费内容读取、音频下载与字幕抓取。
- 试用抓取只允许 `coverage_mode: direct`、`availability: ready`、非 HTML 自动访问方式、无硬阻断的来源。
- 试用资格必须要求最新持久化探测 `outcome=success`、样本数大于零、字段完整度至少 60%，且样本含 `title` 与 `canonical_url`。
- 间接来源只用于发现，不能单独作为事实证据；目录来源只显示缺口及解锁条件，不进入 Worker。
- `ingestion.enabled` 和长期来源资格不得被自动改写；试用操作使用独立 `trial` 作用域并全程记录。
- 页面、报告、日志和测试不得写入 API Key、Cookie、代理地址、`.netrc` 内容或数据库连接串。
- MiniMax 不参与来源合规性、试用资格或长期启用决定。

---

## 文件结构

- Create `src/newsradar/ingestion/trial.py`：无副作用的试用资格规则、错误代码和中文原因。
- Modify `src/newsradar/sources/repository.py`：读取每个来源的最新探测及样本字段。
- Modify `src/newsradar/operations/commands.py`、`src/newsradar/operations/fetch_runtime.py`、`src/newsradar/cli.py`：提交和执行可追踪的 `trial` 抓取操作。
- Modify `src/newsradar/web/queries.py`、`src/newsradar/web/viewmodels.py`、`src/newsradar/web/templates/dashboard.html`：显示初探覆盖、试用资格、发现信号和受限缺口。
- Create `tests/ingestion/test_trial.py`、`tests/test_trial_cli.py`、`tests/web/test_trial_dashboard.py`：覆盖规则、Worker 边界和中文页面。
- Create `reports/source-trial-baseline.md`：真实批量初探后的非敏感中文报告。

### Task 1: 试用资格纯规则与持久化读取

**Files:**
- Create: `src/newsradar/ingestion/trial.py`
- Modify: `src/newsradar/sources/repository.py`
- Create: `tests/ingestion/test_trial.py`

**Interfaces:**
- Produces `TrialDecision(eligible: bool, code: str | None, reason: str)`。
- Produces `SourceRepository.latest_probe_snapshot(source_id: str) -> ProbeSnapshot | None`，其中包含 outcome、sample_count、field_completeness、样本字段集合和探测时间。

- [ ] **Step 1: 写失败测试**

在 `tests/ingestion/test_trial.py` 创建三个最小测试：成功的直连 ready RSS 来源和 success probe 应得到 `eligible=True`；`coverage_mode=indirect` 应得到 `code="discovery_only"`；缺少 `canonical_url` 或完整度低于 `0.60` 应得到 `eligible=False`。

```python
def test_direct_ready_successful_probe_is_trial_eligible() -> None:
    decision = evaluate_trial_eligibility(source, probe)
    assert decision.eligible is True
    assert decision.code is None

def test_indirect_source_is_discovery_only() -> None:
    decision = evaluate_trial_eligibility(indirect_source, successful_probe)
    assert decision == TrialDecision(False, "discovery_only", "仅用于发现，需回源确认")
```

- [ ] **Step 2: 运行并确认失败**

Run: `$env:PYTHONPATH="$PWD/src"; & 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest tests/ingestion/test_trial.py -q`

Expected: FAIL，因为 `newsradar.ingestion.trial` 尚不存在。

- [ ] **Step 3: 实现最小规则与读取 DTO**

在 `trial.py` 定义冻结 Pydantic 模型 `ProbeSnapshot`、`TrialDecision` 以及 `evaluate_trial_eligibility(source, probe)`。按以下顺序拒绝：无 probe、非 direct、availability 非 ready、catalog_only、硬阻断、没有非 HTML 自动方法、outcome 非 success、sample_count 为零、完整度 `< 0.60`、样本字段不同时含 `title`/`canonical_url`。每个拒绝返回稳定的机器代码和中文原因；只在全部条件通过时返回 `TrialDecision(True, None, "可试用抓取：公开直连且首次探测合格")`。

在 `SourceRepository` 用 `SourceProbeRunRecord` 与 `SourceProbeSampleRecord` 查询最新 `finished_at` 探测，构造 `ProbeSnapshot`；没有记录时返回 `None`，不得猜测资格。

- [ ] **Step 4: 运行通过测试与现有来源测试**

Run: `$env:PYTHONPATH="$PWD/src"; & 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest tests/ingestion/test_trial.py tests/test_source_repository.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/newsradar/ingestion/trial.py src/newsradar/sources/repository.py tests/ingestion/test_trial.py
git commit -m "feat: add source trial eligibility"
```

### Task 2: 受控试用抓取操作

**Files:**
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/operations/fetch_runtime.py`
- Modify: `src/newsradar/cli.py`
- Create: `tests/test_trial_cli.py`
- Modify: `tests/operations/test_fetch_runtime.py`

**Interfaces:**
- `OperationCommandService.enqueue_fetch(..., trial: bool = False)` 在 `requested_scope` 保存布尔值 `trial`。
- CLI 新增 `newsradar fetch --trial [--provider ID] [--max-items N] [--wait]`。
- Worker 在网络请求前重新读取最新 probe 并调用同一 `evaluate_trial_eligibility`；不合格时返回 `eligibility_trial_<code>`，不发网络请求。

- [ ] **Step 1: 写失败测试**

在 `tests/test_trial_cli.py` 断言 `newsradar fetch --trial --provider hn` 只排队试用合格的 direct 来源，operation scope 含 `trial: true`；断言 `--trial` 和 `--one-off` 不能同时使用。

在 `tests/operations/test_fetch_runtime.py` 添加测试：scope 含 `trial: true` 且最新 probe 不合格时，结果为 failed/blocked 且 Fetcher 未被调用。

- [ ] **Step 2: 运行并确认失败**

Run: `$env:PYTHONPATH="$PWD/src"; & 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest tests/test_trial_cli.py tests/operations/test_fetch_runtime.py -q`

Expected: FAIL，因为 CLI 与 operation scope 尚无 `trial` 支持。

- [ ] **Step 3: 实现最小试用操作路径**

扩展 `enqueue_fetch` 写入 `trial`。在 CLI 中添加 `--trial`；它只能选择 provider/source 过滤后的来源，使用 repository 最新 probe 决定候选，输出“试用候选数/排除原因”，为空时以 exit 2 结束。试用操作不需要 `ingestion.enabled`，但不允许 `--one-off`、不允许 `--no-approved`，也不允许 manual/html/credentials/payment/approval 来源。

在 `fetch_runtime.py` 对 `requested_scope["trial"]` 调用 repository 的最新 probe 与 `evaluate_trial_eligibility`；只有合格时以 `approved_only=False` 调用既有 `IngestionService`。普通 approved 与 one-off 路径保持原行为。

- [ ] **Step 4: 验证 Worker 边界**

Run: `$env:PYTHONPATH="$PWD/src"; & 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest tests/test_trial_cli.py tests/operations/test_fetch_runtime.py tests/ingestion/test_trial.py -q`

Expected: PASS，且不合格试用来源没有网络调用。

- [ ] **Step 5: 提交**

```powershell
git add src/newsradar/operations/commands.py src/newsradar/operations/fetch_runtime.py src/newsradar/cli.py tests/test_trial_cli.py tests/operations/test_fetch_runtime.py
git commit -m "feat: queue guarded trial source fetches"
```

### Task 3: 中文覆盖与试用状态页面

**Files:**
- Modify: `src/newsradar/web/queries.py`
- Modify: `src/newsradar/web/viewmodels.py`
- Modify: `src/newsradar/web/templates/dashboard.html`
- Create: `tests/web/test_trial_dashboard.py`

**Interfaces:**
- Dashboard view model 新增 `explored_count`、`trial_eligible_count`、`discovery_only_count`、`restricted_count`。
- 每个 Target 行新增 `trial_label` 与 `trial_reason`，内容来自统一试用资格规则。

- [ ] **Step 1: 写失败测试**

在 `tests/web/test_trial_dashboard.py` 建立一个 direct success probe、一个 indirect success probe、一个 requires_credentials 来源。断言首页显示“已探索”“可试用抓取”“仅发现”“受限目录”四个中文指标；断言 targets 页显示三种不同中文原因，且页面 HTML 不含 `DATABASE_URL`、`Authorization`、`Cookie` 字样。

- [ ] **Step 2: 运行并确认失败**

Run: `$env:PYTHONPATH="$PWD/src"; & 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest tests/web/test_trial_dashboard.py -q`

Expected: FAIL，因为页面尚无试用统计与说明。

- [ ] **Step 3: 实现查询与展示**

在 queries 中批量读取 latest probe，复用 `evaluate_trial_eligibility` 计算行状态，避免在模板中复制规则。`explored_count` 是有 latest probe 的 Target 数；`trial_eligible_count` 是 decision eligible 数；`discovery_only_count` 是 code 为 `discovery_only` 的数；`restricted_count` 是 availability 非 ready 或 coverage_mode 为 catalog_only 的数。模板增加中文解释：“试用可抓取表示首次探测合格，不等于长期稳定或事实确认”。

- [ ] **Step 4: 验证网页回归**

Run: `$env:PYTHONPATH="$PWD/src"; & 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest tests/web/test_trial_dashboard.py tests/web/test_routes.py tests/web/test_queries.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/newsradar/web/queries.py src/newsradar/web/viewmodels.py src/newsradar/web/templates/dashboard.html tests/web/test_trial_dashboard.py
git commit -m "feat: show source trial coverage in dashboard"
```

### Task 4: 全量初探、试用基线报告与验收

**Files:**
- Create: `reports/source-trial-baseline.md`

**Interfaces:**
- 消费 Task 1-3 的运行记录和试用资格；不修改 YAML 的 `ingestion.enabled`、`status` 或 `research`。

- [ ] **Step 1: 同步并运行批量探测**

安全地仅注入 `DATABASE_URL` 到子进程环境，不显示值，依次运行：

```powershell
newsradar providers validate --root providers
newsradar sources validate --root sources
newsradar providers sync --root providers
newsradar sources sync --root sources
newsradar sources probe --all --persist
```

单个来源错误只写入自身 probe 结果；命令完成后汇总 success、degraded、blocked、failed，不能为使结果好看而重试受限来源。

- [ ] **Step 2: 生成中文基线报告**

创建 `reports/source-trial-baseline.md`，包含：总 Target 数、已探索数、试用可抓取数、仅发现数、受限目录数；按官方/专业媒体/研究/社区/聚合/社交列出数量；列出每类阻塞原因与解锁步骤；列出试用来源的 ID、名称、访问方式、完整度、样本数、探测 UTC 时间和风险结论。只写非敏感字段，禁止复制请求头、密钥、Cookie、代理或连接串。

- [ ] **Step 3: 运行一次受控试用抓取**

只选择已探测合格的一个公开 RSS 来源，执行：

```powershell
newsradar fetch --trial <source-id> --max-items 5 --wait
```

确认 operation 为 succeeded 或 partial，RawItem 记录存在；若失败，报告 error_code 并停止，不以 one-off 或网页登录替代。

- [ ] **Step 4: 全量回归和浏览器验收**

Run:

```powershell
$env:PYTHONPATH="$PWD/src"
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m ruff check src tests migrations
```

手工访问 `/` 与 `/targets`，确认中文四类指标、试用解释、间接来源回源提示、受限来源解锁说明均可见且无敏感值。

- [ ] **Step 5: 提交**

```powershell
git add reports/source-trial-baseline.md
git commit -m "docs: record source trial baseline"
```

## 计划自检

- 阶段 A 的全量初探、试用资格、间接发现、受限目录、页面可见性和报告分别由 Task 1-4 覆盖。
- 深度审计、三轮稳定性和长期启用只被保留为后续条件，没有作为试用前置。
- 所有运行时入口复用同一 `evaluate_trial_eligibility`，避免 CLI、Worker 和页面判断漂移。
- 计划不新增邮件、非官方爬取、代理配置、摘要、推荐、推送或后台调度。
