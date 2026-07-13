# 系统网络继承实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让来源研究探测和正式抓取自动继承本机的系统代理/VPN 网络环境，并在网页中以中文、无敏感信息地说明该状态。

**Architecture:** 在 `Settings` 中集中定义 `http_trust_env`（默认开启），由研究探测 HTTPX 客户端、正式抓取 HTTPX 客户端和 YouTube 研究的 Requests Session 统一读取。研究探测仍只信任由工厂创建的无 Cookie 客户端，并保留逐跳 URL 校验；网页仅从设置读取布尔状态，绝不读取或渲染代理详情。

**Tech Stack:** Python 3.12、Pydantic Settings、HTTPX、Requests、FastAPI/Jinja2、pytest、ruff。

## 全局约束

- `HTTP_TRUST_ENV` 默认值必须是 `true`；它不是代理 URL 配置。
- 不新增代理地址、端口、用户名或密码字段，不把代理信息写入 YAML、数据库、日志、网页或 `.env.example`。
- 不使用 Cookie、浏览器登录态、代理轮换、验证码破解或规避网站限制。
- 研究探测保持 HTTPS、无凭据、无 Cookie、手工校验跳转、2 MB 响应限制和 20 秒超时。
- Worker 正式抓取继续使用既有超时、限流、重试和每 host 并发限制。
- 网页只显示 `系统网络继承已启用` 或 `系统网络继承已关闭（排障模式）`，不推断 VPN 类型或代理状态。

---

## 文件结构

- 修改 `src/newsradar/settings.py`：定义系统网络继承的单一开关。
- 修改 `src/newsradar/ingestion/fetchers/base.py`：让默认正式抓取客户端读取该开关。
- 修改 `src/newsradar/research/probes/safe_http.py`：让工厂拥有的安全探测客户端继承系统网络设置，同时保持所有已有安全边界。
- 修改 `src/newsradar/research/probes/youtube.py`：让受限的无 Cookie Requests Session 使用相同设置。
- 修改 `src/newsradar/web/app.py`、`src/newsradar/web/templates/base.html`：把只读中文状态注入全站页头。
- 修改 `.env.example`：文档化布尔开关，且不出现任何代理 URL。
- 新建 `tests/test_network_inheritance.py`：覆盖设置、HTTPX、Requests 与安全客户端边界。
- 修改 `tests/research/probes/test_security.py`、`tests/research/probes/test_youtube.py`：将“拒绝系统环境”断言替换为“仍拒绝非工厂客户端和 Cookie”的断言。
- 修改 `tests/web/test_ingestion_pages.py`：验证网页状态文字和代理信息不泄漏。

### Task 1: 统一系统网络继承设置和 HTTP 客户端

**Files:**
- Modify: `src/newsradar/settings.py`
- Modify: `src/newsradar/ingestion/fetchers/base.py`
- Modify: `src/newsradar/research/probes/safe_http.py`
- Modify: `src/newsradar/research/probes/youtube.py`
- Create: `tests/test_network_inheritance.py`
- Modify: `tests/research/probes/test_security.py`
- Modify: `tests/research/probes/test_youtube.py`

**Interfaces:**
- Consumes: `Settings`、`get_settings()`、`HttpPolicy.default()`、`new_safe_probe_client()`、`_create_transcript_session()`。
- Produces: `Settings.http_trust_env: bool`；所有由默认工厂创建的网络客户端使用同一布尔值。

- [ ] **Step 1: 写出失败测试**

在 `tests/test_network_inheritance.py` 增加以下测试；测试中用 `monkeypatch.setattr` 替换各模块已导入的 `get_settings`，避免读取真实 `.env`：

```python
import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.safe_http import new_safe_probe_client
from newsradar.research.probes.youtube import _create_transcript_session
from newsradar.settings import Settings


@pytest.mark.asyncio
async def test_default_clients_inherit_system_network_by_default(monkeypatch):
    settings = Settings(http_trust_env=True)
    monkeypatch.setattr("newsradar.ingestion.fetchers.base.get_settings", lambda: settings)
    monkeypatch.setattr("newsradar.research.probes.safe_http.get_settings", lambda: settings)
    monkeypatch.setattr("newsradar.research.probes.youtube.get_settings", lambda: settings)
    policy = HttpPolicy.default()
    probe_client = new_safe_probe_client()
    transcript_session = _create_transcript_session()
    try:
        assert policy.client.trust_env is True
        assert probe_client.trust_env is True
        assert transcript_session.trust_env is True
        assert list(probe_client.cookies.jar) == []
        assert transcript_session.cookies.get_dict() == {}
    finally:
        await policy.client.aclose()
        await probe_client.aclose()
        transcript_session.close()


@pytest.mark.asyncio
async def test_http_trust_env_false_is_an_explicit_diagnostic_override(monkeypatch):
    settings = Settings(http_trust_env=False)
    monkeypatch.setattr("newsradar.ingestion.fetchers.base.get_settings", lambda: settings)
    monkeypatch.setattr("newsradar.research.probes.safe_http.get_settings", lambda: settings)
    policy = HttpPolicy.default()
    probe_client = new_safe_probe_client()
    try:
        assert policy.client.trust_env is False
        assert probe_client.trust_env is False
    finally:
        await policy.client.aclose()
        await probe_client.aclose()
```

