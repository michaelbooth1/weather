"""Incremental market-day label finalization equals a full run on fixtures.

Guards: the Stage-A 11:55 deadline overrun (market_day_labels_finalize re-finalized
every settled folder with one Gamma GET each); incremental mode must write the same
settlement content as the full ``finalize_folders`` run and re-finalize on any input,
logic, reconciliation or sidecar change. Kills: a reuse predicate that ignores the
tape, the target-date daily-summary row, the logic key, a non-terminal reconciliation,
an override, the recheck-window boundary, or a sidecar rewritten by another path.
"""

import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from weather.backtesting import settlement_ledger
from weather.backtesting.settlement_ledger import FolderFinalizationError, finalize_folders
from weather.operations import daily_refresh_incremental_finalize as incremental
from weather.operations.daily_refresh_source_steps import run_market_day_labels_finalize

TODAY = date(2026, 6, 30)
DATES = (date(2026, 5, 25), date(2026, 5, 26), date(2026, 5, 27))
MONTHS = {5: "may", 6: "june"}


def _slug(day):
    return f"highest-temperature-in-toronto-on-{MONTHS[day.month]}-{day.day}-{day.year}"


def _write_tape(folder, day, high=25.0):
    start = datetime(day.year, day.month, day.day, 11, 0)
    pd.DataFrame([
        {
            "snapshot_id": f"s{i}",
            "captured_at_local": (start + timedelta(minutes=10 * i)).isoformat(),
            "range_label": f"{int(high)} C",
            "bin_kind": "eq",
            "bin_value_c": int(high),
            "model_probability": 0.8,
            "market_yes": 0.4,
            "wu_history_high_c": high,
        }
        for i in range(43)
    ]).to_csv(folder / "snapshots_long.csv", index=False)


def _event(label, closed=True):
    return {
        "closed": closed,
        "markets": [{
            "groupItemTitle": label,
            "closed": closed,
            "umaResolutionStatus": "resolved" if closed else "",
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["1", "0"] if closed else ["0.6", "0.4"]),
        }],
    }


class _Gamma:
    """Counting Gamma stub; ``open_slugs`` answer as an unresolved event."""

    def __init__(self):
        self.calls = []
        self.open_slugs = set()

    def __call__(self, slug, timeout=10):
        self.calls.append(slug)
        return _event("25 C", closed=slug not in self.open_slugs)


def _build_root(root):
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True)
    for day in DATES:
        folder = snapshots / _slug(day)
        folder.mkdir()
        _write_tape(folder, day)
    daily = root / "daily.csv"
    daily.write_text(
        "local_date,row_count,max_temp_bucket_c\n"
        + "".join(f"{day.isoformat()},24,25\n" for day in DATES),
        encoding="utf-8",
    )
    return snapshots, daily


def _csv_rows(path, *, drop=incremental.VOLATILE_LABEL_COLUMNS):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for column in drop:
            row.pop(column, None)
        # Paths embed the per-root temp directory; compare them relative to it.
        for column in ("daily_summary_path", "snapshot_tape_path", "ledger_path"):
            row[column] = Path(row[column]).name
    return sorted(rows, key=lambda row: row["event_slug"])


def _ledger_revisions(root):
    ledger = root / "ledger" / "toronto" / "ledger.jsonl"
    return len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.exists() else 0


class _Pair:
    """Two identical fixture roots: one finalized fully, one incrementally."""

    def __init__(self, tmp):
        self.full = Path(tmp) / "full"
        self.inc = Path(tmp) / "inc"
        for root in (self.full, self.inc):
            _build_root(root)

    def folders(self, root):
        return sorted((root / "snapshots").iterdir())

    def run_full(self, gamma):
        with mock.patch.object(settlement_ledger, "fetch_gamma_event", gamma):
            return finalize_folders(
                self.folders(self.full),
                daily_summary_path=self.full / "daily.csv",
                labels_csv=self.full / "labels.csv",
                reconcile_polymarket=True,
                ledger_root=self.full / "ledger",
            )

    def run_inc(self, gamma, **kwargs):
        kwargs.setdefault("today", TODAY)
        with mock.patch.object(settlement_ledger, "fetch_gamma_event", gamma):
            return incremental.finalize_incrementally(
                self.folders(self.inc),
                daily_summary_path=self.inc / "daily.csv",
                labels_csv=self.inc / "labels.csv",
                overrides=kwargs.pop("overrides", {}),
                interval_minutes=10.0,
                gap_tolerance=1.5,
                ledger_root=self.inc / "ledger",
                **kwargs,
            )

    def both(self, relative, mutate):
        for root in (self.full, self.inc):
            mutate(root / relative)


class IncrementalFinalizeEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pair = _Pair(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def assert_equivalent(self):
        self.assertEqual(
            _csv_rows(self.pair.full / "labels.csv"),
            _csv_rows(self.pair.inc / "labels.csv"),
        )

    def test_first_run_matches_full_and_second_run_reuses_without_gamma(self):
        self.pair.run_full(_Gamma())
        first_gamma = _Gamma()
        labels, plan = self.pair.run_inc(first_gamma)
        self.assertEqual(plan["finalized_folder_count"], 3)
        self.assertEqual(plan["refinalize_reasons"], {"not_indexed": 3})
        self.assertEqual(len(first_gamma.calls), 3)
        self.assert_equivalent()

        revisions = _ledger_revisions(self.pair.inc)
        self.pair.run_full(_Gamma())
        gamma = _Gamma()
        labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [])
        self.assertEqual(plan["finalized_folder_count"], 0)
        self.assertEqual(plan["reused_folder_count"], 3)
        self.assertEqual(len(labels), 3)
        self.assertEqual(_ledger_revisions(self.pair.inc), revisions)
        self.assert_equivalent()
        # The volatile set is exactly what a full rerun rewrites: the full
        # side appended one revision per folder, the incremental side none.
        self.assertEqual(_ledger_revisions(self.pair.full), 2 * revisions)

    def test_changed_tape_refinalizes_only_that_folder(self):
        self.pair.run_full(_Gamma())
        self.pair.run_inc(_Gamma())
        slug = _slug(DATES[1])
        self.pair.both(
            Path("snapshots") / slug,
            lambda folder: _write_tape(folder, DATES[1], high=27.0),
        )
        self.pair.run_full(_Gamma())
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [slug])
        self.assertEqual(plan["refinalize_reasons"], {"inputs_changed": 1})
        self.assert_equivalent()

    def test_late_wu_correction_refinalizes_and_changes_the_bucket(self):
        self.pair.run_full(_Gamma())
        self.pair.run_inc(_Gamma())

        def correct(path):
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    f"{DATES[0].isoformat()},24,25", f"{DATES[0].isoformat()},24,26"
                ),
                encoding="utf-8",
            )

        self.pair.both(Path("daily.csv"), correct)
        self.pair.run_full(_Gamma())
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [_slug(DATES[0])])
        rows = {row["event_slug"]: row for row in _csv_rows(self.pair.inc / "labels.csv")}
        self.assertEqual(rows[_slug(DATES[0])]["settlement_bucket"], "26")
        self.assertEqual(rows[_slug(DATES[1])]["settlement_bucket"], "25")
        self.assert_equivalent()

    def test_unresolved_reconciliation_is_refetched_until_terminal(self):
        open_slug = _slug(DATES[2])
        gamma = _Gamma()
        gamma.open_slugs.add(open_slug)
        self.pair.run_full(gamma)
        self.pair.run_inc(gamma)
        gamma.calls.clear()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [open_slug])
        self.assertEqual(plan["refinalize_reasons"], {"reconciliation_not_terminal": 1})
        gamma.open_slugs.clear()
        self.pair.run_full(gamma)
        self.pair.run_inc(gamma)
        gamma.calls.clear()
        self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [])
        self.assert_equivalent()

    def test_forced_full_refinalizes_everything_and_matches_direct_run(self):
        self.pair.run_inc(_Gamma())
        self.pair.run_full(_Gamma())
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma, force_full=True)
        self.pair.run_full(_Gamma())
        self.assertEqual(plan["mode"], "full")
        self.assertEqual(plan["refinalize_reasons"], {"forced_full": 3})
        self.assertEqual(len(gamma.calls), 3)
        self.assert_equivalent()

    def test_logic_version_change_refinalizes_everything(self):
        self.pair.run_inc(_Gamma())
        gamma = _Gamma()
        with mock.patch.object(incremental, "INCREMENTAL_FINALIZE_LOGIC_VERSION", 999):
            _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(plan["refinalize_reasons"], {"inputs_changed": 3})
        self.assertEqual(len(gamma.calls), 3)

    def test_sidecar_written_by_another_path_is_refinalized(self):
        self.pair.run_inc(_Gamma())
        folder = self.pair.inc / "snapshots" / _slug(DATES[0])
        with mock.patch.object(settlement_ledger, "fetch_gamma_event", _Gamma()):
            # A direct one-folder finalize (e.g. --folders) writes a new revision.
            finalize_folders(
                [folder],
                daily_summary_path=self.pair.inc / "daily.csv",
                labels_csv=self.pair.inc / "other.csv",
                reconcile_polymarket=True,
                ledger_root=self.pair.inc / "ledger",
            )
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(plan["refinalize_reasons"], {"sidecar_revision_changed": 1})
        self.assertEqual(gamma.calls, [_slug(DATES[0])])

    def test_recheck_window_boundary(self):
        self.pair.run_inc(_Gamma())
        # DATES[2] is exactly recheck_days old: inside the window.
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma, today=DATES[2] + timedelta(days=3), recheck_days=3)
        self.assertEqual(gamma.calls, [_slug(DATES[2])])
        self.assertEqual(plan["refinalize_reasons"], {"inside_recheck_window": 1})
        # One day later it is outside the window and reused.
        gamma = _Gamma()
        self.pair.run_inc(gamma, today=DATES[2] + timedelta(days=4), recheck_days=3)
        self.assertEqual(gamma.calls, [])

    def test_override_always_refinalizes(self):
        self.pair.run_inc(_Gamma())
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma, overrides={_slug(DATES[1]): 24})
        self.assertEqual(gamma.calls, [_slug(DATES[1])])
        self.assertEqual(plan["refinalize_reasons"], {"override_applies": 1})

    def test_failure_merges_csv_and_leaves_failed_folder_unindexed(self):
        self.pair.run_inc(_Gamma(), force_full=True)
        failing = _slug(DATES[0])
        real = settlement_ledger.finalize_folder

        def flaky(folder, **kwargs):
            if Path(folder).name == failing:
                raise ValueError("boom")
            return real(folder, **kwargs)

        with mock.patch.object(settlement_ledger, "finalize_folder", flaky):
            with self.assertRaises(FolderFinalizationError):
                self.pair.run_inc(_Gamma(), force_full=True)
        index = incremental.read_finalize_index(incremental.finalize_index_path(self.pair.inc / "labels.csv"))
        self.assertNotIn(failing, index)
        self.assertEqual(len(index), 2)
        rows = {row["event_slug"] for row in _csv_rows(self.pair.inc / "labels.csv")}
        self.assertEqual(rows, {_slug(day) for day in DATES})
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [failing])
        self.assertEqual(plan["refinalize_reasons"], {"not_indexed": 1})


