"""Registration draft §11 reachability gate and the §10 E1-E8 gate report (U3), calibration rehearsals only.

§11 is read from the carried 3-date rehearsal (``rehearsal.rehearse(..., mode="carried")``), score-free:

- **f_cal**: ``informed-v0``'s pooled ``strictly_through`` quoted seconds / eligible seconds. Eligible is every covered
  second of a declared active interval, quoted is eligible with a leg resting: Clarification 3's ``quote_presence``
  read straight from the base pass's scorer sums (``covered``, ``pulled``), so no band-day row, fill or P&L is built
  for it. **PASS iff f_cal >= 0.5** (``THRESHOLD``); no eligible second is UNIDENTIFIED, which is not a pass.
- **Screen pass rate** (reported only, biased toward pass; see below): over ``informed-v0``'s ``strictly_through`` base-pass decisions, those that
  reached the net screen and passed it / those that reached it. With it, the decision-reason histogram keyed
  ``ACTION:REASON`` (counts only), and ``blind_re1``'s and ``clock_only``'s (the selected matched trial) quoted
  fractions. The decisions are counted by a tee in front of the scorer (``counting_engine``); the engine, the
  policy and the scorer are unchanged.
- **Pull identifiability** (policy-free): N_cal opportunities and L_cal large moves (|move| >= 0.05) from midpoints
  alone: the frozen pull endpoint's candidate minutes and start/end midpoint rule (``pull._endpoint``), without
  either policy's state or coverage (``policy_free_opportunities``). ``expected_clock_removed`` = L_cal x (1 - f_cal)
  at calibration scale, and x 14/3 for the 14 quote dates (a linear date-count projection, see the T1 report).

Reading of "reaches the net screen" (T1 report, for the Defender): ``policy.decide`` returns one terminal reason,
so a decision is classified by its (action, terminal reason) pair:

- reached and failed: ``NONPOSITIVE_NET`` (a new proposal whose net <= 0, or resting legs whose net <= 0);
- reached and passed: ``INFORMED_QUOTE``; ``COMPETITION_OUTSIDE_RANGE`` (net > 0, share outside 0.15-0.70); and
  every resting-leg outcome after the ``old_net <= 0`` check (``ADVERSE_LEG_CHANGED``, the informed HOLD
  ``WITHIN_REQUOTE_WINDOW``, ``REQUOTE_CLOCK_FUTURE``, the HOLD ``REQUOTE_COOLDOWN``, ``REQUOTE_REQUIRED``);
- everything else did not reach it (kernel pulls, gates before the size loop, eligibility rejections).

``decide`` tries sizes largest first and keeps only the last size's rejection, so a decision whose larger size
failed the net screen and whose smallest admissible size failed an eligibility check reads as not reached. Only
reached-and-failed decisions are lost that way, so ``reached`` is a lower bound and the **rate is biased toward pass**
(it is not a lower bound on the rate; Defender D6.4). It is reported, never gated.

Decision logic (pinned by a table test): ``status_of`` maps f_cal to PASS (>= 0.5, the boundary included), FAIL or
UNIDENTIFIED (no eligible second); ``verdict`` maps the max_m and R1 statuses to the §11 verdict, where only PASS
passes: an UNIDENTIFIED max_m reads ``UNIDENTIFIED`` (a rehearsal or universe defect, not a reason to run R1), and
R1 rescues only a FAIL, only with its own PASS.

**R1** (the one pre-declared variant): each city's bands read their own ``U_m`` (``calibrate``'s ``cities[m]["upper"]``,
which already carries Clarification 1's pooled fallback) instead of ``max_m U_m``, through ``Kernel.hazard_for``
(``per_city_engine``). The config keeps the ``max_m`` scalar, so report bytes and ceilings measure the same work.
R1 runs in the rehearsal only; if it is adopted (C14), the scored run needs the map bound into its configuration
and ``run_inputs`` first (a follow-up, not this module).
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import math

from maker_core.evidence.journal import digest
from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES

D = Decimal
FORMAT = "maker_core.replay.v2.reachability.v0.1"
GATE_FORMAT = "maker_core.replay.v2.gate_report.v0.1"
THRESHOLD = D("0.5")  # Clarification 3: below it the pull hurdle (ratio >= 2) is out of reach in expectation
POLICY, BOUND = "informed-v0", "strictly_through"
QUOTED_FRACTION_POLICIES = ("informed-v0", "blind_re1", "clock_only")
QUOTE_DATES = 14  # registration §9: the scored run's quote dates
PANEL_SCALE = D(QUOTE_DATES) / D(len(CALIBRATION_DATES))
SCREEN_FAILED = frozenset({("NO_QUOTE", "NONPOSITIVE_NET"), ("CANCEL", "NONPOSITIVE_NET")})
SCREEN_PASSED = frozenset({
    ("QUOTE", "INFORMED_QUOTE"), ("NO_QUOTE", "COMPETITION_OUTSIDE_RANGE"), ("CANCEL", "ADVERSE_LEG_CHANGED"),
    ("HOLD", "WITHIN_REQUOTE_WINDOW"), ("CANCEL", "REQUOTE_CLOCK_FUTURE"), ("HOLD", "REQUOTE_COOLDOWN"),
    ("CANCEL", "REQUOTE_REQUIRED")})
E2_INPUT_BYTES = 1024**3  # E2: <= 1 GiB of v0.2 bytes per date
E4_SECONDS = 2048  # E4: each date <= 2,048 s
EXTERNAL_GATES = ("E1", "E3", "E8")  # evidence produced outside the rehearsal (export receipts, equivalence, suite)
GATES = ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8")


# -- engines ---------------------------------------------------------------------------------------------------------

class _Tee:
    """The scorer sink with every decision also counted by ``ACTION:REASON``; forwards everything unchanged."""

    def __init__(self, sink, counts):
        self.sink, self.counts = sink, counts

    def interval(self, iv):
        self.sink.interval(iv)

    def decision(self, event):
        decision = event.decision
        self.counts[f"{decision.action}:{decision.reasons[0]}"] += 1
        self.sink.decision(event)

    def fill(self, fill):
        self.sink.fill(fill)


def per_city_engine(base, hazards):
    """``base`` with ``hazard_for`` reading the condition's own market's hazard (R1); an unmapped market refuses."""
    hazards = dict(hazards)

    class PerCityHazard(base):
        def hazard_for(self, state):
            try:
                return hazards[state.market_id]
            except KeyError:
                raise BundleError("r1_hazard_market_missing") from None
    PerCityHazard.__name__ = PerCityHazard.__qualname__ = f"PerCityHazard[{base.__name__}]"
    return PerCityHazard


def counting_engine(counts, base):
    """An engine factory for ``pipeline.run_passes``: the ``informed-v0`` ``strictly_through`` base pass (no clock
    windows) gets the counting tee; every other pass is ``base`` unchanged."""
    def make(cfg, plan, *, sink=None):
        if cfg.policy == POLICY and cfg.fill_bound == BOUND and not cfg.clock_pulls:
            sink = _Tee(sink, counts)
        return base(cfg, plan, sink=sink)
    return make


# -- hazards ---------------------------------------------------------------------------------------------------------

def _hazard(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise BundleError("invalid_hazard_value")
    return value


def hazards(calibration, variant):
    """(the scalar, the per-market map or None) from an unchanged ``calibration.calibrate`` document.

    ``max_m``: the document's ``hazard_per_minute`` and no map. ``r1_per_city``: the same scalar (it stays in the
    configuration) and each market's ``upper``, which ``calibrate`` already set to the pooled bound (or 1.0 when the
    pool is sparse) for a sparse or absent city. A document with a global fallback maps every market to its scalar."""
    from maker_core.replay.v2.rehearsal import HAZARD_VARIANTS
    if variant not in HAZARD_VARIANTS:
        raise BundleError("rehearsal_hazard_variant_invalid")
    if not isinstance(calibration, dict) or calibration.get("format") != "maker_core.replay.calibration.v1":
        raise BundleError("invalid_calibration_document")
    scalar = _hazard(calibration["hazard_per_minute"])
    if variant == "max_m":
        return scalar, None
    cities = calibration.get("cities") or {}
    if calibration.get("global_fallback"):
        return scalar, {market: scalar for market in calibration.get("markets") or ()}
    try:
        return scalar, {market: _hazard(row["upper"]) for market, row in sorted(cities.items())}
    except (KeyError, TypeError, ValueError):
        raise BundleError("invalid_calibration_document") from None


def check_hazard_map(variant, hazard_by_market, markets):
    """R1 needs a map covering every market of the run, each value in [0, 1]; ``max_m`` refuses a map."""
    if variant == "max_m":
        if hazard_by_market is not None:
            raise BundleError("max_m_takes_no_hazard_map")
        return None
    if not isinstance(hazard_by_market, dict) or not hazard_by_market:
        raise BundleError("r1_hazard_map_required")
    mapped = {str(m): _hazard(v) for m, v in hazard_by_market.items()}
    if not set(markets) <= set(mapped):
        raise BundleError("r1_hazard_market_missing")
    return mapped


# -- the §11 fields --------------------------------------------------------------------------------------------------

def quoted_fraction(scorer):
    """Clarification 3's pooled quote presence from a scorer's exact sums (microseconds), as strings."""
    eligible = sum((r.covered for r in scorer.rows.values()), 0)
    quoted = eligible - sum((r.pulled for r in scorer.rows.values()), 0)
    return dict(eligible_seconds=str(D(eligible).scaleb(-6)), quoted_seconds=str(D(quoted).scaleb(-6)),
                quoted_fraction=str(D(quoted) / D(eligible)) if eligible else None)


def screen(counts):
    """Reached, passed and the rate from an ``ACTION:REASON`` histogram (see the module docstring)."""
    passed = failed = 0
    for key, n in counts.items():
        pair = tuple(key.split(":", 1))
        passed += n if pair in SCREEN_PASSED else 0
        failed += n if pair in SCREEN_FAILED else 0
    reached = passed + failed
    return dict(reached=reached, passed=passed, rate=str(D(passed) / D(reached)) if reached else None,
                reading="terminal (action, reason); reached is a lower bound, so the rate is biased toward pass")


def policy_free_opportunities(plan, books, *, check=lambda: None):
    """N_cal and L_cal: the frozen endpoint's candidate minutes with a start and an end midpoint, from midpoints only."""
    from maker_core.replay.v2.pull import LARGE_MOVE_MID2, _endpoint, candidate_minutes, windows_by_condition
    empty = ((), (), ())
    candidates = opportunities = large = 0
    excluded = Counter()
    for cid, windows in sorted(windows_by_condition(plan).items()):
        series = books.pull.get(cid, empty)
        for at in candidate_minutes(windows):
            check()
            candidates += 1
            endpoint, reason = _endpoint(series, at)
            if reason:
                excluded[reason] += 1
                continue
            before, after, _ = endpoint
            opportunities += 1
            large += int(abs(after - before) >= LARGE_MOVE_MID2)
    return dict(candidates=candidates, n_cal=opportunities, l_cal=large, exclusions=dict(sorted(excluded.items())))


