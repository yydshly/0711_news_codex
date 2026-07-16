# Cross-Source Safe Event Merge v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely organize already-ingested cross-source RawItems into auditable Events, retire exact old/new algorithm identity duplicates, and require human confirmation for every non-deterministic merge while preserving all source evidence and archived daily-report snapshots.

**Architecture:** Keep RawItem duplicate detection separate from Event merge decisions. Add a versioned `event_merge_candidates` ledger, a deterministic candidate scanner, and a Worker-only apply path that revalidates immutable event versions and fingerprints before taking ordered leases. Reuse EventVersion, EventPublisher, Operation, Worker, query, and template patterns; MiniMax may explain a candidate but never authorize it.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, PostgreSQL/SQLite, FastAPI, Jinja2, Pydantic v2, pytest, Ruff.

## Global Constraints

- Work only in `D:\codex_project_work\news_codex\.worktrees\cross-source-safe-merge-v1` on branch `codex/cross-source-safe-merge-v1`.
- Do not read `.env`, expose credentials, or store complete model prompts, raw exceptions, database URLs, authorization data, cookies, or sensitive URL query parameters.
- Do not modify, stage, commit, delete, or overwrite the user's uncommitted files under the main worktree `reports/`.
- Do not add sources, probe sources, fetch new content, delete RawItems, or rewrite immutable EventVersion or archived DailyReport snapshots.
- Web requests only enqueue Operations; Worker handlers own event mutations. Network/model calls must not hold database transactions or event leases.
- Automatic actions require either exact old/current identity duplication or a strong immutable identity. Title similarity, company overlap, time proximity, Google News intermediary URLs, and model confidence are never sufficient alone.
- MiniMax cannot decide legality, source enablement, merge approval, or bypass a local safety check. The rules pipeline must finish when MiniMax is unavailable.
- One candidate failure must not block the rest of a scan/apply batch. All operations retain deadlines, cancellation, heartbeat, bounded retry, recovery, structured logs, and Chinese diagnostics.
- Existing bare Event-ID merge requests must be rejected; every content merge must reference a live `EventMergeCandidateRecord`.
- Preserve the positive-pair recall floor of 85% and zero false merges on the labeled regression set.
- Before completion run targeted tests, full pytest, Ruff, migration upgrade/downgrade, real PostgreSQL validation, real browser acceptance, and verify the existing service on port 8766 remains healthy.
- Do not merge or push without explicit user confirmation; never force-push.

---

## Milestone 1: Correct the event-entity input boundary

### Task 1: Remove source and publisher contamination from entity extraction

**Files:**
- Modify: `src/newsradar/events/entities.py`
- Modify: `src/newsradar/events/versions.py`
- Modify: `tests/events/test_entities.py`
- Modify: `tests/events/test_pipeline.py`

**Interfaces:**
- Consumes: `RawItemText(title, summary, content, item_kind, publisher_name, source_topics)`.
- Produces: `ENTITY_RULE_VERSION = "entities-v3"`; `extract_entities(item)` reads only `title`, `summary`, and bounded `content` for event-subject entities.
- Preserves: publisher/source topics remain available to relevance and evidence attribution; historical `entities-v2` processing and EventVersion snapshots are not rewritten.

- [ ] **Step 1: Replace the old pure-input-field test with failing contamination tests**

```python
@pytest.mark.parametrize(
    "item",
    [
        RawItemText(item_kind="OpenAI"),
        RawItemText(publisher_name="OpenAI"),
        RawItemText(source_topics=("OpenAI",)),
    ],
)
def test_event_entities_ignore_channel_and_source_metadata(item: RawItemText) -> None:
    assert extract_entities(item) == ()


@pytest.mark.parametrize(
    "item",
    [
        RawItemText(title="Google launches Gemini 3"),
        RawItemText(summary="Google launched Gemini 3"),
        RawItemText(content="Google launched Gemini 3"),
    ],
)
def test_event_entities_still_read_news_claim_text(item: RawItemText) -> None:
    assert "organization:google" in {
        entity.canonical_key for entity in extract_entities(item)
    }


def test_google_news_metadata_does_not_make_google_the_event_subject() -> None:
    item = RawItemText(
        title="Thinking Machines releases first model",
        publisher_name="Reuters",
        source_topics=("google", "artificial_intelligence"),
    )
    assert "organization:google" not in {
        entity.canonical_key for entity in extract_entities(item)
    }
```

Update version assertions to expect `entities-v3` in `tests/events/test_entities.py` and `tests/events/test_pipeline.py`.

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/events/test_entities.py tests/events/test_pipeline.py::test_pipeline_exposes_current_rule_versions
```

Expected: failures show publisher/source metadata still produces organization entities and the current algorithm version is `entities-v2`.

- [ ] **Step 3: Narrow the extractor input and bump the immutable version**

Change `src/newsradar/events/entities.py` to:

```python
ENTITY_RULE_VERSION = "entities-v3"


def _item_text_parts(item: RawItemText) -> tuple[str, ...]:
    return tuple(filter(None, (item.title, item.summary, item.content)))
```

Change `src/newsradar/events/versions.py` to:

```python
EVENT_ALGORITHM_VERSIONS = MappingProxyType(
    {
        "relevance": "relevance-v2",
        "newsworthiness": "newsworthiness-v2",
        "entities": "entities-v3",
        "cluster": "cluster-v3",
        "score": "score-v2",
    }
)
```

Do not remove `publisher_name` or `source_topics` from `RawItemText`; other stages still consume them.

- [ ] **Step 4: Run entity, pipeline, snapshot, wave, and web-version tests**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/events/test_entities.py tests/events/test_pipeline.py tests/events/test_operation_snapshots.py tests/waves/test_runtime.py tests/web/test_event_queries.py tests/web/test_capability_queries.py
```

Expected: all selected tests pass; fixtures that intentionally freeze old algorithm snapshots continue to be treated as historical rather than silently accepted as current.

