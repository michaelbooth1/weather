"""Synthetic tests for the C2/C3 pre-read guard. No real data is read."""
from __future__ import annotations

import gzip
import json

import pytest

from tools.research.released_window import c23_preread_guard as guard
from weather.market.market_registry import REGISTRY

MONTHS = {9: "september", 10: "october"}


def slug(market, month, day):
    return f"{REGISTRY[market].slug_prefix}-{MONTHS[month]}-{day}-2026"


def make_root(tmp_path, days=("2026-10-14",), folders=(("nyc", 10, 14),), ledger=None):
    root = tmp_path / "data"
    for day in days:
        (root / "maker_evidence" / day / "00-0123456789ab").mkdir(parents=True)
        (root / "maker_evidence" / day / "00-0123456789ab" / "manifest.json").write_text("{}", encoding="utf-8")
    for market, month, day in folders:
        (root / "snapshots" / slug(market, month, day)).mkdir(parents=True)
    (root / "snapshots").mkdir(parents=True, exist_ok=True)
    (root / "snapshots" / "observation_triggers.jsonl").write_text("", encoding="utf-8")
    for market, rows in (ledger or {}).items():
        path = root / "settlements" / market / "ledger.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return root


def row(market, month, day, **extra):
    return {"event_slug": slug(market, month, day), "market_id": market, **extra}


# ----------------------------------------------------------------------------- boundary: 10-14 passes

def test_boundary_10_14_passes_everywhere(tmp_path):
    root = make_root(tmp_path, days=("2026-09-23", "2026-10-14"),
                     folders=(("nyc", 10, 14), ("toronto", 10, 14), ("austin", 10, 2), ("austin", 10, 4)),
                     ledger={"nyc": [row("nyc", 10, 14), row("nyc", 10, 14, revision=2)],
                             "austin": [row("austin", 10, 2), row("austin", 10, 4)]})
    summary = guard.run(root)
    assert summary["verdict"] == "PASS"
    assert summary["days"] == ["2026-09-23", "2026-10-14"]
    assert summary["segments"] == 2
    assert summary["slug_folders"] == 4
    assert summary["ledger_rows"] == 4
    assert summary["sealed_segments_opened"] is False