class FinalizeStepModeTests(unittest.TestCase):
    def _args(self, root, **overrides):
        values = {
            "folders": [],
            "snapshots_root": str(root / "snapshots"),
            "daily_summary": str(root / "daily.csv"),
            "labels_csv": str(root / "labels.csv"),
            "ledger_root": str(root / "ledger"),
            "settle": [],
            "interval_minutes": 10.0,
            "tolerance": 1.5,
            "skip_polymarket_reconciliation": False,
            "finalize_full": False,
            "finalize_recheck_days": 0,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_default_step_is_incremental_and_explicit_folders_stay_direct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_root(root)
            with mock.patch.object(settlement_ledger, "fetch_gamma_event", _Gamma()):
                first = run_market_day_labels_finalize(self._args(root))
                second = run_market_day_labels_finalize(self._args(root))
                direct = run_market_day_labels_finalize(
                    self._args(root, folders=[str(root / "snapshots" / _slug(DATES[0]))])
                )
                no_reconcile = run_market_day_labels_finalize(
                    self._args(root, skip_polymarket_reconciliation=True)
                )
        self.assertEqual(first["finalize_mode"], "incremental")
        self.assertEqual(first["label_count"], 3)
        self.assertEqual(second["finalize_plan"]["reused_folder_count"], 3)
        self.assertEqual(second["label_count"], 3)
        self.assertEqual(second["quality_counts"], first["quality_counts"])
        self.assertEqual(second["reconciliation_counts"], {"match": 3})
        self.assertEqual(direct["finalize_mode"], "direct")
        self.assertEqual(no_reconcile["finalize_mode"], "direct")


if __name__ == "__main__":
    unittest.main()
