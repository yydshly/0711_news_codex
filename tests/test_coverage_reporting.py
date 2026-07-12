from newsradar.providers.reporting import render_coverage_report
from newsradar.providers.schema import ProviderDefinition
from newsradar.sources.schema import SourceDefinition

from .test_provider_schema import valid_provider
from .test_source_schema import valid_source


def test_coverage_report_separates_catalog_direct_and_blocked() -> None:
    provider_data = valid_provider()
    providers = [ProviderDefinition.model_validate(provider_data)]
    direct = valid_source()
    direct.update(
        {"provider_id": "bluesky", "official_identity_url": "https://bsky.app/profile/openai.com"}
    )
    blocked = valid_source()
    blocked.update(
        {
            "id": "x-openai",
            "name": "OpenAI on X",
            "provider_id": "x",
            "nature": "social",
            "roles": ["discovery", "engagement"],
            "target_type": "account",
            "availability": "requires_payment",
            "coverage_mode": "catalog_only",
            "official_identity_url": "https://x.com/openai",
        }
    )

    report = render_coverage_report(
        providers,
        [SourceDefinition.model_validate(direct), SourceDefinition.model_validate(blocked)],
    )

    assert "Catalog targets | 2" in report
    assert "Direct targets | 1" in report
    assert "Blocked targets | 1" in report
    assert "requires_payment" in report
