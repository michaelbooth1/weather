r"""Rule B-1 look wrapper: runs ``b_scorer look`` at S1 against a rule bound at S0 (B-1 Clarification 3 draft).

Research and shadow only; it imports ``b_scorer``, whose import refuses from a production package and on the
capture host. It edits no B-bound file and changes no B-1 decision rule. It exists because of finding D4-1
(2026-11-01): B-1 binds ``b_scorer_sha256`` = S0, the one permitted post-binding scorer edit (setting
``MG1_LOOK_ENTRY_SHA256``) turns the file into S1, and ``b_scorer.look`` run directly then VOIDs on 2 (the running
scorer is S1) and, with the control re-run at S1, on 3. Left at S0 it VOIDs on 5 (the sentinel).

What the wrapper does, in order (B-1 Clarification 3 sections 2-4):

1. MG-1's look receipt must exist (checked first, as in ``look_guard``); otherwise it hands straight to
   ``b_scorer.look``, which refuses without consuming anything.
2. S0 to S1: the ``--s0`` bytes must hash to the rule's ``b_scorer_sha256``; the running scorer's bytes (S1) must
   differ from S0 by exactly the one ``MG1_LOOK_ENTRY_SHA256`` line (``b_scorer_entry_edit.s1_problems``), and the
   recorded value must be the running module's constant. Any failure refuses before anything is consumed.
3. While the look runs, VOID 2 accepts S1 for ``b_scorer_sha256`` (and only that field), and VOID 3 accepts a PASS
   control receipt made at S0 or at that verified S1. Every other check is ``b_scorer``'s own, unchanged.
4. Preflight, before ``look_guard`` writes a marker: the outcome-free, code-only conditions (VOID 2, VOID 3 and the
   VOID 5 entry-sha check) are evaluated with ``b_scorer``'s own functions; a failure refuses and spends nothing.
   VOID 1, VOID 4, the rest of VOID 5, and VOID 6-7 are left to ``b_scorer.look`` and spend the look as before.
5. ``b_scorer.look`` runs (``look_guard`` consumes the look), then the wrapper writes
   ``b_look_wrapper_receipt.json`` beside B's receipt (mode "x") with S0, S1, the entry-edit verdict, the preflight
   and this module's sha256.

``python -m weather.calibration.b_look_wrapper look --s0 <bound b_scorer.py bytes> <b_scorer look arguments>``.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# The default scorer; importing it refuses from a production package and on the capture host.
from weather.calibration import b_scorer as _b_scorer

NAME = "b_look_wrapper"
RECEIPT_SCHEMA = "b_look_wrapper_receipt/1"
RECEIPT = "b_look_wrapper_receipt.json"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def module_sha256():
    return _sha(Path(__file__).read_bytes())


def _scorer(scorer=None):
    return _b_scorer if scorer is None else scorer


def verify_entry_edit(rule, s0, scorer=None):
    """S0 is the bound scorer, the running scorer is S1, and S0 to S1 is exactly the permitted constant line."""
    from weather.calibration import b_scorer_entry_edit as entry_edit

    scorer = _scorer(scorer)
    _, fields = scorer.read_rule(rule)
    bound = fields["b_scorer_sha256"]
    s0_bytes = Path(s0).read_bytes()
    s1_bytes = Path(scorer.__file__).read_bytes()
    s0_sha, s1_sha = _sha(s0_bytes), _sha(s1_bytes)
    if s0_sha != bound:
        raise scorer.BRefused(f"--s0 hashes to {s0_sha}, not the rule's bound b_scorer_sha256 {bound}")
    if scorer.module_sha256() != s1_sha:
        raise scorer.BRefused("the running scorer's module_sha256 is not its file bytes")
    problems, recorded = entry_edit.s1_problems(s0_bytes, s1_bytes)
    if problems:
        raise scorer.BRefused(f"the running scorer is not an entry-edit-verified S1 of the bound S0: {problems}")
    if recorded != scorer.MG1_LOOK_ENTRY_SHA256:
        raise scorer.BRefused(f"S1 records {recorded} but the running MG1_LOOK_ENTRY_SHA256 is "
                              f"{scorer.MG1_LOOK_ENTRY_SHA256}")
    return {"pass": True, "s0_sha256": s0_sha, "s1_sha256": s1_sha, "mg1_look_entry_sha256": recorded,
            "b_scorer_entry_edit_sha256": _sha(Path(entry_edit.__file__).read_bytes())}


def _control_sha(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("b_scorer_sha256")
    except (OSError, ValueError, TypeError, AttributeError):
        return None


@contextlib.contextmanager
def accept_s1(scorer, s0_sha, s1_sha):
    """VOID 2 reads S1 for ``b_scorer_sha256``; VOID 3 accepts a control at S0 or S1. Restored on exit."""
    hash_check, control_check = scorer.bound_hash_problems, scorer.control_problems

    def bound_hash_problems(fields, **kwargs):
        if fields.get("b_scorer_sha256") == s0_sha:
            fields = dict(fields, b_scorer_sha256=s1_sha)
        return hash_check(fields, **kwargs)

    def control_problems(path, fields):
        made_at = _control_sha(path) if path else None
        if fields.get("b_scorer_sha256") == s0_sha and made_at in (s0_sha, s1_sha):
            fields = dict(fields, b_scorer_sha256=made_at)
        return control_check(path, fields)

    scorer.bound_hash_problems, scorer.control_problems = bound_hash_problems, control_problems
    try:
        yield
    finally:
        scorer.bound_hash_problems, scorer.control_problems = hash_check, control_check


def preflight(scorer, *, rule, mg2_rule, release_binding, mg2_look, vectors, control_receipt, mg1_look_receipt,
              root=None):
    """The outcome-free, code-only VOID conditions, by ``b_scorer``'s own checks (run inside ``accept_s1``).

    Reads the rule, MG-2's rule, release binding and look record, the vectors' bytes, the dev control receipt and
    MG-1's receipt. Opens no label, price or transfer file.
    """
    from weather.calibration import mg1_look

    _, fields = scorer.read_rule(rule)
    found = {}
    if not scorer.unfilled(fields):  # an unfilled rule is look_guard's refusal, not a preflight one
        hashes = scorer.bound_hash_problems(fields, mg2_rule=mg2_rule, release_binding=release_binding,
                                            mg2_look=mg2_look, vectors=vectors, root=root)
        if hashes:
            found[2] = hashes
        control = scorer.control_problems(control_receipt, fields)
        if control:
            found[3] = control
    written = mg1_look.receipt_problems(mg1_look_receipt)
    if not written:
        entry = (json.loads(Path(mg1_look_receipt).read_text(encoding="utf-8")).get("entry_point") or {}).get(
            "source_sha256")
        if entry != scorer.MG1_LOOK_ENTRY_SHA256:
            found[5] = [f"MG-1 look receipt entry point sha {entry} is not the running MG1_LOOK_ENTRY_SHA256 "
                        f"({scorer.MG1_LOOK_ENTRY_SHA256})"]
    return found


def look(*, s0, rule, mg2_rule, release_binding, layout_root, vectors, mg2_look, transfer, drop_list,
         control_receipt, mg1_look_receipt, out, lih_vectors=None, today=None, now=None, root=None, scorer=None):
    """The single B look at an entry-edit-verified S1 (Clarification 3). Returns ``b_scorer.look``'s payload."""
    scorer = _scorer(scorer)
    look_args = dict(rule=rule, mg2_rule=mg2_rule, release_binding=release_binding, layout_root=layout_root,
                     vectors=vectors, mg2_look=mg2_look, transfer=transfer, drop_list=drop_list,
                     control_receipt=control_receipt, mg1_look_receipt=mg1_look_receipt, out=out,
                     lih_vectors=lih_vectors, today=today, now=now, root=root)
    if not mg1_look_receipt or not Path(mg1_look_receipt).is_file() or Path(mg1_look_receipt).stat().st_size == 0:
        return scorer.look(**look_args)  # look_guard refuses first, consuming nothing
    if (Path(out) / RECEIPT).exists():
        raise scorer.BRefused(f"{Path(out) / RECEIPT} already exists: exactly one look")
    edit = verify_entry_edit(rule, s0, scorer)
    with accept_s1(scorer, edit["s0_sha256"], edit["s1_sha256"]):
        mechanical = preflight(scorer, rule=rule, mg2_rule=mg2_rule, release_binding=release_binding,
                               mg2_look=mg2_look, vectors=vectors, control_receipt=control_receipt,
                               mg1_look_receipt=mg1_look_receipt, root=root)
        if mechanical:
            raise scorer.BRefused(f"preflight: mechanical VOID conditions {sorted(mechanical)} hold; nothing was "
                                  f"read or consumed: {mechanical}")
        payload = scorer.look(**look_args)
    rule_sha, _ = scorer.read_rule(rule)
    receipt = {"schema": RECEIPT_SCHEMA, "wrapper": {"module": f"weather.calibration.{NAME}",
                                                     "source_sha256": module_sha256()},
               "rule_sha256": rule_sha, "entry_edit": edit, "preflight": {"mechanical_voids": {}},
               "b_look_receipt_sha256": scorer.sha256_file(Path(out) / scorer.RECEIPT),
               "b_decision": payload["decision"], "written_at_utc": datetime.now(timezone.utc).isoformat()}
    with open(Path(out) / RECEIPT, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, indent=1, sort_keys=True, default=str))
    return payload


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.b_look_wrapper")
    sub = parser.add_subparsers(dest="command", required=True)
    k = sub.add_parser("look", help="the single B look at an entry-edit-verified S1 (B-1 Clarification 3)")
    k.add_argument("--s0", required=True, help="b_scorer.py bytes as bound by B-1 (sha S0)")
    for name in ("rule", "mg2-rule", "release-binding", "layout", "vectors", "mg2-look", "transfer", "drop-list",
                 "control-receipt", "mg1-look-receipt", "out"):
        k.add_argument(f"--{name}", required=True)
    k.add_argument("--lih-vectors", help="last_in_hour vectors (descriptive secondary only)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    scorer = _scorer()
    try:
        result = look(s0=args.s0, rule=args.rule, mg2_rule=args.mg2_rule, release_binding=args.release_binding,
                      layout_root=args.layout, vectors=args.vectors, mg2_look=args.mg2_look, transfer=args.transfer,
                      drop_list=args.drop_list, control_receipt=args.control_receipt,
                      mg1_look_receipt=args.mg1_look_receipt, out=args.out, lih_vectors=args.lih_vectors)
    except (scorer.BRefused, scorer.mg2.Mg2Refused) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["decision"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
