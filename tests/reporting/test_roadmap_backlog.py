import tempfile
import unittest
from pathlib import Path

from weather.reporting.roadmap_backlog import (
    SCHEMA_VERSION,
    build_payload,
    parse_item,
    write_json,
    write_markdown,
)


def _item(path: Path, number: int, status: str, body: str = "") -> Path:
    path.write_text(
        f"# {number}. Demo Item {number} [{status}]\n\n"
        "Goal: do the thing.\n\n"
        "Source: test.\n\n"
        "Why this matters: test value.\n\n"
        "- [ ] Finish it.\n\n"
        "Acceptance: proof exists.\n"
        + body,
        encoding="utf-8",
    )
    return path


def _roadmap(root: Path, rows: list[str]) -> Path:
    text = "\n".join(
        [
            "# Roadmap",
            "",
            "### Track A",
            "",
            "| Item | File |",
            "| ---: | --- |",
            *rows,
            "",
        ]
    )
    path = root / "ROADMAP.md"
    path.write_text(text, encoding="utf-8")
    return path


class RoadmapBacklogTests(unittest.TestCase):
    def test_parse_item_extracts_status_date_and_disposition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _item(
                Path(tmp) / "item-123-demo.md",
                123,
                "PARTIAL 2026-06-21 - DEMO DISPOSITION",
            )

            item = parse_item(path, root=tmp)

        self.assertEqual(item["number"], 123)
        self.assertEqual(item["title"], "Demo Item 123")
        self.assertEqual(item["status"], "PARTIAL")
        self.assertEqual(item["date"], "2026-06-21")
        self.assertEqual(item["disposition"], "DEMO DISPOSITION")
        self.assertTrue(item["active"])
        self.assertEqual(item["parse_errors"], [])

    def test_build_payload_includes_only_open_and_partial_active_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items"
            items.mkdir()
            _item(items / "item-001-open.md", 1, "OPEN")
            _item(items / "item-002-partial.md", 2, "PARTIAL 2026-06-21 - IN PROGRESS")
            _item(items / "item-003-complete.md", 3, "COMPLETE 2026-06-21 - DONE")

            payload = build_payload(root, generated_at_utc="2026-06-21T00:00:00+00:00")

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["summary"]["item_count"], 3)
        self.assertEqual(payload["summary"]["active_item_count"], 2)
        self.assertEqual([row["number"] for row in payload["active_items"]], [1, 2])

    def test_active_items_missing_required_sections_are_lint_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items"
            items.mkdir()
            (items / "item-001-bad.md").write_text(
                "# 1. Bad Item [OPEN]\n\nGoal: missing pieces.\n",
                encoding="utf-8",
            )

            payload = build_payload(root)

        self.assertEqual(payload["status"], "ERROR")
        categories = {issue["category"] for issue in payload["lint_issues"]}
        self.assertIn("active_item_missing_required_section", categories)

    def test_roadmap_index_lint_catches_duplicate_stale_missing_and_orphan_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items"
            items.mkdir()
            _item(items / "item-001-open.md", 1, "OPEN")
            _item(items / "item-002-partial.md", 2, "PARTIAL 2026-06-21 - IN PROGRESS")
            _item(items / "item-003-complete.md", 3, "COMPLETE 2026-06-21 - DONE")
            _roadmap(
                root,
                [
                    "| 1 | [Demo Item 1 [OPEN]](items/item-001-open.md) |",
                    "| 1 | [Demo Item 1 [OPEN]](items/item-001-open.md) |",
                    "| 2 | [Wrong Item 2 [OPEN]](items/item-002-partial.md) |",
                    "| 999 | [Missing Item [OPEN]](items/item-999-missing.md) |",
                ],
            )

            payload = build_payload(root)

        categories = {issue["category"] for issue in payload["lint_issues"]}
        self.assertEqual(payload["status"], "ERROR")
        self.assertIn("roadmap_index_duplicate_primary_row", categories)
        self.assertIn("roadmap_index_title_mismatch", categories)
        self.assertIn("roadmap_index_status_mismatch", categories)
        self.assertIn("roadmap_index_missing_primary_row", categories)
        self.assertIn("roadmap_index_orphan_link", categories)

    def test_roadmap_index_cross_link_rows_do_not_count_as_duplicate_primary_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items"
            items.mkdir()
            _item(items / "item-001-open.md", 1, "OPEN")
            (root / "ROADMAP.md").write_text(
                "\n".join(
                    [
                        "# Roadmap",
                        "",
                        "### Track A",
                        "",
                        "| Item | File |",
                        "| ---: | --- |",
                        "| 1 | [Demo Item 1 [OPEN]](items/item-001-open.md) |",
                        "",
                        "### Cross-Track References",
                        "",
                        "| Item | File |",
                        "| ---: | --- |",
                        "| 1 | [Demo Item 1 [OPEN]](items/item-001-open.md) |",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            payload = build_payload(root)

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["summary"]["roadmap_index_row_count"], 2)
        self.assertEqual(payload["summary"]["roadmap_index_primary_row_count"], 1)

    def test_write_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items"
            items.mkdir()
            _item(items / "item-001-open.md", 1, "OPEN")
            payload = build_payload(root, generated_at_utc="2026-06-21T00:00:00+00:00")
            json_out = root / "roadmap_backlog.json"
            report_out = root / "active-backlog.md"

            write_json(json_out, payload)
            write_markdown(report_out, payload)

            json_exists = json_out.exists()
            report_text = report_out.read_text(encoding="utf-8")

        self.assertTrue(json_exists)
        self.assertIn("# Active Roadmap Backlog", report_text)
        self.assertIn("Demo Item 1", report_text)

    def test_current_active_roadmap_items_pass_required_lint(self):
        payload = build_payload("docs/roadmap", generated_at_utc="2026-06-21T00:00:00+00:00")

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["lint_issues"], [])


if __name__ == "__main__":
    unittest.main()
