from __future__ import annotations

from newsradar.research.audit import audit_source_catalog
from newsradar.research.reporting import render_research_report
from newsradar.sources.schema import SourceDefinition
from tests.research.test_audit import _verified_research
from tests.test_source_schema import valid_source


def test_report_is_chinese_and_lists_research_details() -> None:
    source = SourceDefinition.model_validate(
        valid_source() | {"research": _verified_research("html")}
    )

    rendered = render_research_report(audit_source_catalog((), (source,)))

    assert "# 来源研究审计报告" in rendered
    assert "真实 Target" in rendered
    assert "HTML" in rendered
    assert "收集公开资讯" in rendered
    assert "所需信息" in rendered
    assert "首选" in rendered
