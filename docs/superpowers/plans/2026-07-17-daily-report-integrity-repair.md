# 中文日报完整性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 修复日报中文审核文本的编码问号，阻止损坏内容归档或合成语音，并在现有单页清晰呈现决策简报、情报全览和完整报告与证据。

**Architecture:** 新增纯函数文本完整性模块，作为审核草稿、归档仓储、查询视图和音频 Worker 的共同契约。页面继续使用现有 DailyReportQueryService 和详情模板，只增加完整性警告、页内定位和完整报告区域标题；日报 5 通过既有修订机制恢复，历史归档记录不修改。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Jinja2、pytest、ruff、MiniMax speech-2.8-hd。

## Global Constraints

- 不重新抓取来源、不重新运行事件管线、不修改历史 RawItem、事件或来源状态。
- 已归档日报及音频制品不可修改；恢复只能创建修订版并追加审核版本。
- MiniMax 只将已审核中文脚本转为音频，不能判断合法性、真实性或收录结论。
- 连续 4 个或以上 ASCII 问号视为编码损坏；中文问号和 1 至 3 个 ASCII 问号合法。
- 不读取、输出或提交 .env；不触碰 reports/；不合并、不推送。
- 所有生产代码先有失败测试；最终运行完整 pytest、ruff check . 和本地网页验收。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| src/newsradar/daily_reports/text_integrity.py | 检测问号损坏并暴露稳定错误码。 |
| schema.py、repository.py、audio_runtime.py | 保存、归档、合成三层防线。 |
| daily_report_queries.py、app.py、日报模板和 CSS | 警告、三段定位、长文本可读性。 |
| tests/daily_reports/test_text_integrity.py | 纯函数与两类审核草稿。 |
| 现有仓储、音频与网页测试 | 防线、错误映射和页面回归。 |

## 契约

~~~python
TEXT_INTEGRITY_ERROR = "daily_report_text_corrupted"

def has_suspicious_question_run(value: str) -> bool: ...
def ensure_editorial_text_integrity(*values: str) -> None: ...
~~~

当任一文本包含连续四个 ASCII 问号时，ensure_editorial_text_integrity 抛出 ValueError(TEXT_INTEGRITY_ERROR)。所有调用方复用该函数，不复制正则表达式。

~~~python
def assert_text_integrity(self, report_id: int) -> None: ...
~~~

它检查该日报的决策条目与全览条目各自最新审核版本；archive() 在变更状态前调用它。

### Task 1: 文本完整性与审核输入防线

**Files:**

- Create: src/newsradar/daily_reports/text_integrity.py
- Modify: src/newsradar/daily_reports/schema.py:36-153
- Create: tests/daily_reports/test_text_integrity.py

**Consumes:** 无状态字符串。

**Produces:** 被草稿、仓储和 Worker 共享的完整性函数。

- [ ] **Step 1: 写失败测试**

~~~python
def test_detects_only_a_run_of_four_or_more_ascii_question_marks() -> None:
    assert has_suspicious_question_run("正常？") is False
    assert has_suspicious_question_run("FAQ???") is False
    assert has_suspicious_question_run("损坏????内容") is True

@pytest.mark.parametrize("field", [
    "zh_title", "zh_summary", "review_recommendation", "evidence_assessment",
])
def test_editorial_drafts_reject_corrupted_text(field: str) -> None:
    values = {
        "decision": "keep", "zh_title": "标题", "zh_summary": "概述",
        "review_recommendation": "继续关注。", "evidence_assessment": "证据说明。",
    }
    values[field] = "????"
    with pytest.raises(ValueError, match="daily_report_text_corrupted"):
        DailyReportEditorialReviewDraft.create(**values)
    with pytest.raises(ValueError, match="daily_report_text_corrupted"):
        DailyReportOverviewEditorialReviewDraft.create(**values)
~~~

- [ ] **Step 2: 验证 RED**

Run: python -m pytest tests/daily_reports/test_text_integrity.py -q

Expected: 模块不存在，且现有草稿接受连续问号。

- [ ] **Step 3: 最小实现**

~~~python
import re

TEXT_INTEGRITY_ERROR = "daily_report_text_corrupted"
_QUESTION_RUN = re.compile(r"\?{4,}")

def has_suspicious_question_run(value: str) -> bool:
    return bool(_QUESTION_RUN.search(value))

def ensure_editorial_text_integrity(*values: str) -> None:
    if any(has_suspicious_question_run(value) for value in values):
        raise ValueError(TEXT_INTEGRITY_ERROR)
~~~

两类草稿先通过既有 _editorial_text 清洗四个字段，再一次性调用 ensure_editorial_text_integrity。保留长度、结论和重复关联校验。

- [ ] **Step 4: 验证 GREEN**

Run: python -m pytest tests/daily_reports/test_text_integrity.py -q

Expected: PASS。

- [ ] **Step 5: 提交**

~~~powershell
git add src/newsradar/daily_reports/text_integrity.py src/newsradar/daily_reports/schema.py tests/daily_reports/test_text_integrity.py
git commit -m "fix: reject corrupted daily report text"
~~~

