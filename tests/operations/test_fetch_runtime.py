from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationRunRecord
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import SourceFetchSummary
from newsradar.operations.repository import OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import Worker
from newsradar.sources.probes.base import ProbeOutcome, ProbeResult, ProbeSample
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _source(source_id: str = "source-a") -> SourceDefinition:
    return SourceDefinition.model_validate(
        {
            "id": source_id,
            "name": "Source A",
            "status": "active",
            "nature": "first_party",
            "roles": ["discovery"],
            "language": "en",
            "topics": ["ai"],
            "authority_score": 5,
            "poll_interval_minutes": 60,
            "official_identity_url": "https://source-a.test",
            "access_methods": [{"kind": "rss", "url": "https://source-a.test/feed", "priority": 1}],
            "expected_fields": ["title", "canonical_url", "published_at"],
            "risk": {
                "terms": 0,
                "authentication": 0,
                "stability": 0,
                "data_quality": 0,
                "operating_cost": 0,
            },
            "ingestion": {"enabled": True, "approved_at": "2026-07-12T00:00:00Z"},
        }
    )


def test_worker_executes_queued_fetch_and_persists_summary() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "source-a"})
        calls: list[str] = []

        def execute(source, operation_id, checkpoint, requested_scope):
            calls.append(source.id)
            assert operation_id == operation.id
            checkpoint("network_complete")
            return SourceFetchSummary(
                source.id,
                FetchResult(outcome=FetchOutcome.SUCCEEDED, items_received=2, items_inserted=1),
                fetch_run_id=9,
            )

        processed = Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert processed is True
        assert calls == ["source-a"]
        assert record is not None
        assert record.status == OperationStatus.SUCCEEDED
        assert record.result_summary == {
            "source_id": "source-a",
            "fetch_run_id": 9,
            "outcome": "succeeded",
            "items_received": 2,
            "items_inserted": 1,
        }


def test_worker_keeps_policy_blocked_fetch_terminal_without_retry() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "source-a"})

        def execute(source, operation_id, checkpoint, requested_scope):
            return SourceFetchSummary(
                source.id,
                FetchResult(
                    outcome=FetchOutcome.BLOCKED,
                    error_code="missing_credentials",
                    error_message="Credentials are not configured",
                ),
            )

        processed = Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert processed is True
        assert record is not None
        assert record.status == OperationStatus.PARTIAL
        assert record.attempt_count == 1
        assert record.error_code == "missing_credentials"


def test_worker_marks_unknown_fetch_source_failed_without_retry() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "missing"})

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([], lambda *_: None)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == OperationStatus.FAILED
        assert record.attempt_count == 1
        assert record.error_code == "unknown_source"


def test_fetch_worker_does_not_retry_credential_or_client_errors() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "source-a"})

        def execute(source, operation_id, checkpoint, requested_scope):
            return SourceFetchSummary(
                source.id,
                FetchResult(
                    outcome=FetchOutcome.FAILED,
                    http_status=403,
                    error_code="missing_credential",
                    error_message="credential is absent",
                ),
            )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == OperationStatus.FAILED
        assert record.attempt_count == 1


def test_fetch_worker_retries_transport_and_rate_limit_failures() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(OperationType.FETCH, {"source_id": "source-a"})

        def execute(source, operation_id, checkpoint, requested_scope):
            return SourceFetchSummary(
                source.id,
                FetchResult(
                    outcome=FetchOutcome.FAILED,
                    http_status=429,
                    error_code="rate_limited",
                    retry_after_seconds=15,
                ),
            )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == OperationStatus.QUEUED
        assert record.attempt_count == 1


def test_fetch_worker_rejects_expired_operation_before_source_execution() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {"source_id": "source-a", "deadline_at": expired},
        )
        calls: list[str] = []

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], lambda *_: calls.append("executed"))
        )

        record = db.get(OperationRunRecord, operation.id)
        assert calls == []
        assert record is not None
        assert record.status == OperationStatus.FAILED
        assert record.error_code == "operation_timeout"


