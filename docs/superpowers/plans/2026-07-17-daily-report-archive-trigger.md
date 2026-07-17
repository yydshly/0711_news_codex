# Daily Report Archive Trigger Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 PostgreSQL 上网页归档日报时因触发标识超过 16 字符而整体回滚的问题，并在操作仓储入口提供稳定的应用层校验。

**Architecture:** Web 路由改用长度合规且语义清晰的 `daily_archive`；持久操作仓储在开启事务前校验所有 `trigger` 输入，非法值统一抛出 `invalid_operation_trigger`。现有“归档 + 决策版语音入队”单事务和幂等复用逻辑保持不变。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL/SQLite、pytest、ruff。

## Global Constraints

- `operation_runs.trigger` 最大长度保持 16，不增加数据库迁移。
- 不截断、不清洗、不替换合法触发标识；合法值原样写入。
- 归档与自动语音入队必须保持同一事务，失败时整体回滚。
- 不修改 MiniMax 模型、语音参数、日报内容或页面布局。
- 不读取或修改 `.env`，不触碰用户保留报告，不合并或推送分支。
- 使用当前独立工作树 `D:\codex_project_work\news_codex\.worktrees\fix-daily-report-archive-trigger`。
- 所有 Python/pytest 命令先执行 `$env:PYTHONPATH=(Resolve-Path 'src').Path`，确保根目录虚拟环境加载当前工作树源码，而不是 editable 安装指向的原 main 源码。

## File Structure

- Modify: `src/newsradar/operations/repository.py` — 定义触发标识长度契约，并在持久操作入队边界校验。
- Modify: `tests/operations/test_repository.py` — 覆盖非法输入拒绝、无数据库写入和 16 字符边界值。
- Modify: `src/newsradar/web/app.py` — 网页归档使用 `daily_archive`。
- Modify: `tests/web/test_daily_report_pages.py` — 证明网页归档写入合规触发标识且仍自动创建决策版语音操作。

---

### Task 1: 操作仓储触发标识契约

**Files:**
- Modify: `tests/operations/test_repository.py`
- Modify: `src/newsradar/operations/repository.py`

**Interfaces:**
- Consumes: `OperationRepository.enqueue(operation_type, requested_scope, trigger="manual", *, in_transaction=False)`。
- Produces: `MAX_OPERATION_TRIGGER_LENGTH = 16`；非法输入抛出 `ValueError("invalid_operation_trigger")`；合法输入原样持久化。

- [ ] **Step 1: 写入非法值和边界值失败测试**

在 `tests/operations/test_repository.py` 增加 `pytest` 导入和以下测试：

```python
import pytest


@pytest.mark.parametrize("trigger", ["", " ", "x" * 17, None, 1])
def test_enqueue_rejects_invalid_operation_trigger(trigger: object) -> None:
    with session() as db:
        with pytest.raises(ValueError, match="^invalid_operation_trigger$"):
            OperationRepository(db).enqueue(
                OperationType.FETCH,
                {},
                trigger=trigger,  # type: ignore[arg-type]
            )

        assert db.scalars(select(OperationRunRecord)).all() == []


def test_enqueue_accepts_sixteen_character_trigger_without_normalizing() -> None:
    with session() as db:
        trigger = "x" * 16

        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {},
            trigger=trigger,
        )

        assert operation.trigger == trigger
```

- [ ] **Step 2: 运行测试并确认红灯**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/operations/test_repository.py -k "operation_trigger or sixteen_character" -q
```

Expected: 非法值参数测试失败；当前仓储没有抛出稳定的 `invalid_operation_trigger`，SQLite 还会接受超过 16 字符的值。

- [ ] **Step 3: 在仓储入口实现最小校验**

在 `src/newsradar/operations/repository.py` 的 `MAX_ATTEMPTS` 旁增加常量，并在 `enqueue` 开启事务前校验：

```python
MAX_ATTEMPTS = 3
MAX_OPERATION_TRIGGER_LENGTH = 16


