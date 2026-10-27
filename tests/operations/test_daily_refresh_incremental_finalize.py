"""Incremental market-day label finalization equals a full run on fixtures.

Guards: the Stage-A 11:55 deadline overrun (market_day_labels_finalize re-finalized
every settled folder with one Gamma GET each); incremental mode must write the same
settlement content as the full ``finalize_folders`` run and re-finalize on any input,
logic, reconciliation or sidecar change. Kills: a reuse predicate that ignores the
tape, the target-date daily-summary row, the logic key, a non-terminal reconciliation,
an override, the recheck-window boundary, or a sidecar rewritten by another path.
Under ``--label-rule venue`` (Lane A4) the same equivalence holds against the direct
venue finalize; a changed venue row, rule version, station config, cutover or rule
switch re-finalizes exactly the post-cutover folders it affects, pre-cutover folders
keep their WU key, and the venue refusals are re-decided every run.
"""

import csv
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from weather.backtesting import settlement_ledger
from weather.backtesting.settlement_ledger import FolderFinalizationError, finalize_folders
from weather.market.market_registry import MarketSpec
from weather.operations import daily_refresh_incremental_finalize as incremental
from weather.operations import daily_refresh_source_steps
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


def _event(label, closed=True, resolved=None):
    resolved = closed if resolved is None else resolved
    return {
        "closed": closed,
        "markets": [{
            "groupItemTitle": label,
            "closed": closed,
            "umaResolutionStatus": "resolved" if resolved else "",
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["1", "0"] if resolved else ["0.6", "0.4"]),
        }],
    }


