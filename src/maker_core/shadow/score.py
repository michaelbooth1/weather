"""Nightly shadow diagnostics: replay agreement and counterfactual fills on a captured panel.

Inputs are sealed tapes (``tape.sealed_tapes``) and a neutral ``Panel`` of
captured public books and trade prints for the same UTC day. Outputs are
diagnostics, labelled ``DIAGNOSTIC_NOT_A_VERDICT``: modelled reward is not paid
reward, simulated fills are not own fills, and no pre-registered hurdle or
verdict rule is applied here. Contract: docs/operations/maker-shadow-runner.md.
"""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from maker_core.evidence.journal import digest
from maker_core.quoting.policy import decide
from maker_core.shadow.paper import crosses
from maker_core.shadow.tape import decision_projection, inputs_from

SCORE_SCHEMA = "maker_core.shadow_score.v0.1"
HORIZONS_MINUTES = (1, 5, 30)
K_SHARES = (1.0, 0.5, 0.3)
RULES = {"strictly_through": "a public print on the leg's asset strictly below the bid fills min(print size, remaining)",
         "at_price": "a public print on the leg's asset at or below the bid fills min(print size, remaining)"}
LEG_LIFE = timedelta(seconds=60)
D = Decimal


class Panel(Protocol):
    def covers(self, asset_id) -> bool: ...
    def mid(self, asset_id, at_utc) -> Decimal | None: ...
    def prints(self, asset_id, start_utc, end_utc) -> list: ...


def _agreement(row, out):
    try:
        inputs = inputs_from(row["inputs"])
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        out["unreconstructable"] += 1
        out["examples"].append({"condition_id": row.get("condition_id"), "error": type(error).__name__})
        return
    again = decide(inputs)
    if decision_projection(again) == row["decision"] and digest(inputs) == row["decision"]["input_hash"]:
        out["matched"] += 1
    else:
        out["mismatched"] += 1
        if len(out["examples"]) < 20:
            out["examples"].append({"condition_id": row["condition_id"], "now": row["inputs"]["now"],
                                    "recorded": row["decision"]["reasons"], "replayed": list(again.reasons)})


def _stratum():
    return {"condition_minutes": 0, "leg_minutes": 0, "legs_not_in_panel": 0,
            "modelled_reward_pusd": {str(k): 0.0 for k in K_SHARES},
            "rules": {rule: {"fills": 0, "shares": D(0), "spread_pusd": D(0), "spread_missing": 0,
                             "horizons": {str(h): {"net_pusd": D(0), "adverse_pusd": D(0), "missing": 0}
                                          for h in HORIZONS_MINUTES}} for rule in RULES}}


def _fills(panel, asset, price, size, start, rule):
    remaining = size
    for at, print_price, print_size in panel.prints(asset, start, start + LEG_LIFE):
        if remaining <= 0:
            break
        if crosses(rule, print_price, price):
            quantity = min(print_size, remaining)
            remaining -= quantity
            yield at, quantity


def _score_legs(stratum, panel, row, legs):
    if not legs:
        return
    terms = row["inputs"]["terms"]
    stratum["condition_minutes"] += 1
    if terms is not None:
        per_minute = float(terms["rate_per_day"]) / 1440 * float(row["decision"]["share_many"])
        for k in K_SHARES:
            stratum["modelled_reward_pusd"][str(k)] += per_minute * k
    start = datetime.fromisoformat(row["inputs"]["now"])
    for leg in legs:
        asset = row["outcomes"][leg["outcome"]]
        if not panel.covers(asset):
            stratum["legs_not_in_panel"] += 1
            continue
        stratum["leg_minutes"] += 1
        price, size = D(leg["price"]), D(leg["size"])
        for rule, out in stratum["rules"].items():
            for at, quantity in _fills(panel, asset, price, size, start, rule):
                out["fills"] += 1
                out["shares"] += quantity
                m0 = panel.mid(asset, at)
                if m0 is None:
                    out["spread_missing"] += 1
                else:
                    out["spread_pusd"] += quantity * (m0 - price)
                for h in HORIZONS_MINUTES:
                    mark, cell = panel.mid(asset, at + timedelta(minutes=h)), out["horizons"][str(h)]
                    if mark is None or m0 is None:
                        cell["missing"] += 1
                        continue
                    cell["net_pusd"] += quantity * (mark - price)
                    cell["adverse_pusd"] += quantity * (m0 - mark)


