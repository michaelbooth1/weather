"""Sentinel test for t2_presence_check_v1.py (master ruling 11-03, condition 2). Synthetic data only.

It plants price-like tokens in synthetic event rows and asserts that:

* no token reaches the result file or stdout;
* no event row is ever decoded: every ``json.loads`` call the checker makes on ``prices.jsonl`` content is a cycle
  record that starts with ``{"complete": ``;
* the integrity checks still pass, because event rows are hashed as raw bytes.

It also pins the checker's sha256. Run with ``python -I tools/research/test_t2_presence_check_sentinel_v1.py``; pytest
also collects ``test_sentinel``.
"""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "t2_presence_check_v1.py"
CHECKER_SHA256 = "b6e4bc83fb79e17b1014183811e116fbbc5d45ffe5e18c4461c8b45d305b6e54"
TOKENS = ("0.4242424242", "PRICE_SENTINEL_7f3a", "13.37", "BOOKSIZE_SENTINEL_9c1e")
SCHEMA_IN = "l3_t1_price_forward/1"


def _load():
    data = CHECKER.read_bytes()
    assert hashlib.sha256(data).hexdigest() == CHECKER_SHA256, "checker is not the pinned file"
    spec = importlib.util.spec_from_file_location("t2_presence_check_v1", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build(root: Path, markets, days):
    for day in days:
        d = root / f"{day:%Y%m%d}"
        d.mkdir(parents=True)
        buf = b""
        for hour in range(3):
            rows = [{"kind": "event", "schema": SCHEMA_IN, "market": m, "horizon": h, "gamma_status": "ok",
                     "ladder_complete": True, "yes_sum": float(TOKENS[2]),
                     "bands": [{"yes": float(TOKENS[0]), "label": TOKENS[1],
                                "best_bid": {"price": 0.4242424242, "size": TOKENS[3]}}]}
                    for m in markets for h in (1, 2)]
            body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
            reasons = [f"{markets[0]}+2:ladder_incomplete"] if hour == 2 else []
            cyc = {"kind": "cycle", "schema": SCHEMA_IN, "slot_utc": f"{day}T{hour:02d}:00:00Z", "top_of_hour": True,
                   "late": False, "events_expected": len(rows), "events_rows": len(rows), "complete": not reasons,
                   "reasons": reasons, "rows_sha256": hashlib.sha256(body).hexdigest()}
            buf += body + (json.dumps(cyc, sort_keys=True) + "\n").encode()
        (d / "prices.jsonl").write_bytes(buf)
        (d / "manifest.json").write_text(json.dumps(
            {"schema": SCHEMA_IN, "utc_day": day.isoformat(), "cycles": 3, "file_sha256": hashlib.sha256(buf).hexdigest(),
             "horizons": [1, 2], "markets": list(markets)}), encoding="utf-8")


def test_sentinel():
    mod = _load()
    decoded = []
    real_loads = mod.json.loads

    def spy(s, *a, **k):
        decoded.append(s if isinstance(s, (bytes, bytearray)) else s.encode("utf-8"))
        return real_loads(s, *a, **k)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "forward"
        markets = ("aaa", "bbb")
        _build(root, markets, [dt.date(2001, 2, 1), dt.date(2001, 2, 2), dt.date(2001, 2, 3)])
        mod.json.loads = spy
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = mod.main(["--root", str(root), "--out", str(Path(tmp) / "out"), "--today-utc", "2001-02-04"])
        finally:
            mod.json.loads = real_loads
        assert rc == 0, rc
        result = (Path(tmp) / "out" / "t2_presence_result.json").read_bytes()
        printed = out.getvalue().encode()
        for tok in TOKENS:
            assert tok.encode() not in result, f"token {tok} leaked to the result"
            assert tok.encode() not in printed, f"token {tok} leaked to stdout"
        for s in decoded:
            if b'"kind": "event"' in s or any(t.encode() in s for t in TOKENS):
                raise AssertionError("an event row was decoded")
        price_decodes = [s for s in decoded if b'"slot_utc"' in s]
        assert price_decodes and all(s.startswith(b'{"complete": ') for s in price_decodes)
        res = json.loads(result)
        assert res["integrity_ok"] is True
        assert res["per_day"][0]["h2_by_market"]["aaa"]["reason_codes"] == {"ladder_incomplete": 1}
        assert res["per_day"][0]["h2_by_market"]["bbb"]["complete_cycles"] == 3
    return "sentinel PASS"


if __name__ == "__main__":
    print(test_sentinel())
    sys.exit(0)