将 `tests/research/probes/test_security.py` 中“工厂客户端因 `trust_env=True` 被拒绝”的测试替换为：手工创建的 `httpx.AsyncClient(trust_env=True)` 即使没有 Cookie 也被 `safe_get()` 拒绝；工厂创建的客户端在 `trust_env=True` 时仍能通过 MockTransport 的安全路径。保留对 Cookie、敏感查询参数、HTTP、私网 IP 和认证候选的拒绝测试。

将 `tests/research/probes/test_youtube.py` 中 `assert session.trust_env is False` 改为通过 monkeypatch 设置 `Settings(http_trust_env=True)` 后断言 `True`，并增加 `False` 覆盖。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH = "$PWD/src"
uv run pytest tests/test_network_inheritance.py tests/research/probes/test_security.py tests/research/probes/test_youtube.py -q
```

Expected: FAIL，因为 `Settings` 尚无 `http_trust_env`，且各客户端仍硬编码 `False` 或拒绝 `trust_env=True`。

- [ ] **Step 3: 实现最小改动**

在 `Settings` 中、`http_connect_timeout_seconds` 前增加：

```python
http_trust_env: bool = True
```

在 `HttpPolicy.default()` 的客户端构造中增加：

```python
return cls(
    httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
        follow_redirects=True,
        trust_env=settings.http_trust_env,
    )
)
```

在 `safe_http.py` 导入 `get_settings`，并将工厂客户端改为：

```python
def new_safe_probe_client() -> httpx.AsyncClient:
    settings = get_settings()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(20),
        trust_env=settings.http_trust_env,
        follow_redirects=False,
        headers=_PROBE_HEADERS,
    )
    _OWNED_SAFE_CLIENTS.add(client)
    return client
```

修改 `_safe_client()`：删除把 `client.trust_env` 与 `client._mounts` 当作不安全条件的判断；保留 `follow_redirects`、Cookie 和“非 `_OWNED_SAFE_CLIENTS` 且非 MockTransport”拒绝。这样只有工厂创建的客户端可继承系统网络，调用方不能传入任意带代理/认证状态的客户端。

在 `youtube.py` 导入 `get_settings`，将注释改为“无 Cookie、受限 Session”，并将：

```python
session.trust_env = get_settings().http_trust_env
```

保留 `RejectingCookieJar`、`session.headers.pop("Cookie", None)` 和超时设置。

- [ ] **Step 4: 运行定向测试确认通过**

Run:

```powershell
$env:PYTHONPATH = "$PWD/src"
uv run pytest tests/test_network_inheritance.py tests/research/probes/test_security.py tests/research/probes/test_youtube.py -q
uv run ruff check src/newsradar/settings.py src/newsradar/ingestion/fetchers/base.py src/newsradar/research/probes tests/test_network_inheritance.py
```

Expected: 全部通过；ruff 无输出且退出码为 0。

- [ ] **Step 5: 提交任务**

```powershell
git add src/newsradar/settings.py src/newsradar/ingestion/fetchers/base.py src/newsradar/research/probes/safe_http.py src/newsradar/research/probes/youtube.py tests/test_network_inheritance.py tests/research/probes/test_security.py tests/research/probes/test_youtube.py
git commit -m "feat: inherit local system network settings"
```

### Task 2: 中文只读网络状态和配置说明

**Files:**
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/base.html`
- Modify: `.env.example`
- Modify: `tests/web/test_ingestion_pages.py`

**Interfaces:**
- Consumes: `get_settings().http_trust_env`。
- Produces: 所有 Jinja 模板可用的 `http_trust_env` 布尔值，以及不含代理详情的全站页头说明。

- [ ] **Step 1: 写出失败测试**

在 `tests/web/test_ingestion_pages.py` 增加：

```python
def test_pages_explain_system_network_inheritance_without_proxy_details(monkeypatch, db_session):
    monkeypatch.setattr(
        "newsradar.web.app.get_settings",
        lambda: Settings(http_trust_env=True),
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@127.0.0.1:7890")
    with _client_with_database(monkeypatch, db_session) as client:
        page = client.get("/fetch-runs")

    assert page.status_code == 200
    assert "系统网络继承已启用" in page.text
    assert "来源探测与后台抓取将遵循本机网络环境" in page.text
    assert "127.0.0.1:7890" not in page.text
    assert "user:secret" not in page.text
```

在本文件顶部加入：

```python
from newsradar.settings import Settings
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH = "$PWD/src"
uv run pytest tests/web/test_ingestion_pages.py::test_pages_explain_system_network_inheritance_without_proxy_details -q
```

Expected: FAIL，因为 `create_app()` 尚未把网络状态写入 Jinja 全局变量，模板未渲染说明。

- [ ] **Step 3: 实现最小网页与文档改动**

在 `web/app.py` 导入：

```python
from newsradar.settings import get_settings
```

