"""Shared local-only construction of reviewed high-value wave plans."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from newsradar.credentials import SettingsCredentials
from newsradar.providers.repository import ProviderRepository
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.sources.repository import SourceRepository
from newsradar.sources.yaml_loader import load_source_tree
from newsradar.waves.loader import load_wave_profile
from newsradar.waves.planning import WavePlan, build_wave_plan

_DEFAULT_PROFILE_PATH = Path("wave_profiles/high-value-ai-tech.yaml")


def build_local_wave_plan(
    session: Session,
    *,
    profile_path: Path = _DEFAULT_PROFILE_PATH,
    window_hours: int,
) -> WavePlan:
    """Freeze reviewed local catalog state without creating network or model clients."""
    profile = load_wave_profile(profile_path)
    profile = profile.model_copy(update={"window_hours": window_hours})
    sources = load_source_tree(Path("sources"))
    providers = load_provider_tree(Path("providers"))
    ProviderRepository(session).sync(providers)
    SourceRepository(session).sync(sources)
    session.flush()
    repository = SourceRepository(session)
    source_ids = list(profile.source_ids)
    return build_wave_plan(
        profile,
        sources,
        repository.latest_probe_snapshots(source_ids),
        SettingsCredentials().configured_names(),
        successful_fetch_access=repository.successful_fetch_access(source_ids),
    )
