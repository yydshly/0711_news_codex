# Task 6 Catalog Audit Report

## Scope and evidence

- Audited 67 Provider records and 166 Target records (including two new Targets).
- Anthropic Newsroom was checked against its official Newsroom and Consumer Terms pages on 2026-07-12. The newsroom exposes dated announcement links; the terms prohibit automated collection unless expressly permitted. It is therefore recorded as `needs_research`, disabled for ingestion, and limited to a manual-only HTML candidate.
- No target was marked `verified` without a documented primary candidate with a successful or partial sample, evidence, purpose, risk conclusion, and fallback treatment.

## Catalog changes

- Added an explicit `research.status` to every existing YAML Target.
- Classified 134 `sources/universe` entries as `placeholder`: they are platform/search-layer candidates, not independently confirmed collectible Targets.
- Classified 30 previously executable named Targets as `needs_research`; their identity and configured entry remain visible, while their method samples, terms review, and fallback analysis remain incomplete.
- Added `anthropic-newsroom`, an official first-party AI-news source with a documented manual-only, no-bypass acquisition boundary.
- Added `sec-nvidia-filings`, an official SEC EDGAR regulatory-evidence Target for NVIDIA, based on the SEC's documented unauthenticated JSON submissions API and kept disabled pending policy review and a compliant sample.

## Generated outputs

- `reports/source-research-v3-audit.md` is a full catalog audit rendering.
- `reports/source-research-v3-matrix.md` is the full per-Target research-method matrix.
- `reports/provider-audit.md` is the generated full Provider coverage report: all 67 Providers are listed with category, cost, availability, probe state, and unlock requirements. Provider YAML schema already requires HTTPS homepage, docs URL, terms URL, and evidence; this report makes the category review visible.
- The current CLI's `research audit` command does not expose the brief's `--output` option; both files were rendered through the same read-only `research report --output` renderer. This is an interface gap, not an unrecorded audit.

## Verification

```powershell
uv run pytest tests/research/test_catalog_completion.py -q
uv run newsradar sources research validate --root sources --provider-root providers
uv run newsradar sources research report --root sources --provider-root providers --output reports/source-research-v3-audit.md
uv run newsradar sources research report --root sources --provider-root providers --output reports/source-research-v3-matrix.md
```

The catalog-completion test passed (2 passed). The validation and report commands completed with warnings only: generic platform targets and duplicated universe identities are intentionally visible, while the 31 named Targets are recorded as `needs_research` rather than fabricated as verified coverage.

## Unfinished work

- Individually research, sample, and, where permitted, promote concrete named Targets; this requires evidence and compliant probe runs per candidate.
- Replace or retire the large placeholder universe set after concrete target identities are selected.
- Add `--output` support to the `research audit` CLI command if the exact command in the brief must be supported.