class _Gamma:
    """Counting Gamma stub; ``open_slugs`` answer as an unresolved event and
    ``provisional_slugs`` as closed but not yet UMA-resolved (0.6/0.4)."""

    def __init__(self):
        self.calls = []
        self.open_slugs = set()
        self.provisional_slugs = set()

    def __call__(self, slug, timeout=10):
        self.calls.append(slug)
        if slug in self.provisional_slugs:
            return _event("25 C", closed=True, resolved=False)
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
                ledger_root=kwargs.pop("ledger_root", self.inc / "ledger"),
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

    def test_closed_but_unresolved_match_is_provisional(self):
        # settlement_ledger admits a winner on closed + Yes > 0.5, so a closed
        # event with an empty umaResolutionStatus priced 0.6/0.4 reads "match".
        slug = _slug(DATES[1])
        gamma = _Gamma()
        gamma.provisional_slugs.add(slug)
        self.pair.run_inc(gamma)
        sidecar = json.loads(
            (self.pair.inc / "snapshots" / slug / "settlement.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sidecar["reconciliation_status"], "match")
        self.assertIs(sidecar["polymarket_reconciliation"]["event_closed"], True)
        gamma.calls.clear()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [slug])
        self.assertEqual(plan["refinalize_reasons"], {"reconciliation_not_terminal": 1})
        gamma.provisional_slugs.clear()
        self.pair.run_inc(gamma)
        gamma.calls.clear()
        self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [])

    def _ledger(self):
        return self.pair.inc / "ledger" / "toronto" / "ledger.jsonl"

    def test_truncated_ledger_refinalizes_the_lost_revision(self):
        self.pair.run_inc(_Gamma())
        ledger = self._ledger()
        lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
        lost = json.loads(lines[-1])["event_slug"]
        ledger.write_text("".join(lines[:-1]), encoding="utf-8")
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [lost])
        self.assertEqual(plan["refinalize_reasons"], {"ledger_disagrees": 1})

    def test_missing_ledger_refinalizes_everything(self):
        self.pair.run_inc(_Gamma())
        self._ledger().unlink()
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(len(gamma.calls), 3)
        self.assertEqual(plan["refinalize_reasons"], {"ledger_disagrees": 3})

    def test_different_ledger_root_refinalizes_everything(self):
        self.pair.run_inc(_Gamma())
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma, ledger_root=self.pair.inc / "other_ledger")
        self.assertEqual(len(gamma.calls), 3)
        self.assertEqual(plan["refinalize_reasons"], {"inputs_changed": 3})

    def test_hand_edited_sidecar_refinalizes(self):
        self.pair.run_inc(_Gamma())
        folder = self.pair.inc / "snapshots" / _slug(DATES[0])
        path = folder / "settlement.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        # A plain edit keeps the recorded revision id and label hash.
        edited = dict(original, settlement_bucket="99")
        path.write_text(json.dumps(edited), encoding="utf-8")
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [_slug(DATES[0])])
        self.assertEqual(plan["refinalize_reasons"], {"ledger_disagrees": 1})
        # An edit that also re-stamps a self-consistent label_hash still
        # disagrees with the ledger row.
        restored = json.loads(path.read_text(encoding="utf-8"))
        forged = dict(restored, settlement_bucket="99")
        forged["label_hash"] = settlement_ledger._canonical_sha256(
            settlement_ledger._label_payload(forged)
        )
        path.write_text(json.dumps(forged), encoding="utf-8")
        index_path = incremental.finalize_index_path(self.pair.inc / "labels.csv")
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["folders"][_slug(DATES[0])]["label_hash"] = forged["label_hash"]
        index_path.write_text(json.dumps(index), encoding="utf-8")
        gamma = _Gamma()
        _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [_slug(DATES[0])])
        self.assertEqual(plan["refinalize_reasons"], {"ledger_disagrees": 1})

    def test_byte_identical_tape_rewrite_is_reused(self):
        self.pair.run_inc(_Gamma())
        tape = self.pair.inc / "snapshots" / _slug(DATES[0]) / "snapshots_long.csv"
        before = tape.stat().st_mtime_ns
        tape.write_bytes(tape.read_bytes())
        os.utime(tape, ns=(before + 10**9, before + 10**9))
        hashed = []
        real = settlement_ledger.file_sha256

        def counting(path):
            hashed.append(Path(path).name)
            return real(path)

        gamma = _Gamma()
        with mock.patch.object(settlement_ledger, "file_sha256", counting):
            _labels, plan = self.pair.run_inc(gamma)
        self.assertEqual(gamma.calls, [])
        self.assertEqual(plan["reused_folder_count"], 3)
        # Only the touched tape was re-hashed; the others took the stat fast path.
        self.assertEqual(hashed, ["snapshots_long.csv"])
        index = incremental.read_finalize_index(
            incremental.finalize_index_path(self.pair.inc / "labels.csv")
        )
        self.assertEqual(index[_slug(DATES[0])]["tape_stat"]["mtime_ns"], before + 10**9)

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


VENUE_TODAY = date(2026, 11, 30)
PRE_CUTOVER = (date(2026, 10, 21), date(2026, 10, 22))
POST_CUTOVER = (date(2026, 10, 23), date(2026, 10, 24))
VENUE_DATES = PRE_CUTOVER + POST_CUTOVER
VENUE_HEADER = (
    "local_date,row_count,max_temp,max_temp_bucket,max_temp_times,"
    "label_source,label_station,label_station_basis,label_rule_version\n"
)


def _venue_slug(day):
    return f"highest-temperature-in-toronto-on-october-{day.day}-{day.year}"


def _venue_row(day, *, row_count=24, bucket=25, basis="registry"):
    return f"{day.isoformat()},{row_count},{bucket}.0,{bucket},15:00,metar_routine,CYYZ,{basis},venue-metar-routine-v1\n"


