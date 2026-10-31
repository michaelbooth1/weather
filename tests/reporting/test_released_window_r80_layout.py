"""Row 80 release layout builder: path, worktree, extract-scope and override guards (synthetic only).

Guards: P1 prep row 80 runbook section 3 (branch claude/embargo-release-export-manifest-20261031 @ 91cae102b) -
the builder refuses 88a/panel paths, any write under C:\\swarm, a non-empty --out, a harness worktree that is
not a clean 2f3f3e8e checkout, a foreign harness sha, and any extract row outside targets 10-01..10-14, the
eleven US markets or the Austin 10-03 exclusion; the boundary is the local target date (master 2026-10-31:
target 10-14 released whatever its capture time, target 10-15+ embargoed whatever its capture time); the two
dev date bounds are
overridden in process only and restored; it computes no score and imports no network module.
"""
from __future__ import annotations

import ast
import gzip
import json
import types
from pathlib import Path

import pytest

from tools.research.released_window import r80_layout as r80

MODULE = Path(r80.__file__)
NETWORK = {"socket", "requests", "urllib", "http", "httpx", "aiohttp", "ftplib", "smtplib"}


def _row(target="2026-10-05", market="nyc", unit="F", captured="2026-10-05T18:00:00+00:00"):
    return {"target_date": target, "market": market, "unit": unit, "captured_at_utc": captured}


