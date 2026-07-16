from __future__ import annotations

import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote

POSTGRES_HOST = "127.0.0.1"
POSTGRES_DEFAULT_PORT = 55432
POSTGRES_USER = "newsradar"
POSTGRES_DATABASE = "newsradar"


class LocalPostgresError(RuntimeError):
    """A safe, user-facing local PostgreSQL lifecycle error."""


Runner = Callable[..., subprocess.CompletedProcess[str]]
PortExcluded = Callable[[int], bool]


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
        "psql.exe",
    )

    @classmethod
    def discover(cls, project_root: Path) -> LocalPostgresPaths:
        root = project_root.resolve()
        candidates: list[Path] = []
        postgres_home = os.getenv("POSTGRES_HOME") or _read_env_value(
            root / ".env", "POSTGRES_HOME"
        )
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


def _read_env_value(env_file: Path, key: str) -> str | None:
    if not env_file.exists():
        return None
    prefix = f"{key}="
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            value = line.removeprefix(prefix).strip().strip('"').strip("'")
            return value or None
    return None


def resolve_postgres_port(project_root: Path) -> int:
    raw = os.getenv("NEWSRADAR_POSTGRES_PORT") or _read_env_value(
        project_root / ".env", "NEWSRADAR_POSTGRES_PORT"
    )
    if raw is None:
        return POSTGRES_DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError as error:
        raise LocalPostgresError(
            "NEWSRADAR_POSTGRES_PORT must be an integer from 1024 to 65535"
        ) from error
    if not 1024 <= port <= 65535:
        raise LocalPostgresError(
            "NEWSRADAR_POSTGRES_PORT must be an integer from 1024 to 65535"
        )
    return port