class VenueIncrementalFinalizeTests(unittest.TestCase):
    """``--label-rule venue`` through the incremental step (Lane A4).

    Two fixture roots share one WU daily summary: ``inc`` runs the scheduled
    incremental step, ``full`` the direct ``finalize_with_venue_labels`` path
    (an explicit folder list), which re-finalizes everything every run.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        wu_root = tmp / "wunderground"
        wu_summary = wu_root / "cyyz" / "daily" / "daily_summary.csv"
        wu_summary.parent.mkdir(parents=True)
        wu_summary.write_text(
            "local_date,row_count,max_temp_bucket_c\n"
            + "".join(f"{day.isoformat()},24,25\n" for day in VENUE_DATES),
            encoding="utf-8",
        )
        self.wu_summary = wu_summary
        patcher = mock.patch.object(
            MarketSpec,
            "data_root",
            property(lambda spec: wu_root / spec.icao.lower()),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.roots = {}
        for name in ("inc", "full"):
            root = tmp / name
            for day in VENUE_DATES:
                folder = root / "snapshots" / _venue_slug(day)
                folder.mkdir(parents=True)
                _write_tape(folder, day)
            self.roots[name] = root
            self.write_venue(name, "".join(_venue_row(day) for day in POST_CUTOVER))

    def tearDown(self):
        self._tmp.cleanup()

    def venue_csv(self, name):
        return self.roots[name] / "venue" / "toronto" / "daily" / "daily_summary.csv"

    def write_venue(self, name, rows):
        path = self.venue_csv(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(VENUE_HEADER + rows, encoding="utf-8")

    def args(self, name, *, label_rule="venue", explicit=False, **overrides):
        root = self.roots[name]
        values = {
            "folders": sorted(str(p) for p in (root / "snapshots").iterdir()) if explicit else [],
            "snapshots_root": str(root / "snapshots"),
            "daily_summary": "",
            "labels_csv": str(root / "labels.csv"),
            "ledger_root": str(root / "ledger"),
            "settle": [],
            "interval_minutes": 10.0,
            "tolerance": 1.5,
            "skip_polymarket_reconciliation": False,
            "finalize_full": False,
            "finalize_recheck_days": 3,
            "label_rule": label_rule,
            "venue_labels_root": str(root / "venue"),
            "venue_metar_root": str(root / "metar"),
            "skip_venue_label_build": True,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def run_step(self, name, gamma=None, **kwargs):
        gamma = gamma or _Gamma()
        # Discovery skips dates the real clock has not settled; the fixture
        # dates are fixed, so pin the default discovered set to the fixtures.
        discovered = sorted((self.roots[name] / "snapshots").iterdir())
        with mock.patch.object(settlement_ledger, "fetch_gamma_event", gamma), \
                mock.patch.object(incremental, "datetime", _FixedDatetime), \
                mock.patch.object(
                    daily_refresh_source_steps, "discover_default_folders", return_value=discovered
                ):
            return run_market_day_labels_finalize(self.args(name, **kwargs))

    def run_full(self):
        result = self.run_step("full", explicit=True)
        self.assertEqual(result["finalize_mode"], "direct")
        return result

    def assert_equivalent(self):
        self.assertEqual(
            _csv_rows(self.roots["full"] / "labels.csv"),
            _csv_rows(self.roots["inc"] / "labels.csv"),
        )

    def index(self):
        return incremental.read_finalize_index(
            incremental.finalize_index_path(self.roots["inc"] / "labels.csv")
        )

    def sidecar(self, day):
        path = self.roots["inc"] / "snapshots" / _venue_slug(day) / "settlement.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_incremental_matches_full_and_second_run_reuses_everything(self):
        self.run_full()
        gamma = _Gamma()
        first = self.run_step("inc", gamma)
        self.assertEqual(first["finalize_mode"], "incremental")
        self.assertEqual(first["label_rule"], "venue")
        self.assertEqual(first["finalize_plan"]["refinalize_reasons"], {"not_indexed": 4})
        self.assertEqual(first["finalize_plan"]["refused_folder_count"], 0)
        self.assertEqual(len(gamma.calls), 4)
        self.assert_equivalent()
        # Pre-cutover folders label from WU, post-cutover from the venue CSV.
        self.assertEqual(Path(self.sidecar(PRE_CUTOVER[0])["daily_summary_path"]), self.wu_summary)
        self.assertEqual(
            Path(self.sidecar(POST_CUTOVER[0])["daily_summary_path"]), self.venue_csv("inc")
        )

        self.run_full()
        gamma = _Gamma()
        second = self.run_step("inc", gamma)
        self.assertEqual(gamma.calls, [])
        self.assertEqual(second["finalize_plan"]["reused_folder_count"], 4)
        self.assertEqual(second["finalize_plan"]["finalized_folder_count"], 0)
        self.assertEqual(second["label_count"], 4)
        self.assert_equivalent()

    def test_post_cutover_key_carries_the_venue_inputs_and_pre_cutover_key_is_the_wu_key(self):
        self.run_step("inc")
        index = self.index()
        venue_key = index[_venue_slug(POST_CUTOVER[0])]["key"]["venue_label"]
        self.assertEqual(venue_key["label_rule"], "venue")
        self.assertEqual(venue_key["label_rule_version"], "venue-metar-routine-v1")
        self.assertEqual(venue_key["cutover_date"], "2026-10-23")
        self.assertEqual(
            venue_key["station_config_sha256"],
            settlement_ledger.file_sha256(incremental.venue_rule_labels.DEFAULT_STATION_CONFIG),
        )
        self.assertIsNotNone(venue_key["venue_row_sha256"])
        self.assertEqual(venue_key["complete_day_min_rows"], settlement_ledger.COMPLETE_DAY_MIN_ROWS)
        for day in PRE_CUTOVER:
            self.assertNotIn("venue_label", index[_venue_slug(day)]["key"])

    def test_changed_venue_row_refinalizes_only_that_folder(self):
        self.run_step("inc")
        self.run_full()
        changed = POST_CUTOVER[1]
        # A provenance-only change (the bucket is unchanged) still re-finalizes;
        # an appended row for an unrelated date does not.
        rows = (
            _venue_row(POST_CUTOVER[0])
            + _venue_row(changed, basis="config_override")
            + _venue_row(date(2026, 10, 25))
        )
        for name in ("inc", "full"):
            self.write_venue(name, rows)
        self.run_full()
        gamma = _Gamma()
        result = self.run_step("inc", gamma)
        self.assertEqual(gamma.calls, [_venue_slug(changed)])
        self.assertEqual(result["finalize_plan"]["refinalize_reasons"], {"inputs_changed": 1})
        self.assert_equivalent()

        bucket_change = _venue_row(POST_CUTOVER[0], bucket=26) + _venue_row(changed, basis="config_override")
        for name in ("inc", "full"):
            self.write_venue(name, bucket_change)
        self.run_full()
        gamma = _Gamma()
        self.run_step("inc", gamma)
        self.assertEqual(gamma.calls, [_venue_slug(POST_CUTOVER[0])])
        self.assertEqual(self.sidecar(POST_CUTOVER[0])["settlement_bucket"], 26)
        self.assert_equivalent()

    def test_rule_switch_invalidates_post_cutover_folders_only(self):
        self.run_step("inc", label_rule="wu")
        wu_index = self.index()
        gamma = _Gamma()
        result = self.run_step("inc", gamma)
        self.assertEqual(sorted(gamma.calls), sorted(_venue_slug(day) for day in POST_CUTOVER))
        self.assertEqual(result["finalize_plan"]["refinalize_reasons"], {"inputs_changed": 2})
        self.assertEqual(result["finalize_plan"]["reused_folder_count"], 2)
        venue_index = self.index()
        for day in PRE_CUTOVER:
            # Pre-cutover reuse is unaffected: same key, same revision.
            self.assertEqual(venue_index[_venue_slug(day)], wu_index[_venue_slug(day)])

        gamma = _Gamma()
        result = self.run_step("inc", gamma, label_rule="wu")
        self.assertEqual(sorted(gamma.calls), sorted(_venue_slug(day) for day in POST_CUTOVER))
        self.assertEqual(result["finalize_plan"]["refinalize_reasons"], {"inputs_changed": 2})
        self.assertEqual(Path(self.sidecar(POST_CUTOVER[0])["daily_summary_path"]), self.wu_summary)

    def test_rule_version_station_config_and_cutover_changes_refinalize_post_cutover(self):
        self.run_step("inc")
        post = sorted(_venue_slug(day) for day in POST_CUTOVER)

        with mock.patch.object(incremental.venue_rule_labels, "VENUE_RULE_VERSION", "venue-v-next"):
            gamma = _Gamma()
            self.run_step("inc", gamma)
        self.assertEqual(sorted(gamma.calls), post)

        self.run_step("inc")  # back to the real version: re-finalizes once more
        config = Path(self._tmp.name) / "stations.json"
        config.write_text('{"schema_version": "venue-rule-stations-v1", "markets": {}}', encoding="utf-8")
        with mock.patch.object(incremental.venue_rule_labels, "DEFAULT_STATION_CONFIG", config):
            gamma = _Gamma()
            result = self.run_step("inc", gamma)
        self.assertEqual(sorted(gamma.calls), post)
        self.assertEqual(result["finalize_plan"]["refinalize_reasons"], {"inputs_changed": 2})

        self.run_step("inc")
        with mock.patch.object(
            incremental.venue_rule_labels, "VENUE_RULE_CUTOVER_DATE", POST_CUTOVER[1]
        ):
            gamma = _Gamma()
            self.run_step("inc", gamma)
        # 10-23 is now labelled from WU (new path) and 10-24's key names the new cutover.
        self.assertEqual(sorted(gamma.calls), post)

    def test_finalize_full_forces_a_full_rebuild(self):
        self.run_step("inc")
        gamma = _Gamma()
        result = self.run_step("inc", gamma, finalize_full=True)
        self.assertEqual(result["finalize_mode"], "full")
        self.assertEqual(result["finalize_plan"]["refinalize_reasons"], {"forced_full": 4})
        self.assertEqual(len(gamma.calls), 4)
        self.run_full()
        self.assert_equivalent()

    def test_refusals_are_unchanged_and_never_reused(self):
        self.run_step("inc")
        thin, missing = POST_CUTOVER
        self.write_venue("inc", _venue_row(thin, row_count=5))
        before = self.sidecar(thin)
        gamma = _Gamma()
        with self.assertRaises(FolderFinalizationError) as raised:
            self.run_step("inc", gamma)
        reasons = dict(raised.exception.failures)
        self.assertIn("has 5 reports, fewer than 18", reasons[str(self.roots["inc"] / "snapshots" / _venue_slug(thin))])
        self.assertIn("no venue-rule label row for 2026-10-24", reasons[str(self.roots["inc"] / "snapshots" / _venue_slug(missing))])
        self.assertEqual(gamma.calls, [])
        self.assertEqual(self.sidecar(thin), before)
        index = self.index()
        self.assertEqual(sorted(index), sorted(_venue_slug(day) for day in PRE_CUTOVER))
        rows = {row["event_slug"] for row in _csv_rows(self.roots["inc"] / "labels.csv")}
        self.assertEqual(rows, {_venue_slug(day) for day in VENUE_DATES})

        self.venue_csv("inc").unlink()
        result = self.run_step("inc")
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "venue_rule_labels_unavailable")

        result = self.run_step("inc", daily_summary=str(self.wu_summary))
        self.assertEqual(result, {"status": "BLOCK", "reason": "daily_summary_override_with_venue_label_rule"})


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(VENUE_TODAY.year, VENUE_TODAY.month, VENUE_TODAY.day, 12, 0, tzinfo=tz)


if __name__ == "__main__":
    unittest.main()
