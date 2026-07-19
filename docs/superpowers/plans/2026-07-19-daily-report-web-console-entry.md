# 中文日报本地网页控制台入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在中文日报页显示本机网页地址，并允许用户复制地址或在默认浏览器打开。

**Architecture:** `/daily-reports` 路由基于当前请求构造安全绝对 URL，传给 Jinja 模板。模板渲染说明、普通链接和可访问的复制控件；现有 `app.js` 完成复制与中文反馈。没有数据库、Worker 或桌面服务变更。

**Tech Stack:** FastAPI、Jinja2、原生 Clipboard API、Pytest、Ruff。

## Global Constraints

- 仅允许 `http` 或 `https` URL；不得读取或显示凭据。
- 不改变 host、端口、服务启动方式或网络可达性。
- 不新增数据库迁移、外部请求或第三方前端依赖。

---

### Task 1: 渲染本地网页控制台入口

**Files:**

- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/daily_reports.html`
- Test: `tests/web/test_daily_report_pages.py`

**Interfaces:**

- Consumes: `Request.url`。
- Produces: 模板上下文 `web_console_url: str`，使用请求的 scheme、netloc 和 `/daily-reports` 路径。

- [ ] **Step 1: Write the failing test**

```python
def test_daily_report_index_shows_local_web_console_entry(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get("/daily-reports")
    assert response.status_code == 200
    assert "本地网页控制台" in response.text
    assert 'href="http://testserver/daily-reports"' in response.text
    assert 'data-copy-web-console-url="http://testserver/daily-reports"' in response.text
    assert "仅本机可访问" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests\web\test_daily_report_pages.py::test_daily_report_index_shows_local_web_console_entry`

Expected: FAIL because the local-console panel does not exist.

- [ ] **Step 3: Write minimal implementation**

Add `_web_console_url(request: Request) -> str` in `app.py`. It rejects a scheme other than `http` or `https` and returns `str(request.url.replace(path="/daily-reports", query=None, fragment=None))`. Pass this value as `web_console_url` to the `/daily-reports` template. Add a panel before the automation console that renders the address, the text “仅本机可访问”, a `target="_blank" rel="noopener"` link, copy button, and status element.

- [ ] **Step 4: Run test to verify it passes**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/newsradar/web/app.py src/newsradar/web/templates/daily_reports.html tests/web/test_daily_report_pages.py; git commit -m "feat: add daily report web console entry"`

### Task 2: 复制地址反馈与回归

**Files:**

- Modify: `src/newsradar/web/static/app.js`
- Test: `tests/web/test_daily_report_pages.py`

**Interfaces:**

- Consumes: `[data-copy-web-console-url]`、`[data-copy-web-console-status]` 和 `navigator.clipboard.writeText`。
- Produces: 成功反馈“已复制本机网页地址”，失败反馈“无法自动复制，请手动复制上方地址”。

- [ ] **Step 1: Write the failing test**

```python
def test_daily_report_index_exposes_accessible_web_console_copy_feedback(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get("/daily-reports")
    assert 'aria-label="复制本机网页地址"' in response.text
    assert 'data-copy-web-console-status' in response.text
    assert 'aria-live="polite"' in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests\web\test_daily_report_pages.py::test_daily_report_index_exposes_accessible_web_console_copy_feedback`

Expected: FAIL because the controls do not yet exist.

- [ ] **Step 3: Write minimal implementation**

In `app.js`, attach a click handler for each `[data-copy-web-console-url]`. If `navigator.clipboard.writeText` exists and resolves, update the status element to the success text; otherwise update it to the failure text. Do not alter existing handlers.

- [ ] **Step 4: Run regression tests and lint**

Run: `& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests\web\test_daily_report_pages.py tests\desktop\test_app.py`

Run: `& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m ruff check src\newsradar\web tests\web\test_daily_report_pages.py`

Expected: both commands exit 0.

- [ ] **Step 5: Commit**

Run: `git add src/newsradar/web/static/app.js tests/web/test_daily_report_pages.py; git commit -m "feat: copy daily report web console address"`

### Task 3: 合并前验收

**Files:**

- Verify only: `src/newsradar/web/app.py`, `src/newsradar/web/templates/daily_reports.html`, `src/newsradar/web/static/app.js`

- [ ] **Step 1: Run tests, lint, migrations and diff check**

Run: `& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests\web\test_daily_report_pages.py tests\desktop\test_app.py`

Run: `& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m ruff check .`

Run: `& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m alembic heads; git diff --check`

Expected: all commands exit 0 and Alembic stays `20260719_0032 (head)`.

- [ ] **Step 2: Perform real local browser acceptance**

Open `http://127.0.0.1:8767/daily-reports`. Verify the address, external link target, copy control and one of the two Chinese feedback outcomes. Do not alter production data.
