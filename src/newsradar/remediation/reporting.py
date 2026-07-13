from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit, urlunsplit

from .schema import RemediationManifest


def render_remediation_report(manifest: RemediationManifest) -> str:
    """Render a public, Chinese report without query, fragment, or credential data."""
    counts = Counter(entry.category.value for entry in manifest.entries)
    lines = [
        "# 来源失败修复报告",
        "",
        f"基线时间：{manifest.baseline_at.isoformat()}",
        f"固定失败 Target 数：{len(manifest.entries)}",
        "",
        "## 分类汇总",
        "",
        "| 分类 | 数量 |",
        "| --- | ---: |",
    ]
    for category, count in sorted(counts.items()):
        lines.append(f"| `{category}` | {count} |")
    lines.extend(
        [
            "",
            "## 固定清单",
            "",
            "| 来源 | 原探测 | 分类 | 中文原因 | 原访问地址 | 建议动作 |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    for entry in manifest.entries:
        lines.append(
            f"| {entry.source_name} (`{entry.source_id}`) | {entry.original_probe_id} "
            f"| `{entry.category.value}` | {entry.reason_zh} | {_public_url(entry.access_url)} "
            f"| {entry.next_action_zh} |"
        )
    return "\n".join(lines) + "\n"


def _public_url(value: str | None) -> str:
    if not value:
        return "—"
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