### Task 2: 归档与 Worker 的防御检查

**Files:**

- Modify: src/newsradar/daily_reports/repository.py:227-355
- Modify: src/newsradar/daily_reports/audio_runtime.py:63-118
- Modify: tests/daily_reports/test_repository.py
- Modify: tests/daily_reports/test_audio_runtime.py

**Consumes:** Task 1 的完整性函数与现有最新审核查询。

**Produces:** assert_text_integrity(report_id)；归档和合成的稳定拒绝。

- [ ] **Step 1: 写失败测试**

~~~python
def test_archive_rejects_latest_corrupted_overview_review_and_keeps_draft(db_session) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).overview_items(report.id)[0]
    db_session.add(_corrupted_overview_review(item.id))
    db_session.commit()

    with pytest.raises(ValueError, match="daily_report_text_corrupted"):
        DailyReportRepository(db_session).archive(report.id)

    assert db_session.get(DailyReportRecord, report.id).status == "draft"
~~~

再添加 Worker 测试：先用干净数据归档，再直接插入最新损坏审核，断言结果为 daily_report_text_corrupted、synthesize 未被调用、没有音频制品。

- [ ] **Step 2: 验证 RED**

Run: python -m pytest tests/daily_reports/test_repository.py tests/daily_reports/test_audio_runtime.py -q

Expected: 当前归档会成功，Worker 会调用合成函数。

- [ ] **Step 3: 最小实现**

~~~python
def assert_text_integrity(self, report_id: int) -> None:
    reviews = self._latest_decision_reviews(report_id) + self._latest_overview_reviews(report_id)
    for review in reviews:
        ensure_editorial_text_integrity(
            review.zh_title, review.zh_summary,
            review.review_recommendation, review.evidence_assessment,
        )
~~~

两个私有查询按 item_id、revision DESC、id DESC 仅取每项最新审核。archive() 在设置 status 前调用该方法。Worker 在已构建最终脚本、写入 DailyReportAudioArtifactRecord 之前调用 ensure_editorial_text_integrity(script)；失败时返回不可重试中文消息“检测到疑似编码损坏的连续问号，请修正中文内容后再继续。”，不创建制品、不调用 MiniMax。

- [ ] **Step 4: 验证 GREEN**

Run: python -m pytest tests/daily_reports/test_repository.py tests/daily_reports/test_audio_runtime.py -q

Expected: PASS，且既有归档回滚和取消测试仍通过。

- [ ] **Step 5: 提交**

~~~powershell
git add src/newsradar/daily_reports/repository.py src/newsradar/daily_reports/audio_runtime.py tests/daily_reports/test_repository.py tests/daily_reports/test_audio_runtime.py
git commit -m "fix: block corrupted daily report archive and audio"
~~~

### Task 3: 现有页面的完整性诊断与阅读结构

**Files:**

- Modify: src/newsradar/web/daily_report_queries.py:43-180,514-612
- Modify: src/newsradar/web/app.py:106-159
- Modify: src/newsradar/web/templates/daily_report_detail.html:193-334
- Modify: src/newsradar/web/static/styles.css:370-590
- Modify: tests/web/test_daily_report_pages.py

**Consumes:** Task 1 的检测函数和现有详情投影。

**Produces:** DailyReportTextIntegrityView、警告、三段锚点、完整报告标题。

- [ ] **Step 1: 写失败测试**

~~~python
def test_detail_counts_latest_corrupted_reviews_and_page_explains_revision(db_session, monkeypatch) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).overview_items(report.id)[0]
    db_session.add(_corrupted_overview_review(item.id))
    db_session.commit()

    detail = DailyReportQueryService(db_session).detail(report.id)
    assert detail.text_integrity.corrupted_review_count == 1

    client, _token = safe_client_with_token(db_session, monkeypatch)
    page = client.get(f"/daily-reports/{report.id}")
    assert "检测到疑似编码损坏" in page.text
    assert 'href="#decision-brief-heading"' in page.text
    assert 'href="#overview-heading"' in page.text
    assert 'href="#complete-report-heading"' in page.text
    assert "完整报告与证据" in page.text
~~~

再添加审核 POST 测试，提交连续问号时断言 HTTP 422 和中文诊断。

- [ ] **Step 2: 验证 RED**

Run: python -m pytest tests/web/test_daily_report_pages.py -q

Expected: text_integrity、警告、锚点和错误映射尚不存在。

- [ ] **Step 3: 最小实现**

~~~python
@dataclass(frozen=True, slots=True)
class DailyReportTextIntegrityView:
    corrupted_review_count: int
~~~

在详情查询中从已经投影的最新决策审核和全览审核计数：任一四字段包含损坏特征，该审核只计一次。给 DailyReportDetailView 增加 text_integrity 字段。

在 _DAILY_REPORT_ERRORS 中增加：

~~~python
"daily_report_text_corrupted": (
    422,
    "检测到疑似编码损坏的连续问号，请修正中文内容后再继续。",
),
~~~