- [ ] **Step 5: Commit the entity boundary**

```powershell
git add src/newsradar/events/entities.py src/newsradar/events/versions.py tests/events/test_entities.py tests/events/test_pipeline.py
git commit -m "fix: isolate event entities from source metadata"
```

---

## Milestone 2: Add an immutable candidate ledger

### Task 2: Define merge-candidate schema, ORM, migration, and repository

**Files:**
- Create: `migrations/versions/20260716_0024_event_merge_candidates.py`
- Create: `src/newsradar/event_merges/__init__.py`
- Create: `src/newsradar/event_merges/schema.py`
- Create: `src/newsradar/event_merges/repository.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `tests/test_migrations.py`
- Create: `tests/event_merges/__init__.py`
- Create: `tests/event_merges/test_repository.py`
- Create: `tests/event_merges/test_schema.py`

**Interfaces:**
- Produces enums `MergeCandidateType`, `MergeCandidateStatus`, and immutable Pydantic values `EventMergeFacts`, `MergeCandidateDraft`, `MergeCandidateDetail`.
- Produces ORM `EventMergeCandidateRecord` and repository methods:
  - `upsert_candidate(draft: MergeCandidateDraft, generated_operation_id: int) -> EventMergeCandidateRecord`
  - `get(candidate_id: int, *, for_update: bool = False) -> EventMergeCandidateRecord | None`
  - `mark_reviewed(candidate_id: int, status: MergeCandidateStatus, operation_id: int) -> EventMergeCandidateRecord`
  - `mark_expired(candidate_id: int, reason_code: str) -> EventMergeCandidateRecord`
  - `mark_applied(candidate_id: int, operation_id: int, result: dict[str, object]) -> EventMergeCandidateRecord`
- Candidate pairs are always normalized so `left_event_id < right_event_id`.

- [ ] **Step 1: Write failing schema and repository tests**

Create tests with these core assertions:

```python
def test_merge_candidate_draft_normalizes_event_order() -> None:
    draft = MergeCandidateDraft(
        left=event_facts(event_id=9, version_number=2),
        right=event_facts(event_id=3, version_number=4),
        candidate_type=MergeCandidateType.MANUAL_REVIEW,
        input_fingerprint="a" * 64,
        reason_codes=("same_object", "same_action"),
        zh_reason="对象和动作相同，但没有强身份，必须人工确认。",
        zh_next_action="核对两个事件的原始报道后确认或保持分开。",
    )
    assert (draft.left.event_id, draft.right.event_id) == (3, 9)


def test_repository_upsert_is_idempotent_for_same_versioned_input(session) -> None:
    first = EventMergeCandidateRepository(session).upsert_candidate(draft(), 10)
    second = EventMergeCandidateRepository(session).upsert_candidate(draft(), 10)
    session.flush()
    assert first.id == second.id


def test_repository_rejects_illegal_status_transition(session) -> None:
    record = EventMergeCandidateRepository(session).upsert_candidate(draft(), 10)
    session.flush()
    with pytest.raises(ValueError, match="event_merge_invalid_transition"):
        EventMergeCandidateRepository(session).mark_applied(record.id, 11, {})
```

Use factories that create the referenced Events, EventVersions, and Operation rows so foreign keys are real.

- [ ] **Step 2: Run tests and verify missing-module/model failures**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/event_merges/test_schema.py tests/event_merges/test_repository.py
```

Expected: collection fails because `newsradar.event_merges` and `EventMergeCandidateRecord` do not yet exist.

- [ ] **Step 3: Add the schema values**

Implement `src/newsradar/event_merges/schema.py` with these stable interfaces:

```python
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MergeCandidateType(StrEnum):
    LEGACY_IDENTITY = "legacy_identity"
    DETERMINISTIC_MERGE = "deterministic_merge"
    MANUAL_REVIEW = "manual_review"


class MergeCandidateStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    APPLIED = "applied"
    EXPIRED = "expired"
    FAILED = "failed"


class EventMergeFacts(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: int = Field(gt=0)
    version_number: int = Field(gt=0)
    visibility: str
    canonical_key: str = Field(min_length=1, max_length=255)
    algorithm_versions: tuple[str, ...] = ()
    raw_item_ids: tuple[int, ...]
    source_ids: tuple[str, ...]
    publishers: tuple[str, ...]
    published_at: tuple[datetime, ...]
    safe_url_identities: tuple[str, ...]
    strong_identities: tuple[str, ...]
    object_entities: tuple[str, ...]
    actions: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    key_numbers: tuple[str, ...] = ()


class MergeCandidateDraft(BaseModel):
    model_config = ConfigDict(frozen=True)
    left: EventMergeFacts
    right: EventMergeFacts
    candidate_type: MergeCandidateType
    algorithm_version: str = "event-merge-v1"
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_codes: tuple[str, ...]
    zh_reason: str = Field(min_length=1, max_length=1000)
    zh_next_action: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def normalize_pair(self) -> "MergeCandidateDraft":
        if self.left.event_id == self.right.event_id:
            raise ValueError("event_merge_pair_requires_distinct_events")
        if self.left.event_id > self.right.event_id:
            return self.model_copy(update={"left": self.right, "right": self.left})
        return self
```

Export the public values from `src/newsradar/event_merges/__init__.py`.

- [ ] **Step 4: Add ORM and migration 0024**

Add `EventMergeCandidateRecord` to `src/newsradar/db/models.py` with columns matching the spec and these database constraints:

