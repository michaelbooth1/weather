r"""Rule B-1 look wrapper: runs ``b_scorer look`` at S1 against a rule bound at S0 (B-1 Clarification 3 draft).

Research and shadow only. It edits no B-bound file and changes no B-1 decision rule. It exists because of finding
D4-1 (2026-11-01): B-1 binds ``b_scorer_sha256`` = S0, the one permitted post-binding scorer edit (setting
``MG1_LOOK_ENTRY_SHA256``) turns the file into S1, and ``b_scorer.look`` run directly then VOIDs on 2 (the running
scorer is S1) and, with the control re-run at S1, on 3. Left at S0 it VOIDs on 5 (the sentinel).

Pins (this module's own constants; changing any one changes this file's sha256, which Clarification 3 pins):

* ``B1_RULE_SHA256``: the bound B-1 rule file (DECISION_LOG 2026-10-28). Another rule file is refused, so an edited
  rule (a new raw sha, hence a new ``look_guard`` marker key) cannot start a second look through the wrapper.
* ``B_SCORER_S0_SHA256``: the bound scorer S0. ``B_SCORER_ENTRY_EDIT_SHA256``: the S0 to S1 checker.
* ``MG1_LOOK_ENTRY_PIN``: the MG-1 look entry sha S1 must record. It is ``PIN_UNSET`` (refuses) until the commit that
  creates S1 sets it to the same value, by the dated clarification (Reading A: before the MG-1 look). S1 cannot be
  re-edited to match whatever MG-1's receipt says without changing this file's pinned sha.
* ``ACCEPT_S0_CONTROL``: False. VOID 3 accepts only a control re-run at S1 (B-1 clarification of 2026-10-26
  section 4); accepting the S0 control is master's option, applied by a reviewed change of this line.

Order (Clarification 3 sections 3-4):

1. MG-1's look receipt must exist (B-1 section 9 step 1); otherwise refuse, reading nothing.
2. Every pin is checked and S0 to S1 is verified on bytes read once (``b_scorer_entry_edit``, itself executed from
   its pinned bytes). Only then are the verified S1 bytes compiled and executed as a fresh module (no ``.pyc``, no
   prior import of ``b_scorer``), so the running scorer is exactly the verified bytes.
3. While the look runs, VOID 2 accepts S1 for ``b_scorer_sha256`` (and only that field) and VOID 3 accepts a PASS
   control made at S1 (and at S0 only if ``ACCEPT_S0_CONTROL``). Every other check is ``b_scorer``'s own.
4. Preflight, before ``look_guard`` writes a marker: VOID 2 and VOID 3 by ``b_scorer``'s own functions; a failure
   refuses and spends nothing. VOID 5 is NOT in the preflight: an MG-1 entry mismatch is a tripwire and spends the
   look, as do VOID 1, 4, 6 and 7.
5. ``b_scorer.look`` runs (``look_guard`` consumes the look). The wrapper then writes ``b_look_wrapper_receipt.json``
   beside B's receipt (mode "x"), including ABORTED when an exception escapes after THIS call consumed the look.

Concurrency and the rule bytes (second adversarial pass, 2026-11-01):

* ``--out`` holds an exclusive ``b_look_wrapper.lock`` (mode "x") from before the pins are checked until the call
  ends, whatever the outcome; only a hard kill leaves it, and then it must be removed by hand once no run is alive.
  A second run on the same ``--out`` is refused while it exists.
* ABORTED is attributed to this call only if the fixed marker did not exist at the start, exists now, records this
  call's resolved ``--out`` and was consumed at or after this call started (another run on another ``--out`` that
  consumed the look is not this call's abort).
* The rule is read once into ``b_look_wrapper_rule.md`` inside ``--out``; the pins, the preflight and
  ``b_scorer.look`` all read that private copy, never the caller's path again. After the look the copy is
  re-hashed; a change is recorded in the receipt and raised.
* A refusal before ``look_guard`` removes the lock and the copy, and ``--out`` itself if this call created it, so a
  refusal leaves nothing behind.

``python -m weather.calibration.b_look_wrapper look --s0 <bound b_scorer.py bytes> <b_scorer look arguments>``.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

# Capture-host refusal on import (B-bound, imported read-only; b_scorer itself is executed from verified bytes).
from weather.calibration import mg2_composite as _mg2  # noqa: F401

NAME = "b_look_wrapper"
RECEIPT_SCHEMA = "b_look_wrapper_receipt/1"
RECEIPT = "b_look_wrapper_receipt.json"
LOCK = "b_look_wrapper.lock"
RULE_COPY = "b_look_wrapper_rule.md"
PIN_UNSET = "UNSET: set by the commit that creates S1 (B-1 Clarification 3 section 5)"

# docs/operations/B_FORWARD_TEST_DESIGN.md raw sha256, DECISION_LOG 2026-10-28 (B-1 and MG-2 bound).
B1_RULE_SHA256 = "e8bad6e8ce9988180e41e5f9589e180326a8c1886f6043f182187de38a2a6030"
# B-1 b_rule_v1 b_scorer_sha256 (S0).
B_SCORER_S0_SHA256 = "f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439"
# src/weather/calibration/b_scorer_entry_edit.py (B-1 clarification of 2026-10-26 section 4).
B_SCORER_ENTRY_EDIT_SHA256 = "a08c1eaa09d26d38e0481dfcd651d7dc46d11ce524ca29d913bb4a1a50a0005c"
MG1_LOOK_ENTRY_PIN = PIN_UNSET
ACCEPT_S0_CONTROL = False

_VERIFIED = "B_LOOK_WRAPPER_ENTRY_EDIT"  # set on a scorer module executed by load_verified_scorer


class WrapperRefused(RuntimeError):
    """The wrapper refused before ``look_guard``: nothing was read beyond code, pins and receipts; nothing spent."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def module_sha256():
    return _sha(Path(__file__).read_bytes())