def write_extract(root, rows=None, days=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    rows = [_row()] if rows is None else rows
    days = [{"target_date": r["target_date"], "market": r["market"], "admitted": True} for r in rows] \
        if days is None else days
    for name, items in (("guidance_rows.jsonl.gz", rows), ("market_days.jsonl.gz", days)):
        with gzip.open(root / name, "wt", encoding="utf-8") as stream:
            stream.writelines(json.dumps(x) + "\n" for x in items)
    return root


class FakeHarness(types.SimpleNamespace):
    """Stands in for tools.research.model_parity.harness at 2f3f3e8e; records the bound it saw."""

    def __init__(self, sha=r80.EXPECTED_HARNESS_SHA256, parser=r80.PARSER_HEAD):
        super().__init__(LAST_TARGET_DATE="2026-09-29", PARSER_HEAD=parser, seen=None, sha=sha)

    def harness_sha256(self):
        return self.sha

    def verify_extract(self, root):
        return {"input_path": str(root), "status": "COMPLETE"}

    def build_cache(self, root, cache, force=False):
        assert not force
        self.seen = self.LAST_TARGET_DATE
        Path(cache).mkdir(parents=True)
        receipt = {"rows_with_target_after_2026_09_29": 0}
        (Path(cache) / "cache_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        return receipt


class FakeOutcomes(types.SimpleNamespace):
    def __init__(self, dates=("2026-10-05",), harness_sha=r80.EXPECTED_HARNESS_SHA256):
        super().__init__(DEV_LAST_DATE="2026-09-29", seen=None, dates=list(dates), harness_sha=harness_sha)

    def split_v2_cache(self, out_root, cache=None):
        self.seen = self.DEV_LAST_DATE
        Path(out_root).mkdir(parents=True)
        manifest = {"schema": "harness_v3_layout/1", "source": {"harness_sha256": self.harness_sha},
                    "files": {"labels.parquet": {"sha256": "0" * 64, "rows": 1, "dates": self.dates}}}
        (Path(out_root) / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest


@pytest.mark.parametrize("path", [r"C:\t\88a\x", r"C:\t\Panel_b", "data/88A"])
def test_paths_naming_88a_or_panel_are_refused(path):
    with pytest.raises(r80.Refused, match="88a or panel"):
        r80.screen_path(path, "--out")


def test_out_dir_must_be_new_or_empty_and_outside_swarm(tmp_path):
    swarm = tmp_path / "swarm"
    with pytest.raises(r80.Refused, match="under"):
        r80.check_out_dir(swarm / "cache", swarm_root=swarm)
    full = tmp_path / "full"
    full.mkdir()
    (full / "x").write_text("x")
    with pytest.raises(r80.Refused, match="not empty"):
        r80.check_out_dir(full, swarm_root=swarm)
    assert r80.check_out_dir(tmp_path / "new", swarm_root=swarm) == tmp_path / "new"


def _runner(head, dirty=""):
    def run(cmd, **_):
        out = head if "rev-parse" in cmd else dirty
        return types.SimpleNamespace(returncode=0, stdout=out + "\n", stderr="")
    return run


def test_worktree_must_be_a_clean_checkout_of_the_pin(tmp_path):
    with pytest.raises(r80.Refused, match="HEAD"):
        r80.check_worktree(tmp_path, runner=_runner("0" * 40))
    with pytest.raises(r80.Refused, match="tracked changes"):
        r80.check_worktree(tmp_path, runner=_runner(r80.HARNESS_PIN, " M tools/research/model_parity/harness.py"))
    assert r80.check_worktree(tmp_path, runner=_runner(r80.HARNESS_PIN)) == r80.HARNESS_PIN


def test_harness_import_refuses_a_tools_package_from_another_tree(tmp_path):
    with pytest.raises(r80.Refused, match="python -I"):
        r80.load_harness(tmp_path, modules={"tools": object()})


def test_a_foreign_harness_sha_or_parser_head_is_refused():
    with pytest.raises(r80.Refused, match="harness_sha256"):
        r80.check_harness(FakeHarness(sha="f" * 64))
    with pytest.raises(r80.Refused, match="PARSER_HEAD"):
        r80.check_harness(FakeHarness(parser="abc1234"))


@pytest.mark.parametrize(("row", "message"), [
    (_row(target="2026-09-30"), "outside"),
    (_row(target="2026-10-15", captured="2026-10-14T12:00:00+00:00"), "embargoed"),
    (_row(target="2026-10-16"), "embargoed"),
    (_row(market="toronto", unit="C"), "eleven US markets"),
    (_row(target="2026-10-03", market="austin"), "excluded market-day"),
    (_row(unit="C"), "unit"),
])
def test_extract_scope_refuses_every_out_of_window_row(tmp_path, row, message):
    extract = write_extract(tmp_path / "x", rows=[_row(), row], days=[])
    with pytest.raises(r80.Refused, match=message):
        r80.check_extract_scope(extract)


def test_extract_scope_also_screens_market_days(tmp_path):
    extract = write_extract(tmp_path / "x", days=[{"target_date": "2026-10-03", "market": "austin"}])
    with pytest.raises(r80.Refused, match="market_days holds excluded"):
        r80.check_extract_scope(extract)


def test_extract_scope_accepts_the_release_window(tmp_path):
    # a 10-14 target captured on UTC 10-15 (US evening) is released: the boundary is the local target date
    rows = [_row(target="2026-10-01"), _row(target="2026-10-14", market="seattle",
                                            captured="2026-10-15T06:30:00+00:00")]
    assert r80.check_extract_scope(write_extract(tmp_path / "x", rows=rows)) == {"guidance_rows": 2,
                                                                                 "market_days": 2}


def test_overrides_are_in_process_and_restored_even_on_failure():
    h, o = FakeHarness(), FakeOutcomes()
    with pytest.raises(RuntimeError):
        with r80.release_overrides(h, o):
            assert (h.LAST_TARGET_DATE, o.DEV_LAST_DATE) == ("2026-10-14", "2026-10-14")
            raise RuntimeError("boom")
    assert (h.LAST_TARGET_DATE, o.DEV_LAST_DATE) == ("2026-09-29", "2026-09-29")


def test_build_writes_only_under_out_and_records_no_score(tmp_path):
    h, o = FakeHarness(), FakeOutcomes()
    out = tmp_path / "out"
    receipt = r80.build(write_extract(tmp_path / "x"), out, h, o, worktree_head=r80.HARNESS_PIN,
                        swarm_root=tmp_path / "swarm")
    assert (h.seen, o.seen) == ("2026-10-14", "2026-10-14")
    assert (h.LAST_TARGET_DATE, o.DEV_LAST_DATE) == ("2026-09-29", "2026-09-29")
    assert sorted(p.name for p in out.iterdir()) == ["cache", "layout", "layout_receipt.json"]
    assert receipt["layout_dates"] == ["2026-10-05"]
    assert json.loads((out / "layout_receipt.json").read_text(encoding="utf-8")) == receipt
    text = json.dumps(receipt).lower()
    assert not any(word in text for word in ("brier", "ratio", "verdict"))


@pytest.mark.parametrize(("outcomes", "message"), [
    (FakeOutcomes(dates=("2026-10-05", "2026-10-15")), "embargoed target"),
    (FakeOutcomes(dates=("2026-09-30", "2026-10-05")), "outside the window"),
    (FakeOutcomes(harness_sha="e" * 64), "source.harness_sha256"),
])
def test_build_refuses_a_layout_outside_the_rule(tmp_path, outcomes, message):
    with pytest.raises(r80.Refused, match=message):
        r80.build(write_extract(tmp_path / "x"), tmp_path / "out", FakeHarness(), outcomes,
                  swarm_root=tmp_path / "swarm")
    assert not (tmp_path / "out" / "layout_receipt.json").exists()


def test_the_module_imports_no_network_library():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & NETWORK
