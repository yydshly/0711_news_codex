from newsradar.events.coverage import summarize_event_version_payloads


def test_evidence_coverage_counts_exact_event_versions() -> None:
    payloads = (
        {
            "status": "confirmed",
            "evidence_summary": {"official_roots": 1, "professional_roots": 0},
        },
        {
            "status": "emerging",
            "evidence_summary": {"official_roots": 0, "professional_roots": 1},
        },
        {
            "status": "confirmed",
            "evidence_summary": {"official_roots": 0, "professional_roots": 2},
        },
    )

    metrics = summarize_event_version_payloads(payloads)

    assert metrics.events_with_official_root == 1
    assert metrics.events_with_one_professional_root == 1
    assert metrics.events_with_two_professional_roots == 1
    assert metrics.confirmed_event_count == 2


def test_evidence_coverage_treats_malformed_and_disguised_counts_as_zero() -> None:
    payloads = (
        {},
        {"status": "confirmed", "evidence_summary": None},
        {
            "status": "emerging",
            "evidence_summary": {
                "official_roots": True,
                "professional_roots": -1,
            },
        },
        {"status": "confirmed", "evidence_summary": "private raw content"},
    )

    metrics = summarize_event_version_payloads(payloads)

    assert metrics.events_with_official_root == 0
    assert metrics.events_with_one_professional_root == 0
    assert metrics.events_with_two_professional_roots == 0
    assert metrics.confirmed_event_count == 2
