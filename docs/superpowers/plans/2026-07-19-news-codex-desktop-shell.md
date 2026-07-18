# News Codex Desktop Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供默认显示窗口、可隐藏至托盘并能安全管理本地 News Codex 服务的 Windows 桌面壳。

**Architecture:** `DesktopController` 管理 HTTP 健康检查与仅限自有子进程的启动、停止、超时状态。`DesktopApplication` 用 pywebview 呈现既有日报页面，以 pystray 提供托盘控制；CLI 和 Windows 登录项只连接这两个边界。

**Tech Stack:** Python 3.12、Typer、httpx、pywebview、pystray、Pillow、Windows 注册表、pytest。

## Global Constraints

- 仅支持 Windows 桌面壳；不改写现有网页、Worker、数据库或自动日报策略。
- 不读取、展示或写入 `.env` 秘密；不自动执行数据库迁移。
- 只停止 DesktopController 自己创建的服务进程；不可按端口 PID 停止外部进程。
- 默认显示窗口；关闭窗口仅隐藏；“退出”是唯一停止自有服务的入口。
- README 用中文说明命令启动、窗口启动、登录启动、隐藏与退出。

---

### Task 1: 可测试的桌面运行控制器

**Files:**
- Create: `src/newsradar/desktop/controller.py`
- Create: `tests/desktop/test_controller.py`

**Interfaces:**
- Produces: `DesktopController(port: int, process_factory, probe, clock, sleeper)`，包含 `status() -> DesktopStatus`、`start_service() -> DesktopStatus`、`stop_service() -> DesktopStatus` 与 `shutdown()`。
- Consumes: `newsradar serve --host 127.0.0.1 --port <port>` 作为唯一受管子进程。

- [ ] **Step 1: Write failing tests**

```python
def test_controller_starts_missing_service_and_waits_for_health() -> None:
    controller = DesktopController(port=8767, process_factory=factory, probe=probe)
    assert controller.start_service().state == "running"
    assert factory.calls == 1

def test_controller_never_stops_an_unowned_running_service() -> None:
    controller = DesktopController(port=8767, probe=lambda _: True)
    assert controller.stop_service().state == "external_running"
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run --extra dev pytest tests/desktop/test_controller.py -q`

Expected: FAIL because `newsradar.desktop.controller` does not exist.

- [ ] **Step 3: Implement the controller**

```python
@dataclass(frozen=True)
class DesktopStatus:
    state: Literal["running", "starting", "stopped", "external_running", "failed"]
    message_zh: str

class DesktopController:
    def start_service(self) -> DesktopStatus: ...
    def stop_service(self) -> DesktopStatus: ...
```

Use a 20-attempt, 0.5-second bounded health wait and retain only the created `Popen` instance as ownership evidence.

- [ ] **Step 4: Run controller tests and Ruff**

Run: `uv run --extra dev pytest tests/desktop/test_controller.py -q && uv run --extra dev ruff check src/newsradar/desktop tests/desktop`

Expected: PASS.

### Task 2: Windows 登录项和 CLI 命令

**Files:**
- Create: `src/newsradar/desktop/autostart.py`
- Modify: `src/newsradar/cli.py`
- Create: `tests/desktop/test_autostart.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `desktop` Typer command group with `run`, `autostart-enable`, `autostart-disable`, `autostart-status`.
- Produces: `WindowsAutostart` with `enable(command: str)`, `disable()`, `status() -> AutostartStatus`.

- [ ] **Step 1: Write failing tests**

```python
def test_autostart_writes_current_user_run_value_without_secrets() -> None:
    registry = FakeRegistry()
    WindowsAutostart(registry).enable('"C:/Python/python.exe" -m newsradar desktop run')
    assert registry.values[RUN_VALUE] == '"C:/Python/python.exe" -m newsradar desktop run'

def test_cli_desktop_autostart_status_is_chinese() -> None:
    result = runner.invoke(app, ["desktop", "autostart-status"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run --extra dev pytest tests/desktop/test_autostart.py tests/test_cli.py -q`

Expected: FAIL because the desktop CLI group does not exist.

- [ ] **Step 3: Implement registry adapter and CLI**

Use `winreg.HKEY_CURRENT_USER` only; on non-Windows return an explicit Chinese unsupported status. The `run` command lazily imports GUI dependencies so ordinary CLI commands remain usable without desktop extras.

- [ ] **Step 4: Run focused tests**

Run: `uv run --extra dev pytest tests/desktop/test_autostart.py tests/test_cli.py -q`

Expected: PASS.

### Task 3: 原生窗口与系统托盘适配器

**Files:**
- Create: `src/newsradar/desktop/app.py`
- Modify: `pyproject.toml`
- Create: `tests/desktop/test_app.py`

**Interfaces:**
- Produces: `DesktopApplication(controller, ui_factory)` with `run()` and `quit()`.
- Consumes: lazy-imported `webview`, `pystray`, `PIL.Image` only from desktop execution.

- [ ] **Step 1: Write failing tests**

```python
def test_window_close_hides_instead_of_stopping_service() -> None:
    app = DesktopApplication(controller, ui_factory)
    app.on_window_closing()
    assert ui.window.hidden is True
    assert controller.stop_calls == 0

def test_explicit_quit_stops_owned_service_and_tray() -> None:
    app.quit()
    assert controller.shutdown_calls == 1
    assert ui.tray.stopped is True
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run --extra dev pytest tests/desktop/test_app.py -q`

Expected: FAIL because `DesktopApplication` does not exist.

- [ ] **Step 3: Implement desktop adapter and dependencies**

Add bounded runtime dependencies `pywebview`, `pystray`, `pillow`. The default window URL is `/daily-reports`; pystray uses a default “显示窗口” action and dynamic status label. `run_detached` starts tray integration before `webview.start()`.

- [ ] **Step 4: Run focused tests and import check**

Run: `uv run --extra dev pytest tests/desktop/test_app.py -q && uv run python -c "import webview, pystray; from PIL import Image"`

Expected: PASS.

### Task 4: 中文 README 与端到端验证

**Files:**
- Modify: `README.md`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Documents: `newsradar serve`, `newsradar desktop run`, `newsradar desktop autostart-enable`, `autostart-disable`.

- [ ] **Step 1: Write README assertion test**

```python
def test_readme_documents_desktop_runtime_controls() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "newsradar desktop run" in text
    assert "隐藏到右下角" in text
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run --extra dev pytest tests/test_cli.py -q`

Expected: FAIL because README lacks desktop documentation.

- [ ] **Step 3: Document exact daily usage**

Explain command-only run, visible desktop run, Windows login start, hide-on-close and explicit full exit; state that automatic reports remain controlled on the webpage.

- [ ] **Step 4: Full verification**

Run: `uv run --extra dev --extra research pytest -q && uv run --extra dev ruff check .`

Expected: PASS.