```python
class EventMergeCandidateRecord(Base):
    __tablename__ = "event_merge_candidates"
    __table_args__ = (
        CheckConstraint("left_event_id < right_event_id", name="ck_event_merge_pair_order"),
        CheckConstraint("left_version_number > 0", name="ck_event_merge_left_version"),
        CheckConstraint("right_version_number > 0", name="ck_event_merge_right_version"),
        CheckConstraint(
            "candidate_type IN ('legacy_identity','deterministic_merge','manual_review')",
            name="ck_event_merge_candidate_type",
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','dismissed','applied','expired','failed')",
            name="ck_event_merge_candidate_status",
        ),
        UniqueConstraint(
            "left_event_id", "left_version_number", "right_event_id",
            "right_version_number", "algorithm_version", "input_fingerprint",
            name="uq_event_merge_candidate_input",
        ),
        Index("ix_event_merge_candidates_status_type", "status", "candidate_type", "id"),
    )
```

Columns must include both event/version foreign references, `facts_snapshot`, reasons/copy, generated/reviewed/applied Operation IDs, `reviewed_at`, `result_summary`, and timestamps. Use `ondelete="RESTRICT"` for Event and Operation references. Migration `20260716_0024` has `down_revision = "20260716_0023"`, creates the table/indexes, and drops only these new objects on downgrade.

- [ ] **Step 5: Implement repository transitions with row locking**

Implement repository transitions with SQLAlchemy `select(record).with_for_update()`; allow only:

```python
_ALLOWED_TRANSITIONS = {
    "pending": {"confirmed", "dismissed", "applied", "expired", "failed"},
    "confirmed": {"applied", "expired", "failed"},
    "dismissed": set(),
    "applied": set(),
    "expired": set(),
    "failed": set(),
}
```

`upsert_candidate()` must use dialect-aware `ON CONFLICT DO NOTHING`, then select the unique row. Store `facts_snapshot` from `draft.left/right.model_dump(mode="json")`; never store raw payloads or unsanitized URLs.

- [ ] **Step 6: Test SQLite migration, ORM parity, downgrade, and transitions**

Add migration assertions for table, columns, checks, unique constraint, indexes, upgrade `0023 → 0024`, downgrade `0024 → 0023`, and a second upgrade. Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/event_merges tests/test_migrations.py
```

Expected: all tests pass and downgrade preserves `events`, `event_versions`, `event_items`, and `daily_reports`.

- [ ] **Step 7: Commit the candidate ledger**

```powershell
git add migrations/versions/20260716_0024_event_merge_candidates.py src/newsradar/db/models.py src/newsradar/event_merges tests/event_merges tests/test_migrations.py
git commit -m "feat: add event merge candidate ledger"
```

---

## Milestone 3: Generate safe candidates without mutating events

### Task 3: Build bounded facts, classification rules, scan service, and scan Operation

**Files:**
- Create: `src/newsradar/event_merges/facts.py`
- Create: `src/newsradar/event_merges/rules.py`
- Create: `src/newsradar/event_merges/service.py`
- Create: `src/newsradar/event_merges/runtime.py`
- Modify: `src/newsradar/event_merges/__init__.py`
- Modify: `src/newsradar/operations/schema.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/cli.py`
- Create: `tests/event_merges/test_facts.py`
- Create: `tests/event_merges/test_rules.py`
- Create: `tests/event_merges/test_service.py`
- Create: `tests/event_merges/test_runtime.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces `EVENT_MERGE_RULE_VERSION = "event-merge-v1"`.
- Produces `load_event_facts(session, event_id) -> EventMergeFacts` and `merge_input_fingerprint(left, right) -> str`.
- Produces `classify_pair(left, right, latest_snapshot_event_ids) -> MergeCandidateDraft | None`.
- Produces `EventMergeService.scan(operation_id: int, checkpoint: Callable[[str], None]) -> MergeScanResult`.
- Produces `OperationType.EVENT_MERGE_SCAN` and `OperationCommandService.enqueue_event_merge_scan(trigger: str) -> int`.
- Scan writes only candidate/audit rows; it never changes Event, EventVersion, EventItem, RawItem, DailyReport, or source state.

- [ ] **Step 1: Write failing facts and URL-safety tests**

```python
def test_event_facts_exclude_google_news_intermediary_from_strong_identity(session) -> None:
    event_id = seed_event(
        session,
        canonical_url="https://news.google.com/rss/articles/abc?token=secret",
        original_url="https://news.google.com/rss/articles/abc?token=secret",
    )
    facts = load_event_facts(session, event_id)
    assert facts.safe_url_identities == ("news.google.com/rss/articles/abc",)
    assert facts.strong_identities == ()
    assert "secret" not in repr(facts)


def test_event_facts_keep_real_original_media_identity(session) -> None:
    event_id = seed_event(
        session,
        canonical_url="https://example.com/story?id=secret",
        original_url="https://www.reuters.com/technology/story-123?utm_source=x",
    )
    facts = load_event_facts(session, event_id)
    assert "www.reuters.com/technology/story-123" in facts.strong_identities
```

- [ ] **Step 2: Write failing classification tests for all three channels**

```python
def test_exact_old_and_current_membership_is_legacy_identity_candidate() -> None:
    left = facts(event_id=1, algorithms=("cluster-v2",), raw_item_ids=(10, 11))
    right = facts(event_id=2, algorithms=("cluster-v3",), raw_item_ids=(10, 11))
    draft = classify_pair(left, right, latest_snapshot_event_ids=frozenset({2}))
    assert draft is not None
    assert draft.candidate_type is MergeCandidateType.LEGACY_IDENTITY


def test_subset_membership_is_never_automatic_legacy_retirement() -> None:
    left = facts(event_id=1, algorithms=("cluster-v2",), raw_item_ids=(10,))
    right = facts(event_id=2, algorithms=("cluster-v3",), raw_item_ids=(10, 11))
    draft = classify_pair(left, right, latest_snapshot_event_ids=frozenset({2}))
    assert draft is None or draft.candidate_type is MergeCandidateType.MANUAL_REVIEW


def test_same_real_original_url_is_deterministic_merge() -> None:
    left = facts(event_id=1, strong_identities=("www.reuters.com/story/1",))
    right = facts(event_id=2, strong_identities=("www.reuters.com/story/1",))
    assert classify_pair(left, right, frozenset()).candidate_type is (
        MergeCandidateType.DETERMINISTIC_MERGE
    )


def test_same_object_action_and_time_is_manual_not_automatic() -> None:
    left = facts(event_id=1, objects=("model:orion",), actions=("launch",))
    right = facts(event_id=2, objects=("model:orion",), actions=("launch",))
    draft = classify_pair(left, right, frozenset())
    assert draft.candidate_type is MergeCandidateType.MANUAL_REVIEW


@pytest.mark.parametrize("conflict", ["object", "action", "key_number"])
def test_conflicting_facts_do_not_create_merge_candidate(conflict: str) -> None:
    left, right = conflicting_facts(conflict)
    assert classify_pair(left, right, frozenset()) is None
```

