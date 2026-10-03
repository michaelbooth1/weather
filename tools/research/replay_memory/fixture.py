"""Fictional 88a-shaped day bundles (exam tree on PYTHONPATH). Copied unchanged from
tools/research/pull_cap_precheck/fixture.py on codex/pull-cap-precheck-20261003 (PR #166, not merged here).

No captured market, wallet or calibration data is read; every value is invented.

Density mirrors maker_replay_bundle.export at the exam tree: one capture cycle a minute; one reward
row per selected condition per minute at its own clock (-> one terms record each); ceil(2*D/100)
books rows per cycle, each projecting book + coverage for every condition with a descriptor;
outcome views every 10 minutes (valid 1 h); public trade-stream rows at random clocks, each with a
coverage record for every condition. ``reduced=True`` keeps one record per (clock, schedule effect),
which leaves the engine's heap-timestamp set unchanged (validated against full density).
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import math
import random

from maker_core.contracts import MarketDescriptor, OutcomeView
from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.quoting.policy import Book, RewardTerms
from maker_core.replay.bundle import FORMAT, Bundle, CapturedRecord, Condition, sha256, load_bundle

HASHES = {"fictional": "0" * 64}


def day_records(day, d_inst, churn=1.0, trades=0, minutes=1440, seed=0, reduced=False, rewards="per_minute"):
    """Return (conditions, records) for one UTC day; records are plain dicts in bundle row shape."""
    rng = random.Random(f"{day}-{d_inst}-{churn}-{trades}-{seed}")
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    d_union = max(d_inst, round(d_inst * churn))
    # Slot i hosts a run of conditions back to back; extra conditions spread over the first slots.
    slots = [[] for _ in range(d_inst)]
    for k in range(d_union):
        slots[k % d_inst].append(f"c{day:%m%d}-{k:04d}")
    selected_at = {}  # cid -> (from_minute, until_minute)
    for slot in slots:
        for j, cid in enumerate(slot):
            selected_at[cid] = (minutes * j // len(slot), minutes * (j + 1) // len(slot))
    cids = sorted(selected_at)
    conditions = [dict(condition_id=c, market_id=f"city{int(c[-4:]) % 12:02d}", domain_id="fictional",
                       active_from=start.isoformat(), active_until=end.isoformat()) for c in cids]
    records = []

    def add(cid, kind, at, payload):
        payload = plain(payload)
        records.append(dict(sequence=len(records), captured_at=at.isoformat(), condition_id=cid, kind=kind,
                            payload=payload, payload_sha256=sha256(canonical_bytes(payload)),
                            source_hashes=HASHES))

    def descriptor(cid):
        return MarketDescriptor("fictional", "event-" + cid, cid, {"YES": cid + "-y", "NO": cid + "-n"},
                                D(".01"), D(20), None, end + timedelta(days=1), end + timedelta(days=1, minutes=1),
                                None, "fixture", {"fixture": "0" * 64})

    seen, last_book, last_terms, last_view = set(), {}, {}, {}
    stream = sorted(start + timedelta(microseconds=rng.randrange(minutes * 60 * 10**6)) for _ in range(trades))
    batches = max(1, math.ceil(2 * d_inst / 100))
    events = []
    for minute in range(minutes):
        base = start + timedelta(seconds=minute * 60, microseconds=250_000 + rng.randrange(500_000))
        active = [c for c in cids if selected_at[c][0] <= minute < selected_at[c][1]]
        for i, cid in enumerate(active):
            if rewards == "per_minute" or (rewards == "hourly" and minute % 60 == 0):
                events.append((base + timedelta(seconds=1, microseconds=15_000 * i + rng.randrange(10_000)),
                               "reward", cid))
        for k in range(batches):
            batch = [c for j, c in enumerate(active) if j * 2 // 100 == k]
            events.append((base + timedelta(seconds=3, microseconds=400_000 * k + rng.randrange(100_000)),
                           "books", batch))
    for at in stream:
        events.append((at, "trade", None))
    events.sort(key=lambda e: e[0])
    for at, kind, value in events:
        if kind == "reward":
            terms = RewardTerms(at, D(20), D(5), D(100))
            last_terms[value] = terms
            if value in seen:
                add(value, "terms", at, terms)
        elif kind == "books":
            for cid in value:
                last_book[cid] = at
            projected = [c for c in cids if c in last_book]
            booked = set()  # reduced: one book per distinct as_of clock, the only schedule effect
            for n, cid in enumerate(projected):
                if cid not in seen:
                    seen.add(cid)
                    add(cid, "descriptor", at, dict(market=plain(descriptor(cid)), horizon_days=1))
                    add(cid, "info_event", at, {"events": []})
                    if cid in last_terms:
                        add(cid, "terms", at, last_terms[cid])
                as_of = last_book[cid]
                if not reduced or as_of not in booked:
                    booked.add(as_of)
                    add(cid, "book", at, Book(as_of, ((D(".49"), D(75)),), ((D(".51"), D(75)),),
                                              ((D(".49"), D(75)),), ((D(".51"), D(75)),)))
                if last_view.get(cid) is None or at - last_view[cid] >= timedelta(minutes=10):
                    last_view[cid] = at
                    view = OutcomeView(cid, .5, .015, None, at, at + timedelta(hours=1),
                                       sha256(canonical_bytes({"at": at.isoformat()})), "synthetic", "none")
                    add(cid, "outcome_view", at, dict(available=True, value=plain(view)))
                if not (reduced and n):
                    add(cid, "coverage", at, dict(trade_stream_ok=True, valid_until_utc=at + timedelta(seconds=30)))
        else:
            projected = [c for c in cids if c in seen]
            if projected:
                add(projected[rng.randrange(len(projected))], "trade", at,
                    dict(trade_id=f"t{len(records)}", outcome="YES", price=".5", size="10",
                         traded_at_utc=at.isoformat(), aggressor_side="SELL"))
            for n, cid in enumerate(projected):
                if reduced and n:
                    break
                add(cid, "coverage", at, dict(trade_stream_ok=True, valid_until_utc=at + timedelta(seconds=30)))
    return conditions, records


def in_memory(day, conditions, records):
    """A Bundle without disk IO; load_bundle on the sealed files gives the same records (checked once)."""
    rows = []
    for r in records:
        rows.append(CapturedRecord(r["sequence"], datetime.fromisoformat(r["captured_at"]), r["condition_id"],
                                   r["kind"], r["payload"], r["payload_sha256"], r["source_hashes"]))
    rows.sort(key=lambda r: (r.captured_at, r.sequence))
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    conds = tuple(sorted((Condition(c["condition_id"], c["market_id"], c["domain_id"],
                                    datetime.fromisoformat(c["active_from"]), datetime.fromisoformat(c["active_until"]))
                          for c in conditions), key=lambda c: c.condition_id))
    return Bundle(day, start + timedelta(days=1), "synthetic", conds, tuple(rows), {}, 0)


def seal(root, day, conditions, records):
    root.mkdir(parents=True)
    raw = b"".join(canonical_bytes(r) for r in records)
    (root / "records.jsonl").write_bytes(raw)
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    manifest = dict(format=FORMAT, day=day.isoformat(), sealed_at=(start + timedelta(days=1)).isoformat(),
                    provenance="synthetic", conditions=conditions,
                    streams=[dict(path="records.jsonl", sha256=sha256(raw), bytes=len(raw), records=len(records))])
    (root / "bundle.json").write_bytes(canonical_bytes(manifest))
    return root