def default_s1():
    """The checkout's ``b_scorer.py`` (located without importing it)."""
    return Path(importlib.util.find_spec("weather.calibration.b_scorer").origin)


def _exec_bytes(raw, path, name):
    """A fresh module executed from ``raw`` (compiled here: no bytecode cache, no earlier import is reused)."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = "weather.calibration"
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _entry_edit():
    path = Path(importlib.util.find_spec("weather.calibration.b_scorer_entry_edit").origin)
    raw = path.read_bytes()
    if _sha(raw) != B_SCORER_ENTRY_EDIT_SHA256:
        raise WrapperRefused(f"b_scorer_entry_edit.py hashes to {_sha(raw)}, not the pinned "
                             f"{B_SCORER_ENTRY_EDIT_SHA256}")
    return _exec_bytes(raw, path, f"weather.calibration._b_entry_edit_{_sha(raw)[:16]}"), _sha(raw)


def verify(rule, s0, s1):
    """Every pin, and S0 to S1 exactly the permitted constant line; returns ``(entry_edit verdict, S1 bytes)``."""
    rule_sha = _sha(Path(rule).read_bytes())
    if rule_sha != B1_RULE_SHA256:
        raise WrapperRefused(f"the rule {rule} hashes to {rule_sha}, not the bound B-1 rule {B1_RULE_SHA256}")
    s0_bytes, s1_bytes = Path(s0).read_bytes(), Path(s1).read_bytes()
    s0_sha, s1_sha = _sha(s0_bytes), _sha(s1_bytes)
    if s0_sha != B_SCORER_S0_SHA256:
        raise WrapperRefused(f"--s0 hashes to {s0_sha}, not the bound b_scorer_sha256 {B_SCORER_S0_SHA256}")
    if MG1_LOOK_ENTRY_PIN == PIN_UNSET:
        raise WrapperRefused("MG1_LOOK_ENTRY_PIN is UNSET: the commit that creates S1 sets it (Clarification 3 s5)")
    checker, checker_sha = _entry_edit()
    problems, recorded = checker.s1_problems(s0_bytes, s1_bytes)
    if problems:
        raise WrapperRefused(f"the scorer is not an entry-edit-verified S1 of the bound S0: {problems}")
    if recorded != MG1_LOOK_ENTRY_PIN:
        raise WrapperRefused("S1 records an MG-1 look entry sha other than the pinned MG1_LOOK_ENTRY_PIN")
    return ({"pass": True, "rule_sha256": rule_sha, "s0_sha256": s0_sha, "s1_sha256": s1_sha,
             "mg1_look_entry_sha256": recorded, "b_scorer_entry_edit_sha256": checker_sha}, s1_bytes)


def load_verified_scorer(*, rule, s0, s1=None):
    """Verify, then execute the verified S1 bytes as a fresh scorer module (the CLI always does this)."""
    s1 = Path(s1) if s1 is not None else default_s1()
    edit, s1_bytes = verify(rule, s0, s1)
    scorer = _exec_bytes(s1_bytes, s1, f"weather.calibration._b_scorer_s1_{edit['s1_sha256'][:16]}")
    if scorer.module_sha256() != edit["s1_sha256"]:
        raise WrapperRefused(f"{s1} changed after it was verified")
    _, fields = scorer.read_rule(rule)
    if fields["b_scorer_sha256"] != edit["s0_sha256"]:
        raise WrapperRefused("the rule's b_scorer_sha256 is not the pinned S0")
    setattr(scorer, _VERIFIED, dict(edit))
    return scorer


def _control_sha(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("b_scorer_sha256")
    except (OSError, ValueError, TypeError, AttributeError):
        return None


@contextlib.contextmanager
def accept_s1(scorer, s0_sha, s1_sha):
    """VOID 2 reads S1 for ``b_scorer_sha256``; VOID 3 accepts a control at S1 (S0 too if ACCEPT_S0_CONTROL)."""
    hash_check, control_check = scorer.bound_hash_problems, scorer.control_problems

    def bound_hash_problems(fields, **kwargs):
        if fields.get("b_scorer_sha256") == s0_sha:
            fields = dict(fields, b_scorer_sha256=s1_sha)
        return hash_check(fields, **kwargs)

    def control_problems(path, fields):
        if fields.get("b_scorer_sha256") == s0_sha:
            made_at = _control_sha(path) if path else None
            accepted_at = s0_sha if ACCEPT_S0_CONTROL and made_at == s0_sha else s1_sha
            fields = dict(fields, b_scorer_sha256=accepted_at)
        return control_check(path, fields)

    scorer.bound_hash_problems, scorer.control_problems = bound_hash_problems, control_problems
    try:
        yield
    finally:
        scorer.bound_hash_problems, scorer.control_problems = hash_check, control_check


def _file_sha(scorer, path):
    return scorer.sha256_file(path) if path and Path(path).is_file() else None


def preflight(scorer, *, rule, mg2_rule, release_binding, mg2_look, vectors, control_receipt, root=None):
    """VOID 2 and VOID 3 by ``b_scorer``'s own checks (run inside ``accept_s1``): ``(found, inputs)``.

    Reads the rule, MG-2's rule, release binding and look record, the vectors' and emit audit's bytes and the dev
    control receipt. Opens no label, price or transfer file.
    """
    _, fields = scorer.read_rule(rule)
    found = {}
    if not scorer.unfilled(fields):  # an unfilled rule is look_guard's refusal
        hashes = scorer.bound_hash_problems(fields, mg2_rule=mg2_rule, release_binding=release_binding,
                                            mg2_look=mg2_look, vectors=vectors, root=root)
        if hashes:
            found[2] = hashes
        control = scorer.control_problems(control_receipt, fields)
        if control:
            found[3] = control
    inputs = {"mg2_rule_sha256": _file_sha(scorer, mg2_rule),
              "release_binding_sha256": _file_sha(scorer, release_binding),
              "mg2_look_sha256": _file_sha(scorer, mg2_look), "vectors_sha256": _file_sha(scorer, vectors),
              "control_receipt_sha256": _file_sha(scorer, control_receipt),
              "control_made_at_b_scorer_sha256": _control_sha(control_receipt) if control_receipt else None}
    return found, inputs


def _write_receipt(out, receipt):
    Path(out).mkdir(parents=True, exist_ok=True)
    with open(Path(out) / RECEIPT, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, indent=1, sort_keys=True, default=str) + "\n")


def _consumed_by_this_call(fixed, out, started):
    """The fixed marker exists, names this call's resolved ``--out`` and was consumed at or after ``started``."""
    try:
        marker = json.loads(Path(fixed).read_text(encoding="utf-8"))
        consumed_at = datetime.fromisoformat(marker["consumed_at_utc"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False
    return marker.get("out") == str(Path(out).resolve()) and consumed_at >= started


def _release(out, *, created, keep_copy):
    """Drop the lock (and the rule copy unless kept); remove ``out`` if this call created it and it is now empty."""
    out = Path(out)
    if not keep_copy:
        (out / RULE_COPY).unlink(missing_ok=True)
    (out / LOCK).unlink(missing_ok=True)
    if created:
        with contextlib.suppress(OSError):
            out.rmdir()


def look(*, s0, rule, mg2_rule, release_binding, layout_root, vectors, mg2_look, transfer, drop_list,
         control_receipt, mg1_look_receipt, out, lih_vectors=None, today=None, now=None, root=None, s1=None,
         scorer=None):
    """The single B look at a pinned, entry-edit-verified S1. Returns ``b_scorer.look``'s payload.

    ``scorer`` is for tests: a module from ``load_verified_scorer`` (re-verified here); the CLI never passes it.
    """
    started = datetime.now(timezone.utc)
    if not mg1_look_receipt or not Path(mg1_look_receipt).is_file() or Path(mg1_look_receipt).stat().st_size == 0:
        raise WrapperRefused("MG-1's look receipt does not exist: B never reads before MG-1's look (B-1 sections 4, 9)")
    out = Path(out)
    if (out / RECEIPT).exists():
        raise WrapperRefused(f"{out / RECEIPT} already exists: exactly one look")
    created = not out.exists()
    out.mkdir(parents=True, exist_ok=True)
    try:
        with open(out / LOCK, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"started_at_utc": started.isoformat()}) + "\n")
    except FileExistsError as exc:
        raise WrapperRefused(f"{out / LOCK} exists: another wrapper run holds this --out (or one was killed; remove "
                             f"the lock by hand once no run is alive)") from exc
    looked = False
    try:
        rule_copy = out / RULE_COPY
        rule_copy.write_bytes(Path(rule).read_bytes())  # read once; every later reader uses this private copy
        if scorer is None:
            scorer = load_verified_scorer(rule=rule_copy, s0=s0, s1=s1)
        else:
            edit, _ = verify(rule_copy, s0, scorer.__file__)
            if getattr(scorer, _VERIFIED, None) != edit:
                raise WrapperRefused("the scorer module was not executed from these verified S1 bytes")
        edit = dict(getattr(scorer, _VERIFIED))
        look_args = dict(rule=rule_copy, mg2_rule=mg2_rule, release_binding=release_binding,
                         layout_root=layout_root, vectors=vectors, mg2_look=mg2_look, transfer=transfer,
                         drop_list=drop_list, control_receipt=control_receipt, mg1_look_receipt=mg1_look_receipt,
                         out=out, lih_vectors=lih_vectors, today=today, now=now, root=root)
        fixed = scorer.rule_marker(edit["rule_sha256"])
        receipt = {"schema": RECEIPT_SCHEMA,
                   "wrapper": {"module": f"weather.calibration.{NAME}", "source_sha256": module_sha256(),
                               "accept_s0_control": ACCEPT_S0_CONTROL},
                   "rule_sha256": edit["rule_sha256"], "entry_edit": edit,
                   "mg1_look_receipt_sha256": scorer.sha256_file(mg1_look_receipt),
                   "started_at_utc": started.isoformat()}
        with accept_s1(scorer, edit["s0_sha256"], edit["s1_sha256"]):
            found, inputs = preflight(scorer, rule=rule_copy, mg2_rule=mg2_rule, release_binding=release_binding,
                                      mg2_look=mg2_look, vectors=vectors, control_receipt=control_receipt,
                                      root=root)
            if found:
                raise WrapperRefused(f"preflight: VOID conditions {sorted(found)} hold; look_guard did not run and "
                                     f"nothing was consumed: {found}")
            receipt["preflight"] = {"checked": [2, 3], "found": {}, "inputs": inputs}
            consumed_before = fixed.exists()
            looked = True
            try:
                payload = scorer.look(**look_args)
            except BaseException as exc:
                if not consumed_before and _consumed_by_this_call(fixed, out, started):
                    b_receipt = out / scorer.RECEIPT
                    _write_receipt(out, {**receipt, **_rule_after(rule_copy, edit),
                                         "b_look_receipt_sha256": _file_sha(scorer, b_receipt),
                                         "b_decision": {"verdict": "ABORTED",
                                                        "error": f"{type(exc).__name__}: {exc}"},
                                         "written_at_utc": datetime.now(timezone.utc).isoformat()})
                raise
        after = _rule_after(rule_copy, edit)
        _write_receipt(out, {**receipt, **after,
                             "b_look_receipt_sha256": scorer.sha256_file(out / scorer.RECEIPT),
                             "b_decision": payload["decision"],
                             "written_at_utc": datetime.now(timezone.utc).isoformat()})
        if not after["rule_copy"]["unchanged"]:
            raise RuntimeError(f"{rule_copy} changed while b_scorer.look ran (recorded in {out / RECEIPT}): "
                               f"{after['rule_copy']}")
        return payload
    finally:
        _release(out, created=created and not looked, keep_copy=looked)