Add explicit tests that same organization, title similarity, time proximity, or model confidence alone returns `None`.

- [ ] **Step 3: Implement bounded fact loading and fingerprinting**

`load_event_facts()` must read the Event row, its exact current EventVersion, active EventItems, RawItems, SourceDefinitions, EventCandidate algorithms, and version payload evidence. Build URLs with:

```python
_INTERMEDIARY_HOSTS = frozenset({"news.google.com", "news.yahoo.com"})


def safe_url_identity(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.hostname.casefold()}{port}{parsed.path or '/'}"[:1000]


def strong_url_identity(value: str | None) -> str | None:
    identity = safe_url_identity(value)
    if identity is None or identity.split("/", 1)[0] in _INTERMEDIARY_HOSTS:
        return None
    return identity
```

Extract current entities from news text with `entities-v3`, actions with the existing deterministic clustering action vocabulary, key numbers with a bounded local regex, and stable repository/paper IDs where available. Sort and deduplicate every tuple. Hash only `model_dump(mode="json")` of both normalized facts plus `EVENT_MERGE_RULE_VERSION`.

- [ ] **Step 4: Implement rule classification and bounded pair generation**

Apply rules in this order:

```python
def classify_pair(left, right, latest_snapshot_event_ids):
    if _exact_cross_algorithm_identity(left, right, latest_snapshot_event_ids):
        return _draft(
            MergeCandidateType.LEGACY_IDENTITY,
            left,
            right,
            reason_codes=("exact_cross_algorithm_membership",),
            zh_reason="旧算法与当前算法事件包含完全相同的原始条目。",
            zh_next_action="保留当前算法事件，并把旧身份转入历史目录。",
        )
    if _conflicting_facts(left, right):
        return None
    if set(left.strong_identities) & set(right.strong_identities):
        return _draft(
            MergeCandidateType.DETERMINISTIC_MERGE,
            left,
            right,
            reason_codes=("same_strong_identity",),
            zh_reason="两个事件共享同一个可验证的原始内容标识。",
            zh_next_action="复核原始媒体后应用确定性合并。",
        )
    if _manual_review_boundary(left, right):
        return _draft(
            MergeCandidateType.MANUAL_REVIEW,
            left,
            right,
            reason_codes=("same_object_action_without_strong_identity",),
            zh_reason="对象、动作和时间接近，但缺少可自动证明同一事件的强标识。",
            zh_next_action="人工核对两侧原始报道后确认合并或保持分开。",
        )
    return None
```

`_draft()` has the exact signature below and computes the fingerprint internally:

```python
def _draft(
    candidate_type: MergeCandidateType,
    left: EventMergeFacts,
    right: EventMergeFacts,
    *,
    reason_codes: tuple[str, ...],
    zh_reason: str,
    zh_next_action: str,
) -> MergeCandidateDraft:
    return MergeCandidateDraft(
        left=left,
        right=right,
        candidate_type=candidate_type,
        algorithm_version=EVENT_MERGE_RULE_VERSION,
        input_fingerprint=merge_input_fingerprint(left, right),
        reason_codes=reason_codes,
        zh_reason=zh_reason,
        zh_next_action=zh_next_action,
    )
```

Candidate generation must not compute a global unrestricted cross product. Use indexes for active RawItem membership, strong identity, concrete object entity, and a 48-hour time bucket; deduplicate normalized Event-ID pairs and cap one scan to the finite current-event set loaded at Operation start.

- [ ] **Step 5: Implement the scan service and per-candidate isolation**

`EventMergeService.scan()` must:

1. Freeze current Event IDs and latest complete current-algorithm Operation snapshot IDs.
2. Load each event facts value independently; record an operation-safe diagnostic and continue if one event is malformed.
3. Generate bounded pairs and classify each independently.
4. Upsert candidates in short transactions; a single `IntegrityError` or malformed pair rolls back only that candidate.
5. Expire still-pending candidates from the same algorithm when either referenced version is no longer current.
6. Return counts by candidate type, status, failure reason, current events, single-member events, cross-source events, and overlapping current membership.

- [ ] **Step 6: Add scan Operation command and Worker routing**

Add:

```python
class OperationType(StrEnum):
    # existing values remain unchanged
    EVENT_MERGE_SCAN = "event_merge_scan"
```

`enqueue_event_merge_scan()` scope contains actor, `algorithm_version="event-merge-v1"`, current `EVENT_ALGORITHM_VERSIONS`, `window_end`, idempotency key, and deadline. Register `EventMergeOperationHandler.production(create_session)` for `event_merge_scan` in `cli.run_worker`; the handler validates the scope and maps scan results into `OperationResult` without network calls.

