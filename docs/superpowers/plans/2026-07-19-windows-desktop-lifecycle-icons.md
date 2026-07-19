# Windows Desktop Lifecycle and Icon Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tray exit reliably stop the owned News Codex process tree, clean only branded orphan workers on startup, and render one shared icon across the EXE and system tray.

**Architecture:** Add a bounded `psutil`-backed process module with explicit cleanup results and inject its two operations into `DesktopController`. Add one code-native icon factory that both the packaged EXE builder and tray UI consume. Keep window-close-as-hide and external Python service ownership unchanged.

**Tech Stack:** Python 3.12, psutil, Pillow, PyInstaller, pytest, Ruff, pywebview, pystray.

## Global Constraints

- Work only on `codex/windows-desktop-lifecycle-icons` in its isolated worktree.
- Never read or output `.env` contents and never stage user-retained report files.
- Window close hides to tray; tray exit is the only full desktop shutdown action.
- Never terminate manual Python services, PostgreSQL, another executable path, or a branded tree with a live branded Supervisor.
- Process enumeration occurs only once during service startup and once during explicit shutdown; no background polling is added.
- All waits are bounded and failures return Chinese diagnostics.
- Do not push or merge without user confirmation.

---

### Task 1: Bounded branded process-tree management

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/newsradar/desktop/processes.py`
- Create: `tests/desktop/test_processes.py`

**Interfaces:**
- Produces: `ProcessCleanupResult(matched_pids, stopped_pids, failed_pids)` with a `succeeded` property.
- Produces: `stop_owned_process_tree(root_pid: int, timeout_seconds: float = 5.0) -> ProcessCleanupResult`.
- Produces: `cleanup_orphaned_internal_processes(executable_path: Path, current_pid: int | None = None, timeout_seconds: float = 3.0) -> ProcessCleanupResult`.
- Produces: `cleanup_current_packaged_orphans() -> ProcessCleanupResult`, which is a no-op outside a frozen executable.

- [ ] **Step 1: Prepare the isolated Python environment**

Run:

```powershell
uv sync --extra dev --extra research
```

Expected: the worktree-local `.venv` is created and the existing locked dependencies install successfully.

- [ ] **Step 2: Add failing orphan-selection tests**

Create fake process objects exposing `pid`, `ppid()`, `exe()`, `cmdline()`, `children()`, `terminate()`, `kill()`, and `is_running()`. Cover these exact cases:

```python
def test_cleanup_selects_only_same_executable_orphan_web_and_worker(monkeypatch, tmp_path):
    executable = tmp_path / "NewsCodex.exe"
    orphan_web = FakeProcess(201, 999, executable, [str(executable), MARKER, "web"])
    orphan_worker = FakeProcess(202, 999, executable, [str(executable), MARKER, "worker"])
    manual_python = FakeProcess(203, 999, tmp_path / "python.exe", ["python", "-m", "newsradar"])
    live_child = FakeProcess(204, 205, executable, [str(executable), MARKER, "web"])
    supervisor = FakeProcess(205, 1, executable, [str(executable), MARKER, "serve"])
    install_fake_backend(monkeypatch, [orphan_web, orphan_worker, manual_python, live_child, supervisor])

    result = cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.matched_pids == (201, 202)
    assert manual_python.terminate_calls == 0
    assert live_child.terminate_calls == 0
```

- [ ] **Step 3: Verify the new tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\desktop\test_processes.py -q
```

Expected: collection fails because `newsradar.desktop.processes` does not exist.

- [ ] **Step 4: Add `psutil` and the minimal process module**

Run `uv add "psutil>=6,<8"` to update `pyproject.toml`, `uv.lock`, and the worktree environment. Implement the result type and exact filtering rules:

```python
@dataclass(frozen=True, slots=True)
class ProcessCleanupResult:
    matched_pids: tuple[int, ...] = ()
    stopped_pids: tuple[int, ...] = ()
    failed_pids: tuple[int, ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.failed_pids
```

Normalize executable paths with `Path.resolve(strict=False)` and `os.path.normcase`. A child is protected when its live parent has the same normalized executable path and command role `serve`. Catch `psutil.NoSuchProcess`, `psutil.AccessDenied`, and `psutil.ZombieProcess`; record inaccessible matched processes as failed instead of widening the target set.

