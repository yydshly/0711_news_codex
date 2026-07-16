# 本机 PostgreSQL 端口兼容实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 让项目专用 PostgreSQL 在 Windows 保留 `55432` 时可无损切换到 `55232`，并完成真实数据库与 v1.5 验收。

**架构：** `LocalPostgresManager` 持有单一端口配置，所有数据库命令、URL 和状态检查都从该实例读取。Windows 端口排除检测是独立、可注入的只读预检；`db repair` 负责在实例停止时原子更新项目专用配置与 `.env`，不重建数据目录。

**技术栈：** Python 3.12、Typer、PostgreSQL 18、pytest、标准库 `subprocess`/`socket`/`re`

## 全局约束

- `NEWSRADAR_POSTGRES_PORT` 只接受 `1024–65535` 的整数，未配置时兼容默认值 `55432`。
- 当前本机迁移目标端口固定为 `55232`。
- 不修改 Windows 端口保留策略，不接管 `5432` 的其他 PostgreSQL 服务。
- 不删除或重建 `.local/postgres`，不提交 `.env`、密码或数据库数据。
- 不改变来源抓取、事件处理、MiniMax 或网页产品逻辑。

---

### Task 1：统一可配置端口

**文件：**
- 修改：`src/newsradar/local_postgres.py`
- 修改：`.env.example`
- 测试：`tests/test_local_postgres.py`

**接口：**
- 产出：`resolve_postgres_port(project_root: Path) -> int`
- 产出：`LocalPostgresManager(..., port: int = POSTGRES_DEFAULT_PORT)`
- 约束：`build_local_postgres_manager()` 解析端口后只向 manager 注入一次。

- [ ] **Step 1：编写端口解析与命令一致性的失败测试**

增加测试，验证环境变量优先于 `.env`、非法范围抛出 `LocalPostgresError`，并验证 URL、`pg_isready`、`createdb`、端口占用检查与 `postgresql.conf` 全部使用 `55232`：

```python
def local_paths(tmp_path: Path) -> LocalPostgresPaths:
    return LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )


def test_configured_port_is_used_by_all_local_postgres_surfaces(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWSRADAR_POSTGRES_PORT", "55232")
    paths = local_paths(tmp_path)
    manager = build_local_postgres_manager(tmp_path)
    assert manager.port == 55232
    manager.write_database_url("secret")
    assert "@127.0.0.1:55232/newsradar" in paths.env_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("value", ["text", "0", "1023", "65536"])
def test_invalid_postgres_port_is_rejected(tmp_path, monkeypatch, value):
    monkeypatch.setenv("NEWSRADAR_POSTGRES_PORT", value)
    with pytest.raises(LocalPostgresError, match="1024.*65535"):
        build_local_postgres_manager(tmp_path)
```

- [ ] **Step 2：确认测试失败**

运行：`uv run pytest tests/test_local_postgres.py -q`

预期：新测试因缺少 `resolve_postgres_port`、`port` 属性和动态端口而失败。

- [ ] **Step 3：实现单一端口配置**

将模块级端口改为兼容默认值，并由 manager 持有：

```python
POSTGRES_DEFAULT_PORT = 55432


def resolve_postgres_port(project_root: Path) -> int:
    raw = os.getenv("NEWSRADAR_POSTGRES_PORT") or _read_env_value(
        project_root / ".env", "NEWSRADAR_POSTGRES_PORT"
    )
    if raw is None:
        return POSTGRES_DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError as error:
        raise LocalPostgresError("NEWSRADAR_POSTGRES_PORT must be an integer from 1024 to 65535") from error
    if not 1024 <= port <= 65535:
        raise LocalPostgresError("NEWSRADAR_POSTGRES_PORT must be an integer from 1024 to 65535")
    return port
```

`LocalPostgresManager` 的所有 `POSTGRES_PORT` 引用改为 `self.port`；`write_database_url()` 同时只保留一条 `NEWSRADAR_POSTGRES_PORT=<port>`。`.env.example` 增加 `NEWSRADAR_POSTGRES_PORT=55432`。

- [ ] **Step 4：验证并提交**

运行：`uv run pytest tests/test_local_postgres.py -q && uv run ruff check src/newsradar/local_postgres.py tests/test_local_postgres.py`

预期：全部通过。

提交：`git commit -m "feat: make local postgres port configurable"`

---

### Task 2：Windows 保留端口预检

**文件：**
- 修改：`src/newsradar/local_postgres.py`
- 测试：`tests/test_local_postgres.py`

**接口：**
- 产出：`parse_excluded_port_ranges(output: str) -> tuple[tuple[int, int], ...]`
- 产出：`windows_port_is_excluded(port: int, runner: Runner = subprocess.run) -> bool`
- 消费：`LocalPostgresManager._ensure_port_available()` 在占用检查前调用。

- [ ] **Step 1：编写 Windows 范围解析与错误提示测试**

```python
def test_windows_excluded_port_is_rejected_with_recovery_instruction(tmp_path):
    manager = LocalPostgresManager(
        local_paths(tmp_path),
        port=55432,
        port_excluded=lambda port: port == 55432,
        port_in_use=lambda: False,
    )
    with pytest.raises(LocalPostgresError, match="NEWSRADAR_POSTGRES_PORT=55232"):
        manager.start()


def test_parse_windows_excluded_ranges():
    output = "55409       55508\n50000       50059     *\n"
    assert parse_excluded_port_ranges(output) == ((55409, 55508), (50000, 50059))
```

