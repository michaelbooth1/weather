"""Re-run and attribute (shadow-gate spec v3.2 §1.4, v3.3 §4.2) for the engine rulings W1(a), W2(a) and F3.

Every changed decision between the frozen engine and a ruling must trace to an allowed class, directly or as a
cascade, or the re-run fails:

- **A1** (W1): a resting leg on a YES-side level the public book lacks (created level), incl. the mid it moves;
- **A2** (W1): own size on ``no_bids``/``no_asks`` (the mirror), read by ``touch_buffer`` or the crossed check;
- **A3** (W1): own-vs-public crossed book (``CROSSED_BOOK`` on a public book that is not crossed);
- **A5** (W2): a same-instant replacement decided on the public book instead of the pre-cancel book;
- **A6** (F3): the horizon read differs from the latest captured descriptor's because a derived local-midnight
  descriptor precedes it. (A7, the reopen class, does not arise: this engine applies no reopen records.)

Variants (``VARIANTS``) switch each ruling on alone and all together; ``frozen`` reproduces the engine before
the rulings (T1 decision book, T2 replacement book, no refresh) and is pinned to the pre-fix digests by
``tests/maker_core/test_replay_v2_attribution.py``. Fictional fixtures only (``FIXTURES``); never a captured day.

    python -m tools.research.maker_replay_v2.attribution OUT.json   # through the workstation queue only
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
import sys

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import drive, run_plan
from maker_core.replay.v2.score import BandDayScorer, Books

D = Decimal
POLICIES = ("informed-v0", "blind_re1", "no_quote", "clock_only")
BOUNDS = ("strictly_through", "at_price")
HAZARD = .001


# -- the frozen books (spec v3.1 §3.7.1(b) T1, §3.7.2(b) T2) ------------------------------------------------
def frozen_book(book, legs):
    """T1: own size added only at existing levels — a YES leg on ``yes_bids`` at p, a NO leg on ``yes_asks`` at
    1 - q; ``no_bids``/``no_asks`` untouched; at one price the last leg wins. T2 is T1 of the cancelled legs."""
    def add_own(levels, outcome, mirror=False):
        additions = {leg.price if not mirror else 1 - leg.price: leg.size for leg in legs if leg.outcome == outcome}
        return tuple((price, size + additions.get(price, D(0))) for price, size in levels)
    return replace(book, yes_bids=add_own(book.yes_bids, "YES"), yes_asks=add_own(book.yes_asks, "NO", True))


def variant(engine, name):
    """``engine`` with the decision and replacement books of one variant (refresh is chosen at ``drive``)."""
    from maker_core.replay.v2.kernel import compose_book
    w1 = name in ("W1", "all")
    w2 = name in ("W2", "all")

    class Variant(engine):
        def decision_book(self, state, legs):
            return (compose_book if w1 else frozen_book)(state.latest["book"], legs)

        def replacement_book(self, state, cancelled):
            return self.decision_book(state, () if w2 else cancelled)

    Variant.__name__ = f"{engine.__name__}_{name}"
    return Variant


VARIANTS = {"frozen": False, "W1": False, "W2": False, "F3": True, "all": True}  # name -> local-midnight refresh


def strip(decision):
    return canonical_bytes((decision.action, decision.legs, decision.reasons, decision.centre,
                            decision.share_many, decision.net_per_minute))


def attributing(engine):
    """``engine`` that runs the direct check (rule 1) at every ``decide()`` and records each decision's inputs."""
    from maker_core.replay.v2 import kernel as k

    class Attributing(engine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.direct, self.classes = [], Counter()
            self.captured, self.derived_shas = {}, set()
            self.inputs, self._pending = [], None

        def instant(self, at, batch):
            self.derived_shas.update(i.payload_sha256 for i in batch if getattr(i, "derived", None))
            super().instant(at, batch)

        def ingest(self, cid, kind, payload_sha, value, error, at):
            super().ingest(cid, kind, payload_sha, value, error, at)
            if kind == "descriptor" and error is None and payload_sha not in self.derived_shas:
                self.captured[cid] = value.horizon_days

        def _record(self, cid, classes):
            self.direct.append((self.now, cid, classes))
            self.classes.update(classes)

        def decision_book(self, state, legs):
            book = super().decision_book(state, legs)
            if self.config.policy == "blind_re1":  # blind RE-1 decides inside its runtime: book-level check
                frozen = frozen_book(state.latest["book"], legs)
                if book != frozen:
                    self._record(self._ticking, (book_class(book, frozen, state.latest["book"], legs, None, None),))
            return book

        def evaluate(self, value, cancelled=None):
            cid = self._ticking
            state = self.states[cid]
            public = state.latest["book"]
            post = k.decide(value)
            reference = frozen_book(public, value.existing if cancelled is None else cancelled)
            captured = self.captured.get(cid, value.horizon_days)
            classes = ()
            if (value.book != reference or captured != value.horizon_days) and strip(
                    k.decide(replace(value, book=reference, horizon_days=captured))) != strip(post):
                book_only = strip(k.decide(replace(value, book=reference))) != strip(post)
                horizon_only = strip(k.decide(replace(value, horizon_days=captured))) != strip(post)
                classes = tuple(c for c, on in ((book_class(value.book, reference, public, value.existing,
                                                            cancelled, post),
                                                 book_only or (value.book != reference and not horizon_only)),
                                                ("A6", horizon_only or (captured != value.horizon_days
                                                                        and not book_only))) if on)
                self._record(cid, classes or ("UNATTRIBUTED",))
            self._pending = digest(value)
            return post

        def record_decision(self, cid, at, decision):
            self.inputs.append(self._pending)
            self._pending = None
            super().record_decision(cid, at, decision)

    Attributing.__name__ = "Attributing" + engine.__name__
    return Attributing


def book_class(book, frozen, public, existing, cancelled, post):
    """The class of a decision-book difference from the frozen book, or UNATTRIBUTED when the book is neither
    the ruled composition (``compose_book``) nor, for a replacement, the public book."""
    from maker_core.replay.v2.kernel import compose_book, crossed
    if cancelled is not None and book == public:
        return "A5"
    if book != compose_book(public, existing if cancelled is None else cancelled):
        return "UNATTRIBUTED"
    if (post is None or post.reasons[0] == "CROSSED_BOOK") and not crossed(public) and crossed(book):
        return "A3"
    if (book.yes_bids, book.yes_asks) != (frozen.yes_bids, frozen.yes_asks):
        return "A1"
    return "A2"


# -- one run ------------------------------------------------------------------------------------------------
def run(sources, name, zones, *, engine=EngineV2, config=None):
    """Every base pass (4 policies x 2 fill bounds) of one variant on one parse; engines kept for alignment."""
    from maker_core.replay.v2.day_roll import NO_REFRESH
    config = config or V2Config(hazard_per_minute=HAZARD, keep=True)
    plan = run_plan(sources)
    cls = attributing(variant(engine, name))
    books, passes = Books(), {}
    for bound in BOUNDS:
        for policy in POLICIES:
            scorer = BandDayScorer(policy, bound, pull_runs=policy in ("informed-v0", "clock_only"))
            passes[bound, policy] = (cls(replace(config, policy=policy, fill_bound=bound), plan, sink=scorer), scorer)
    drive(sources, [e for e, _ in passes.values()], observers=(books,),
          time_zones=zones if VARIANTS[name] else NO_REFRESH)
    markets = {c.condition_id: c.market_id for day in plan.days for c in day.conditions}
    return {key: (e, metrics(e, s.band_days(e.settlements, books, markets))) for key, (e, s) in passes.items()}


def metrics(engine, rows):
    nets = [r["modeled_net_k1"] for r in rows if r.get("modeled_net_k1") is not None]
    quotes = [d for d in engine.decisions if d.decision.action == "QUOTE"]
    return dict(decision_sha256=engine.decision_sha.hexdigest(), decisions=engine.decision_count,
                quotes=len(quotes), legs_placed=sum(len(d.decision.legs) for d in quotes), fills=len(engine.fills),
                final_cash=str(engine.cash), intervals=engine.interval_count,
                own_leg_crossed=sum(engine.own_leg_crossed.values()) if hasattr(engine, "own_leg_crossed") else 0,
                pnl_rows=len(rows), pnl_cells_with_net=len(nets), net_k1_sum=str(sum(nets, D(0))),
                reward_k1_sum=str(sum((r["reward_k1"] for r in rows), D(0))),
                pnl_rows_sha256=digest(rows))


# -- alignment and the three rules --------------------------------------------------------------------------
def aligned(engine):
    seen, out = Counter(), {}
    for n, d in enumerate(engine.decisions):
        key = (d.at, d.condition_id)
        out[key + (seen[key],)] = (d, engine.inputs[n])
        seen[key] += 1
    return out


def attribute(base, post):
    """Rules 1-3 of v3.2 §1.4 for one pass: counts, the first difference, and PASS or the failing rule."""
    a, b = aligned(base), aligned(post)
    changed = []
    determinism = 0
    for key in sorted(set(a) | set(b)):
        x, y = a.get(key), b.get(key)
        if x is None or y is None or strip(x[0].decision) != strip(y[0].decision):
            changed.append(key)
            if x is not None and y is not None and x[1] is not None and x[1] == y[1]:
                determinism += 1
    direct = sorted((at, cid) for at, cid, _ in post.direct)
    direct_at = {(at, cid) for at, cid in direct}
    unattributed = post.classes.get("UNATTRIBUTED", 0)
    first = changed[0] if changed else None
    first_direct = first is None or (first[0], first[1]) in direct_at
    cascade = sum(1 for key in changed if not direct or direct[0][0] > key[0])
    verdict = ("FAIL_RULE1_UNATTRIBUTED" if unattributed else "FAIL_RULE2_DETERMINISM" if determinism
               else "FAIL_RULE3_FIRST_NOT_DIRECT" if not first_direct else "FAIL_RULE3_CASCADE" if cascade
               else "PASS")
    return dict(verdict=verdict, changed_decisions=len(changed), direct_checks=len(post.direct),
                classes=dict(sorted(post.classes.items())),
                first_difference=None if first is None else [first[0].isoformat(), first[1], first[2]])


def delta(base, post):
    out = {}
    for field, value in post.items():
        before = base.get(field)
        if before is None:
            continue
        if isinstance(value, int):
            out[field] = [before, value, value - before]
        elif field in ("final_cash", "net_k1_sum", "reward_k1_sum"):
            out[field] = [before, value, str(D(value) - D(before))]
        else:
            out[field] = [before, value, "same" if value == before else "changed"]
    return out


# -- fictional fixtures ---------------------------------------------------------------------------------------
def fixtures():
    from tools.research.maker_replay_v2.dense import DenseDay, OnLevelReplacementDay
    from tools.research.maker_replay_v2.sources import FIXTURE_ZONES, ScaledDay, materialize
    return {
        "dense-09-27": lambda: [materialize(DenseDay(date(2026, 9, 27), union=12, trades=20000, minutes=40))[0]],
        "dense-11-01-dst": lambda: [materialize(DenseDay(date(2026, 11, 1), union=12, trades=2000,
                                                         start_minute=225, minutes=40))[0]],
        "w0-09-27-roll": lambda: [materialize(ScaledDay(date(2026, 9, 27), union=12, trades=2000,
                                                        start_minute=225, minutes=30))[0]],
        # W2(a) on its own: the cancelled legs rest on public levels at a same-instant replacement.
        "w2-on-level": lambda: [materialize(OnLevelReplacementDay(date(2026, 11, 20)))[0]],
    }, FIXTURE_ZONES


def report(names=None, variants=("W1", "W2", "F3", "all")):
    table, zones = fixtures()
    out = {}
    for fixture in names or table:
        sources = table[fixture]()
        base = run(sources, "frozen", zones)
        out[fixture] = dict(frozen={f"{p}/{b}": m for (b, p), (_, m) in base.items()})
        for name in variants:
            post = run(sources, name, zones)
            out[fixture][name] = {f"{p}/{b}": dict(attribution=attribute(base[b, p][0], post[b, p][0]),
                                                   delta=delta(base[b, p][1], post[b, p][1]))
                                  for (b, p) in post}
    return out


if __name__ == "__main__":
    result = report()
    text = json.dumps(result, indent=1, sort_keys=True, default=str)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print(text)