在页面顶部新增三个锚点：“决策简报”“情报全览”“完整报告与证据”。计数大于 0 时显示 diagnostic-warning，明确历史版应创建修订版。保留两种音频位置。用一个标题为“完整报告与证据”的容器包住当前确认要闻和早期线索，不删除公开证据、审核历史、编辑、归档或修订控件。CSS 使用现有 token，导航允许换行，正文和 URL 使用 overflow-wrap: anywhere，不破坏窄屏媒体规则。

- [ ] **Step 4: 验证 GREEN**

Run: python -m pytest tests/web/test_daily_report_pages.py -q

Expected: PASS。

- [ ] **Step 5: 提交**

~~~powershell
git add src/newsradar/web/daily_report_queries.py src/newsradar/web/app.py src/newsradar/web/templates/daily_report_detail.html src/newsradar/web/static/styles.css tests/web/test_daily_report_pages.py
git commit -m "feat: surface daily report integrity diagnostics"
~~~

### Task 4: 创建修订版并恢复日报 5

**Files:**

- Create temporarily: scripts/repair_daily_report_5_integrity.py
- Delete before commit: scripts/repair_daily_report_5_integrity.py
- Runtime only: 新修订日报、追加审核历史和两个音频制品。

**Consumes:** Tasks 1–3、DailyReportRepository.revise、日报 5 固定快照。

**Produces:** 无损坏审核的日报 5 新修订版和两个独立音频。

- [ ] **Step 1: 先编写 UTF-8 安全修复脚本**

用 apply_patch 创建 UTF-8 脚本，绝不通过 PowerShell 管道传递中文。脚本只经 create_session() 读取设置，不输出设置或文本。它调用 repository.revise(5)，为每个含连续问号的最新决策/全览审核追加新版本；保留结论与重复目标，标题和概述取固定快照，审核建议和证据评价只依据既有结论、独立证据根数、确认说明、限制和公开证据生成。输出仅含 report ID 与计数。

~~~python
with create_session() as session:
    revision = DailyReportRepository(session).revise(5)
    repaired = repair_corrupted_latest_reviews(session, revision.id)
    if args.dry_run:
        session.rollback()
    print(json.dumps({"report_id": revision.id, "repaired": repaired}, ensure_ascii=True))
~~~

- [ ] **Step 2: 先干跑**

Run: python scripts/repair_daily_report_5_integrity.py --dry-run

Expected: 输出将修复 29 条且回滚，不持久化任何新记录。

- [ ] **Step 3: 执行修复并做无内容泄露的数据库核验**

Run: python scripts/repair_daily_report_5_integrity.py --apply

使用第二个短校验只输出新 report ID、状态、决策损坏数、全览损坏数、决策收录数和全览收录数。Expected: 草稿状态、两类损坏数均为 0，关联和审核结论仍有效。

- [ ] **Step 4: 复核、归档与生成音频**

在本地新修订页逐项检查 17 条进入全览内容：任何超过固定快照证据边界的条目降为 needs_evidence 或 exclude，不提升弱证据。全部候选均已审核后使用现有“归档定稿”，再生成并等待决策版、全览版音频。核验两个成功制品均无连续问号、文件非空，模型为 speech-2.8-hd。

- [ ] **Step 5: 删除临时脚本**

仅用 apply_patch 删除 scripts/repair_daily_report_5_integrity.py，保留追加式数据库历史、音频和修订日报。确认 git status --short 不含该脚本。

### Task 5: 完整验证与不推送交付

**Files:**

- Modify only if a prior verification exposes a reproducible defect.

**Consumes:** 前四项。

**Produces:** 有证据的交付状态；分支保持未推送。

- [ ] **Step 1: 静态检查**

Run: python -m ruff check .

Expected: exit code 0。

- [ ] **Step 2: 完整测试**

Run: python -m pytest -q

Expected: 全部通过；记录实际 passed、skipped、warnings。

- [ ] **Step 3: 本地网页验收**

启动修复分支的本地服务，访问新修订日报。桌面和窄屏各验收一次：

~~~text
决策简报 → 中文报告 + 决策版音频
情报全览 → 收录条目、待补证标签 + 全览版音频
完整报告与证据 → 确认要闻、早期线索、审核历史与公开证据
~~~

确认长中文和 URL 不横向溢出，页面和两份音频脚本均无连续问号。

- [ ] **Step 4: 检查 diff 并提交代码**

~~~powershell
git diff --check
git status --short
git log --oneline main..HEAD
git add src/newsradar/daily_reports src/newsradar/web tests docs/superpowers/plans/2026-07-17-daily-report-integrity-repair.md
git commit -m "fix: complete daily report integrity repair"
~~~

只提交源代码、测试和计划；不得暂存 reports/、.env、数据库、音频或临时修复脚本。

- [ ] **Step 5: 报告但不合并、不推送**

报告修订日报 ID、两类损坏计数、决策/全览条目数、两个音频状态、pytest、ruff 与网页验收结果；等待用户明确决定合并或推送。