def test_fetch_worker_passes_audited_scope_to_executor() -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler

    with _session() as db:
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {
                "source_id": "source-a",
                "dry_run": True,
                "max_items": 3,
                "one_off": True,
            },
        )
        scopes: list[dict[str, object]] = []

        def execute(source, operation_id, checkpoint, requested_scope):
            scopes.append(dict(requested_scope))
            return SourceFetchSummary(
                source.id,
                FetchResult(outcome=FetchOutcome.SUCCEEDED),
            )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler([_source()], execute)
        )

        assert scopes == [operation.requested_scope]


def test_trial_fetch_worker_blocks_ineligible_latest_probe_before_creating_fetcher(
    monkeypatch,
) -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler
    from newsradar.sources.repository import SourceRepository

    with _session() as db:
        source = _source()
        SourceRepository(db).sync([source])
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {"source_id": source.id, "trial": True},
        )
        factory_calls: list[object] = []

        def fail_if_fetcher_created(policy):
            factory_calls.append(policy)
            raise AssertionError("trial eligibility must be checked before creating a fetcher")

        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.create_session", lambda: nullcontext(db)
        )
        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.FetcherFactory", fail_if_fetcher_created
        )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler.production([source])
        )

        record = db.get(OperationRunRecord, operation.id)
        assert factory_calls == []
        assert record is not None
        assert record.status == OperationStatus.PARTIAL
        assert record.error_code == "eligibility_trial_no_probe"


def test_trial_fetch_worker_blocks_credentials_access_before_creating_fetcher(monkeypatch) -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler
    from newsradar.sources.repository import SourceRepository

    source_data = valid_source()
    source_data["id"] = "source-a"
    source_data["access_methods"] = [
        {
            "kind": "rss",
            "url": "https://source-a.test/feed",
            "priority": 1,
            "auth_envs": ["TRIAL_TEST_TOKEN"],
        }
    ]
    source = SourceDefinition.model_validate(source_data)
    with _session() as db:
        repository = SourceRepository(db)
        repository.sync([source])
        now = datetime(2026, 7, 13, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rss",
                access_url="https://source-a.test/feed",
                outcome=ProbeOutcome.SUCCESS,
                started_at=now,
                finished_at=now,
                sample_count=1,
                field_completeness=1.0,
                suggested_status="candidate",
                reason="ok",
                samples=[
                    ProbeSample(
                        external_id="one",
                        title="First",
                        canonical_url="https://source-a.test/one",
                    )
                ],
            )
        )
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {"source_id": source.id, "trial": True},
        )
        factory_calls: list[object] = []

        def fail_if_fetcher_created(policy):
            factory_calls.append(policy)
            raise AssertionError("credentials trial source must not create a fetcher")

        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.create_session", lambda: nullcontext(db)
        )
        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.FetcherFactory", fail_if_fetcher_created
        )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler.production([source])
        )

        record = db.get(OperationRunRecord, operation.id)
        assert factory_calls == []
        assert record is not None
        assert record.status == OperationStatus.PARTIAL
        assert record.error_code == "eligibility_trial_credentials_not_allowed"


def test_trial_fetch_worker_blocks_sensitive_headers_before_creating_fetcher(monkeypatch) -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler
    from newsradar.sources.repository import SourceRepository

    source_data = valid_source()
    source_data["id"] = "sensitive-header-source"
    source_data["access_methods"] = [
        {
            "kind": "rss",
            "url": "https://source-a.test/feed",
            "priority": 1,
            "headers": {"aUtHoRiZaTiOn": "Bearer test"},
        }
    ]
    source = SourceDefinition.model_validate(source_data)
    with _session() as db:
        repository = SourceRepository(db)
        repository.sync([source])
        now = datetime(2026, 7, 13, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rss",
                access_url="https://source-a.test/feed",
                outcome=ProbeOutcome.SUCCESS,
                started_at=now,
                finished_at=now,
                sample_count=1,
                field_completeness=1.0,
                suggested_status="candidate",
                reason="ok",
                samples=[
                    ProbeSample(
                        external_id="one",
                        title="First",
                        canonical_url="https://source-a.test/one",
                    )
                ],
            )
        )
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH, {"source_id": source.id, "trial": True}
        )

        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.create_session", lambda: nullcontext(db)
        )
        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.FetcherFactory",
            lambda policy: (_ for _ in ()).throw(
                AssertionError("sensitive-header trial must not create a fetcher")
            ),
        )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler.production([source])
        )

        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == OperationStatus.PARTIAL
        assert record.error_code == "eligibility_trial_sensitive_headers_not_allowed"


