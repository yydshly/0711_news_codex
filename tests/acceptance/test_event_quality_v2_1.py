from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from newsradar.events.clustering import evaluate_pair_rules
from newsradar.events.schema import ClusterItem, PairDecisionKind

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "events" / "pair_labels_v2_1.yaml"
NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


def _pair(index: int, sample: dict[str, object]) -> tuple[ClusterItem, ClusterItem]:
    case = str(sample["case"])
    common = {
        "published_at": NOW + timedelta(minutes=index),
        "publisher_name": "fixture",
    }
    left = ClusterItem(
        raw_item_id=index * 2,
        title="OpenAI releases Atlas model",
        canonical_url=f"https://left.test/{index}",
        entities=("organization:openai", "model:atlas"),
        **common,
    )
    right = ClusterItem(
        raw_item_id=index * 2 + 1,
        title="OpenAI releases Atlas model",
        canonical_url=f"https://right.test/{index}",
        entities=("organization:openai", "model:atlas"),
        **common,
    )
    if case == "same_url":
        right = right.model_copy(update={"canonical_url": left.canonical_url})
    elif case == "same_repository":
        left = left.model_copy(update={"repository_id": f"repo-{index}"})
        right = right.model_copy(update={"repository_id": f"repo-{index}"})
    elif case == "same_paper":
        left = left.model_copy(update={"paper_id": f"paper-{index}"})
        right = right.model_copy(update={"paper_id": f"paper-{index}"})
    elif case == "shared_object_action":
        pass
    elif case == "same_root":
        root = f"https://origin.test/{index}"
        left = left.model_copy(update={"original_url": root})
        right = right.model_copy(update={"original_url": root})
    elif case == "conflicting_actions":
        left = left.model_copy(update={"entities": ("organization:openai",)})
        right = right.model_copy(
            update={
                "title": "Anthropic raises funding",
                "entities": ("organization:anthropic",),
            }
        )
    elif case == "shared_organization_only":
        left = left.model_copy(update={"entities": ("organization:openai",)})
        right = right.model_copy(update={"entities": ("organization:openai",)})
    elif case == "same_object_different_action":
        right = right.model_copy(update={"title": "OpenAI raises funding for Atlas"})
    elif case == "unrelated":
        right = right.model_copy(
            update={
                "title": "NVIDIA announces Rubin chips",
                "entities": ("organization:nvidia", "product:rubin"),
            }
        )
    elif case == "same_title_different_identity":
        left = left.model_copy(update={"entities": ("organization:openai",)})
        right = right.model_copy(update={"entities": ("organization:anthropic",)})
    else:
        raise AssertionError(f"unknown fixture case: {case}")
    return left, right


def test_pair_label_regression_has_safe_recall_and_zero_false_merges() -> None:
    document = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    labels = document["labels"]
    assert len(labels) >= 100
    assert sum(label["expected"] == "merge" for label in labels) >= 50
    assert sum(label["expected"] == "separate" for label in labels) >= 50
    assert all(label["id"] and label["reason_zh"] for label in labels)

    positive_total = positive_merged = negative_merged = 0
    for index, label in enumerate(labels, start=1):
        decision = evaluate_pair_rules(*_pair(index, label))
        merged = decision.kind == PairDecisionKind.DIRECT_MERGE
        if label["expected"] == "merge":
            positive_total += 1
            positive_merged += int(merged)
        else:
            negative_merged += int(merged)

    assert positive_merged / positive_total >= 0.85
    assert negative_merged == 0