- [ ] **Step 2：确认测试失败**

运行：`uv run pytest tests/test_local_postgres.py -q`

预期：新函数与注入参数不存在。

- [ ] **Step 3：实现只读预检**

Windows 使用 `netsh interface ipv4 show excludedportrange protocol=tcp`，解析每行两个整数；命令失败或非 Windows 返回 `False`。`initialize()`、`start()` 和需要启动集群的 `repair()` 统一调用 `_ensure_port_available()`：先报系统保留，再报端口已占用。提示中包含当前端口和 `NEWSRADAR_POSTGRES_PORT=55232`。

- [ ] **Step 4：验证并提交**

运行：`uv run pytest tests/test_local_postgres.py -q && uv run ruff check src tests`

预期：全部通过，既有端口占用测试仍通过。

提交：`git commit -m "feat: diagnose windows reserved postgres ports"`

---

### Task 3：无损端口迁移与真实验收

**文件：**
- 修改：`src/newsradar/local_postgres.py`
- 修改：`tests/test_local_postgres.py`
- 本机配置（不提交）：`.env`、`.local/postgres/data/postgresql.conf`

**接口：**
- 产出：`LocalPostgresManager.repair(password: str | None = None)` 支持已有 `DATABASE_URL` 的端口迁移。
- 行为：运行中集群拒绝切换；停止状态更新专用配置和 URL，不重建数据。

- [ ] **Step 1：编写迁移安全性失败测试**

```python
def initialized_paths(
    tmp_path: Path, *, database_port: int, config_port: int
) -> LocalPostgresPaths:
    paths = local_paths(tmp_path)
    paths.data_dir.mkdir(parents=True)
    paths.data_dir.joinpath("PG_VERSION").write_text("18", encoding="utf-8")
    paths.data_dir.joinpath("postgresql.conf").write_text(
        f"# News Codex project-local settings\nport = {config_port}\n",
        encoding="utf-8",
    )
    paths.env_file.write_text(
        "DATABASE_URL=postgresql+psycopg://newsradar:hidden"
        f"@127.0.0.1:{database_port}/newsradar\n",
        encoding="utf-8",
    )
    return paths


def stopped_runner(command, **kwargs):
    return subprocess.CompletedProcess(command, 3, stdout="no server running", stderr="")


def running_runner(command, **kwargs):
    return subprocess.CompletedProcess(command, 0, stdout="server is running", stderr="")


def test_repair_migrates_stopped_existing_cluster_to_configured_port(tmp_path):
    paths = initialized_paths(tmp_path, database_port=55432, config_port=55432)
    manager = LocalPostgresManager(paths, port=55232, runner=stopped_runner)
    message = manager.repair()
    assert "port = 55232" in paths.data_dir.joinpath("postgresql.conf").read_text(encoding="utf-8")
    assert "@127.0.0.1:55232/newsradar" in paths.env_file.read_text(encoding="utf-8")
    assert "without deleting data" in message


def test_repair_refuses_port_switch_while_cluster_is_running(tmp_path):
    paths = initialized_paths(tmp_path, database_port=55432, config_port=55432)
    manager = LocalPostgresManager(paths, port=55232, runner=running_runner)
    with pytest.raises(LocalPostgresError, match="db stop"):
        manager.repair()
```

- [ ] **Step 2：确认测试失败**

运行：`uv run pytest tests/test_local_postgres.py -q`

预期：现有 `repair()` 将错误返回“不需要修复”。

- [ ] **Step 3：实现配置迁移**

读取 `.env` 的现有 `DATABASE_URL`，使用 `sqlalchemy.engine.make_url()` 保留用户名、密码与数据库，仅替换端口。更新 `postgresql.conf` 中最后生效的项目端口设置；若缺少项目设置则追加。先在内存生成两个新文本，再分别写入临时文件并 `Path.replace()`，避免半写文件。运行中的实例只允许端口一致的普通修复。

- [ ] **Step 4：运行自动化验证**

运行：`uv run pytest tests/test_local_postgres.py -q && uv run pytest -q && uv run ruff check src tests && git diff --check`

预期：全套测试通过；真实 PostgreSQL 验收仍默认跳过。

- [ ] **Step 5：迁移本机实例并验证**

在当前 PowerShell 会话和 `.env` 设置 `NEWSRADAR_POSTGRES_PORT=55232`，依次运行：

```powershell
uv run newsradar db repair
uv run newsradar db start
uv run newsradar db status
uv run alembic current
$env:NEWSRADAR_RUN_POSTGRES_ACCEPTANCE='1'
uv run pytest tests/acceptance/test_high_value_news_wave_v1_5.py -q
```

预期：`55232` 接受连接；Alembic 为当前 head；v1.5 真实数据库验收通过。任何失败都停止后续步骤，并保留数据与日志供诊断。

- [ ] **Step 6：提交实现**

仅提交源码、测试和 `.env.example`：

`git commit -m "feat: migrate local postgres to a usable port"`