- [ ] **Step 7: Run focused scanner, command, Worker, and regression tests**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/event_merges tests/test_cli.py tests/operations tests/acceptance/test_event_quality_v2_1.py
```

Expected: all pass; labeled pair recall remains at least 85%, negative merges remain zero, and scanner tests assert Event/EventVersion/EventItem/RawItem counts and values do not change.

- [ ] **Step 8: Commit safe candidate generation**

```powershell
git add src/newsradar/event_merges src/newsradar/operations/schema.py src/newsradar/operations/commands.py src/newsradar/cli.py tests/event_merges tests/test_cli.py
git commit -m "feat: generate safe event merge candidates"
```

---

## Milestone 4: Apply decisions through a revalidated Worker path

### Task 4: Enforce candidate-only merge execution and immutable event retirement

**Files:**
- Modify: `src/newsradar/event_merges/service.py`
- Modify: `src/newsradar/event_merges/runtime.py`
- Modify: `src/newsradar/events/repository.py`
- Modify: `src/newsradar/events/runtime.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/cli.py`
- Modify: `tests/event_merges/test_service.py`
- Modify: `tests/event_merges/test_runtime.py`
- Modify: `tests/events/test_repository.py`
- Modify: `tests/events/test_runtime.py`
- Modify: `tests/operations/test_commands.py`

**Interfaces:**
- Produces `OperationCommandService.enqueue_event_merge_decision(candidate_id: int, decision: Literal["apply", "confirm", "dismiss", "recheck"], trigger: str) -> int`.
- Reuses `OperationType.EVENT_MERGE` for candidate application, but its scope must contain `candidate_id`; bare `event_id/target_event_id` merge scopes are invalid.
- Produces `EventMergeService.apply(candidate_id, operation_id, checkpoint) -> MergeApplyResult` and `review(candidate_id, decision, operation_id) -> EventMergeCandidateRecord`.
- Extends `EventRepository.publish_complete_event` with keyword `visibility: EventVisibility = EventVisibility.CURRENT` so a complete immutable version can be published directly as `legacy` without a transient current state.
- Produces `MergeApplyResult(status, candidate_id, survivor_event_id, survivor_version_number, legacy_event_id, legacy_version_number, error_code)` and `candidate_still_safe(candidate_type, left, right) -> bool`.

- [ ] **Step 1: Write failing candidate-only command and scope tests**

```python
def test_merge_command_requires_candidate_id(session) -> None:
    with pytest.raises(ValueError, match="event_merge_candidate_required"):
        OperationCommandService(session).enqueue_event_action(
            "merge", 1, {"target_event_id": 2}, "web"
        )


def test_confirm_command_freezes_candidate_id_and_deadline(session) -> None:
    candidate = seed_pending_manual_candidate(session)
    operation_id = OperationCommandService(session).enqueue_event_merge_decision(
        candidate.id, "confirm", "web"
    )
    operation = session.get(OperationRunRecord, operation_id)
    assert operation.requested_scope["candidate_id"] == candidate.id
    assert operation.requested_scope["decision"] == "confirm"
    assert "target_event_id" not in operation.requested_scope
```

- [ ] **Step 2: Write failing stale-input, ordered-lease, and rollback tests**

```python
def test_apply_expires_candidate_when_event_version_changes(session_factory) -> None:
    candidate = seed_confirmed_candidate(session_factory)
    publish_another_version(session_factory, candidate.left_event_id)
    result = run_apply(session_factory, candidate.id)
    assert result.error_code == "event_merge_version_changed"
    assert candidate_status(session_factory, candidate.id) == "expired"
    assert current_memberships(session_factory) == memberships_before_apply()


def test_apply_claims_events_in_sorted_order_and_releases_reverse(monkeypatch) -> None:
    observed = []
    observe_claims_and_releases(monkeypatch, observed)
    result = run_confirmed_apply(left_event_id=9, right_event_id=3)
    assert result.status is OperationStatus.SUCCEEDED
    assert observed == [("claim", 3), ("claim", 9), ("release", 9), ("release", 3)]


def test_apply_failure_rolls_back_both_versions_and_releases_leases(monkeypatch) -> None:
    fail_before_visibility_switch(monkeypatch)
    result = run_confirmed_apply()
    assert result.status is OperationStatus.FAILED
    assert event_versions_after() == event_versions_before()
    assert all_leases_are_clear()
```

Add tests proving `apply` accepts only pending `legacy_identity` and
`deterministic_merge` candidates, while `confirm` accepts only pending
`manual_review` candidates. Also test idempotent retry, already-applied candidate,
dismissed candidate, timeout/cancel, quality input unavailable, and one-candidate
failure isolation.

- [ ] **Step 3: Add legacy publication as an explicit repository parameter**

Add the `visibility` keyword to the existing repository signature and replace the
hard-coded current assignment. Keep the rest of the existing method body unchanged:

```python
model_usages: tuple[ModelUsage, ...] = (),
visibility: EventVisibility = EventVisibility.CURRENT,
```

```python
record.visibility = visibility.value
```

All existing callers use the default. Add repository tests proving a legacy publication writes its full EventVersion, EventItems, score, and current pointer atomically while the Event row is never exposed as current after the transaction.

- [ ] **Step 4: Implement deterministic survivor selection and full recomputation**

Use this stable survivor order:

1. For `legacy_identity`, retain the event referenced by the latest current-algorithm snapshot.
2. Otherwise prefer the event whose candidate algorithm includes current `cluster-v3`.
3. Then prefer the lower positive Event ID.

Do not use form order. Rebuild union `ClusterItem` facts from persisted RawItems, then call existing `build_candidate_score_input()` and `EventPublisher.assemble_snapshot()` to recalculate evidence, publication status, score, tier, rank, and rule fallback. Preserve the survivor's safe existing enrichment only when it remains structurally valid; otherwise use deterministic rule enrichment. No model call is required for merge legality or completion.

- [ ] **Step 5: Implement candidate revalidation and atomic application**

The Worker flow must use the following concrete control sequence. Implement
`_publish_revalidated_pair()` in `EventMergeService` with the survivor selection and
full recomputation contract from Step 4:

```python
record = repository.get(candidate_id, for_update=True)
if record is None:
    raise LookupError("event_merge_candidate_not_found")
if record.status not in {"confirmed", "pending"}:
    raise ValueError("event_merge_candidate_not_applicable")