def _text(value):
    if isinstance(value, dict):
        return {k: _text(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return round(value, 9)
    return value


CODE_FIELDS = ("git_commit", "git_dirty", "git_error")


def tape_code(tape):
    """The code identity a tape's ``opened`` scope recorded; tapes from before the field read as unrecorded."""
    rows = tape.get("rows") or ()
    scope = rows[0].get("scope") if rows and rows[0].get("event") == "opened" else None
    scope = scope if isinstance(scope, dict) else {}
    if "git_commit" not in scope:
        return {"git_commit": None, "git_dirty": None, "git_error": "not_recorded"}
    return {name: scope.get(name) for name in CODE_FIELDS}


def code_summary(codes):
    """Distinct commits and the tapes that are dirty or carry no commit; surfaced, never a verdict."""
    commits = sorted({c["git_commit"] for c in codes if c["git_commit"]})
    return {"git_commits": commits, "tapes": len(codes),
            "dirty_tapes": sum(1 for c in codes if c["git_dirty"] is True),
            "unbound_tapes": sum(1 for c in codes if not c["git_commit"] or c["git_dirty"] is not False)}


def score_day(tapes, panel, *, utc_day, unsealed=(), panel_summary=None):
    """Score every condition-minute of the day's sealed tapes against the panel."""
    agreement = {"matched": 0, "mismatched": 0, "unreconstructable": 0, "examples": []}
    strata = {"policy": _stratum(), "gated": _stratum()}
    actions, reasons, guard = Counter(), Counter(), Counter()
    minutes = condition_minutes = unevaluated = 0
    # OD23 diagnostic (#267): per-minute counts summed; minutes before the field existed are counted apart.
    own_mid = {"books_with_own_legs": 0, "mid_differs": 0, "minutes_recorded": 0, "minutes_not_recorded": 0}
    for tape in tapes:
        for record in tape["rows"]:
            if record["event"] != "minute":
                continue
            if record["minute_utc"][:10] != utc_day:
                raise ValueError("tape_minute_outside_day")
            minutes += 1
            guard[record["guard"]["action"]] += 1
            counts = record.get("own_size_mid")
            if isinstance(counts, dict):
                own_mid["minutes_recorded"] += 1
                for key in ("books_with_own_legs", "mid_differs"):
                    own_mid[key] += int(counts.get(key, 0))
            else:
                own_mid["minutes_not_recorded"] += 1
            for row in record["conditions"]:
                condition_minutes += 1
                if "decision" not in row:
                    unevaluated += 1
                    continue
                decision = row["decision"]
                actions[decision["action"]] += 1
                reasons.update(decision["reasons"])
                _agreement(row, agreement)
                wanted = decision["legs"] if decision["action"] in ("QUOTE", "HOLD") else []
                _score_legs(strata["policy"], panel, row, wanted)
                _score_legs(strata["gated"], panel, row, record["resting_after"].get(row["condition_id"], []))
    compared = agreement["matched"] + agreement["mismatched"] + agreement["unreconstructable"]
    agreement["status"] = ("NOT_RUN" if not compared else
                           "PASS" if compared == agreement["matched"] else "FAIL")
    return _text({
        "schema_version": SCORE_SCHEMA, "utc_day": utc_day, "label": "DIAGNOSTIC_NOT_A_VERDICT",
        "tapes": [{"tape": t["tape"], "sha256": t["sha256"], "tape_schema": t.get("tape_schema"),
                   "records_stream": t.get("records_stream"), **tape_code(t)} for t in tapes],
        "code": code_summary([tape_code(t) for t in tapes]), "unsealed_tapes": list(unsealed),
        "minutes": minutes, "condition_minutes": condition_minutes, "unevaluated": unevaluated,
        "decisions": dict(sorted(actions.items())), "reasons": dict(sorted(reasons.items())),
        "minute_guard_actions": dict(sorted(guard.items())), "own_size_mid": own_mid, "agreement": agreement,
        "strata": strata, "fill_rules": RULES, "horizons_minutes": list(HORIZONS_MINUTES),
        "k_share": list(K_SHARES), "leg_life_seconds": int(LEG_LIFE.total_seconds()),
        "panel": panel_summary or {},
    })


__all__ = ["CODE_FIELDS", "HORIZONS_MINUTES", "K_SHARES", "Panel", "RULES", "SCORE_SCHEMA", "code_summary",
           "score_day", "tape_code"]
