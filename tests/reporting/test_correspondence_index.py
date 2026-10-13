import os
import subprocess

import pytest

from weather.reporting.roadmap import correspondence_index as index


def put(root, name, text):
    path = root / "docs/roadmap" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_index_pairs_exact_ids_lists_collisions_and_escapes_titles(tmp_path):
    put(tmp_path, "workstation-handoff-2026-09-93a-topic.md", "# A | [title]\nEF §10m, §1c; RF §99; item 330; items 2, 3.\n[old](missing.md)\n")
    put(tmp_path, "agent-report-2026-09-93a-one.md", "# First\n")
    put(tmp_path, "agent-report-2026-09-93a-two.md", "# Second\n")
    put(tmp_path, "agent-report-2026-09-93b-unrelated.md", "# Other\n")
    put(tmp_path, "agent-work-order-2026-06-99z.md", "# Work order\n")
    outputs = index.render_outputs(tmp_path, {})
    assert set(outputs) == {index.OUTPUT, f"{index.SHARD_DIR}/uncommitted.md"}
    text = outputs[f"{index.SHARD_DIR}/uncommitted.md"]
    assert "(../agent-report-2026-09-93a-one.md)" in text
    handoff = next(line for line in text.splitlines() if "| handoff |" in line)
    assert "93a-one.md" in handoff and "93a-two.md" in handoff
    assert "93b-unrelated.md" not in handoff
    assert "A &#124; &#91;title&#93;" in handoff
    assert "1c, 10m" in handoff and "2, 3, 330" in handoff
    assert "uncommitted" in handoff
    order = next(line for line in text.splitlines() if "| work order |" in line)
    assert "none in tree" in order


