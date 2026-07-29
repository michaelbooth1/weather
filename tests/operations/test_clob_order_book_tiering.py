import gzip
import os
import tempfile
import time
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from weather.operations.clob_order_book_tiering import MIN_QUIET_SECONDS, build_payload, run


DiskUsage = namedtuple("DiskUsage", "total used free")


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_long_book(folder, text="capture_id,side,level_index,price,size\nb1,bid,1,0.40,10\n", *, quiet=True):
    write(folder / "order_books_summary.csv", "capture_id,best_bid,best_ask\nb1,0.40,0.45\n")
    write(folder / "order_books.jsonl", "{}\n")
    write(folder / "clob_tokens.csv", "token\n")
    source = write(folder / "order_books_long.csv", text)
    if quiet:
        # These fixtures stand in for closed days, so age them past MIN_QUIET_SECONDS.
        # A freshly written file is deliberately ineligible: the writer may still hold it.
        old = time.time() - (MIN_QUIET_SECONDS + 60)
        os.utime(source, (old, old))
    return source


class ClobOrderBookTieringTests(unittest.TestCase):
    def test_plan_recognizes_gzip_only_canonical_raw_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder)
            raw = folder / "order_books.jsonl"
            with (folder / "order_books.jsonl.gz").open("wb") as raw_target:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=raw_target,
                    mtime=0,
                ) as target:
                    target.write(raw.read_bytes())
            raw.unlink()

            payload = build_payload(
                root,
                settled_before="2026-06-19",
                min_free_bytes=0,
            )

        self.assertTrue(payload["rows"][0]["raw_jsonl_present"])

    def test_plan_blocks_divergent_plain_and_gzip_long_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder, "plain-half\n")
            with (folder / "order_books_long.csv.gz").open("wb") as raw_target:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=raw_target,
                    mtime=0,
                ) as target:
                    target.write(b"gzip-half\n")

            payload = build_payload(
                root,
                settled_before="2026-06-19",
                min_free_bytes=0,
            )

        row = payload["rows"][0]
        self.assertEqual(row["status"], "blocked_conflicting_tiered_pair")
        self.assertTrue(row["tiered_pair_conflict"])

    def test_plan_blocks_divergent_canonical_raw_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder)
            with (folder / "order_books.jsonl.gz").open("wb") as raw_target:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=raw_target,
                    mtime=0,
                ) as target:
                    target.write(b'{"different":true}\n')

            payload = build_payload(
                root,
                settled_before="2026-06-19",
                min_free_bytes=0,
            )

        row = payload["rows"][0]
        self.assertEqual(
            row["status"],
            "blocked_conflicting_canonical_raw_pair",
        )
        self.assertTrue(row["canonical_raw_pair_conflict"])
        self.assertFalse(row["raw_jsonl_present"])

    def test_plan_identifies_settled_candidates_and_blocks_active_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settled = root / "highest-temperature-in-nyc-on-june-16-2026"
            active = root / "highest-temperature-in-nyc-on-june-20-2026"
            unknown = root / "manual-event"
            write_long_book(settled)
            write_long_book(active)
            write_long_book(unknown)

            payload = build_payload(root, settled_before="2026-06-19", min_free_bytes=0)

        counts = payload["summary"]["status_counts"]
        self.assertEqual(payload["status"], "WARN")
        self.assertEqual(counts["candidate"], 1)
        self.assertEqual(counts["blocked_active_or_unsettled"], 1)
        self.assertEqual(counts["blocked_unknown_event_date"], 1)
        self.assertGreater(payload["summary"]["candidate_bytes"], 0)

    def test_settled_day_still_being_written_is_not_a_candidate(self):
        # The UTC-vs-local cutoff once marked the current day settled from 20:00 local while
        # the CLOB loop was still appending (2026-07-27). The date arithmetic is only a cheap
        # pre-filter; recent writer activity is the invariant that actually protects the file.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder, quiet=False)

            payload = build_payload(root, settled_before="2026-06-19", min_free_bytes=0)

        counts = payload["summary"]["status_counts"]
        self.assertEqual(counts.get("candidate", 0), 0)
        self.assertEqual(counts["blocked_recently_written"], 1)

    def test_apply_refuses_a_source_written_since_the_plan(self):
        # Apply re-checks rather than trusting the plan: a plan can be hours old.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            source = write_long_book(folder)

            payload = build_payload(root, settled_before="2026-06-19", min_free_bytes=0)
            self.assertEqual(payload["summary"]["status_counts"]["candidate"], 1)

            # A writer touches the file between plan and apply.
            source.write_text("capture_id,side,level_index,price,size\nb2,ask,1,0.55,4\n", encoding="utf-8")

            from weather.operations.clob_order_book_tiering import apply_tiering

            result = apply_tiering(payload, delete_source=True)

            self.assertTrue(source.exists(), "source must survive a refused apply")
            self.assertFalse(folder.joinpath("order_books_long.csv.gz").exists())

        self.assertEqual(result["actions"][0]["status"], "skipped_recently_written")
        self.assertEqual(result["summary"]["deleted_sources"], 0)

    def test_apply_compresses_and_deletes_source_after_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            source_text = "capture_id,side,level_index,price,size\nb1,bid,1,0.40,10\n"
            write_long_book(folder, source_text)

            payload = run(
                snapshots_root=root,
                settled_before="2026-06-19",
                min_free_bytes=0,
                apply=True,
                delete_source=True,
            )
            gzip_path = folder / "order_books_long.csv.gz"

            with gzip.open(gzip_path, "rt", encoding="utf-8") as handle:
                restored = handle.read()
            source_exists = (folder / "order_books_long.csv").exists()
            gzip_exists = gzip_path.exists()

        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(source_exists)
        self.assertTrue(gzip_exists)
        self.assertEqual(restored, source_text)
        self.assertEqual(payload["apply"]["summary"]["compressed_files"], 1)
        self.assertEqual(payload["apply"]["summary"]["deleted_sources"], 1)

    def test_apply_skips_without_headroom_and_leaves_source_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder)

            with patch(
                "weather.operations.clob_order_book_tiering.shutil.disk_usage",
                return_value=DiskUsage(total=100, used=99, free=1),
            ):
                payload = run(
                    snapshots_root=root,
                    settled_before="2026-06-19",
                    min_free_bytes=100,
                    apply=True,
                    delete_source=True,
                )
            source_exists = (folder / "order_books_long.csv").exists()
            gzip_exists = (folder / "order_books_long.csv.gz").exists()

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertTrue(source_exists)
        self.assertFalse(gzip_exists)
        self.assertEqual(payload["apply"]["summary"]["insufficient_headroom"], 1)

    def test_apply_records_compression_failures_without_deleting_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder)
            (folder / "order_books_long.csv.gz.tmp").write_text("leftover\n", encoding="utf-8")

            payload = run(
                snapshots_root=root,
                settled_before="2026-06-19",
                min_free_bytes=0,
                apply=True,
                delete_source=True,
            )
            source_exists = (folder / "order_books_long.csv").exists()

        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["apply"]["actions"][0]["status"], "failed")
        self.assertIn("temporary gzip path already exists", payload["apply"]["actions"][0]["error"])
        self.assertTrue(source_exists)


if __name__ == "__main__":
    unittest.main()
