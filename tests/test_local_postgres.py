from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import newsradar.local_postgres as local_postgres
from newsradar.local_postgres import (
    LocalPostgresError,
    LocalPostgresManager,
    LocalPostgresPaths,
)


def make_install(root: Path) -> Path:
    bin_dir = root / "PostgreSQL" / "18" / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("initdb.exe", "pg_ctl.exe", "createdb.exe", "pg_isready.exe", "psql.exe"):
        (bin_dir / name).touch()
    return bin_dir


def make_paths(tmp_path: Path) -> LocalPostgresPaths:
    return LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )


def test_postgres_port_environment_overrides_project_env(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "NEWSRADAR_POSTGRES_PORT=55111\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSRADAR_POSTGRES_PORT", "55232")

    assert local_postgres.resolve_postgres_port(tmp_path) == 55232


def test_postgres_port_reads_project_env_when_process_env_is_unset(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "NEWSRADAR_POSTGRES_PORT=55232\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("NEWSRADAR_POSTGRES_PORT", raising=False)

    assert local_postgres.resolve_postgres_port(tmp_path) == 55232


@pytest.mark.parametrize("value", ["text", "0", "1023", "65536"])
def test_invalid_postgres_port_is_rejected(tmp_path, monkeypatch, value) -> None:
    monkeypatch.setenv("NEWSRADAR_POSTGRES_PORT", value)

    with pytest.raises(LocalPostgresError, match="1024.*65535"):
        local_postgres.resolve_postgres_port(tmp_path)


def test_configured_port_is_used_for_status_and_database_url(tmp_path) -> None:
    paths = make_paths(tmp_path)
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        normalized = [str(part) for part in command]
        calls.append(normalized)
        return subprocess.CompletedProcess(normalized, 0, stdout="ready", stderr="")

    manager = LocalPostgresManager(paths, port=55232, runner=runner)

    manager.status()
    manager.write_database_url("secret")

    status_command = calls[0]
    assert status_command[status_command.index("--port") + 1] == "55232"
    env_contents = paths.env_file.read_text(encoding="utf-8")
    assert "NEWSRADAR_POSTGRES_PORT=55232" in env_contents
    assert "@127.0.0.1:55232/newsradar" in env_contents


def test_parse_windows_excluded_port_ranges() -> None:
    output = """
Protocol tcp Port Exclusion Ranges

Start Port    End Port
----------    --------
     50000       50059     *
     55409       55508
"""

    assert local_postgres.parse_excluded_port_ranges(output) == (
        (50000, 50059),
        (55409, 55508),
    )


def test_windows_port_exclusion_uses_netsh_output(monkeypatch) -> None:
    monkeypatch.setattr(local_postgres.sys, "platform", "win32")
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="55409       55508\n",
            stderr="",
        )

    assert local_postgres.windows_port_is_excluded(55432, runner=runner) is True
    assert calls == [
        [
            "netsh",
            "interface",
            "ipv4",
            "show",
            "excludedportrange",
            "protocol=tcp",
        ]
    ]


def test_windows_excluded_port_is_rejected_with_recovery_instruction(tmp_path) -> None:
    paths = make_paths(tmp_path)
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")

    manager = LocalPostgresManager(
        paths,
        port=55432,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 3, stdout="not running", stderr=""
        ),
        port_in_use=lambda: False,
        port_excluded=lambda port: port == 55432,
    )

    with pytest.raises(
        LocalPostgresError,
        match="55432.*NEWSRADAR_POSTGRES_PORT=55232",
    ):
        manager.start()


def test_nonexcluded_port_preserves_existing_occupied_port_error(tmp_path) -> None:
    paths = make_paths(tmp_path)
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")
    manager = LocalPostgresManager(
        paths,
        port=55232,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 3, stdout="not running", stderr=""
        ),
        port_in_use=lambda: True,
        port_excluded=lambda _: False,
    )

    with pytest.raises(LocalPostgresError, match="55232.*already in use"):
        manager.start()


def make_initialized_port_paths(
    tmp_path: Path,
    *,
    database_port: int = 55432,
    config_port: int = 55432,
) -> LocalPostgresPaths:
    paths = make_paths(tmp_path)
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")
    (paths.data_dir / "postgresql.conf").write_text(
        "# Existing PostgreSQL settings\n"
        "max_connections = 100\n"
        "# News Codex project-local settings\n"
        "listen_addresses = '127.0.0.1'\n"
        f"port = {config_port}\n",
        encoding="utf-8",
    )
    paths.env_file.write_text(
        "MINIMAX_API_KEY=keep-existing\n"
        "DATABASE_URL=postgresql+psycopg://newsradar:hidden"
        f"@127.0.0.1:{database_port}/newsradar\n",
        encoding="utf-8",
    )
    return paths