def enqueue(
    self,
    operation_type: OperationType,
    requested_scope: dict[str, Any],
    trigger: str = "manual",
    *,
    in_transaction: bool = False,
) -> OperationRunRecord:
    if (
        not isinstance(trigger, str)
        or not trigger.strip()
        or len(trigger) > MAX_OPERATION_TRIGGER_LENGTH
    ):
        raise ValueError("invalid_operation_trigger")
    context = nullcontext() if in_transaction else self._transaction()
```

不要对合法 `trigger` 调用 `strip()` 后再保存；`strip()` 只用于判断全空白输入。

- [ ] **Step 4: 运行仓储测试并确认绿灯**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/operations/test_repository.py -q
```

Expected: `tests/operations/test_repository.py` 全部通过。

- [ ] **Step 5: 提交仓储契约**

```powershell
git add -- src/newsradar/operations/repository.py tests/operations/test_repository.py
git diff --cached --check
git commit -m "fix: validate operation trigger length"
```

### Task 2: 网页归档使用合规触发标识

**Files:**
- Modify: `tests/web/test_daily_report_pages.py`
- Modify: `src/newsradar/web/app.py`

**Interfaces:**
- Consumes: `OperationCommandService.archive_and_enqueue_daily_report_audio(*, report_id: int, trigger: str) -> int`。
- Produces: `POST /daily-reports/{report_id}/archive` 创建 `trigger == "daily_archive"` 的 `daily_report_audio` 操作。

- [ ] **Step 1: 强化网页归档回归测试**

在 `test_archiving_daily_report_automatically_queues_decision_audio` 读取到 `operation` 后增加：

```python
    assert operation.trigger == "daily_archive"
    assert len(operation.trigger) <= 16
```

保留现有响应状态、操作类型和 `requested_scope` 断言。

- [ ] **Step 2: 运行测试并确认红灯**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/web/test_daily_report_pages.py::test_archiving_daily_report_automatically_queues_decision_audio -q
```

Expected: FAIL，当前实际值为 `daily_report_archive`。

- [ ] **Step 3: 修改 Web 路由触发标识**

在 `src/newsradar/web/app.py` 的 `archive_daily_report` 路由中只改动触发值：

```python
OperationCommandService(session).archive_and_enqueue_daily_report_audio(
    report_id=report_id,
    trigger="daily_archive",
)
```

- [ ] **Step 4: 运行日报网页与事务测试**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/web/test_daily_report_pages.py -k "archiv or audio_enqueue" -q
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/operations/test_commands.py -k "daily_report_audio or archive" -q
```

Expected: 网页归档、重复操作复用和失败回滚测试全部通过。

- [ ] **Step 5: 提交网页修复**

```powershell
git add -- src/newsradar/web/app.py tests/web/test_daily_report_pages.py
git diff --cached --check
git commit -m "fix: use valid daily archive trigger"
```

### Task 3: 完整验证与交付检查

**Files:**
- Verify only; no additional source files should change.

**Interfaces:**
- Consumes: Tasks 1–2 的两个提交。
- Produces: 可复核的测试、静态检查和分支状态证据。

- [ ] **Step 1: 运行相关测试文件**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/operations/test_repository.py tests/operations/test_commands.py tests/web/test_daily_report_pages.py -q
```

Expected: 三个相关测试文件全部通过。

- [ ] **Step 2: 运行完整 pytest**

Run:

```powershell
$env:PYTHONUTF8='1'
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest
```

Expected: 全部测试通过，仅允许已有的跳过项和弃用警告。

- [ ] **Step 3: 运行 ruff 和差异检查**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check .
git diff --check HEAD~2..HEAD
git status --short --branch
```

Expected: ruff 与差异检查通过；工作树干净，分支仍为 `codex/fix-daily-report-archive-trigger`。

- [ ] **Step 4: 检查原 main 用户文件未受影响**

在原工作区运行：

```powershell
git status --short --branch
```

Expected: 用户保留报告仍保持原有未提交状态，没有被暂存或提交。

- [ ] **Step 5: 汇报并等待集成确认**

汇报两个修复提交、测试结果和真实故障原因。不要合并、推送或重启 main 服务；等待用户明确选择本地合并或其他集成方式。