def test_missing_roots_pass_empty(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    summary = guard.run(root)
    assert (summary["days"], summary["slug_folders"], summary["ledger_rows"]) == ([], 0, 0)


# ----------------------------------------------------------------------------- 10-15 refuses

def test_maker_evidence_10_15_refuses(tmp_path):
    root = make_root(tmp_path, days=("2026-10-14", "2026-10-15"))
    with pytest.raises(guard.Refused, match=r"maker_evidence/2026-10-15 is embargoed"):
        guard.run(root)


def test_maker_evidence_later_day_refuses(tmp_path):
    root = make_root(tmp_path, days=("2026-11-02",))
    with pytest.raises(guard.Refused, match="embargoed"):
        guard.run(root)


def test_slug_folder_10_15_refuses(tmp_path):
    root = make_root(tmp_path, folders=(("nyc", 10, 14), ("seattle", 10, 15)))
    with pytest.raises(guard.Refused, match=r"target 2026-10-15 is embargoed"):
        guard.run(root)


def test_ledger_row_10_15_refuses(tmp_path):
    root = make_root(tmp_path, ledger={"nyc": [row("nyc", 10, 14), row("nyc", 10, 15)]})
    with pytest.raises(guard.Refused, match=r"ledger.jsonl line 2: target 2026-10-15 is embargoed"):
        guard.run(root)


def test_ledger_row_10_15_by_target_date_refuses(tmp_path):
    root = make_root(tmp_path, ledger={"nyc": [{"market_id": "nyc", "target_date": "2026-10-15"}]})
    with pytest.raises(guard.Refused, match="embargoed"):
        guard.run(root)


def test_gz_ledger_is_checked(tmp_path):
    root = make_root(tmp_path)
    path = root / "settlements" / "nyc" / "ledger.jsonl.gz"
    path.parent.mkdir(parents=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps(row("nyc", 10, 15)) + "\n")
    with pytest.raises(guard.Refused, match="embargoed"):
        guard.run(root)


# ----------------------------------------------------------------------------- Austin 10-03 refuses

def test_austin_10_03_slug_folder_refuses(tmp_path):
    root = make_root(tmp_path, folders=(("austin", 10, 3),))
    with pytest.raises(guard.Refused, match=r"excluded market-day austin 2026-10-03"):
        guard.run(root)


def test_austin_10_03_ledger_row_refuses(tmp_path):
    root = make_root(tmp_path, ledger={"austin": [row("austin", 10, 2), row("austin", 10, 3)]})
    with pytest.raises(guard.Refused, match=r"line 2: excluded market-day austin 2026-10-03"):
        guard.run(root)


def test_austin_10_03_ledger_row_by_target_date_refuses(tmp_path):
    root = make_root(tmp_path, ledger={"austin": [{"market_id": "austin", "target_date": "2026-10-03"}]})
    with pytest.raises(guard.Refused, match="excluded market-day"):
        guard.run(root)


# ----------------------------------------------------------------------------- negations

@pytest.mark.parametrize(("market", "month", "day"), [
    ("nyc", 10, 3),        # another market on 10-03
    ("austin", 10, 2),     # Austin the day before
    ("austin", 10, 4),     # Austin the day after
    ("austin", 9, 30),     # Austin in another month
    ("toronto", 10, 3),    # the twelfth market on 10-03
])
def test_not_austin_10_03_passes(tmp_path, market, month, day):
    root = make_root(tmp_path, folders=((market, month, day),), ledger={market: [row(market, month, day)]})
    assert guard.run(root)["verdict"] == "PASS"


@pytest.mark.parametrize("day", ["2026-09-23", "2026-09-30", "2026-10-13", "2026-10-14"])
def test_maker_days_before_10_15_pass(tmp_path, day):
    assert guard.run(make_root(tmp_path, days=(day,)))["days"] == [day]


def test_segments_are_not_opened(tmp_path, monkeypatch):
    root = make_root(tmp_path, days=("2026-10-03",))
    (root / "maker_evidence" / "2026-10-03" / "00-0123456789ab" / "books.jsonl").write_text(
        json.dumps({"event_slug": slug("austin", 10, 3)}) + "\n", encoding="utf-8")
    opened = []
    real_open, real_path_open, real_gzip_open = open, guard.Path.open, guard.gzip.open

    def spy(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    def path_spy(self, *args, **kwargs):
        opened.append(str(self))
        return real_path_open(self, *args, **kwargs)

    def gzip_spy(path, *args, **kwargs):
        opened.append(str(path))
        return real_gzip_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy)
    monkeypatch.setattr(guard.Path, "open", path_spy)
    monkeypatch.setattr(guard.gzip, "open", gzip_spy)
    assert guard.run(root)["verdict"] == "PASS"   # ruling (a): readers drop Austin 10-03 inside segments
    assert opened                                  # the spies are live (the module's own sha read)
    assert not any("maker_evidence" in p for p in opened)


# ----------------------------------------------------------------------------- malformed inputs refuse

@pytest.mark.parametrize("name", ["latest", "2026-10-1", "2026-13-01"])
def test_non_day_maker_entry_refuses(tmp_path, name):
    root = make_root(tmp_path, days=())
    (root / "maker_evidence" / name).mkdir(parents=True)
    with pytest.raises(guard.Refused, match="not a YYYY-MM-DD day directory"):
        guard.run(root)


def test_loose_file_in_maker_evidence_refuses(tmp_path):
    root = make_root(tmp_path)
    (root / "maker_evidence" / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(guard.Refused, match="not a YYYY-MM-DD"):
        guard.run(root)


def test_unregistered_slug_folder_refuses(tmp_path):
    root = make_root(tmp_path)
    (root / "snapshots" / "highest-temperature-in-nowhere-on-october-5-2026").mkdir()
    with pytest.raises(guard.Refused, match="not a registered market's event slug"):
        guard.run(root)


def test_unparseable_ledger_row_refuses(tmp_path):
    root = make_root(tmp_path, ledger={"nyc": [{"market_id": "nyc"}]})
    with pytest.raises(guard.Refused, match="no parseable event slug or target date"):
        guard.run(root)


def test_invalid_json_ledger_line_refuses(tmp_path):
    root = make_root(tmp_path)
    path = root / "settlements" / "nyc" / "ledger.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(guard.Refused, match="not valid JSON"):
        guard.run(root)


# ----------------------------------------------------------------------------- CLI

def test_main_exit_codes_and_receipt(tmp_path, capsys):
    root = make_root(tmp_path)
    receipt = tmp_path / "receipt.json"
    assert guard.main(["--data-root", str(root), "--receipt", str(receipt)]) == 0
    assert json.loads(receipt.read_text(encoding="utf-8"))["verdict"] == "PASS"
    assert guard.main(["--data-root", str(root), "--receipt", str(receipt)]) == 2   # receipt must be new
    assert guard.main(["--data-root", str(root), "--receipt", str(root / "r.json")]) == 2   # not inside root
    bad = make_root(tmp_path / "bad", days=("2026-10-15",))
    assert guard.main(["--data-root", str(bad)]) == 2
    assert "embargoed" in capsys.readouterr().err