def test_repair_migrates_stopped_existing_cluster_to_configured_port(tmp_path) -> None:
    paths = make_initialized_port_paths(tmp_path)
    original_version = (paths.data_dir / "PG_VERSION").read_bytes()

    def stopped_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 3, stdout="not running", stderr="")

    manager = LocalPostgresManager(
        paths,
        port=55232,
        runner=stopped_runner,
        port_in_use=lambda: False,
        port_excluded=lambda _: False,
    )

    message = manager.repair()

    config = (paths.data_dir / "postgresql.conf").read_text(encoding="utf-8")
    env_contents = paths.env_file.read_text(encoding="utf-8")
    assert "port = 55232" in config
    assert "port = 55432" not in config
    assert "@127.0.0.1:55232/newsradar" in env_contents
    assert "NEWSRADAR_POSTGRES_PORT=55232" in env_contents
    assert "MINIMAX_API_KEY=keep-existing" in env_contents
    assert (paths.data_dir / "PG_VERSION").read_bytes() == original_version
    assert "without deleting data" in message


def test_repair_refuses_port_switch_while_cluster_is_running(tmp_path) -> None:
    paths = make_initialized_port_paths(tmp_path)
    original_config = (paths.data_dir / "postgresql.conf").read_bytes()
    original_env = paths.env_file.read_bytes()

    def running_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="server is running", stderr="")

    manager = LocalPostgresManager(
        paths,
        port=55232,
        runner=running_runner,
        port_in_use=lambda: False,
        port_excluded=lambda _: False,
    )

    with pytest.raises(LocalPostgresError, match="db stop"):
        manager.repair()

    assert (paths.data_dir / "postgresql.conf").read_bytes() == original_config
    assert paths.env_file.read_bytes() == original_env


def test_repair_dependency_is_part_of_postgres_discovery() -> None:
    assert "psql.exe" in LocalPostgresPaths.required_binaries


def test_paths_are_project_local_and_postgres_home_is_selected(tmp_path, monkeypatch):
    bin_dir = make_install(tmp_path)
    monkeypatch.setenv("POSTGRES_HOME", str(bin_dir.parent))
    project_root = tmp_path / "repo"

    paths = LocalPostgresPaths.discover(project_root)

    assert paths.bin_dir == bin_dir
    assert paths.data_dir == project_root / ".local" / "postgres" / "data"
    assert paths.log_file == project_root / ".local" / "postgres" / "postgres.log"
    assert paths.env_file == project_root / ".env"


def test_discovery_rejects_missing_postgres_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(LocalPostgresPaths, "default_install_root", tmp_path / "empty")

    with pytest.raises(LocalPostgresError, match="command-line tools"):
        LocalPostgresPaths.discover(tmp_path / "repo")


def test_discovery_reads_postgres_home_from_project_env(tmp_path, monkeypatch):
    bin_dir = make_install(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".env").write_text(
        f"POSTGRES_HOME={bin_dir.parent}\nMINIMAX_API_KEY=\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("POSTGRES_HOME", raising=False)
    monkeypatch.setattr(LocalPostgresPaths, "default_install_root", tmp_path / "empty")

    paths = LocalPostgresPaths.discover(project_root)

    assert paths.bin_dir == bin_dir


def test_write_database_url_preserves_values_and_encodes_password(tmp_path):
    paths = LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )
    paths.env_file.write_text("MINIMAX_API_KEY=existing\nDATABASE_URL=old\n", encoding="utf-8")
    manager = LocalPostgresManager(paths)

    message = manager.write_database_url("unsafe:/ password")

    contents = paths.env_file.read_text(encoding="utf-8")
    assert "MINIMAX_API_KEY=existing" in contents
    assert contents.count("DATABASE_URL=") == 1
    assert (
        "DATABASE_URL=postgresql+psycopg://newsradar:unsafe%3A%2F%20password"
        "@127.0.0.1:55432/newsradar" in contents
    )
    assert "unsafe:/ password" not in message