if record.status == "pending" and record.candidate_type == "manual_review":
    raise ValueError("event_merge_manual_confirmation_required")
if record.status == "confirmed" and record.candidate_type != "manual_review":
    raise ValueError("event_merge_confirmation_type_mismatch")
current_left = load_event_facts(session, record.left_event_id)
current_right = load_event_facts(session, record.right_event_id)
if (
    current_left.version_number != record.left_version_number
    or current_right.version_number != record.right_version_number
):
    repository.mark_expired(candidate_id, "event_merge_version_changed")
    session.commit()
    return MergeApplyResult.expired(candidate_id, "event_merge_version_changed")
if merge_input_fingerprint(current_left, current_right) != record.input_fingerprint:
    repository.mark_expired(candidate_id, "event_merge_membership_changed")
    session.commit()
    return MergeApplyResult.expired(candidate_id, "event_merge_membership_changed")
if not candidate_still_safe(record.candidate_type, current_left, current_right):
    repository.mark_expired(candidate_id, "event_merge_identity_not_strong")
    session.commit()
    return MergeApplyResult.expired(candidate_id, "event_merge_identity_not_strong")
claimed_ids: list[int] = []
lease_until = datetime.now(UTC) + timedelta(minutes=5)
for event_id in sorted((record.left_event_id, record.right_event_id)):
    if not EventRepository(session).claim_event(event_id, operation_id, lease_until):
        raise EventMergeLeaseUnavailable(event_id)
    claimed_ids.append(event_id)
session.commit()
checkpoint("before_event_merge_mutation")
result = self._publish_revalidated_pair(
    record=record,
    left=current_left,
    right=current_right,
    operation_id=operation_id,
)
repository.mark_applied(candidate_id, operation_id, result.model_dump(mode="json"))
for event_id in reversed(claimed_ids):
    EventRepository(session).release_event(event_id, operation_id)
session.commit()
```

Add the immutable result value to `src/newsradar/event_merges/schema.py`:

```python
class MergeApplyResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    candidate_id: int = Field(gt=0)
    survivor_event_id: int | None = None
    survivor_version_number: int | None = None
    legacy_event_id: int | None = None
    legacy_version_number: int | None = None
    error_code: str | None = None

    @classmethod
    def expired(cls, candidate_id: int, error_code: str) -> "MergeApplyResult":
        return cls(status="expired", candidate_id=candidate_id, error_code=error_code)
```

Calls in the control sequence use
`MergeApplyResult.expired(candidate_id, "event_merge_version_changed")` and the
corresponding membership/identity error code. Define
`EventMergeLeaseUnavailable(RuntimeError)` with stable code
`event_merge_lease_unavailable`; the handler maps it to a retryable failed
`OperationResult` and always releases `claimed_ids` in a recovery transaction.

If revalidation fails before leases, mark only the candidate expired. If any publication fails after leases, roll back all event/candidate changes, release both leases in a recovery transaction, and return a stable retry/error result.

- [ ] **Step 6: Remove unsafe EventOperationHandler merge behavior**

Remove `OperationType.EVENT_MERGE` from `_EVENT_TYPES` and delete the branch in `_validate_event_action()` / `_apply_event_action()` that merges by `target_event_id`. Route `event_merge` to `EventMergeOperationHandler` in `cli.run_worker`. Keep recluster, enrich, split, and exclude behavior unchanged.

- [ ] **Step 7: Implement apply, confirm, dismiss, and recheck semantics**

- `apply`: only pending `legacy_identity` or `deterministic_merge` candidates may
  proceed directly to authoritative revalidation and application. Scan never calls
  this automatically; it is triggered by an explicit page action or controlled
  apply Operation after candidate inspection.
- `dismiss`: transition pending candidate to dismissed in a short Worker transaction; no event leases.
- `confirm`: only a pending `manual_review` candidate may become confirmed; the same
  Operation then revalidates and applies it.
- `recheck`: expire the old pending candidate and rescan only its two event IDs into a new versioned candidate; never mutate events.

Store `reviewed_operation_id`, `applied_operation_id`, resulting survivor/legacy Event IDs and version numbers, and stable Chinese diagnostic codes.

- [ ] **Step 8: Run repository, runtime, Worker, and daily-report immutability tests**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/event_merges tests/events/test_repository.py tests/events/test_runtime.py tests/operations tests/daily_reports tests/web/test_daily_report_pages.py
```

Expected: all pass; archived report snapshots are byte-equivalent before and after seeded event merges.

- [ ] **Step 9: Commit the safe apply path**

```powershell
git add src/newsradar/event_merges src/newsradar/events/repository.py src/newsradar/events/runtime.py src/newsradar/operations/commands.py src/newsradar/cli.py tests/event_merges tests/events/test_repository.py tests/events/test_runtime.py tests/operations
git commit -m "feat: apply revalidated event merge decisions"
```

---

## Milestone 5: Add the Chinese review and diagnostics workflow

### Task 5: Build merge-candidate pages, routes, and safe actions

**Files:**
- Create: `src/newsradar/web/event_merge_queries.py`
- Create: `src/newsradar/web/templates/event_merge_candidates.html`
- Create: `src/newsradar/web/templates/event_merge_candidate_detail.html`
- Modify: `src/newsradar/web/templates/base.html`
- Modify: `src/newsradar/web/templates/event_detail.html`
- Modify: `src/newsradar/web/app.py`
- Create: `tests/web/test_event_merge_pages.py`
- Modify: `tests/web/test_event_routes.py`

**Interfaces:**
- Produces `EventMergeQueryService.summary() -> EventMergeSummaryView`.
- Produces `list_candidates(status, candidate_type, limit=200) -> tuple[EventMergeCandidateRow, ...]`.
- Produces `get_candidate(candidate_id) -> EventMergeCandidateDetail | None`.
- Adds GET `/event-merge-candidates`, GET `/event-merge-candidates/{id}`, POST `/event-merge-candidates/scan`, and POST `/event-merge-candidates/{id}/{decision}`.
- Existing POST `/events/merge` returns a safe 409/422 diagnostic and cannot enqueue a bare-ID merge.

