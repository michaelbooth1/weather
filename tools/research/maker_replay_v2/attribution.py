"""Re-run and attribute (shadow-gate spec v3.2 §1.4, v3.3 §4.2) for the engine rulings W1(a), W2(a), F3 and Q2(a).

Every changed decision between the frozen engine and a ruling must trace to an allowed class, directly or as a
cascade, or the re-run fails:

- **A1** (W1): a resting leg on a YES-side level the public book lacks (created level), incl. the mid it moves;
- **A2** (W1): own size on ``no_bids``/``no_asks`` (the mirror), read by ``touch_buffer`` or the crossed check;
- **A3** (W1): own-vs-public crossed book (``CROSSED_BOOK`` on a public book that is not crossed);
- **A5** (W2): a same-instant replacement decided on the public book instead of the pre-cancel book;
- **A6** (F3): the horizon read differs from the latest captured descriptor's because a derived local-midnight
  descriptor precedes it. (A7, the reopen class, does not arise: this engine applies no reopen records.)
- **A8** (Q2(a), owner 2026-10-08; its own class, not A6): the registration §4 horizon clause. Either the condition
  is outside its active interval at t only because the latest captured or derived descriptor holds a lead other
  than 1 or 2 (``maker_core.replay.v2.horizon``; the interval ends at local midnight and the legs are withdrawn
  there, and a later wake inside the old envelope is not decided at all; a base decision with no post wake at an
  instant where the condition is outside its clause window, such as the base's window-start
  ``MISSING_DESCRIPTOR`` pull, is A8 too: ``absent_a8``), or blind RE-1 is refused by its new
  horizon gate (``HORIZON_NOT_ELIGIBLE``, ``Kernel.blind_horizons``). A8 is attributed against ``all``
  (W1+W2+F3), not against ``frozen``: Q2 is a change on top of the three 2026-10-07 rulings and needs the refresh.

Variants (``VARIANTS``) switch each ruling on alone and all together; ``frozen`` reproduces the engine before
the rulings (T1 decision book, T2 replacement book, no refresh, no blind horizon gate) and is pinned to the pre-fix
digests by ``tests/maker_core/test_replay_v2_attribution.py``. ``Q2`` is ``all`` plus the blind gate, run on the
same sources with their windows cut by the horizon clause (``horizon_sources``); ``report_q2`` attributes it
against ``all`` on the envelope windows. Fictional fixtures only (``FIXTURES``); never a captured day.

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
    w1 = name in ("W1", "all", "Q2")
    w2 = name in ("W2", "all", "Q2")

    class Variant(engine):
        blind_horizons = engine.blind_horizons if name == "Q2" else None  # the Q2(a) blind gate

        def decision_book(self, state, legs):
            return (compose_book if w1 else frozen_book)(state.latest["book"], legs)

        def replacement_book(self, state, cancelled):
            return self.decision_book(state, () if w2 else cancelled)

    Variant.__name__ = f"{engine.__name__}_{name}"
    return Variant


VARIANTS = {"frozen": False, "W1": False, "W2": False, "F3": True, "all": True, "Q2": True}  # name -> refresh


def strip(decision):
    return canonical_bytes((decision.action, decision.legs, decision.reasons, decision.centre,
                            decision.share_many, decision.net_per_minute))


def attributing(engine, q2=False):
    """``engine`` that runs the direct check (rule 1) at every ``decide()`` and records each decision's inputs.

    With ``q2`` the base is ``all`` (same books and refresh), so the book and horizon checks are off and the direct
    check is A8's: a tick at which the condition is inside its envelope (``active_from``/``active_until``, the base
    run's window) but outside its horizon-clause window, or a blind RE-1 ``HORIZON_NOT_ELIGIBLE`` pull."""
    from maker_core.replay.v2 import kernel as k

    class Attributing(engine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.direct, self.classes = [], Counter()
            self.captured, self.derived_shas = {}, set()
            self.inputs, self._pending = [], None
            self.envelope = {}
            for day in self.plan.days:
                for c in day.conditions:
                    self.envelope.setdefault(c.condition_id, []).append((c.active_from, c.active_until))

        def tick(self, cid, at):
            if q2 and self.outside_clause(cid, at):
                self._record(cid, ("A8",))
            super().tick(cid, at)

        def pull(self, cid, at, reason):
            if q2 and reason == "HORIZON_NOT_ELIGIBLE":
                self._record(cid, ("A8",))
            super().pull(cid, at, reason)

        def instant(self, at, batch):
            self.derived_shas.update(i.payload_sha256 for i in batch if getattr(i, "derived", None))
            super().instant(at, batch)

        def ingest(self, cid, kind, payload_sha, value, error, at):
            super().ingest(cid, kind, payload_sha, value, error, at)
            if kind == "descriptor" and error is None and payload_sha not in self.derived_shas:
                self.captured[cid] = value.horizon_days

        def _record(self, cid, classes, at=None):
            self.direct.append((self.now if at is None else at, cid, classes))
            self.classes.update(classes)

        def outside_clause(self, cid, at):
            """A8's direct condition: inside the envelope (the base's window) but outside the clause window."""
            return not self.active(cid, at) and any(a <= at < b for a, b in self.envelope.get(cid, ()))

        def absent_a8(self, base):
            """A base decision with no post wake at all is A8 when the post condition is outside its clause window
            there (e.g. the base's window-start MISSING_DESCRIPTOR pull before the first descriptor)."""
            seen = {(at, cid) for at, cid, _ in self.direct}
            for d in base.decisions:
                if (d.at, d.condition_id) not in seen and self.outside_clause(d.condition_id, d.at):
                    self._record(d.condition_id, ("A8",), d.at)
                    seen.add((d.at, d.condition_id))

        def decision_book(self, state, legs):
            book = super().decision_book(state, legs)
            if not q2 and self.config.policy == "blind_re1":  # blind RE-1 decides in its runtime: book check
                frozen = frozen_book(state.latest["book"], legs)
                if book != frozen:
                    self._record(self._ticking, (book_class(book, frozen, state.latest["book"], legs, None, None),))
            return book

        def evaluate(self, value, cancelled=None):
            if q2:  # the base already has W1, W2 and F3: only A8 can differ
                self._pending = digest(value)
                return k.decide(value)
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
def horizon_sources(sources, zones):
    """The same day sources with each condition's windows cut by the horizon clause (``horizon.day_windows``).

    ``declared`` is kept as the source's, so the only difference from the envelope run is the clause itself."""
    from types import MappingProxyType
    from maker_core.replay.v2 import horizon
    from maker_core.replay.v2.lockstep import DayPlan, DaySource
    lines = horizon.timelines(sources, zones)
    out = []
    for s in sources:
        windows, _ = horizon.day_windows(s.plan, lines)
        p = s.plan
        out.append(DaySource(DayPlan(p.day, p.conditions, MappingProxyType(windows), p.groups, p.provenance,
                                     p.input_hashes, p.declared), s.records))
    return out


def run(sources, name, zones, *, engine=EngineV2, config=None):
    """Every base pass (4 policies x 2 fill bounds) of one variant on one parse; engines kept for alignment."""
    from maker_core.replay.v2.day_roll import NO_REFRESH
    config = config or V2Config(hazard_per_minute=HAZARD, keep=True)
    plan = run_plan(sources)
    cls = attributing(variant(engine, name), q2=name == "Q2")
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


def report_q2(names=None):
    """A8: ``Q2`` on horizon-clause windows against ``all`` on the envelope windows, per fixture and pass."""
    table, zones = fixtures()
    out = {}
    for fixture in names or table:
        sources = table[fixture]()
        base = run(sources, "all", zones)
        post = run(horizon_sources(sources, zones), "Q2", zones)
        for key, (engine, _) in post.items():
            engine.absent_a8(base[key][0])
        out[fixture] = {f"{p}/{b}": dict(attribution=attribute(base[b, p][0], post[b, p][0]),
                                         delta=delta(base[b, p][1], post[b, p][1]))
                        for (b, p) in post}
    return out


if __name__ == "__main__":
    result = dict(rulings=report(), q2_against_all=report_q2())
    text = json.dumps(result, indent=1, sort_keys=True, default=str)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print(text)