def test_trial_fetch_worker_uses_public_method_when_credential_method_has_priority(
    monkeypatch,
) -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler
    from newsradar.sources.repository import SourceRepository

    source_data = valid_source()
    source_data["id"] = "source-a"
    source_data["access_methods"] = [
        {
            "kind": "rss",
            "url": "https://source-a.test/credential-feed",
            "priority": 1,
            "auth_envs": ["TRIAL_TEST_TOKEN"],
        },
        {
            "kind": "rss",
            "url": "https://source-a.test/public-feed",
            "priority": 2,
        },
    ]
    source = SourceDefinition.model_validate(source_data)
    with _session() as db:
        repository = SourceRepository(db)
        repository.sync([source])
        now = datetime(2026, 7, 13, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rss",
                access_url="https://source-a.test/public-feed",
                outcome=ProbeOutcome.SUCCESS,
                started_at=now,
                finished_at=now,
                sample_count=1,
                field_completeness=1.0,
                suggested_status="candidate",
                reason="ok",
                samples=[
                    ProbeSample(
                        external_id="one",
                        title="First",
                        canonical_url="https://source-a.test/one",
                    )
                ],
            )
        )
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH,
            {"source_id": source.id, "trial": True},
        )
        selected_methods: list[str] = []

        class RecordingFetcher:
            async def fetch(self, source, method, state, limit):
                selected_methods.append(str(method.url))
                return FetchResult(outcome=FetchOutcome.NO_CHANGE)

        class RecordingFactory:
            def for_method(self, method, *, credential_free_only=False):
                assert credential_free_only is True
                selected_methods.append(str(method.url))
                return RecordingFetcher()

        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.create_session", lambda: nullcontext(db)
        )
        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.FetcherFactory", lambda policy: RecordingFactory()
        )
        monkeypatch.setattr(
            "newsradar.ingestion.service.SettingsCredentials.configured_names",
            lambda self: {"TRIAL_TEST_TOKEN"},
        )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler.production([source])
        )

        record = db.get(OperationRunRecord, operation.id)
        assert selected_methods == [
            "https://source-a.test/public-feed",
            "https://source-a.test/public-feed",
        ]
        assert record is not None


def test_trial_fetch_worker_uses_header_safe_method_when_sensitive_method_has_priority(
    monkeypatch,
) -> None:
    from newsradar.operations.fetch_runtime import FetchOperationHandler
    from newsradar.sources.repository import SourceRepository

    source_data = valid_source()
    source_data["id"] = "header-priority-source"
    source_data["access_methods"] = [
        {
            "kind": "rss",
            "url": "https://source-a.test/sensitive-feed",
            "priority": 1,
            "headers": {"Cookie": "test-session"},
        },
        {"kind": "rss", "url": "https://source-a.test/public-feed", "priority": 2},
    ]
    source = SourceDefinition.model_validate(source_data)
    with _session() as db:
        repository = SourceRepository(db)
        repository.sync([source])
        now = datetime(2026, 7, 13, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rss",
                access_url="https://source-a.test/public-feed",
                outcome=ProbeOutcome.SUCCESS,
                started_at=now,
                finished_at=now,
                sample_count=1,
                field_completeness=1.0,
                suggested_status="candidate",
                reason="ok",
                samples=[
                    ProbeSample(
                        external_id="one",
                        title="First",
                        canonical_url="https://source-a.test/one",
                    )
                ],
            )
        )
        OperationRepository(db).enqueue(
            OperationType.FETCH, {"source_id": source.id, "trial": True}
        )
        selected_methods: list[str] = []

        class RecordingFetcher:
            async def fetch(self, source, method, state, limit):
                selected_methods.append(str(method.url))
                return FetchResult(outcome=FetchOutcome.NO_CHANGE)

        class RecordingFactory:
            def for_method(self, method, *, credential_free_only=False):
                assert credential_free_only is True
                selected_methods.append(str(method.url))
                return RecordingFetcher()

        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.create_session", lambda: nullcontext(db)
        )
        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.FetcherFactory", lambda policy: RecordingFactory()
        )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler.production([source])
        )

        assert selected_methods == [
            "https://source-a.test/public-feed",
            "https://source-a.test/public-feed",
        ]


