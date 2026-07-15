from __future__ import annotations

import httpx

from newsradar.providers.schema import ProviderDefinition
from newsradar.sources.catalog_refresh import (
    CatalogRefreshLane,
    CatalogResultCode,
    build_catalog_refresh_plan,
    validate_catalog_entry,
)
from newsradar.sources.schema import SourceDefinition

from .test_provider_schema import valid_provider
from .test_source_schema import valid_source


def catalog_source(source_id: str = "catalog-source", **changes: object) -> SourceDefinition:
    payload = valid_source()
    payload.update({"id": source_id, "name": source_id})
    for key, value in changes.items():
        payload[key] = value
    return SourceDefinition.model_validate(payload)


def catalog_provider(**changes: object) -> ProviderDefinition:
    payload = valid_provider()
    payload.update(changes)
    return ProviderDefinition.model_validate(payload)


def test_plan_routes_ready_rss_to_content() -> None:
    source = catalog_source()

    plan = build_catalog_refresh_plan([source], [catalog_provider(id="independent")], {}, set())

    assert plan.members[0].lane is CatalogRefreshLane.CONTENT


def test_plan_routes_capability_and_catalog_cases() -> None:
    credentialed = catalog_source(
        "credentialed",
        access_methods=[
            {
                "kind": "rss",
                "url": "https://www.anthropic.com/news/rss.xml",
                "priority": 1,
                "auth_envs": ["SOURCE_TOKEN"],
            }
        ],
    )
    approval = catalog_source("approval", availability="requires_approval")
    payment = catalog_source("payment", availability="requires_payment")
    unavailable = catalog_source("unavailable", availability="unavailable")
    manual = catalog_source("manual", availability="manual_only")
    catalog_only = catalog_source("catalog-only", coverage_mode="catalog_only")
    html = catalog_source(
        "html",
        access_methods=[
            {
                "kind": "html",
                "url": "https://www.anthropic.com/news",
                "priority": 1,
                "requires_manual_approval": True,
            }
        ],
    )
    provider = catalog_provider(id="independent")

    plan = build_catalog_refresh_plan(
        [credentialed, approval, payment, unavailable, manual, catalog_only, html],
        [provider],
        {},
        set(),
    )

    members = {member.source_id: member for member in plan.members}
    assert members["credentialed"].lane is CatalogRefreshLane.CAPABILITY
    assert members["credentialed"].initial_result_code is CatalogResultCode.MISSING_CREDENTIALS
    assert {
        source_id
        for source_id, member in members.items()
        if member.lane is CatalogRefreshLane.CAPABILITY
    } == {"credentialed", "approval", "payment", "unavailable"}
    assert {
        source_id
        for source_id, member in members.items()
        if member.lane is CatalogRefreshLane.CATALOG
    } == {"manual", "catalog-only", "html"}


def test_plan_excludes_archived_source_and_keeps_current_kind_when_latest_is_stale() -> None:
    archived = catalog_source("archived")
    object.__setattr__(archived, "catalog_state", "archived")
    current = catalog_source("current")

    plan = build_catalog_refresh_plan(
        [archived, current],
        [catalog_provider(id="independent")],
        {"current": {"access_kind": "html"}},
        set(),
    )

    assert [member.source_id for member in plan.members] == ["current"]
    assert plan.members[0].access_kind == "rss"
    assert plan.members[0].initial_result_code is CatalogResultCode.STALE_RESULT


def test_plan_is_sorted_and_has_stable_digest() -> None:
    alpha = catalog_source("alpha")
    beta = catalog_source("beta")
    provider = catalog_provider(id="independent")

    first = build_catalog_refresh_plan([beta, alpha], [provider], {}, set())
    second = build_catalog_refresh_plan([alpha, beta], [provider], {}, set())

    assert [member.source_id for member in first.members] == ["alpha", "beta"]
    assert first.catalog_digest == second.catalog_digest
    assert first.digest == first.catalog_digest
    assert first.lane_counts == {CatalogRefreshLane.CONTENT: 2}


def test_plan_routes_credentialed_ready_source_to_content_when_keys_are_supplied() -> None:
    source = catalog_source(
        access_methods=[
            {
                "kind": "rss",
                "url": "https://www.anthropic.com/news/rss.xml",
                "priority": 1,
                "auth_envs": ["SOURCE_TOKEN"],
            }
        ]
    )

    plan = build_catalog_refresh_plan(
        [source], [catalog_provider(id="independent")], {}, {"SOURCE_TOKEN"}
    )

    assert plan.members[0].lane is CatalogRefreshLane.CONTENT
    assert plan.members[0].initial_result_code is None


def test_catalog_validation_is_complete_and_never_uses_http(monkeypatch) -> None:
    source = catalog_source(
        official_identity_url="https://www.anthropic.com/",
        reviewed_at="2026-07-11",
        risk={**valid_source()["risk"], "evidence": ["https://www.anthropic.com/legal"]},
        research={"conclusion": "该来源具备清晰的官方身份与可审计风险证据。"},
    )

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )
    result = validate_catalog_entry(source, catalog_provider(id="independent"))

    assert result.code is CatalogResultCode.CATALOG_VERIFIED
    assert result.missing == ()
    assert result.missing_fields == result.missing


def test_catalog_validation_reports_missing_fields_in_stable_order() -> None:
    result = validate_catalog_entry(catalog_source(), catalog_provider(id="independent"))

    assert result.code is CatalogResultCode.CATALOG_INCOMPLETE
    assert result.missing == (
        "official_identity_url",
        "risk_evidence",
        "reviewed_at",
        "readable_conclusion",
    )