def status_of(f_cal):
    """§11: PASS iff f_cal >= 0.5 (the boundary passes); no eligible second (None) is UNIDENTIFIED, never a pass."""
    if f_cal is None:
        return "UNIDENTIFIED"
    return "PASS" if D(f_cal) >= THRESHOLD else "FAIL"


def verdict(max_m, r1=None):
    """The §11 verdict from the max_m status and, when R1 was run, its status (None: not run)."""
    if max_m == "PASS":
        return "PASS"
    if max_m != "FAIL":
        return "UNIDENTIFIED"
    if r1 is None:
        return "FAIL_R1_NOT_RUN"
    return "PASS_UNDER_R1" if r1 == "PASS" else "FAIL"


def block(run, counts, *, check=lambda: None):
    """The rehearsal document's ``reachability`` block from a carried run (counts and fractions only)."""
    fractions = {policy: quoted_fraction(run.passes[BOUND][policy].scorer) for policy in QUOTED_FRACTION_POLICIES}
    f_cal = fractions[POLICY]["quoted_fraction"]
    opportunities = policy_free_opportunities(run.plan, run.books, check=check)
    status = status_of(f_cal)
    removed = None if f_cal is None else D(opportunities["l_cal"]) * (1 - D(f_cal))
    return dict(status=status, f_cal=f_cal, screen_pass_rate=screen(counts),
                decision_reasons=dict(sorted(counts.items())), quoted_fraction=fractions,
                n_cal=opportunities["n_cal"], l_cal=opportunities["l_cal"],
                pull_candidates=opportunities["candidates"], opportunity_exclusions=opportunities["exclusions"],
                expected_clock_removed=None if removed is None else dict(
                    calibration=str(removed), panel=str(removed * PANEL_SCALE),
                    panel_scale=f"{QUOTE_DATES}/{len(CALIBRATION_DATES)} quote dates per calibration date"))