For owned-tree shutdown, snapshot `root.children(recursive=True)` before terminating, request termination for children and root, call `psutil.wait_procs` with the bounded timeout, kill survivors, and call `wait_procs` once more. Return every still-running or inaccessible PID in `failed_pids`.

- [ ] **Step 5: Verify process tests and lint pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\desktop\test_processes.py -q
.\.venv\Scripts\ruff.exe check src\newsradar\desktop\processes.py tests\desktop\test_processes.py
```

Expected: all process tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 6: Commit the process module**

```powershell
git add pyproject.toml uv.lock src/newsradar/desktop/processes.py tests/desktop/test_processes.py
git commit -m "feat: manage Windows desktop process trees"
```

---

### Task 2: Integrate cleanup with desktop start and tray exit

**Files:**
- Modify: `src/newsradar/desktop/controller.py`
- Modify: `tests/desktop/test_controller.py`
- Verify: `tests/desktop/test_app.py`

**Interfaces:**
- Consumes: `ProcessCleanupResult`, `stop_owned_process_tree`, and `cleanup_current_packaged_orphans` from Task 1.
- Produces: `DesktopController(..., tree_stopper=..., orphan_cleaner=...)` with injected callables for deterministic tests.
- Requires: `ManagedProcess.pid: int` in the controller protocol and fakes.

- [ ] **Step 1: Write failing controller lifecycle tests**

Add tests with injected functions:

```python
def test_controller_cleans_orphans_before_health_probe():
    calls = []
    controller = DesktopController(
        probe=lambda _url: True,
        orphan_cleaner=lambda: calls.append("cleanup") or ProcessCleanupResult(),
    )
    assert controller.start_service().state == "external_running"
    assert calls == ["cleanup"]


def test_controller_stops_the_complete_owned_tree():
    process = FakeProcess(pid=321)
    stopped = []
    controller = DesktopController(
        process_factory=lambda _command: process,
        probe=sequenced_probe(False, True),
        tree_stopper=lambda pid: stopped.append(pid) or ProcessCleanupResult((pid,), (pid,), ()),
        orphan_cleaner=lambda: ProcessCleanupResult(),
    )
    controller.start_service()
    assert controller.stop_service().state == "stopped"
    assert stopped == [321]
```

Also cover cleanup failure returning `failed`, retry preserving `_owned_process`, and external service shutdown never invoking `tree_stopper`.

- [ ] **Step 2: Verify controller tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\desktop\test_controller.py tests\desktop\test_app.py -q
```

Expected: failures show missing injected cleanup interfaces and missing `pid` support.

- [ ] **Step 3: Implement minimal controller integration**

Add injected callable aliases and defaults. Run orphan cleanup once at the beginning of the first `start_service()` call, before probing port 8767. If it returns failed PIDs, return:

```python
DesktopStatus("failed", "检测到无法清理的 News Codex 遗留进程，请退出旧实例后重试。")
```

When `_owned_process` exists, call `tree_stopper(process.pid)` even if the Supervisor has already exited, then run the orphan cleaner once to catch branded descendants whose parent disappeared during the race. Only clear `_owned_process` when both cleanup results succeed. Preserve the current `external_running` rule when no process is owned.

- [ ] **Step 4: Verify lifecycle behavior**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\desktop\test_controller.py tests\desktop\test_app.py tests\test_runtime.py -q
.\.venv\Scripts\ruff.exe check src\newsradar\desktop\controller.py tests\desktop\test_controller.py
```

Expected: all selected tests pass; close-button tests still prove no shutdown call, and tray-quit tests prove shutdown happens once.

- [ ] **Step 5: Commit lifecycle integration**

```powershell
git add src/newsradar/desktop/controller.py tests/desktop/test_controller.py
git commit -m "fix: stop owned desktop process tree on exit"
```

---

### Task 3: Use one icon factory for EXE and tray

**Files:**
- Create: `src/newsradar/desktop/icon.py`
- Modify: `src/newsradar/desktop/app.py`
- Modify: `tools/build_windows_desktop.py`
- Create: `tests/desktop/test_icon.py`
- Modify: `tests/desktop/test_app.py`

**Interfaces:**
- Produces: `create_news_codex_icon(size: int = 256) -> PIL.Image.Image`.
- Produces: `create_tray_icon_image() -> PIL.Image.Image`, delegating to `create_news_codex_icon(64)`.
- Consumes: the same icon factory in `tools.build_windows_desktop.create_icon`.

- [ ] **Step 1: Write failing shared-icon tests**

```python
def test_news_codex_icon_has_expected_sizes_and_shared_tray_pixels():
    master = create_news_codex_icon(256)
    tray = create_tray_icon_image()
    assert master.mode == "RGBA"
    assert master.size == (256, 256)
    assert tray.size == (64, 64)
    assert tray.tobytes() == create_news_codex_icon(64).tobytes()


