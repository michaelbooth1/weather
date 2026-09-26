import pytest

from weather.operations import agent_docs_audit as audit
from weather.operations import knowledge_structure_audit as knowledge
from weather.reporting.roadmap import correspondence_index as correspondence
from weather.reporting.roadmap import roadmap_backlog


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_audit_requires_actual_table_rows_for_files_and_directories(tmp_path):
    write(tmp_path, "docs/roadmap/audits/audit.md", "# Audit")
    write(tmp_path, "docs/roadmap/audits/group/README.md", "# Group")
    index = write(tmp_path, "docs/roadmap/audits/README.md", "[mention](audit.md)\n")
    assert len(knowledge.audit_index_errors(tmp_path)) == 2
    index.write_text("| [audit](audit.md) | done |\n| [group](group/) | done |\n", encoding="utf-8")
    assert knowledge.audit_index_errors(tmp_path) == []
    # Removing a row fails even though the filename still occurs in prose.
    index.write_text("audit.md\n| [group](group/) | done |\n", encoding="utf-8")
    assert "missing audit row for audit.md" in knowledge.audit_index_errors(tmp_path)[0]


def test_digest_citations_include_continuations_not_other_documents(tmp_path):
    write(tmp_path, knowledge.EF, "## 1. Base\n### 1c. Child\n## 4a-bis. Archive\n")
    digest = write(tmp_path, knowledge.OPS + "FINDINGS_DIGEST.md", "EF §1, §1c; RF §90; HW §80; EF §4a-bis.\n")
    assert knowledge.ef_citation_errors(tmp_path) == []
    digest.write_text("EF §1, §10m.\n```\nEF §99\n```\n", encoding="utf-8")
    assert knowledge.ef_citation_errors(tmp_path) == [
        "docs/operations/FINDINGS_DIGEST.md: dangling EF §10m (no EF heading)"
    ]


def question_tree(root, rows):
    write(root, knowledge.EF, "## 10m. Rewards\n")
    return write(root, knowledge.OPS + "OPEN_QUESTIONS.md", "| Id | Evidence | Status |\n| --- | --- | --- |\n" + rows)


def test_question_ids_unique_and_shaped(tmp_path):
    question_tree(tmp_path, "| Q-01 | x | OPEN |\n| Q-01 | y | OPEN |\n| Q-1 | z | OPEN |\n")
    errors = knowledge.question_errors(tmp_path)
    assert len(errors) == 2
    assert "duplicate question id" in errors[0]
    assert "expected Q-nn" in errors[1]


@pytest.mark.parametrize("status", ["ANSWERED -> EF §10m", "ANSWERED -> [EF](ESTABLISHED_FINDINGS.md#10m-rewards)"])
def test_answered_question_resolves_to_ef(tmp_path, status):
    question_tree(tmp_path, f"| Q-01 | x | {status} |\n")
    assert knowledge.question_errors(tmp_path) == []


@pytest.mark.parametrize("status", ["ANSWERED", "ANSWERED -> EF §10n", "ANSWERED -> [EF](ESTABLISHED_FINDINGS.md#missing)", "ANSWERED -> [other](OPEN_QUESTIONS.md)"])
def test_answer_cannot_borrow_an_ef_citation_from_evidence(tmp_path, status):
    question_tree(tmp_path, f"| Q-01 | [EF](ESTABLISHED_FINDINGS.md#10m-rewards) EF §10m | {status} |\n")
    assert any("ANSWERED row must cite" in error for error in knowledge.question_errors(tmp_path))


def test_question_pointers_check_files_fragments_and_escape(tmp_path):
    question_tree(tmp_path, "| Q-01 | [a](missing.md) [b](ESTABLISHED_FINDINGS.md#missing) [c](../../../outside.md) | OPEN |\n")
    errors = knowledge.question_errors(tmp_path)
    assert len(errors) == 3
    assert any("missing pointer:" in error for error in errors)
    assert any("missing pointer anchor:" in error for error in errors)
    assert any("escapes repository" in error for error in errors)


def test_owner_dates_need_same_date_rows_not_mentions(tmp_path):
    write(tmp_path, knowledge.OPS + "STATE_OF_PLAY.md", "Owner 2026-09-23: a. owner 2026-09-24: b.\n")
    log = write(tmp_path, knowledge.OPS + "DECISION_LOG.md", "2026-09-24\n| 2026-09-23 | decision |\n")
    assert len(knowledge.decision_errors(tmp_path)) == 1
    with log.open("a", encoding="utf-8") as stream:
        stream.write("| 2026-09-24 | decision |\n")
    assert knowledge.decision_errors(tmp_path) == []


def test_generated_checks_use_source_parity_without_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(correspondence, "git_added_dates", lambda root: {})
    write(tmp_path, "docs/roadmap/items/item-1-done.md", "# 1. Done [COMPLETE]\n\n## Completion notes\nDone.\n")
    write(tmp_path, correspondence.OUTPUT, correspondence.render_index(tmp_path, {}))
    payload = roadmap_backlog.build_payload(tmp_path / "docs/roadmap")
    backlog = write(tmp_path, "docs/roadmap/active-backlog.md", roadmap_backlog.render_markdown(payload))
    assert knowledge.generated_index_errors(tmp_path) == []
    original = backlog.read_bytes()
    write(tmp_path, "docs/roadmap/agent-report-2026-09-93a-new.md", "# New report\n")
    backlog.write_text("stale\n", encoding="utf-8")
    errors = knowledge.generated_index_errors(tmp_path)
    assert len(errors) == 2 and all("stale" in error for error in errors)
    assert backlog.read_text() == "stale\n"  # check mode did not repair it
    assert not (tmp_path / "data").exists()
    backlog.write_bytes(original)


def test_main_runs_knowledge_checks_in_repository(capsys):
    # The workstation wrapper admits pytest, not an arbitrary docs module; exercise
    # the actual CLI here while retaining its identity, mutex and Job containment.
    assert audit.main([]) == 0
    assert "Agent docs audit: PASS" in capsys.readouterr().out


def test_work_orders_keep_historical_link_tolerance(tmp_path):
    path = write(tmp_path, "docs/roadmap/agent-work-order-2026-06-90a.md", "[old](retired.md)\n")
    assert audit.broken_local_links(tmp_path, [path]) == []