def parse_excluded_port_ranges(output: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for line in output.splitlines():
        match = re.fullmatch(r"\s*(\d+)\s+(\d+)(?:\s+\*)?\s*", line)
        if match:
            ranges.append((int(match.group(1)), int(match.group(2))))
    return tuple(ranges)


def windows_port_is_excluded(port: int, *, runner: Runner = subprocess.run) -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = runner(
            [
                "netsh",
                "interface",
                "ipv4",
                "show",
                "excludedportrange",
                "protocol=tcp",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    return any(start <= port <= end for start, end in parse_excluded_port_ranges(result.stdout))


class LocalPostgresManager:
    def __init__(
        self,
        paths: LocalPostgresPaths,
        *,
        port: int = POSTGRES_DEFAULT_PORT,
        runner: Runner = subprocess.run,
        port_in_use: Callable[[], bool] | None = None,
        port_excluded: PortExcluded | None = None,
    ) -> None:
        self.paths = paths
        self.port = port
        self._runner = runner
        self._port_in_use = port_in_use or self._default_port_in_use
        self._port_excluded = port_excluded or (lambda _: False)

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
        self._ensure_port_available()

        generated_password = password or secrets.token_urlsafe(32)
        runtime_dir = self.paths.data_dir.parent
        runtime_dir.mkdir(parents=True, exist_ok=True)
        password_path: Path | None = None
        started = False
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
            self._configure_cluster()
            self._start_process()
            started = True
            process_env = os.environ.copy()
            process_env["PGPASSWORD"] = generated_password
            self._run(
                [
                    self._binary("createdb.exe"),
                    "--host",
                    POSTGRES_HOST,
                    "--port",
                    str(self.port),
                    "--username",
                    POSTGRES_USER,
                    POSTGRES_DATABASE,
                ],
                env=process_env,
            )
            self.write_database_url(generated_password)
        except Exception:
            if started:
                self._stop_process_safely()
            raise
        finally:
            if password_path is not None:
                password_path.unlink(missing_ok=True)
        return f"Project-local PostgreSQL initialized at {POSTGRES_HOST}:{self.port}."

    def repair(self, *, password: str | None = None) -> str:
        has_cluster = self._is_initialized()
        has_database_url = self._has_database_url()
        if not has_cluster:
            if has_database_url:
                raise LocalPostgresError(
                    "Local PostgreSQL data is missing while .env still contains the project "
                    "DATABASE_URL; preserve .env and backups, then restore data manually"
                )
            raise LocalPostgresError("Project-local PostgreSQL is not initialized; run db init")
        if has_database_url:
            return "Project-local PostgreSQL does not require repair."
        if not password:
            raise LocalPostgresError("A database password is required to repair DATABASE_URL")

        started = False
        try:
            if not self._cluster_running():
                self._ensure_port_available()
                self._start_process()
                started = True
            if not self._database_exists(password):
                process_env = os.environ.copy()
                process_env["PGPASSWORD"] = password
                self._run(
                    [
                        self._binary("createdb.exe"),
                        "--host",
                        POSTGRES_HOST,
                        "--port",
                        str(self.port),
                        "--username",
                        POSTGRES_USER,
                        POSTGRES_DATABASE,
                    ],
                    env=process_env,
                )
            self.write_database_url(password)
        except Exception:
            if started:
                self._stop_process_safely()
            raise
        return "Project-local PostgreSQL repaired without deleting data or logs."

    def write_database_url(self, password: str) -> str:
        encoded_password = quote(password, safe="")
        database_url = (
            f"postgresql+psycopg://{POSTGRES_USER}:{encoded_password}"
            f"@{POSTGRES_HOST}:{self.port}/{POSTGRES_DATABASE}"
        )
        lines = self._initial_env_lines()
        replacements = {
            "DATABASE_URL": f"DATABASE_URL={database_url}",
            "NEWSRADAR_POSTGRES_PORT": f"NEWSRADAR_POSTGRES_PORT={self.port}",
        }
        updated: list[str] = []
        replaced: set[str] = set()
        for line in lines:
            key = line.partition("=")[0]
            if key in replacements:
                if key not in replaced:
                    updated.append(replacements[key])
                    replaced.add(key)
                continue
            updated.append(line)
        for key in ("NEWSRADAR_POSTGRES_PORT", "DATABASE_URL"):
            if key not in replaced:
                updated.insert(0, replacements[key])
        self.paths.env_file.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
        return "Updated the local DATABASE_URL without exposing credentials."

    def start(self) -> str:
        self._require_initialized()
        if self._cluster_running():
            return "Project-local PostgreSQL is already running."
        self._ensure_port_available()
        self._start_process()
        return f"Project-local PostgreSQL started at {POSTGRES_HOST}:{self.port}."

    def status(self) -> str:
        self._require_initialized()
        result = self._run(
            [
                self._binary("pg_isready.exe"),
                "--host",
                POSTGRES_HOST,
                "--port",
                str(self.port),
                "--dbname",
                POSTGRES_DATABASE,
            ],
            check=False,
        )
        if result.returncode == 0:
            state = "is accepting connections"
        else:
            state = "is not accepting connections"
        return f"Project-local PostgreSQL {state} at {POSTGRES_HOST}:{self.port}."

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
            config.write(f"port = {self.port}\n")
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
            ],
            capture_output=False,
        )

    def _stop_process_safely(self) -> None:
        try:
            self._run(
                [
                    self._binary("pg_ctl.exe"),
                    "--pgdata",
                    str(self.paths.data_dir),
                    "--wait",
                    "stop",
                ],
                check=False,
            )
        except LocalPostgresError:
            pass

    def _database_exists(self, password: str) -> bool:
        process_env = os.environ.copy()
        process_env["PGPASSWORD"] = password
        result = self._run(
            [
                self._binary("psql.exe"),
                "--host",
                POSTGRES_HOST,
                "--port",
                str(self.port),
                "--username",
                POSTGRES_USER,
                "--dbname",
                "postgres",
                "--tuples-only",
                "--no-align",
                "--command",
                f"SELECT 1 FROM pg_database WHERE datname = '{POSTGRES_DATABASE}'",
            ],
            env=process_env,
        )
        return result.stdout.strip() == "1"

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
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner(
                [str(part) for part in command],
                env=env,
                check=check,
                capture_output=capture_output,
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
        expected = f"@{POSTGRES_HOST}:{self.port}/{POSTGRES_DATABASE}"
        return any(
            line.startswith("DATABASE_URL=") and expected in line
            for line in self.paths.env_file.read_text(encoding="utf-8").splitlines()
        )

    def _require_initialized(self) -> None:
        if not self._is_initialized():
            raise LocalPostgresError("Project-local PostgreSQL is not initialized; run db init")

    def _ensure_port_available(self) -> None:
        if self._port_excluded(self.port):
            raise LocalPostgresError(
                f"Port {self.port} is reserved by Windows; set "
                "NEWSRADAR_POSTGRES_PORT=55232 and run newsradar db repair"
            )
        if self._port_in_use():
            raise LocalPostgresError(f"Port {self.port} is already in use")

    def _default_port_in_use(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.25)
            return connection.connect_ex((POSTGRES_HOST, self.port)) == 0


def build_local_postgres_manager(project_root: Path | None = None) -> LocalPostgresManager:
    root = project_root or Path.cwd()
    return LocalPostgresManager(
        LocalPostgresPaths.discover(root),
        port=resolve_postgres_port(root),
        port_excluded=windows_port_is_excluded,
    )