在创建 `Jinja2Templates` 后设置：

```python
templates.env.globals["http_trust_env"] = get_settings().http_trust_env
```

在 `base.html` 的 `status-cluster` 中、数据库状态徽章之后插入：

```html
<span class="status status-info">
  {% if http_trust_env %}
    系统网络继承已启用：来源探测与后台抓取将遵循本机网络环境
  {% else %}
    系统网络继承已关闭（排障模式）
  {% endif %}
</span>
```

不要输出 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 或任意环境变量值。

在 `.env.example` 的 HTTP 超时设置附近增加：

```dotenv
# 默认继承 Windows/VPN/环境的网络设置；无需填写代理地址。
HTTP_TRUST_ENV=true
```

- [ ] **Step 4: 运行网页与静态检查**

Run:

```powershell
$env:PYTHONPATH = "$PWD/src"
uv run pytest tests/web/test_ingestion_pages.py -q
uv run ruff check src/newsradar/web/app.py tests/web/test_ingestion_pages.py
```

Expected: 全部通过；测试 HTML 不包含测试注入的代理地址和凭据。

- [ ] **Step 5: 提交任务**

```powershell
git add src/newsradar/web/app.py src/newsradar/web/templates/base.html .env.example tests/web/test_ingestion_pages.py
git commit -m "feat: explain local network inheritance"
```

### Task 3: 真实网络回归、Worker 验收与报告

**Files:**
- Create: `reports/system-network-inheritance-validation.md`

**Interfaces:**
- Consumes: 已实现的 `HTTP_TRUST_ENV=true`、现有 CLI 探测/抓取命令与本机 PostgreSQL。
- Produces: 不含敏感网络数据的中文验证报告，记录来源结果、错误分类及 Worker 行为。

- [ ] **Step 1: 确认运行时配置与迁移状态**

Run:

```powershell
uv run alembic current
uv run newsradar sources validate --root sources
```

Expected: 数据库位于当前 head；来源校验成功。命令输出中不得打印 `.env` 或代理变量。

- [ ] **Step 2: 运行四个真实来源研究探测**

Run:

```powershell
uv run newsradar sources research probe openai-youtube --candidate youtube-atom --limit 5 --persist
uv run newsradar sources probe openai-news --persist
uv run newsradar sources probe arxiv-ai --persist
uv run newsradar sources probe hacker-news-topstories --persist
```

Expected: 每个命令独立完成；成功时持久化样本，失败时持久化可读分类。不得因失败把来源自动升级为 `active` 或 `verified`。

- [ ] **Step 3: 验证 Worker 真实消费一个开放抓取任务**

在已有 Worker 运行时，先列出可用来源 ID，再对一个 RSS 或 Hacker News 开放来源排队单次任务：

```powershell
uv run newsradar sources fetch hacker-news-topstories --max-items 5
uv run newsradar operations list --limit 5
uv run newsradar sources report
```

Expected: operation 从 `queued` 变为 `succeeded` 或带明确错误分类的终态；不会无限卡住。若 Worker 未运行，报告应明确标记为“验收前置条件未满足”，不能伪造抓取成功。

- [ ] **Step 4: 编写无敏感信息的中文报告**

创建 `reports/system-network-inheritance-validation.md`，固定包含：

```markdown
# 系统网络继承验证报告

## 执行环境

- `HTTP_TRUST_ENV=true`
- 代理地址、VPN 节点、账号、Cookie 和环境变量值：未收集、未展示。

## 来源探测结果

| 来源 | 方法 | 结果 | 样本数 | 说明 |
| --- | --- | --- | --- | --- |

## Worker 抓取验收

| 任务 | 最终状态 | RawItem 数量 | 结论 |
| --- | --- | --- | --- |

## 结论与限制

规则模式下每个域名是否可达取决于当时系统网络规则；本报告只陈述实际探测结果，不把失败归因到特定代理。
```

以实际 CLI 输出填充表格，错误正文只保留分类（例如 `connection_error`、`timeout`、`http_429`），删除任何 URL 查询敏感信息、凭据或代理细节。

- [ ] **Step 5: 完整回归、浏览器验收与提交**

Run:

```powershell
$env:PYTHONPATH = "$PWD/src"
uv run pytest -q
uv run ruff check src tests migrations
```

手工打开 `http://127.0.0.1:8766/fetch-runs` 与 `http://127.0.0.1:8766/research`，确认页头显示中文网络状态且不显示代理地址。随后：

```powershell
git add reports/system-network-inheritance-validation.md
git commit -m "docs: record system network validation"
```

Expected: 全量测试与 ruff 通过；报告只包含结果与错误分类。

## 计划自检

- 规范中的默认开启、探测与 Worker 一致性、Requests YouTube 路径、安全边界、网页只读提示、无敏感信息和真实验证，分别由任务 1、2、3 覆盖。
- 本计划不包含动态网页抓取、代理配置页、摘要、推荐或来源资格升级，符合范围限制。
- 所有新增接口名称均在任务 1 定义；后续任务只消费 `Settings.http_trust_env`。