- [ ] **Step 1: Write failing query tests for exact summary semantics**

```python
def test_summary_separates_current_membership_and_candidate_states(session) -> None:
    seed_current_events_and_candidates(session)
    summary = EventMergeQueryService(session).summary()
    assert summary.current_event_count == 4
    assert summary.single_member_event_count == 2
    assert summary.cross_source_event_count == 1
    assert summary.raw_items_in_multiple_current_events == 1
    assert summary.legacy_identity_pending_count == 1
    assert summary.deterministic_pending_count == 1
    assert summary.manual_pending_count == 1


def test_candidate_detail_uses_snapshot_versions_and_safe_urls(session) -> None:
    candidate = seed_candidate_with_sensitive_query(session)
    detail = EventMergeQueryService(session).get_candidate(candidate.id)
    assert detail.left.version_number == candidate.left_version_number
    assert "token=" not in repr(detail)
    assert detail.zh_reason
    assert detail.zh_next_action
```

- [ ] **Step 2: Write failing route/template security and action tests**

```python
def test_candidate_page_labels_identity_retirement_not_content_merge(client) -> None:
    response = client.get("/event-merge-candidates/1")
    assert response.status_code == 200
    assert "旧算法身份重复" in response.text
    assert "跨来源内容已确认相同" not in response.text


def test_confirm_only_enqueues_candidate_operation(client, monkeypatch) -> None:
    observed = capture_merge_command(monkeypatch)
    response = client.post(
        "/event-merge-candidates/3/confirm",
        data={"action_token": valid_action_token(client)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert observed == [(3, "confirm", "web")]


def test_apply_only_enqueues_automatic_candidate_operation(client, monkeypatch) -> None:
    observed = capture_merge_command(monkeypatch)
    response = client.post(
        "/event-merge-candidates/2/apply",
        data={"action_token": valid_action_token(client)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert observed == [(2, "apply", "web")]


def test_bare_event_id_merge_is_rejected(client) -> None:
    response = client.post(
        "/events/merge",
        data={"event_id": "1", "target_event_id": "2", "action_token": valid_token()},
    )
    assert response.status_code in {409, 422}
    assert "candidate" in response.text.casefold() or "候选" in response.text
```

Also test missing/expired/applied candidate, invalid decision, unsafe origin, reused action token, database unavailable, and raw exception/secret URL redaction.

- [ ] **Step 3: Implement bounded query viewmodels and Chinese projection**

Define frozen dataclasses for summary, list row, event side, member row, and detail. Map stable reason/error codes to Chinese in one dictionary, including:

```python
_REASON_COPY = {
    "exact_cross_algorithm_membership": (
        "旧算法与当前算法事件包含完全相同的原始条目。",
        "保留当前算法事件，并把旧身份转入历史目录。",
    ),
    "same_strong_identity": (
        "两个事件共享同一个可验证的原始内容标识。",
        "复核原始媒体后应用确定性合并。",
    ),
    "same_object_action_without_strong_identity": (
        "对象、动作和时间接近，但缺少可自动证明同一事件的强标识。",
        "人工核对两侧原始报道后确认合并或保持分开。",
    ),
    "event_merge_version_changed": (
        "候选生成后事件版本已经变化。",
        "重新检查并生成新的候选。",
    ),
}
```

Unknown codes use a generic bounded Chinese message and never echo raw database text.

- [ ] **Step 4: Add pages and navigation**

The list page shows all required summary metrics and filter tabs. The detail page shows both Event IDs/versions, titles, sources, publishers, publication times, sanitized URLs, active RawItems, shared objects/actions, time distance, evidence roots, conflicts, Chinese conclusion, and next action. Only valid pending candidates show action forms.

Add “事件合并候选” navigation to `base.html`. Add read-only links from global current Event details to candidate searches; do not add a free-form target Event-ID input.

- [ ] **Step 5: Add safe routes that only enqueue Operations**

All POST routes call `require_safe_action(request)` first. `/scan` calls `enqueue_event_merge_scan("web")`; candidate decisions call `enqueue_event_merge_decision(candidate_id, decision, "web")`. Validate candidate existence/state before enqueue only for user-friendly 404/409 responses; Worker still performs authoritative revalidation.

- [ ] **Step 6: Run page, route, security, and operation-page tests**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/web/test_event_merge_pages.py tests/web/test_event_routes.py tests/web/test_security.py tests/web/test_operation_pages.py
```

Expected: all pass, no secret marker or sensitive query value appears in returned HTML.

- [ ] **Step 7: Commit the Chinese review workflow**

```powershell
git add src/newsradar/web/event_merge_queries.py src/newsradar/web/templates/event_merge_candidates.html src/newsradar/web/templates/event_merge_candidate_detail.html src/newsradar/web/templates/base.html src/newsradar/web/templates/event_detail.html src/newsradar/web/app.py tests/web/test_event_merge_pages.py tests/web/test_event_routes.py
git commit -m "feat: add Chinese event merge review pages"
```

---

## Milestone 6: Close the feature on real data

### Task 6: Add PostgreSQL acceptance coverage and perform controlled real validation

**Files:**
- Create: `tests/acceptance/test_cross_source_safe_merge_v1.py`
- Modify: `tests/test_migrations.py`
- Write ignored evidence only: `.superpowers/sdd/cross-source-safe-merge-v1-acceptance.md`

**Interfaces:**
- Automated acceptance uses existing optional PostgreSQL fixtures and skips cleanly when the test database is not configured.
- Real project validation first scans candidates read-only; event writes occur only after all automatic candidates are manually inspected and shown to satisfy the spec.
- Acceptance evidence contains counts, IDs, stable reason codes, and hashes only; it excludes credentials, `.env`, raw connection strings, sensitive URL queries, and full payloads.

- [ ] **Step 1: Write PostgreSQL concurrency and idempotency acceptance tests**

```python
def test_postgres_concurrent_apply_creates_one_survivor_version(postgres_session_factory):
    candidate = seed_confirmed_candidate(postgres_session_factory)
    results = run_two_workers(candidate.id, postgres_session_factory)
    assert sum(result.status is OperationStatus.SUCCEEDED for result in results) == 1
    assert current_survivor_version_delta(postgres_session_factory) == 1
    assert candidate_status(postgres_session_factory, candidate.id) == "applied"
    assert no_event_leases(postgres_session_factory)


