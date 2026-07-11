from __future__ import annotations

import os
import secrets
import socket
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote

POSTGRES_HOST = "127.0.0.1"
POSTGRES_PORT = 55432
POSTGRES_USER = "newsradar"
POSTGRES_DATABASE = "newsradar"


class LocalPostgresError(RuntimeError):
    """A safe, user-facing local PostgreSQL lifecycle error."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class LocalPostgresPaths:
    project_root: Path
    bin_dir: Path
    data_dir: Path
    log_file: Path
    env_file: Path

    default_install_root: ClassVar[Path] = Path(r"C:\Program Files\PostgreSQL")
    required_binaries: ClassVar[tuple[str, ...]] = (
        "initdb.exe",
        "pg_ctl.exe",
        "createdb.exe",
        "pg_isready.exe",
    )

    @classmethod
    def discover(cls, project_root: Path) -> LocalPostgresPaths:
        candidates: list[Path] = []
        postgres_home = os.getenv("POSTGRES_HOME")
        if postgres_home:
            candidates.append(Path(postgres_home) / "bin")
        if cls.default_install_root.is_dir():
            version_dirs = sorted(
                cls.default_install_root.iterdir(),
                key=lambda path: _version_key(path.name),
                reverse=True,
            )
            candidates.extend(path / "bin" for path in version_dirs)

        bin_dir = next(
            (
                candidate.resolve()
                for candidate in candidates
                if all((candidate / name).is_file() for name in cls.required_binaries)
            ),
            None,
        )
        if bin_dir is None:
            raise LocalPostgresError(
                "PostgreSQL command-line tools were not found; set POSTGRES_HOME to the "
                "PostgreSQL installation directory"
            )

        root = project_root.resolve()
        runtime_dir = root / ".local" / "postgres"
        return cls(
            project_root=root,
            bin_dir=bin_dir,
            data_dir=runtime_dir / "data",
            log_file=runtime_dir / "postgres.log",
            env_file=root / ".env",
        )


def _version_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return (0,)


class LocalPostgresManager:
    def __init__(
        self,
        paths: LocalPostgresPaths,
        *,
        runner: Runner = subprocess.run,
        port_in_use: Callable[[], bool] | None = None,
    ) -> None:
        self.paths = paths
        self._runner = runner
        self._port_in_use = port_in_use or self._default_port_in_use

    def initialize(self, *, password: str | None = None) -> str:
        has_cluster = self._is_initialized()
        has_database_url = self._has_database_url()
        if has_cluster and has_database_url:
            return "Project-local PostgreSQL is already initialized."
        if has_cluster != has_database_url:
            raise LocalPostgresError(
                "Local PostgreSQL state is inconsistent: .env and data directory must both "
                "exist or both be absent"
            )
        if self._port_in_use():
            raise LocalPostgresError(f"Port {POSTGRES_PORT} is already in use")

        generated_password = password or secrets.token_urlsafe(32)
        runtime_dir = self.paths.data_dir.parent
        runtime_dir.mkdir(parents=True, exist_ok=True)
        password_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=runtime_dir,
                prefix="initdb-password-",
                delete=False,
            ) as password_file:
                password_file.write(generated_password)
                password_path = Path(password_file.name)
            password_path.chmod(0o600)
            self._run(
                [
                    self._binary("initdb.exe"),
                    f"--pgdata={self.paths.data_dir}",
                    f"--username={POSTGRES_USER}",
                    "--auth-host=scram-sha-256",
                    "--auth-local=trust",
                    "--encoding=UTF8",
                    f"--pwfile={password_path}",
                ]
            )
        finally:
            if password_path is not None:
                password_path.unlink(missing_ok=True)

        self._configure_cluster()
        self._start_process()
        process_env = os.environ.copy()
        process_env["PGPASSWORD"] = generated_password
        self._run(
            [
                self._binary("createdb.exe"),
                "--host",
                POSTGRES_HOST,
                "--port",
                str(POSTGRES_PORT),
                "--username",
                POSTGRES_USER,
                POSTGRES_DATABASE,
            ],
            env=process_env,
        )
        self.write_database_url(generated_password)
        return f"Project-local PostgreSQL initialized at {POSTGRES_HOST}:{POSTGRES_PORT}."

    def write_database_url(self, password: str) -> str:
        encoded_password = quote(password, safe="")
        database_url = (
            f"postgresql+psycopg://{POSTGRES_USER}:{encoded_password}"
            f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"
        )
        lines = self._initial_env_lines()
        replacement = f"DATABASE_URL={database_url}"
        updated: list[str] = []
        replaced = False
        for line in lines:
            if line.startswith("DATABASE_URL="):
                if not replaced:
                    updated.append(replacement)
                    replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated.insert(0, replacement)
        self.paths.env_file.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
        return "Updated the local DATABASE_URL without exposing credentials."

    def start(self) -> str:
        self._require_initialized()
        if self._cluster_running():
            return "Project-local PostgreSQL is already running."
        if self._port_in_use():
            raise LocalPostgresError(f"Port {POSTGRES_PORT} is already in use")
        self._start_process()
        return f"Project-local PostgreSQL started at {POSTGRES_HOST}:{POSTGRES_PORT}."

    def status(self) -> str:
        self._require_initialized()
        result = self._run(
            [
                self._binary("pg_isready.exe"),
                "--host",
                POSTGRES_HOST,
                "--port",
                str(POSTGRES_PORT),
                "--dbname",
                POSTGRES_DATABASE,
            ],
            check=False,
        )
        if result.returncode == 0:
            state = "is accepting connections"
        else:
            state = "is not accepting connections"
        return f"Project-local PostgreSQL {state} at {POSTGRES_HOST}:{POSTGRES_PORT}."

    def stop(self) -> str:
        self._require_initialized()
        if not self._cluster_running():
            return "Project-local PostgreSQL is already stopped."
        self._run(
            [
                self._binary("pg_ctl.exe"),
                "--pgdata",
                str(self.paths.data_dir),
                "--wait",
                "stop",
            ]
        )
        return "Project-local PostgreSQL stopped."

    def _initial_env_lines(self) -> list[str]:
        if self.paths.env_file.exists():
            return self.paths.env_file.read_text(encoding="utf-8").splitlines()
        example = self.paths.project_root / ".env.example"
        if example.exists():
            return example.read_text(encoding="utf-8").splitlines()
        return []

    def _configure_cluster(self) -> None:
        config_path = self.paths.data_dir / "postgresql.conf"
        with config_path.open("a", encoding="utf-8") as config:
            config.write("\n# News Codex project-local settings\n")
            config.write(f"listen_addresses = '{POSTGRES_HOST}'\n")
            config.write(f"port = {POSTGRES_PORT}\n")
            config.write("password_encryption = 'scram-sha-256'\n")

    def _start_process(self) -> None:
        self.paths.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self._binary("pg_ctl.exe"),
                "--pgdata",
                str(self.paths.data_dir),
                "--log",
                str(self.paths.log_file),
                "--wait",
                "start",
            ]
        )

    def _cluster_running(self) -> bool:
        result = self._run(
            [
                self._binary("pg_ctl.exe"),
                "--pgdata",
                str(self.paths.data_dir),
                "status",
            ],
            check=False,
        )
        return result.returncode == 0

    def _run(
        self,
        command: Sequence[str | Path],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner(
                [str(part) for part in command],
                env=env,
                check=check,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "PostgreSQL command failed").strip()
            raise LocalPostgresError(detail) from None
        except OSError as exc:
            raise LocalPostgresError(f"Unable to run PostgreSQL command: {exc}") from None

    def _binary(self, name: str) -> Path:
        return self.paths.bin_dir / name

    def _is_initialized(self) -> bool:
        return (self.paths.data_dir / "PG_VERSION").is_file()

    def _has_database_url(self) -> bool:
        if not self.paths.env_file.exists():
            return False
        expected = f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"
        return any(
            line.startswith("DATABASE_URL=") and expected in line
            for line in self.paths.env_file.read_text(encoding="utf-8").splitlines()
        )

    def _require_initialized(self) -> None:
        if not self._is_initialized():
            raise LocalPostgresError("Project-local PostgreSQL is not initialized; run db init")

    @staticmethod
    def _default_port_in_use() -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.25)
            return connection.connect_ex((POSTGRES_HOST, POSTGRES_PORT)) == 0


def build_local_postgres_manager(project_root: Path | None = None) -> LocalPostgresManager:
    root = project_root or Path.cwd()
    return LocalPostgresManager(LocalPostgresPaths.discover(root))
