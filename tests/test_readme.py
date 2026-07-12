from pathlib import Path


def test_readme_documents_operational_runtime_and_current_boundaries() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    for command in (
        "uv run newsradar serve",
        "uv run newsradar worker --once",
        "uv run newsradar worker --forever",
        "uv run newsradar fetch hackernews-top --root sources --no-wait",
        "uv run newsradar db repair",
    ):
        assert command in readme
    assert "MiniMax 适配器尚未接入 RawItem v1.1" in readme
    assert "GDELT 默认不进入常规抓取" in readme
