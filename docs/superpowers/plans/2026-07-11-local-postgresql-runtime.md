# Project-Local PostgreSQL Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Create and operate a News Codex-owned PostgreSQL 18 cluster on `127.0.0.1:55432`, then migrate, sync, and persist real source probes without changing the existing Windows PostgreSQL service.

**Architecture:** A focused Python `LocalPostgresManager` owns binary discovery, safe local paths, secret generation, `.env` updates, and subprocess calls. Typer exposes `newsradar db init|start|status|stop`; a small PowerShell wrapper provides convenient Windows commands. Runtime data stays under ignored `.local/`, while application tables continue to use the existing SQLAlchemy/Alembic layer.

**Tech Stack:** Python 3.12, Typer, PostgreSQL 18 command-line tools, Alembic, SQLAlchemy 2, pytest, PowerShell.

## Global Constraints

- Do not use Docker or modify/start/stop the existing `postgresql-x64-18` Windows service.
- Bind only to `127.0.0.1:55432`; fail if that fixed port is occupied.
- Store runtime data below `.local/postgres/` and secrets only in ignored `.env`.
- Use SCRAM-SHA-256 for TCP authentication and delete the temporary password file after `initdb`.
- Initialization and environment updates must be idempotent and preserve unrelated `.env` values.
- MiniMax and optional source credentials remain optional.

---

### Task 1: Tested local PostgreSQL manager

**Files:**
- Create: `src/newsradar/local_postgres.py`
- Create: `tests/test_local_postgres.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `LocalPostgresPaths.discover(project_root: Path) -> LocalPostgresPaths`.
- Produces: `LocalPostgresManager.initialize() -> str`, `start() -> str`, `status() -> str`, and `stop() -> str`.
- Produces: `LocalPostgresError`, used by the CLI for safe user-facing failures.

- [x] **Step 1: Write failing unit tests for safe paths, PostgreSQL discovery, and environment updates**

```python
def test_paths_are_project_local_and_postgres_18_is_selected(tmp_path, monkeypatch):
    install = tmp_path / "PostgreSQL" / "18" / "bin"
    install.mkdir(parents=True)
    for name in ("initdb.exe", "pg_ctl.exe", "createdb.exe", "pg_isready.exe"):
        (install / name).touch()
    monkeypatch.setenv("POSTGRES_HOME", str(install.parent))

    paths = LocalPostgresPaths.discover(tmp_path / "repo")

    assert paths.bin_dir == install
    assert paths.data_dir == tmp_path / "repo" / ".local" / "postgres" / "data"