def test_build_icon_uses_shared_factory(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(build_windows_desktop, "create_news_codex_icon", fake_icon(calls))
    build_windows_desktop.create_icon(tmp_path / "news-codex.ico")
    assert calls == [256]
```

- [ ] **Step 2: Verify icon tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\desktop\test_icon.py tests\desktop\test_app.py -q
```

Expected: failures show the shared icon module and tray factory are missing.

- [ ] **Step 3: Implement the shared icon factory**

Render one 256×256 RGBA master using the existing EXE colors and geometry. Return the master for size 256; for other positive sizes use `Image.Resampling.LANCZOS`:

```python
def create_news_codex_icon(size: int = 256) -> Image.Image:
    if size <= 0:
        raise ValueError("icon_size_must_be_positive")
    image = _draw_master_icon()
    if size == 256:
        return image
    return image.resize((size, size), Image.Resampling.LANCZOS)
```

Delete the duplicate `Image.new`/`ImageDraw` tray drawing from `_start_tray`. Make the build script call the shared factory before saving the multi-size ICO.

- [ ] **Step 4: Verify icon tests and build script**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\desktop\test_icon.py tests\desktop\test_app.py -q
.\.venv\Scripts\ruff.exe check src\newsradar\desktop\icon.py src\newsradar\desktop\app.py tools\build_windows_desktop.py tests\desktop\test_icon.py tests\desktop\test_app.py
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit shared icon work**

```powershell
git add src/newsradar/desktop/icon.py src/newsradar/desktop/app.py tools/build_windows_desktop.py tests/desktop/test_icon.py tests/desktop/test_app.py
git commit -m "fix: share desktop and tray icon artwork"
```

---

### Task 4: Full verification, package, and real Windows acceptance

**Files:**
- Modify only if verification identifies a scoped defect in Tasks 1–3.
- Build outputs: `build/windows-desktop/` and `dist/NewsCodex/` remain Git-ignored.

**Interfaces:**
- Consumes: all production and test interfaces from Tasks 1–3.
- Produces: a verified `dist/NewsCodex/NewsCodex.exe` ready for user acceptance.

- [ ] **Step 1: Run complete automated verification serially**

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: Ruff exits 0 and pytest reaches 100% with no failures. Existing dependency deprecation warnings may remain but no new warning is accepted from the changed modules.

- [ ] **Step 2: Stop only the currently running old branded EXE tree**

Resolve processes whose executable path exactly equals `D:\codex_project_work\news_codex\dist\NewsCodex\NewsCodex.exe`, report their PIDs, and stop them before replacing locked files. Do not stop Python, PostgreSQL, Git, Codex, or a different executable path.

- [ ] **Step 3: Build the final EXE**

```powershell
uv run --extra dev --extra research python tools\build_windows_desktop.py
```

Expected: `Built: dist/NewsCodex/NewsCodex.exe` and PyInstaller exits 0.

- [ ] **Step 4: Perform bounded process-tree smoke acceptance**

Launch the final EXE, verify port 8767 returns HTTP 200, and record the branded process tree. Confirm it contains a desktop process, live Supervisor, Web, and Worker. Use the tray Exit action, then verify:

```text
matching NewsCodex.exe processes = 0
port 8767 listeners = 0
manual Python/PostgreSQL processes remain unchanged
```

Then relaunch and close the window with the title-bar X. Confirm the window hides while the owned process tree and port 8767 remain healthy. Finally exit from the tray again.

- [ ] **Step 5: Visually verify icon identity**

Confirm the same artwork appears in the EXE file, taskbar, Alt+Tab, visible system tray, and overflow/hidden-icons panel. Differences caused only by Windows scaling or monochrome hover treatment are acceptable; different shapes are not.

- [ ] **Step 6: Record final repository state**

```powershell
git status --short --branch
git log --oneline --decorate -5
```

Expected: feature worktree is clean, all implementation commits are on `codex/windows-desktop-lifecycle-icons`, user-retained report files remain untouched in the main worktree, and nothing has been pushed or merged.