# -- §10 and §11 gate report -----------------------------------------------------------------------------------------

def _external(name, evidence):
    if evidence is None:
        return dict(status="NOT_SUPPLIED")
    if (not isinstance(evidence, dict) or evidence.get("status") not in ("PASS", "FAIL")
            or not isinstance(evidence.get("evidence"), str) or not evidence["evidence"]):
        raise BundleError(f"gate_evidence_invalid:{name}")
    return dict(status=evidence["status"], evidence=evidence["evidence"])


def _carried(doc, variant):
    from maker_core.replay.v2.rehearsal import whitelisted
    whitelisted(doc)
    if doc.get("mode") != "carried" or doc.get("hazard_variant") != variant or "reachability" not in doc:
        raise BundleError(f"gate_carried_rehearsal_required:{variant}")
    return doc


def gate_report(per_date, carried, repeat, *, r1=None, e1=None, e3=None, e8=None):
    """The §10 E1-E8 and §11 gate document, from rehearsal documents and supplied external evidence only.

    ``per_date``: {ISO calibration date: per-date document}; ``carried``: the carried ``max_m`` document;
    ``repeat``: a second per-date document of one of the dates (E7); ``r1``: the carried ``r1_per_city`` document,
    required only when ``max_m`` fails §11. ``e1``/``e3``/``e8``: {"status": "PASS"|"FAIL", "evidence": text} from the
    export receipts, the v0.1 equivalence check and the fixture suite; absent is NOT_SUPPLIED, which is not a pass.
    E6's pull-candidate clause has no derived ``max_events`` ceiling to compare with (§9 derives none; owner ruling
    pending), so E6 reads INCOMPLETE (FAIL when the ceilings are not executable) and never PASS (Defender D6.2).
    Only PASS passes: the executability status is PASS when every gate passes, FAIL when any fails, else INCOMPLETE."""
    from maker_core.replay.v2 import ceilings
    from maker_core.replay.v2.rehearsal import ceiling_input, whitelisted
    expected = [d.isoformat() for d in CALIBRATION_DATES]
    if not isinstance(per_date, dict) or sorted(per_date) != expected:
        raise BundleError("incomplete_ceiling_measurement")
    for day, doc in per_date.items():
        whitelisted(doc)
        if doc.get("mode") != "per_date" or doc.get("dates") != [day] or doc.get("hazard_variant") != "max_m":
            raise BundleError("gate_per_date_rehearsal_required:" + day)
    carried = _carried(carried, "max_m")
    measured = {day: ceiling_input(doc) for day, doc in per_date.items()}
    derived = ceilings.derive(measured, ceiling_input(carried))
    whitelisted(repeat)
    day = (repeat.get("dates") or [None])[0]
    if repeat.get("mode") != "per_date" or day not in per_date:
        raise BundleError("gate_repeat_rehearsal_required")
    first = per_date[day]["hashes"]
    same = {k: first[k] == repeat["hashes"][k] for k in ("decision_sha256", "report_sha256", "sidecar_sha256")}
    gates = dict(
        E1=_external("E1", e1),
        E2=dict(status="PASS" if all(m["input_bytes"] <= E2_INPUT_BYTES for m in measured.values()) else "FAIL",
                limit_bytes=E2_INPUT_BYTES, per_date={d: m["input_bytes"] for d, m in measured.items()}),
        E3=_external("E3", e3),
        E4=dict(status="PASS" if all(m["runtime_seconds"] <= E4_SECONDS for m in measured.values()) else "FAIL",
                limit_seconds=E4_SECONDS, per_date={d: m["runtime_seconds"] for d, m in measured.items()}),
        E5=ceilings.e5_memory(measured, ceiling_input(carried), derived),
        E6=dict(status="INCOMPLETE" if derived["executable"] else "FAIL",
                host_limit_binding=derived["host_limit_binding"],
                projected_pull_candidates=carried["reachability"]["pull_candidates"] * ceilings.N
                // len(CALIBRATION_DATES),
                max_events="not derived: §9 has no pull-candidate ceiling (owner ruling pending)"),
        E7=dict(status="PASS" if all(same.values()) else "FAIL", date=day, identical=same),
        E8=_external("E8", e8))
    reach = {"max_m": carried["reachability"]}
    if r1 is not None:
        reach["r1_per_city"] = _carried(r1, "r1_per_city")["reachability"]
    outcome = verdict(reach["max_m"]["status"], reach.get("r1_per_city", {}).get("status"))
    statuses = [g["status"] for g in gates.values()]
    status = "PASS" if all(s == "PASS" for s in statuses) else "FAIL" if "FAIL" in statuses else "INCOMPLETE"
    doc = dict(format=GATE_FORMAT, dates=expected, calibration_sha256=carried["calibration_sha256"],
               executability=dict(status=status,
                                  not_supplied=[n for n, g in gates.items() if g["status"] == "NOT_SUPPLIED"],
                                  not_evaluated=[n for n, g in gates.items() if g["status"] == "INCOMPLETE"],
                                  gates=gates),
               ceilings=derived, reachability=dict(verdict=outcome, threshold=str(THRESHOLD), variants=reach),
               rehearsal_sha256=dict(per_date={d: digest(doc) for d, doc in sorted(per_date.items())},
                                     carried=digest(carried), repeat=digest(repeat),
                                     r1=None if r1 is None else digest(r1)),
               interpretation="Executability and reachability on calibration dates only; no score, fill, P&L, "
                              "reward or contrast.")
    return doc