def git(root, *args, date="2026-09-24T12:00:00+00:00"):
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def test_cli_uses_first_git_addition_and_check_never_writes(tmp_path):
    git(tmp_path, "init")
    path = put(tmp_path, "agent-report-2026-09-93a-topic.md", "# Original\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "core.hooksPath=", "commit", "-m", "add", date="2026-08-10T12:00:00+00:00")
    path.write_text("# New title\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "core.hooksPath=", "commit", "-m", "edit")
    dates = index.git_added_dates(tmp_path)
    assert dates[path.relative_to(tmp_path).as_posix()] == "2026-08-10"
    assert index.main(["--repo-root", str(tmp_path)]) == 0
    report = tmp_path / index.SHARD_DIR / "2026-08.md"
    original = report.read_bytes()
    assert b"New title" in original and b"2026-08-10" in original
    assert b"(correspondence-index/2026-08.md)" in (tmp_path / index.OUTPUT).read_bytes()
    assert index.main(["--repo-root", str(tmp_path), "--check"]) == 0
    path.write_text("# Changed again\n", encoding="utf-8")
    assert index.main(["--repo-root", str(tmp_path), "--check"]) == 1
    assert report.read_bytes() == original


def test_new_month_leaves_closed_shards_untouched_and_uncommitted_shard_is_transient(tmp_path):
    git(tmp_path, "init")
    put(tmp_path, "agent-report-2026-08-01a-old.md", "# Old\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "core.hooksPath=", "commit", "-m", "old", date="2026-08-10T12:00:00+00:00")
    assert index.write_outputs(tmp_path) == [index.OUTPUT, f"{index.SHARD_DIR}/2026-08.md"]
    closed = (tmp_path / index.SHARD_DIR / "2026-08.md").read_bytes()

    put(tmp_path, "agent-report-2026-09-02a-new.md", "# New\n")
    assert index.write_outputs(tmp_path) == [index.OUTPUT, f"{index.SHARD_DIR}/uncommitted.md"]
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "core.hooksPath=", "commit", "-m", "new", date="2026-09-24T12:00:00+00:00")
    assert index.write_outputs(tmp_path) == [
        index.OUTPUT, f"{index.SHARD_DIR}/2026-09.md", f"{index.SHARD_DIR}/uncommitted.md",
    ]
    assert not (tmp_path / index.SHARD_DIR / "uncommitted.md").exists()
    assert (tmp_path / index.SHARD_DIR / "2026-08.md").read_bytes() == closed
    assert index.write_outputs(tmp_path) == []
    assert index.parity_errors(tmp_path) == []

    (tmp_path / index.SHARD_DIR / "2026-01.md").write_text("# stray\n", encoding="utf-8")
    assert index.parity_errors(tmp_path) == [
        f"{index.SHARD_DIR}/2026-01.md: no longer generated; "
        "run python -m weather.reporting.roadmap.correspondence_index"
    ]


def test_history_failure_is_not_a_fabricated_date(tmp_path):
    put(tmp_path, "agent-report-2026-09-93a-topic.md", "# Report\n")
    assert index.main(["--repo-root", str(tmp_path), "--check"]) == 1
    assert not (tmp_path / index.OUTPUT).exists()


def test_shallow_history_fails_closed(tmp_path):
    git(tmp_path, "init")
    put(tmp_path, "agent-report-2026-09-93a-topic.md", "# Report\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "core.hooksPath=", "commit", "-m", "add")
    head = git(tmp_path, "rev-parse", "HEAD").stdout.decode().strip()
    (tmp_path / ".git/shallow").write_text(head + "\n", encoding="utf-8")
    assert "history is shallow" in index.parity_errors(tmp_path)[0]


def test_sort_uses_git_dates_not_mission_labels(tmp_path):
    early = "workstation-handoff-2026-09-99z-early.md"
    late = "workstation-handoff-2026-07-01a-late.md"
    put(tmp_path, early, "# Early\n")
    put(tmp_path, late, "# Late\n")
    dates = {f"docs/roadmap/{early}": "2026-08-01", f"docs/roadmap/{late}": "2026-09-01"}
    assert [row["name"] for row in index.correspondence_rows(tmp_path, dates)] == [early, late]


def test_section_citations_accept_file_names_links_and_bis():
    text = ("`ESTABLISHED_FINDINGS.md` §4a-bis; "
            "[EF](../operations/ESTABLISHED_FINDINGS.md#10m-reward); "
            "[ESTABLISHED_FINDINGS.md §4 and §8](../operations/ESTABLISHED_FINDINGS.md); "
            "EF §1, §1c; RF §99")
    assert index.ef_sections(text) == ["1", "1c", "4", "4a-bis", "8", "10m"]


def test_unknown_correspondence_name_is_not_silently_omitted(tmp_path, monkeypatch):
    put(tmp_path, "agent-report-new.md", "# Report\n")
    monkeypatch.setattr(index, "git_added_dates", lambda root: {})
    assert "unparseable correspondence filename" in index.parity_errors(tmp_path)[0]


# --- option D: branches do not commit the index; structural vs strict -------

def _landed_index(tmp_path):
    """A repo whose committed index is fully regenerated (the closeout state)."""
    git(tmp_path, "init")
    put(tmp_path, "workstation-handoff-2026-09-10a-topic.md", "# Handoff\n")
    put(tmp_path, "agent-report-2026-09-11a-other.md", "# Other\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "core.hooksPath=", "commit", "-m", "add", date="2026-09-10T12:00:00+00:00")
    index.write_outputs(tmp_path)
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "core.hooksPath=", "commit", "-m", "index", date="2026-09-10T13:00:00+00:00")
    assert index.parity_errors(tmp_path) == []
    return tmp_path / index.SHARD_DIR / "2026-09.md"


@pytest.mark.spawns
def test_structure_allows_pending_rows_and_lagging_answers_strict_does_not(tmp_path):
    shard = _landed_index(tmp_path)
    # A branch adds the handoff's answering report without regenerating the index.
    put(tmp_path, "agent-report-2026-09-10a-answer.md", "# Answer\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "core.hooksPath=", "commit", "-m", "answer", date="2026-09-12T12:00:00+00:00")
    errors, pending = index.structural_check(tmp_path)
    assert errors == [] and pending == 1
    assert "none in tree" in shard.read_text(encoding="utf-8")  # the handoff's answers lag
    assert index.parity_errors(tmp_path)  # strict still demands the closeout
    assert index.main(["--repo-root", str(tmp_path), "--check-structure"]) == 0
    assert index.main(["--repo-root", str(tmp_path), "--check"]) == 1
    # The closeout regeneration is idempotent and restores strict parity.
    assert index.write_outputs(tmp_path)
    assert index.write_outputs(tmp_path) == []
    assert index.parity_errors(tmp_path) == [] and index.structural_check(tmp_path) == ([], 0)


@pytest.mark.spawns
def test_structure_fails_a_stale_row(tmp_path):
    """Mutant: a committed row that no longer matches its source must fail."""
    _landed_index(tmp_path)
    put(tmp_path, "agent-report-2026-09-11a-other.md", "# Retitled\n")
    errors = index.structural_errors(tmp_path)
    assert len(errors) == 1 and "differs from its source" in errors[0]
    assert "drop the hunk" in errors[0]


@pytest.mark.spawns
def test_structure_fails_stray_edited_wrong_answer_and_out_of_order_rows(tmp_path):
    shard = _landed_index(tmp_path)
    original = shard.read_text(encoding="utf-8")
    header, rows = original.rstrip("\n").split("\n")[:-2], original.rstrip("\n").split("\n")[-2:]

    def with_rows(*lines):
        shard.write_text("\n".join([*header, *lines]) + "\n", encoding="utf-8")
        return index.structural_errors(tmp_path)

    report = next(row for row in rows if "11a-other" in row)
    handoff = next(row for row in rows if "| handoff |" in row)
    assert rows == [report, handoff]  # same added date: filename order
    stray = report.replace("agent-report-2026-09-11a-other.md", "agent-report-2026-09-11a-gone.md")
    assert any("no source in tree" in e for e in with_rows(*rows, stray))
    assert any("differs from its source" in e
               for e in with_rows(report.replace("| 2026-09-10 |", "| 2026-09-09 |"), handoff))
    wrong = handoff.replace("none in tree", "[agent-report-2026-09-11a-other.md](../agent-report-2026-09-11a-other.md)")
    assert any("does not share its id" in e for e in with_rows(report, wrong))
    assert any("out of order" in e for e in with_rows(handoff, report))
    assert any("duplicate row" in e for e in with_rows(*rows, report))
    assert with_rows(handoff) == []  # dropping a row is only pending
    assert with_rows(*rows) == []


@pytest.mark.spawns
def test_structure_checks_the_root_month_list_not_its_prose(tmp_path):
    _landed_index(tmp_path)
    root = tmp_path / index.OUTPUT
    text = root.read_text(encoding="utf-8")
    root.write_text(text.replace("Branches do not commit", "Older prose: branches commit"), encoding="utf-8")
    assert index.structural_errors(tmp_path) == []  # the first closeout migrates the prose
    root.write_text(text + "- [2026-01](correspondence-index/2026-01.md)\n", encoding="utf-8")
    assert any("no longer generated" in e for e in index.structural_errors(tmp_path))
    root.write_text(text, encoding="utf-8")
    (tmp_path / index.SHARD_DIR / "2026-09.md").unlink()
    assert any("shard is missing" in e for e in index.structural_errors(tmp_path))