def test_initialize_runs_expected_commands_and_deletes_password_file(tmp_path):
    paths = LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )
    calls: list[tuple[list[str], dict[str, str] | None, bool]] = []

    def runner(command, *, env=None, check=True, capture_output=True, text=True):
        command = [str(part) for part in command]
        calls.append((command, env, capture_output))
        if command[0].endswith("initdb.exe"):
            paths.data_dir.mkdir(parents=True, exist_ok=True)
            (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")
            (paths.data_dir / "postgresql.conf").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    manager = LocalPostgresManager(paths, runner=runner, port_in_use=lambda: False)

    message = manager.initialize(password="generated-secret")

    commands = [call[0][0] for call in calls]
    assert any(command.endswith("initdb.exe") for command in commands)
    assert any(
        command.endswith("pg_ctl.exe") and "start" in call[0]
        for call in calls
        for command in call[0][:1]
    )
    assert any(command.endswith("createdb.exe") for command in commands)
    start_call = next(call for call in calls if call[0][0].endswith("pg_ctl.exe"))
    assert start_call[2] is False
    init_command = next(call[0] for call in calls if call[0][0].endswith("initdb.exe"))
    password_argument = next(part for part in init_command if part.startswith("--pwfile="))
    assert not Path(password_argument.split("=", 1)[1]).exists()
    assert "generated-secret" not in message
    assert "port = 55432" in (paths.data_dir / "postgresql.conf").read_text(encoding="utf-8")
    assert "listen_addresses = '127.0.0.1'" in (paths.data_dir / "postgresql.conf").read_text(
        encoding="utf-8"
    )


def test_initialize_is_idempotent_for_existing_configured_cluster(tmp_path):
    paths = LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")
    paths.env_file.write_text(
        "DATABASE_URL=postgresql+psycopg://newsradar:hidden@127.0.0.1:55432/newsradar\n",
        encoding="utf-8",
    )
    calls = []
    manager = LocalPostgresManager(paths, runner=lambda *args, **kwargs: calls.append(args))

    message = manager.initialize()

    assert "already initialized" in message.lower()
    assert calls == []


def test_start_rejects_occupied_port_when_cluster_is_not_running(tmp_path):
    paths = LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")

    def stopped_cluster(command, **kwargs):
        return subprocess.CompletedProcess(command, 3, stdout="no server running", stderr="")

    manager = LocalPostgresManager(
        paths,
        runner=stopped_cluster,
        port_in_use=lambda: True,
    )

    with pytest.raises(LocalPostgresError, match="55432.*already in use"):
        manager.start()


def test_subprocess_failure_is_redacted(tmp_path):
    paths = LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")

    def failing_runner(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="database command failed")

    manager = LocalPostgresManager(paths, runner=failing_runner, port_in_use=lambda: False)

    with pytest.raises(LocalPostgresError, match="database command failed"):
        manager.start()


def test_initialize_failure_stops_started_cluster_and_preserves_data(tmp_path):
    paths = LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        command = [str(part) for part in command]
        calls.append(command)
        if command[0].endswith("initdb.exe"):
            paths.data_dir.mkdir(parents=True, exist_ok=True)
            (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")
            (paths.data_dir / "postgresql.conf").write_text("", encoding="utf-8")
        if command[0].endswith("createdb.exe"):
            raise subprocess.CalledProcessError(1, command, stderr="create failed")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    manager = LocalPostgresManager(paths, runner=runner, port_in_use=lambda: False)

    with pytest.raises(LocalPostgresError, match="create failed"):
        manager.initialize(password="fixed")

    assert any(command[0].endswith("pg_ctl.exe") and "stop" in command for command in calls)
    assert (paths.data_dir / "PG_VERSION").is_file()
    assert not paths.env_file.exists()


def test_repair_restores_missing_env_for_valid_cluster(tmp_path):
    paths = LocalPostgresPaths(
        project_root=tmp_path,
        bin_dir=make_install(tmp_path),
        data_dir=tmp_path / ".local" / "postgres" / "data",
        log_file=tmp_path / ".local" / "postgres" / "postgres.log",
        env_file=tmp_path / ".env",
    )
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "PG_VERSION").write_text("18", encoding="utf-8")

    def runner(command, **kwargs):
        command = [str(part) for part in command]
        stdout = "1\n" if command[0].endswith("psql.exe") else "ok"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    manager = LocalPostgresManager(paths, runner=runner, port_in_use=lambda: True)

    message = manager.repair(password="fixed")

    assert "repaired" in message.lower()
    assert "DATABASE_URL=" in paths.env_file.read_text(encoding="utf-8")