@pytest.mark.parametrize(
    ("host", "path"),
    [
        ("www.googleapis.com", "/youtube/v3/search"),
        ("oauth.reddit.com", "/r/LocalLLaMA/new"),
    ],
)
def test_trial_worker_blocks_special_host_without_constructing_credential_fetcher_or_network(
    monkeypatch, host: str, path: str
) -> None:
    from newsradar.ingestion.fetchers.credentials import EnvironmentCredentials
    from newsradar.operations.fetch_runtime import FetchOperationHandler
    from newsradar.sources.repository import SourceRepository

    source_data = valid_source()
    source_data["id"] = f"special-{host.split('.')[0]}"
    source_data["access_methods"] = [
        {"kind": "rest_api", "url": f"https://{host}{path}", "priority": 1}
    ]
    source = SourceDefinition.model_validate(source_data)
    with _session() as db:
        repository = SourceRepository(db)
        repository.sync([source])
        now = datetime(2026, 7, 13, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rest_api",
                access_url=str(source.access_methods[0].url),
                outcome=ProbeOutcome.SUCCESS,
                started_at=now,
                finished_at=now,
                sample_count=1,
                field_completeness=1.0,
                suggested_status="candidate",
                reason="ok",
                samples=[
                    ProbeSample(
                        external_id="one",
                        title="First",
                        canonical_url="https://source-a.test/one",
                    )
                ],
            )
        )
        operation = OperationRepository(db).enqueue(
            OperationType.FETCH, {"source_id": source.id, "trial": True}
        )

        def fail_credentials_init(self, *args, **kwargs):
            raise AssertionError("trial must not construct a credential provider")

        async def fail_network(self, *args, **kwargs):
            raise AssertionError("trial must not make a network request")

        monkeypatch.setattr(
            "newsradar.operations.fetch_runtime.create_session", lambda: nullcontext(db)
        )
        monkeypatch.setattr(EnvironmentCredentials, "__init__", fail_credentials_init)
        monkeypatch.setattr("newsradar.ingestion.fetchers.base.HttpPolicy.get", fail_network)
        monkeypatch.setattr("httpx.AsyncClient.post", fail_network)
        fetcher_module = "youtube" if host == "www.googleapis.com" else "reddit"
        fetcher_name = "YouTubeFetcher" if fetcher_module == "youtube" else "RedditFetcher"
        monkeypatch.setattr(
            f"newsradar.ingestion.fetchers.{fetcher_module}.{fetcher_name}",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("trial must not construct a credential-reading fetcher")
            ),
        )

        Worker(OperationRepository(db), "worker-a").run_once(
            FetchOperationHandler.production([source])
        )

        record = db.get(OperationRunRecord, operation.id)
        assert record is not None
        assert record.status == OperationStatus.PARTIAL
        assert record.error_code == "eligibility_trial_credentials_not_allowed"


@pytest.mark.asyncio
async def test_non_trial_special_host_still_constructs_its_specialized_fetcher() -> None:
    import httpx

    from newsradar.ingestion.fetchers.base import FetcherFactory, HttpPolicy
    from newsradar.ingestion.fetchers.youtube import YouTubeFetcher

    method = SourceDefinition.model_validate(
        {
            **valid_source(),
            "access_methods": [
                {
                    "kind": "rest_api",
                    "url": "https://www.googleapis.com/youtube/v3/search",
                    "priority": 1,
                }
            ],
        }
    ).access_methods[0]
    async with httpx.AsyncClient() as client:
        fetcher = FetcherFactory(HttpPolicy(client), credentials=object()).for_method(method)

    assert isinstance(fetcher, YouTubeFetcher)
