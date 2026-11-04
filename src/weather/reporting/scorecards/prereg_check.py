"""Pre-registration checker: refuse a rule file that lacks any section the checklist requires.

The checklist is ``docs/operations/PREREGISTRATION_CHECKLIST.md``. A rule file must carry five headed
sections (any Markdown heading level; an optional ``(a)``..``(e)`` prefix is allowed), each with the
content named below. A section containing ``TBD`` or ``TODO`` does not count.

- (a) ``Positive control``: the control and its expected values (at least one decimal number).
- (b) ``Comparator fairness``: the comparator gets the same floor and calibration as the candidate
  (must name both ``floor`` and ``calibration``).
- (c) ``Targeted loss slice``: the slice and its expected size from the loss atlas (an atlas sha256
  prefix of >= 12 hex characters and a number).
- (d) ``MDE and clusters``: the MDE (a decimal number) and the cluster count (``N clusters`` or
  ``clusters: N``).
- (e) ``Dev-window reuse``: the reuse count from ``DEV_WINDOW_LEDGER.md`` (names the ledger and an integer).

With ``--forward`` (a pre-registration that spends forward dates; MODEL_IMPROVEMENT_METHOD section 5 rules
6 and 7) two more sections are required, each written as ``- key: value`` field lines:

- (f) ``Power gate``: ``sigma_d`` (exactly one labelled source block, history or dev, and a sha256 of at
  least 12 hex), ``rho`` (lag-1), ``VIF`` (at least max(1, (1 + rho) / (1 - rho)), and at least the square
  of ``block3 ratio`` when that is given), ``delta`` (the effect of interest), ``N`` (at least 20),
  ``MDE80`` (at least 2.802 x sigma_d x sqrt(VIF) / sqrt(N), 2% tolerance), ``power`` (at least 0.5 and
  not above the normal power at delta by more than 0.02), ``class`` (POWERED when delta >= MDE80,
  otherwise SCREEN with ``N80``), ``intervals`` (names the date-clustered and the block-3 interval).
- (g) ``Futility``: the Rule B looks that fall before N, exactly ``look 7: HARM if t > 3.143``,
  ``look 14: FUTILE if z > +0.5``, ``look 21: FUTILE if z > 0``, ``look 31: FUTILE if z > -0.5``;
  ``final N`` equal to the power gate's N; ``interim PASS: never``.

Text-only and offline; it reads one file and prints one JSON line.

    python -m weather.reporting.scorecards.prereg_check [--forward] <rule.md>

Exit 0 when every required section is present and valid, 2 otherwise or when the file cannot be read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
PLACEHOLDER = re.compile(r"\b(TBD|TODO)\b")
DECIMAL = re.compile(r"[-+−]?\d*\.\d+")
NUMBER = re.compile(r"[-+−]?\d+(?:\.\d+)?")

SECTIONS = (
    ("a", "positive control", re.compile(r"positive\s+control", re.I),
     (("expected values (a decimal number)", lambda b: DECIMAL.search(b)),)),
    ("b", "comparator fairness", re.compile(r"comparator\s+fairness", re.I),
     (("the comparator's floor", lambda b: re.search(r"\bfloor", b, re.I)),
      ("the comparator's calibration", lambda b: re.search(r"calibrat", b, re.I)))),
    ("c", "targeted loss slice", re.compile(r"targeted\s+loss\s+slice", re.I),
     (("a loss-atlas sha256 (>= 12 hex)", lambda b: re.search(r"\b[0-9a-f]{12,64}\b", b)),
      ("the expected size (a number)", lambda b: NUMBER.search(re.sub(r"\b[0-9a-f]{12,64}\b", "", b))))),
    ("d", "MDE and clusters", re.compile(r"\bMDE\b", re.I),
     (("the MDE (a decimal number)", lambda b: DECIMAL.search(b)),
      ("the cluster count", lambda b: re.search(r"\d+\s+(?:\w+\s+)?clusters?\b|clusters?\s*[:=]\s*\d+", b, re.I)))),
    ("e", "dev-window reuse", re.compile(r"dev[-\s]window\s+reuse", re.I),
     (("the ledger (DEV_WINDOW_LEDGER)", lambda b: re.search(r"DEV_WINDOW_LEDGER", b)),
      ("the reuse count (an integer)", lambda b: re.search(r"\b\d+\b", b)))),
)

# ----------------------------------------------------------------------------- forward: (f) and (g)

Z80 = 2.802            # z(0.975) + z(0.80): one-sided 2.5%, 80% power
Z975 = 1.959964
MIN_FORWARD_N = 20     # section 5 rule 6: at least 20 dates before any PASS
MIN_POWER = 0.5        # section 5 rule 6: no screen launches below power 0.5
MDE_TOLERANCE = 0.02
POWER_TOLERANCE = 0.02
# Rule B (section 5 rule 7): (look, outcome, statistic, stop when statistic > bound).
RULE_B = ((7, "HARM", "t", 3.143), (14, "FUTILE", "z", 0.5), (21, "FUTILE", "z", 0.0), (31, "FUTILE", "z", -0.5))
FIELD = re.compile(r"^\s*[-*]\s*([A-Za-z][A-Za-z0-9_ ]*?)\s*:\s*(.+?)\s*$")
LOOK = re.compile(r"^look\s+(\d+)$", re.I)
BOUND = re.compile(r"^(HARM|FUTILE)\s+if\s+([tz])\s*>\s*([-+]?\d+(?:\.\d+)?)$", re.I)
HEX = re.compile(r"\b[0-9a-f]{12,64}\b")
FORWARD_REQUIRED = ("sigma_d", "rho", "vif", "delta", "n", "mde80", "power", "class", "intervals")


def _num(text):
    m = NUMBER.search((text or "").replace("−", "-"))
    return float(m.group(0)) if m else None


def _fields(body):
    out = {}
    for line in body.splitlines():
        m = FIELD.match(line)
        if m:
            out.setdefault(m.group(1).strip().lower(), m.group(2))
    return out


def _ndtr(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def check_power_gate(body):
    """(f) problems plus the planned N (None when it cannot be read)."""
    f = _fields(body)
    missing = [k for k in FORWARD_REQUIRED if k not in f]
    if missing:
        return [f"(f) power gate: does not state {', '.join(missing)}"], None
    vals = {k: _num(HEX.sub("", f[k])) for k in FORWARD_REQUIRED if k not in ("class", "intervals")}
    bad = [k for k, v in vals.items() if v is None]
    if bad:
        return [f"(f) power gate: no number for {', '.join(bad)}"], None
    sigma, rho, vif, delta, n, mde, power = (vals[k] for k in ("sigma_d", "rho", "vif", "delta", "n", "mde80", "power"))
    problems = []
    src = f["sigma_d"].lower()
    if bool(re.search(r"\bhistory\b", src)) == bool(re.search(r"\bdev\b", src)):
        problems.append("(f) power gate: sigma_d must name exactly one source block, history or dev (never pooled)")
    if not HEX.search(f["sigma_d"]):
        problems.append("(f) power gate: sigma_d does not cite its file sha256 (>= 12 hex)")
    if sigma <= 0 or delta <= 0 or vif <= 0:
        problems.append("(f) power gate: sigma_d, delta and VIF must be positive")
        return problems, None
    if not -1 < rho < 1:
        problems.append("(f) power gate: rho must lie in (-1, 1)")
    else:
        floor = max(1.0, (1 + rho) / (1 - rho))
        ratio = _num(f.get("block3 ratio"))
        if ratio is not None:
            floor = max(floor, ratio ** 2)
        if vif < floor * (1 - 1e-3):
            problems.append(f"(f) power gate: VIF {vif:g} is below the serial-dependence floor {floor:.3f} "
                            "(max of 1, (1 + rho) / (1 - rho) and the block3 ratio squared)")
    planned = int(n) if n == int(n) else None
    if planned is None or planned < MIN_FORWARD_N:
        problems.append(f"(f) power gate: N must be an integer of at least {MIN_FORWARD_N}")
    se = sigma * math.sqrt(vif) / math.sqrt(n) if n > 0 else math.inf
    if mde < Z80 * se * (1 - MDE_TOLERANCE):
        problems.append(f"(f) power gate: MDE80 {mde:g} is below 2.802 x sigma_d x sqrt(VIF) / sqrt(N) = "
                        f"{Z80 * se:.5f}")
    if not 0 <= power <= 1:
        problems.append("(f) power gate: power must lie in [0, 1]")
    else:
        normal = _ndtr(delta / se - Z975)
        if power > normal + POWER_TOLERANCE:
            problems.append(f"(f) power gate: power {power:g} overstates the normal power at delta ({normal:.3f})")
        if power < MIN_POWER:
            problems.append(f"(f) power gate: power {power:g} is below {MIN_POWER} (no screen launches below it)")
    words = f["class"].split()
    cls = words[0].upper().strip(".,;") if words else ""
    if cls not in ("POWERED", "SCREEN"):
        problems.append("(f) power gate: class must be POWERED or SCREEN")
    elif (cls == "POWERED") != (delta >= mde):
        problems.append(f"(f) power gate: class {cls} contradicts delta {delta:g} against MDE80 {mde:g}")
    elif cls == "SCREEN" and _num(f.get("n80")) is None:
        problems.append("(f) power gate: a SCREEN must state N80")
    iv = f["intervals"].lower()
    if "date-clustered" not in iv or not re.search(r"block[-\s]?3", iv):
        problems.append("(f) power gate: intervals must name the date-clustered and the block-3 interval")
    return problems, planned


def check_futility(body, planned):
    f = _fields(body)
    problems = []
    looks = {int(m.group(1)): v.strip() for k, v in f.items() for m in [LOOK.match(k)] if m}
    final = _num(f.get("final n"))
    if final is None:
        problems.append("(g) futility: does not state final N")
    elif planned is not None and int(final) != planned:
        problems.append(f"(g) futility: final N {final:g} differs from the power gate's N {planned}")
    horizon = final if final is not None else math.inf
    for k, kind, stat, bound in RULE_B:
        if k >= horizon:
            if k in looks:
                problems.append(f"(g) futility: look {k} is not before final N")
            continue
        if k not in looks:
            problems.append(f"(g) futility: Rule B look {k} missing")
            continue
        m = BOUND.match(looks[k].replace("−", "-"))
        if (not m or m.group(1).upper() != kind or m.group(2).lower() != stat
                or abs(float(m.group(3)) - bound) > 1e-9):
            problems.append(f"(g) futility: look {k} must read '{kind} if {stat} > {bound:+g}'")
    extra = sorted(set(looks) - {k for k, *_ in RULE_B})
    if extra:
        problems.append(f"(g) futility: looks {extra} are not Rule B looks")
    if f.get("interim pass", "").strip().lower().rstrip(".") != "never":
        problems.append("(g) futility: must state 'interim PASS: never'")
    return problems


def check_forward(sections):
    gate = [body for title, body in sections if re.search(r"power\s+gate", title, re.I)]
    fut = [body for title, body in sections if re.search(r"\bfutility\b", title, re.I)]
    problems, planned = [], None
    for letter, name, found in (("f", "power gate", gate), ("g", "futility", fut)):
        if not found:
            problems.append(f"({letter}) {name}: section missing")
        elif PLACEHOLDER.search("\n".join(found)):
            problems.append(f"({letter}) {name}: contains a TBD/TODO placeholder")
    if gate and not any(p.startswith("(f)") for p in problems):
        gate_problems, planned = check_power_gate("\n".join(gate))
        problems += gate_problems
    if fut and not any(p.startswith("(g)") for p in problems):
        problems += check_futility("\n".join(fut), planned)
    return problems


def split_sections(text):
    """[(heading title, body)] for every Markdown heading outside fenced code."""
    out, title, body, fenced = [], None, [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        m = None if fenced else HEADING.match(line)
        if m:
            if title is not None:
                out.append((title, "\n".join(body)))
            title, body = m.group(2), []
        elif title is not None:
            body.append(line)
    if title is not None:
        out.append((title, "\n".join(body)))
    return out


def check_text(text, forward=False):
    """Return a list of human-readable problems (empty when the rule file passes).

    ``forward`` also requires (f) power gate and (g) futility (a pre-registration on forward dates)."""
    sections = split_sections(text)
    problems = []
    for letter, name, pattern, requirements in SECTIONS:
        found = [body for title, body in sections if pattern.search(title)]
        if not found:
            problems.append(f"({letter}) {name}: section missing")
            continue
        body = "\n".join(found)
        if PLACEHOLDER.search(body):
            problems.append(f"({letter}) {name}: contains a TBD/TODO placeholder")
            continue
        for what, test in requirements:
            if not test(body):
                problems.append(f"({letter}) {name}: does not state {what}")
    if forward:
        problems += check_forward(sections)
    return problems


def check_file(path, forward=False):
    raw = Path(path).read_bytes()
    problems = check_text(raw.decode("utf-8-sig"), forward)
    return {"rule": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "forward": bool(forward),
            "verdict": "PASS" if not problems else "REFUSED", "problems": problems}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.reporting.scorecards.prereg_check",
                                     description="Refuse a pre-registration rule file missing a required section.")
    parser.add_argument("--forward", action="store_true",
                        help="also require (f) power gate and (g) futility (a pre-registration on forward dates)")
    parser.add_argument("rule")
    args = parser.parse_args(argv)
    try:
        result = check_file(args.rule, args.forward)
    except (OSError, UnicodeDecodeError) as exc:
        print(json.dumps({"rule": args.rule, "verdict": "REFUSED", "problems": [f"unreadable: {exc}"]}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