def test_update_env_preserves_values_and_never_returns_password(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("MINIMAX_API_KEY=existing\n", encoding="utf-8")

    manager = manager_for(tmp_path)
    message = manager.write_database_url("unsafe:/ password")

    contents = env_file.read_text(encoding="utf-8")
    assert "MINIMAX_API_KEY=existing" in contents
    assert "DATABASE_URL=postgresql+psycopg://newsradar:unsafe%3A%2F%20password@127.0.0.1:55432/newsradar" in contents
    assert "unsafe:/ password" not in message
```

- [x] **Step 2: Run tests and confirm the module is missing**

Run: `uv run pytest tests/test_local_postgres.py -v`

Expected: collection fails with `ModuleNotFoundError: newsradar.local_postgres`.

- [x] **Step 3: Implement binary discovery, guarded local paths, secret-safe `.env` editing, and subprocess abstraction**

```python
@dataclass(frozen=True)
class LocalPostgresPaths:
    project_root: Path
    bin_dir: Path
    data_dir: Path
    log_file: Path
    env_file: Path

    @classmethod
    def discover(cls, project_root: Path) -> "LocalPostgresPaths":
        postgres_home = os.getenv("POSTGRES_HOME")
        candidates = [Path(postgres_home) / "bin"] if postgres_home else []
        candidates.extend(sorted(Path(r"C:\Program Files\PostgreSQL").glob("*/bin"), reverse=True))
        bin_dir = next((path for path in candidates if (path / "initdb.exe").is_file()), None)
        if bin_dir is None:
            raise LocalPostgresError("PostgreSQL command-line tools were not found")
        runtime = project_root.resolve() / ".local" / "postgres"
        return cls(project_root.resolve(), bin_dir, runtime / "data", runtime / "postgres.log", project_root.resolve() / ".env")
```

`initialize()` must create a temporary password file with restrictive access, run `initdb --auth-host=scram-sha-256 --auth-local=trust --username=newsradar --pwfile=...`, append fixed listen/port settings, delete the password file in `finally`, start the cluster, create the `newsradar` database, and write the URL. Existing `PG_VERSION` plus a valid `.env` must return an unchanged/idempotent result.

- [x] **Step 4: Run manager tests**

Run: `uv run pytest tests/test_local_postgres.py -v`

Expected: all tests pass, including occupied-port, missing-binary, subprocess-failure, password cleanup, and repeated-initialization cases.

- [x] **Step 5: Commit manager and tests**

```powershell
git add .gitignore src/newsradar/local_postgres.py tests/test_local_postgres.py
git commit -m "feat: add project-local PostgreSQL manager"
```

### Task 2: Database lifecycle CLI and PowerShell entry point

**Files:**
- Modify: `src/newsradar/cli.py`
- Modify: `tests/test_cli.py`
- Create: `scripts/postgres.ps1`

**Interfaces:**
- Consumes: `LocalPostgresManager` and `LocalPostgresError` from Task 1.
- Produces: `newsradar db init`, `newsradar db start`, `newsradar db status`, and `newsradar db stop`.
- Produces: `scripts/postgres.ps1 -Action init|start|status|stop`.

- [x] **Step 1: Write failing CLI tests with a fake manager**

```python
@pytest.mark.parametrize("command,method", [("init", "initialize"), ("start", "start"), ("status", "status"), ("stop", "stop")])
def test_db_command_delegates_to_manager(monkeypatch, command, method):
    fake = Mock()
    getattr(fake, method).return_value = f"{command} complete"
    monkeypatch.setattr("newsradar.cli.build_local_postgres_manager", lambda: fake)

    result = runner.invoke(app, ["db", command])

    assert result.exit_code == 0
    assert f"{command} complete" in result.stdout
    getattr(fake, method).assert_called_once_with()
```

- [x] **Step 2: Run the focused CLI tests and confirm failure**

Run: `uv run pytest tests/test_cli.py -k db_command -v`

Expected: FAIL because the `db` Typer group does not exist.

- [x] **Step 3: Add the Typer group and safe error conversion**

```python
db_app = typer.Typer(help="Manage the project-local PostgreSQL runtime")
app.add_typer(db_app, name="db")

def _run_db_action(action: str) -> None:
    try:
        message = getattr(build_local_postgres_manager(), action)()
    except LocalPostgresError as exc:
        typer.echo(f"Database error: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(message)
```

Add four explicit Typer commands that call `_run_db_action`. The PowerShell wrapper must use a validated parameter and execute `uv run newsradar db $Action`, returning its exit code without printing environment variables.

- [x] **Step 4: Run CLI and full unit tests**

Run: `uv run pytest tests/test_cli.py tests/test_local_postgres.py -v`

Expected: all focused tests pass.

- [x] **Step 5: Commit lifecycle commands**

```powershell
git add src/newsradar/cli.py tests/test_cli.py scripts/postgres.ps1
git commit -m "feat: expose local PostgreSQL lifecycle commands"
```

### Task 3: Initialize the real cluster and persist the source registry

**Files:**
- Runtime only, ignored: `.local/postgres/**`, `.env`
- Existing migration: `migrations/versions/20260711_0001_source_registry.py`

**Interfaces:**
- Consumes: Task 2 CLI and the existing Alembic/source registry CLI.
- Produces: a running PostgreSQL cluster with migrated and synchronized source tables.

- [x] **Step 1: Verify the fixed port is unused and the system service is stopped**

Run:

```powershell
Get-NetTCPConnection -LocalPort 55432 -State Listen -ErrorAction SilentlyContinue
Get-Service postgresql-x64-18 | Select-Object Name,Status
```

Expected: no listener on `55432`; system service remains `Stopped`.

- [x] **Step 2: Initialize and check the project cluster**

Run:

```powershell
uv run newsradar db init
uv run newsradar db status
```

Expected: initialization succeeds and status reports `127.0.0.1:55432` accepting connections, without printing the password.

- [x] **Step 3: Apply migrations and synchronize all audited sources twice**

Run:

```powershell
uv run alembic upgrade head
uv run newsradar sources sync --root sources
uv run newsradar sources sync --root sources
```

Expected: first sync creates 27 sources; second sync reports 27 unchanged and creates no versions.

- [x] **Step 4: Assert migrated data with a secret-safe Python query**

```powershell
@'
from sqlalchemy import create_engine, text
from newsradar.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as connection:
    version = connection.execute(text("select version_num from alembic_version")).scalar_one()
    sources = connection.execute(text("select count(*) from source_definitions")).scalar_one()
    versions = connection.execute(text("select count(*) from source_definition_versions")).scalar_one()
print({"migration": version, "sources": sources, "versions": versions})
'@ | uv run python -
```

Expected: latest migration identifier, `sources: 27`, and `versions: 27`.

- [x] **Step 5: Confirm ignored runtime files and unchanged system service**

Run:

```powershell
git status --short
git check-ignore .env .local/postgres/data/PG_VERSION .local/postgres/postgres.log
Get-Service postgresql-x64-18 | Select-Object Name,Status
```

Expected: runtime paths are ignored, no secret is staged, and the system service remains stopped.

### Task 4: Persist a real probe batch, document operations, and verify

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-11-local-postgresql-runtime.md` (check completed steps only)

**Interfaces:**
- Consumes: the live local database and existing `sources probe --all` command.
- Produces: persisted probe runs/samples plus operator instructions.

- [x] **Step 1: Run a real persistent source probe**

Run:

```powershell
uv run newsradar sources probe --all --root sources --persist --report-output reports/live-source-intelligence.md
```

Expected: the batch completes even when optional sources are blocked or rate-limited.

- [x] **Step 2: Assert persisted history**

```powershell
@'
from sqlalchemy import create_engine, text
from newsradar.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as connection:
    probes = connection.execute(text("select count(*) from source_probe_runs")).scalar_one()
    samples = connection.execute(text("select count(*) from source_probe_samples")).scalar_one()
print({"probe_runs": probes, "probe_samples": samples})
assert probes >= 27
assert samples > 0
'@ | uv run python -
```

Expected: at least 27 probe runs and at least one stored sample.

- [x] **Step 3: Document lifecycle and recovery commands**

Add README commands for `db init/start/status/stop`, state that port `55432` is fixed, explain `POSTGRES_HOME`, and warn that `.local/` deletion permanently removes the project database. Do not include a real database URL or password.

- [x] **Step 4: Run complete verification**

Run:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv run newsradar sources validate --root sources
git diff --check
git status --short --branch
```

Expected: formatting/lint pass, all tests pass, 27 sources validate, and only intentional tracked changes appear.

- [x] **Step 5: Commit documentation and final plan state**

```powershell
git add README.md docs/superpowers/plans/2026-07-11-local-postgresql-runtime.md
git commit -m "docs: add local PostgreSQL operations"
```