def _rule_after(rule_copy, edit):
    """The private rule copy re-hashed after the look."""
    try:
        sha = _sha(Path(rule_copy).read_bytes())
    except OSError:
        sha = None
    return {"rule_copy": {"path": str(rule_copy), "sha256_after_look": sha, "unchanged": sha == edit["rule_sha256"]}}


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.b_look_wrapper")
    sub = parser.add_subparsers(dest="command", required=True)
    k = sub.add_parser("look", help="the single B look at a pinned, entry-edit-verified S1 (B-1 Clarification 3)")
    k.add_argument("--s0", required=True, help="b_scorer.py bytes as bound by B-1 (sha S0)")
    for name in ("rule", "mg2-rule", "release-binding", "layout", "vectors", "mg2-look", "transfer", "drop-list",
                 "control-receipt", "mg1-look-receipt", "out"):
        k.add_argument(f"--{name}", required=True)
    k.add_argument("--lih-vectors", help="last_in_hour vectors (descriptive secondary only)")
    return parser


def _is_refusal(exc):
    return isinstance(exc, WrapperRefused) or type(exc).__name__ in ("BRefused", "Mg2Refused")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = look(s0=args.s0, rule=args.rule, mg2_rule=args.mg2_rule, release_binding=args.release_binding,
                      layout_root=args.layout, vectors=args.vectors, mg2_look=args.mg2_look, transfer=args.transfer,
                      drop_list=args.drop_list, control_receipt=args.control_receipt,
                      mg1_look_receipt=args.mg1_look_receipt, out=args.out, lih_vectors=args.lih_vectors)
    except Exception as exc:  # noqa: BLE001  (refusals exit 2; anything else propagates)
        if not _is_refusal(exc):
            raise
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["decision"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
