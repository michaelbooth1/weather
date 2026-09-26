import os
import subprocess

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
    text = index.render_index(tmp_path, {})
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
    report = tmp_path / index.OUTPUT
    original = report.read_bytes()
    assert b"New title" in original and b"2026-08-10" in original
    assert index.main(["--repo-root", str(tmp_path), "--check"]) == 0
    path.write_text("# Changed again\n", encoding="utf-8")
    assert index.main(["--repo-root", str(tmp_path), "--check"]) == 1
    assert report.read_bytes() == original


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