def test_postgres_failed_second_publication_rolls_back_first(postgres_session_factory, monkeypatch):
    candidate = seed_confirmed_candidate(postgres_session_factory)
    before = event_state_hash(postgres_session_factory)
    fail_absorbed_event_publication(monkeypatch)
    run_apply(candidate.id, postgres_session_factory)
    assert event_state_hash(postgres_session_factory) == before
    assert no_event_leases(postgres_session_factory)
```

- [ ] **Step 2: Run all targeted automated tests and static checks**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/event_merges tests/events tests/operations tests/web/test_event_merge_pages.py tests/acceptance/test_event_quality_v2_1.py tests/acceptance/test_cross_source_safe_merge_v1.py tests/test_migrations.py
..\..\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

Expected: all tests pass, Ruff says `All checks passed!`, and `git diff --check` is silent.

- [ ] **Step 3: Verify real migration upgrade/downgrade without data loss**

Before touching the project database, use a temporary UTF-8 PostgreSQL database. Run `0023 → 0024`, inspect constraints/indexes/FKs, downgrade to `0023`, and upgrade again. Assert core counts for RawItem, Event, EventVersion, EventItem, Operation, DailyReport, and DailyReportItem are unchanged across the cycle.

Then migrate the real project database only after a read-only schema/version check confirms it is at `0023`. Record before/after core counts and verify the new table starts empty.

- [ ] **Step 4: Generate real candidates in read-only event mode**

Enqueue one `event_merge_scan` Operation through the normal command/service and run one Worker. Record:

- frozen current Event count;
- single-member and cross-source counts;
- RawItems in multiple current Events;
- counts for legacy identity, deterministic, manual, expired, and per-candidate failures;
- before/after hashes/counts for Event, EventVersion, EventItem, RawItem, DailyReport, and model usage.

Expected: the scan changes only Operation/candidate/audit rows; all Event/RawItem/DailyReport hashes and counts remain unchanged.

- [ ] **Step 5: Manually inspect every automatic candidate and at least 20 manual candidates**

For each automatic candidate verify both exact membership/current-algorithm snapshot proof or a permitted strong identity. If any automatic candidate is ambiguous, stop acceptance and fix the classifier before applying anything. For manual candidates inspect titles, original publishers, safe URLs, timestamps, concrete objects, actions, key numbers, and evidence roots.

Expected: automatic-candidate precision is 100%; ambiguous pairs remain pending.

- [ ] **Step 6: Apply controlled identity retirement and one confirmed content merge**

Apply only inspected candidates through the web/Operation/Worker path. Verify:

- exact v2/v3 duplicates leave one current identity and one legacy identity;
- subset/partial-overlap nightly release cases remain unmodified;
- one genuinely confirmed content merge produces a recomputed survivor version and an empty-member legacy absorbed version;
- RawItem/source/original URL/publication time/evidence attribution remain queryable;
- no RawItem is deleted and no lease remains;
- archived DailyReport snapshot hashes are unchanged.

- [ ] **Step 7: Run real browser acceptance on an isolated port**

Start the feature service on a temporary port such as 8879 without disturbing 8766. Using the in-app browser, verify summary metrics, filters, one candidate of each type, sanitized external links, apply/confirm/dismiss/recheck actions, Operation redirects, expired-candidate diagnostics, and both resulting Event detail pages. Stop only the temporary service afterward.

- [ ] **Step 8: Run final full verification**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q
..\..\.venv\Scripts\python.exe -m ruff check .
git diff --check
git status --short --branch
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8766/' -TimeoutSec 10
```

Expected: full pytest exits 0, Ruff passes, diff check is silent, only intentional tracked changes exist, and port 8766 returns HTTP 200.

- [ ] **Step 9: Request independent review and fix every Critical/Important issue**

Prepare a review package from `main..HEAD`. Reviewer scope must include migration safety, ORM/migration parity, URL redaction, classifier precision, stale-candidate fencing, lock order, rollback, idempotency, candidate-only routing, immutable daily reports, and Chinese diagnostics. Repeat targeted/full verification after any fix.

- [ ] **Step 10: Commit acceptance-only test changes**

```powershell
git add tests/acceptance/test_cross_source_safe_merge_v1.py tests/test_migrations.py
git commit -m "test: validate cross-source event merge closure"
```

Do not add `.superpowers/sdd/cross-source-safe-merge-v1-acceptance.md` if it is ignored, and never add files under the user's protected `reports/` paths.

---

## Plan Self-Review Checklist

- Every design requirement maps to one of Tasks 1–6: entity isolation, ledger, three candidate channels, stale fencing, ordered leases, recomputation, legacy retirement, Chinese workflow, security, PostgreSQL, browser, and daily-report immutability.
- `entities-v3`, `event-merge-v1`, candidate types, statuses, reason codes, Operation names, and method signatures are used consistently across tasks.
- Event merge candidate records are distinct from RawItem duplicate candidates.
- No step authorizes a global unrestricted pair cross product, direct SQL mutation of real events, bare Event-ID merge, model-authorized merge, source fetch/probe, RawItem deletion, or archived-report rewrite.
- No implementation placeholder is left; each code change has an explicit failing test, command, expected failure/pass condition, implementation contract, and commit boundary.
- The feature remains useful without MiniMax and does not require any new external service or dependency.
