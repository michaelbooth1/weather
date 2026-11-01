"""Rule B-1 end to end: the rule bound at S0, the scorer at S1, one look through ``look_guard``.

Guards: finding D4-1 of the 2026-11-01 formal review (adversarially confirmed by master) and the draft B-1
Clarification 3 (docs/research/b-look-s0-s1-2026-11-01/b1-clarification-3-s0-s1-look-wrapper-DRAFT.md).

D4-1: B's single look is a deterministic VOID as built. B-1 binds ``b_scorer_sha256`` = S0 (``B_FORWARD_TEST_DESIGN.md`` b_rule_v1 block); the
only permitted post-binding scorer edit sets ``MG1_LOOK_ENTRY_SHA256`` (S0 to S1, B-1 clarification of 2026-10-26
section 4, checked by ``b_scorer_entry_edit``); that clarification says the control is re-run at S1 and the look runs
at S1. Run directly, ``b_scorer.look`` then fires VOID 2 (``module_sha256()`` is S1, the rule says S0) and VOID 3 (the
control ran at S1, the rule says S0); left at S0 it fires VOID 5 (the sentinel matches no receipt). Through the
new pinned ``b_look_wrapper`` (S0 to S1 verified by ``b_scorer_entry_edit``, S1 executed from the verified bytes)
the same look scores, and a VOID 2 or 3 is refused before ``look_guard`` spends the look.

Everything here is synthetic and lives under ``tmp_path``: a temp copy of the scorer edited to S1 by exactly the
permitted constant line, a fixture git commit holding the MG-2 release files, a receipt written by ``mg1_look``'s
own ``Look``/``finish`` code (``__main__`` is stood in as the registered entry point, and its clock, ``head_commit``
and ``LOOK_ROOT`` are monkeypatched), a synthetic transfer and drop list, and the one-look markers. No sha constant
is monkeypatched: S1 carries the recorded MG-1 entry sha in its own bytes and the rule carries S0. The wrapper's
pins for the synthetic rule and the entry sha are set in a temp copy of the wrapper's own source (the repository
wrapper keeps the bound rule sha and the UNSET entry pin, which the CLI test shows refusing).
"""
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather.reporting.scorecards import dev_scorecard as sc
from weather.reporting.scorecards import dev_scorecard_data as data

from tests.host_guard import import_or_skip_on_capture_host

ROOT = Path(__file__).resolve().parents[2]

b = import_or_skip_on_capture_host("weather.calibration.b_scorer")
mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")
mg1_look = import_or_skip_on_capture_host("weather.calibration.mg1_look")
entry_edit = import_or_skip_on_capture_host("weather.calibration.b_scorer_entry_edit")
wrapper = import_or_skip_on_capture_host("weather.calibration.b_look_wrapper")

MG1_RULE = ROOT / "docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md"
DESIGN = ROOT / "docs/operations/B_FORWARD_TEST_DESIGN.md"
SENTINEL_LINE = "MG1_LOOK_ENTRY_SHA256 = MG1_LOOK_ENTRY_UNRECORDED\n"
CONSTANT_LINE = re.compile(r"^MG1_LOOK_ENTRY_SHA256 = .*\n", re.M)

D0 = date(2026, 10, 28)
DATES = [(D0 + timedelta(days=i)).isoformat() for i in range(45)]
TODAY = date(2026, 12, 20)
MG1_LOOKED = "2026-12-14T00:00:00Z"
TRANSFERRED = "2026-12-15T00:00:00Z"
FIXTURE_GIT_CONFIG = ("user.name=Fixture", "user.email=fixture@example.invalid", "commit.gpgSign=false")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------------------- S0 and S1

def _bound_s0_sha():
    """B-1's bound scorer sha, read from the bound rule block (no outcome is read)."""
    _, fields = b.read_rule(DESIGN)
    return fields["b_scorer_sha256"]


def _s0_bytes():
    src = Path(b.__file__).read_bytes()
    text = src.decode("utf-8")
    s0 = src if _sha(src) == _bound_s0_sha() else CONSTANT_LINE.sub(SENTINEL_LINE, text, count=1).encode("utf-8")
    assert _sha(s0) == _bound_s0_sha(), "cannot reconstruct the bound S0 scorer bytes"
    return s0


def _s0_s1(tmp_path, recorded=None):
    """S0 = the bound scorer bytes; S1 = S0 with the one permitted constant line set to the MG-1 entry sha."""
    s0 = _s0_bytes()
    recorded = recorded or mg1_look.module_sha256()  # what the dated MG-1 scoring clarification records
    s1 = CONSTANT_LINE.sub(f'MG1_LOOK_ENTRY_SHA256 = "{recorded}"\n', s0.decode("utf-8"), count=1).encode("utf-8")
    problems, got = entry_edit.s1_problems(s0, s1)
    assert problems == [] and got == recorded  # exactly the permitted edit
    folder = tmp_path / "scorer"
    folder.mkdir()
    (folder / "b_scorer_s0.py").write_bytes(s0)
    (folder / "b_scorer.py").write_bytes(s1)
    return folder / "b_scorer_s0.py", folder / "b_scorer.py"


def _load(path, name):
    """Import a temp copy of the scorer under its own name; ``module_sha256()`` is then the copy's bytes."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ----------------------------------------------------------------------------- the synthetic world

def _forward(seed=0, markets=b.MARKETS + ("denver",), dates=DATES, hours=(8, 14), better=0.25):
    rng = np.random.default_rng(seed)
    snaps, bands, labels, market, vec = [], [], [], [], []
    for d in dates:
        for m in markets:
            for h in hours:
                rk = f"{m}|{d}|{h}"
                snaps.append({"row_key": rk, "market": m, "date": d, "local_hour": h, "n_bands": 3,
                              "guidance_physical_floor": 60.0, "high_so_far": np.nan, "trusted_current_max": np.nan,
                              "captured_at_utc": f"{d}T{h:02d}:05:00Z"})
                for i, (kind, lo, hi) in enumerate((("lte", np.nan, 69.0), ("between", 70.0, 71.0),
                                                    ("gte", 72.0, np.nan))):
                    bands.append({"row_key": rk, "band_index": i, "kind": kind, "low": lo, "high": hi,
                                  "p_served": 1 / 3})
                win = int(rng.integers(0, 3))
                labels.append({"row_key": rk, "date": d, "market": m, "winner": win})
                q = rng.dirichlet([2, 2, 2])
                market += [{"row_key": rk, "band_index": i, "p_market_yes": float(q[i])} for i in range(3)]
                p = (1 - better) * q + better * np.eye(3)[win]
                vec += [{"row_key": rk, "band_index": i, "p": float(p[i])} for i in range(3)]
    return (pd.DataFrame(snaps), pd.DataFrame(bands), pd.DataFrame(labels), pd.DataFrame(market),
            pd.DataFrame(vec))


def _mg1_receipt(tmp_path, monkeypatch):
    """A receipt written by ``mg1_look``'s own code, ``__main__`` stood in as the registered entry point."""
    monkeypatch.setattr(mg1_look, "LOOK_ROOT", tmp_path / "_mg1_look")  # never the repository's data/
    with pytest.MonkeyPatch.context() as m:
        main = types.ModuleType("__main__")
        main.__spec__ = types.SimpleNamespace(name=mg1_look.MODULE, origin=mg1_look.__file__)
        m.setitem(sys.modules, "__main__", main)
        m.setattr(mg1_look, "_utc_now", lambda: MG1_LOOKED)
        m.setattr(mg1_look, "head_commit", lambda root=None: "a" * 40)
        look = mg1_look.Look(MG1_RULE)
        look.join_outcomes(lambda: None)
        result = tmp_path / "_mg1_look" / "mg1_result.json"
        result.write_text("{}", encoding="utf-8")
        return look.finish(result=result, dates=DATES)


def _world(tmp_path, monkeypatch, *, s0_sha, control_sha):
    """Every B-1 look input, consistent with a binding at ``s0_sha``; the control receipt at ``control_sha``."""
    from tests.git_template import commit_fixture_tree
    from weather.model import observed_running_max

    repo = tmp_path / "repo"
    for rel in mg2.RELEASE_FILES:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, repo / rel)
    commit = commit_fixture_tree(repo, cache_root=tmp_path / "git-templates", config=FIXTURE_GIT_CONFIG,
                                 message="binding fixture", quiet=True)
    mg2_fields = {"switch_hour": "13", "d0": D0.isoformat(), "n_forward_dates": "45", "owner_decision_id": "NONE",
                  "l6_coefficients_sha256": "4" * 64, "p3d_n_state_sha256": "5" * 64,
                  "forecast_high_source": "captured_nbm_v2_mean_07z", "own_obs_source": "captured_metar_l6_own",
                  "function_sha256": mg2.sha256_file(observed_running_max.__file__),
                  "noninferiority_margin_00_16": "0.0010"}
    mg2_rule = tmp_path / "mg2_rule.md"
    mg2_rule.write_text("```mg2_rule_v1\n" + "\n".join(f"{k}: {v}" for k, v in mg2_fields.items()) + "\n```\n",
                        encoding="utf-8")
    mg2_sha, _ = mg2.read_rule(mg2_rule)
    binding = tmp_path / "release-binding.json"
    binding.write_text(json.dumps({"schema": mg2.RELEASE_BINDING_SCHEMA, "rule_sha256": mg2_sha,
                                   "files": mg2.release_hashes(repo), "l6_state_sha256": "7" * 64,
                                   **{k: mg2_fields[k] for k in ("l6_coefficients_sha256", "p3d_n_state_sha256",
                                                                 "forecast_high_source", "own_obs_source",
                                                                 "function_sha256")}}), encoding="utf-8")

    snaps, bands, labels, market, vec = _forward()
    layout = tmp_path / "layout"
    layout.mkdir()
    snaps.to_parquet(layout / data.SNAPSHOTS_FILE, index=False)
    bands.to_parquet(layout / data.BANDS_FILE, index=False)
    emit = tmp_path / "emit"
    emit.mkdir()
    vectors = emit / mg2.ASOF_VECTORS
    vec.to_parquet(vectors, index=False)
    (emit / mg2.EMIT_AUDIT).write_text(json.dumps({
        "mode": "forward", "asof_capture": {"vectors_sha256": mg2.sha256_file(vectors)},
        "l6_coefficients_sha256": "4" * 64, "p3d_n_state_sha256": "5" * 64, "nowcasts_sha256": "9" * 64,
        "l6_state_sha256": "7" * 64,
        "nowcasts_manifest": {"nowcasts_sha256": "9" * 64, "l6_state_sha256": "7" * 64,
                              "prev_day_source": mg2.FORWARD_PREV_DAY_SOURCE}}), encoding="utf-8")
    (tmp_path / "mg2").mkdir()
    mg2_look = tmp_path / "mg2" / "mg2_look.json"
    mg2_look.write_text(json.dumps({
        "gate": {"verdict": "PASS"}, "rule_sha256": mg2_sha, "vectors_sha256": mg2.sha256_file(vectors),
        "void_conditions": {name: {"pass": True, "detail": "ok"} for name in mg2.SECTION7_CONDITIONS},
        "pre_look_reads": []}), encoding="utf-8")

    receipt = _mg1_receipt(tmp_path, monkeypatch)
    transfer = tmp_path / "transfer"
    transfer.mkdir()
    labels.to_parquet(transfer / "labels.parquet", index=False)
    market.to_parquet(transfer / "market.parquet", index=False)
    (transfer / b.TRANSFER_MANIFEST).write_text(json.dumps({
        "schema": b.TRANSFER_SCHEMA, "transferred_at_utc": TRANSFERRED,
        "mg1_look_receipt_sha256": b.sha256_file(receipt),
        "dates": [{"date": d, "promotion_countable": True} for d in DATES],
        "files": {n: b.sha256_file(transfer / n) for n in b.TRANSFER_FILES}}), encoding="utf-8")
    drop = tmp_path / "drop.json"
    drop.write_text(json.dumps({"schema": b.DROP_LIST_SCHEMA, "dropped": []}), encoding="utf-8")
    control = tmp_path / "control" / b.CONTROL
    control.parent.mkdir()
    control.write_text(json.dumps({"schema": b.CONTROL_SCHEMA, "verdict": "PASS", "b_scorer_sha256": control_sha,
                                   "scorecard_code_sha256": sc.code_sha256()}), encoding="utf-8")

    fields = dict(b.RULE_CONSTANTS, mg2_rule_sha256=mg2_sha, mg2_binding_commit=commit,
                  mg2_release_binding_sha256=mg2.sha256_file(binding), mg2_owner_decision_id="NONE",
                  l6_coefficients_sha256="4" * 64, l6_state_sha256="7" * 64, p3d_n_state_sha256="5" * 64,
                  function_sha256=mg2_fields["function_sha256"], b_scorer_sha256=s0_sha,
                  scorecard_code_sha256=sc.code_sha256(), d0=D0.isoformat(), d0_latest="2026-11-02")
    rule = tmp_path / "b1.md"
    rule.write_text(f"# Rule B-1 (synthetic)\n\n```{b.RULE_BLOCK}\n"
                    + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n```\n", encoding="utf-8")
    return dict(rule=rule, mg2_rule=mg2_rule, release_binding=binding, layout_root=layout, vectors=vectors,
                mg2_look=mg2_look, transfer=transfer, drop_list=drop, control_receipt=control,
                mg1_look_receipt=receipt, out=tmp_path / "out", today=TODAY, root=repo)


def _set_constant(text, name, value):
    new, n = re.subn(rf"^{name} = .*$", f"{name} = {value}", text, count=1, flags=re.M)
    assert n == 1, name
    return new


def _wrapper_copy(tmp_path, *, entry_pin, rule_pin, accept_s0=False):
    """The wrapper's own source with its rule and entry pins set for this synthetic world (nothing monkeypatched)."""
    text = Path(wrapper.__file__).read_bytes().decode("utf-8")
    text = _set_constant(text, "MG1_LOOK_ENTRY_PIN", f'"{entry_pin}"')
    text = _set_constant(text, "B1_RULE_SHA256", f'"{rule_pin}"')
    if accept_s0:
        text = _set_constant(text, "ACCEPT_S0_CONTROL", "True")
    folder = tmp_path / "wrapper_copy"
    folder.mkdir(exist_ok=True)
    path = folder / f"b_look_wrapper_{_sha(text.encode('utf-8'))[:12]}.py"
    path.write_bytes(text.encode("utf-8"))
    return _load(path, path.stem)


def _spent(tmp_path, args):
    """Every one-look marker that exists: the fixed root, beside the transfer, beside mg2_look.json."""
    fixed = sorted((tmp_path / "_b_look").glob("*")) if (tmp_path / "_b_look").exists() else []
    beside = [p for p in (args["transfer"] / b.CONSUMED, args["mg2_look"].parent / b.CONSUMED) if p.exists()]
    return fixed + beside


def _s1_world(tmp_path, monkeypatch, control="s1", recorded=None, entry_pin=None, rule_pin=None, accept_s0=False):
    """The world, the S0 and S1 files, a wrapper copy pinned to it, and (when the pins verify) the verified scorer."""
    recorded = recorded or mg1_look.module_sha256()
    s0_path, s1_path = _s0_s1(tmp_path, recorded)
    s0_sha, s1_sha = _sha(s0_path.read_bytes()), _sha(s1_path.read_bytes())
    control_sha = {"s0": s0_sha, "s1": s1_sha}.get(control, control)
    args = _world(tmp_path, monkeypatch, s0_sha=s0_sha, control_sha=control_sha)
    w = _wrapper_copy(tmp_path, entry_pin=entry_pin or recorded, rule_pin=rule_pin or _sha(args["rule"].read_bytes()),
                      accept_s0=accept_s0)
    try:
        scorer = w.load_verified_scorer(rule=args["rule"], s0=s0_path, s1=s1_path)
    except w.WrapperRefused:
        scorer = None
    else:
        assert scorer.module_sha256() == s1_sha != s0_sha
        monkeypatch.setattr(scorer, "CONSUMED_ROOT", tmp_path / "_b_look")  # a path, never a sha
    return types.SimpleNamespace(w=w, scorer=scorer, s0=s0_path, s1=s1_path, s0_sha=s0_sha, s1_sha=s1_sha,
                                 args=args)


def _wrapper_receipt(args):
    return json.loads((args["out"] / wrapper.RECEIPT).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- the look as prescribed

@pytest.mark.spawns
def test_b_look_end_to_end_rule_at_s0_scorer_at_s1_control_at_s1_scores(tmp_path, monkeypatch):
    """The look day as B-1 and its 2026-10-26 clarification prescribe it reaches a verdict, not a VOID, when it
    runs through the pinned look wrapper of B-1 Clarification 3 (the red form of this test ran ``b_scorer.look``
    directly and was VOID [2, 3])."""
    x = _s1_world(tmp_path, monkeypatch)  # control re-run at S1 (B-1 clarification of 2026-10-26 section 4)

    out = x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)  # through look_guard

    decision = out["decision"]
    assert decision["verdict"] != "VOID", f"deterministic VOID: {decision}"
    assert decision["verdict"] == "PASS" and out["surviving_dates"] == 45
    assert out["b_scorer_sha256"] == x.s1_sha
    receipt = _wrapper_receipt(x.args)
    assert receipt["entry_edit"]["s0_sha256"] == x.s0_sha and receipt["entry_edit"]["s1_sha256"] == x.s1_sha
    assert receipt["entry_edit"]["mg1_look_entry_sha256"] == mg1_look.module_sha256()
    assert receipt["entry_edit"]["b_scorer_entry_edit_sha256"] == wrapper.B_SCORER_ENTRY_EDIT_SHA256
    assert receipt["wrapper"]["source_sha256"] == x.w.module_sha256()
    assert receipt["preflight"]["inputs"]["control_made_at_b_scorer_sha256"] == x.s1_sha
    assert receipt["b_decision"]["verdict"] == "PASS"
    assert b"\r\n" not in (x.args["out"] / wrapper.RECEIPT).read_bytes()
    assert len(_spent(tmp_path, x.args)) == 3  # the look is spent once it has scored
    with pytest.raises(x.w.WrapperRefused, match="exactly one look"):
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)


@pytest.mark.spawns
def test_an_edited_rule_cannot_start_a_second_look(tmp_path, monkeypatch):
    """look_guard's fixed marker is keyed on the rule's raw sha; the wrapper refuses any rule but the pinned one."""
    x = _s1_world(tmp_path, monkeypatch)
    assert x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)["decision"]["verdict"] == "PASS"
    x.args["rule"].write_bytes(x.args["rule"].read_bytes() + b"\n")  # a new raw sha, the same fields
    with pytest.raises(x.w.WrapperRefused, match="not the bound B-1 rule"):
        x.w.look(s0=x.s0, s1=x.s1, **dict(x.args, out=tmp_path / "out2"))


@pytest.mark.spawns
def test_the_control_at_s0_is_refused_by_default(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch, control="s0")
    with pytest.raises(x.w.WrapperRefused, match=r"preflight: VOID conditions \[3\]"):
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert _spent(tmp_path, x.args) == [] and not x.args["out"].exists()


@pytest.mark.spawns
def test_the_control_at_s0_is_accepted_only_under_masters_option(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch, control="s0", accept_s0=True)
    out = x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert out["decision"]["verdict"] == "PASS"
    assert _wrapper_receipt(x.args)["wrapper"]["accept_s0_control"] is True


@pytest.mark.spawns
def test_the_wrapper_restores_the_scorer_checks(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch)
    before = (x.scorer.bound_hash_problems, x.scorer.control_problems)
    x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert (x.scorer.bound_hash_problems, x.scorer.control_problems) == before


# ----------------------------------------------------------------------------- D4-1 pinned on the direct path

@pytest.mark.spawns
def test_d4_1_direct_scorer_look_at_s1_is_void_2_and_3_and_spends_the_look(tmp_path, monkeypatch):
    s0_path, s1_path = _s0_s1(tmp_path)
    scorer = _load(s1_path, "b_scorer_s1_copy")
    monkeypatch.setattr(scorer, "CONSUMED_ROOT", tmp_path / "_b_look")
    args = _world(tmp_path, monkeypatch, s0_sha=_sha(s0_path.read_bytes()), control_sha=scorer.module_sha256())
    out = scorer.look(**args)
    assert out["decision"]["verdict"] == "VOID" and out["decision"]["conditions"] == [2, 3]
    assert "b_scorer_sha256" in out["decision"]["reasons"]["2"]
    assert "control ran at another scorer sha" in out["decision"]["reasons"]["3"]
    assert len(_spent(tmp_path, args)) == 3  # the mechanical VOID spent the one look


@pytest.mark.spawns
def test_d4_1_direct_scorer_look_left_at_s0_is_void_5(tmp_path, monkeypatch):
    s0_path, _ = _s0_s1(tmp_path)
    scorer = _load(s0_path, "b_scorer_s0_copy")
    s0_sha = scorer.module_sha256()
    assert s0_sha == _bound_s0_sha() and scorer.MG1_LOOK_ENTRY_SHA256 == scorer.MG1_LOOK_ENTRY_UNRECORDED
    monkeypatch.setattr(scorer, "CONSUMED_ROOT", tmp_path / "_b_look")
    args = _world(tmp_path, monkeypatch, s0_sha=s0_sha, control_sha=s0_sha)
    out = scorer.look(**args)
    assert out["decision"]["verdict"] == "VOID" and out["decision"]["conditions"] == [5]


# ----------------------------------------------------------------------------- refusals before look_guard spend nothing

@pytest.mark.spawns
def test_the_wrapper_refuses_a_scorer_left_at_s0_without_consuming(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch)
    with pytest.raises(x.w.WrapperRefused, match="S1 is identical to S0"):
        x.w.look(s0=x.s0, s1=x.s0, **x.args)
    assert _spent(tmp_path, x.args) == [] and not x.args["out"].exists()


@pytest.mark.spawns
def test_the_wrapper_refuses_an_s1_with_any_other_edit_without_consuming(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch)
    x.s1.write_bytes(x.s1.read_bytes().replace(b'NAME = "b_scorer"', b'NAME = "b_scorer2"', 1))
    with pytest.raises(x.w.WrapperRefused, match="not an entry-edit-verified S1"):
        x.w.look(s0=x.s0, s1=x.s1, **x.args)
    with pytest.raises(x.w.WrapperRefused, match="not an entry-edit-verified S1"):  # a scorer loaded before the edit
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert _spent(tmp_path, x.args) == []


@pytest.mark.spawns
def test_the_wrapper_refuses_an_s0_that_is_not_the_bound_scorer(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch)
    fake = tmp_path / "fake_s0.py"
    fake.write_bytes(x.s0.read_bytes() + b"\n")
    with pytest.raises(x.w.WrapperRefused, match="not the bound b_scorer_sha256"):
        x.w.look(s0=fake, s1=x.s1, **x.args)
    assert _spent(tmp_path, x.args) == []


@pytest.mark.spawns
def test_the_entry_pin_must_match_what_s1_records(tmp_path, monkeypatch):
    """M1: S1 cannot be re-edited to whatever MG-1's receipt says; the recorded sha is pinned in the wrapper."""
    x = _s1_world(tmp_path, monkeypatch, entry_pin="d" * 64)
    assert x.scorer is None
    with pytest.raises(x.w.WrapperRefused, match="other than the pinned MG1_LOOK_ENTRY_PIN"):
        x.w.look(s0=x.s0, s1=x.s1, **x.args)
    assert _spent(tmp_path, x.args) == [] and not x.args["out"].exists()


@pytest.mark.spawns
def test_the_rule_pin_must_match(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch, rule_pin="0" * 64)
    with pytest.raises(x.w.WrapperRefused, match="not the bound B-1 rule"):
        x.w.look(s0=x.s0, s1=x.s1, **x.args)
    assert _spent(tmp_path, x.args) == []


def test_the_repository_wrapper_pins_are_the_bound_values():
    """Reads only the bound rule file and the checker's bytes (no outcome)."""
    assert wrapper.B1_RULE_SHA256 == _sha(DESIGN.read_bytes())
    assert wrapper.B_SCORER_S0_SHA256 == _bound_s0_sha()
    assert wrapper.B_SCORER_ENTRY_EDIT_SHA256 == _sha(Path(entry_edit.__file__).read_bytes())
    assert wrapper.MG1_LOOK_ENTRY_PIN == wrapper.PIN_UNSET and wrapper.ACCEPT_S0_CONTROL is False


@pytest.mark.spawns
def test_a_void_3_is_refused_by_the_preflight_and_the_look_stays_unspent(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch, control="e" * 64)
    with pytest.raises(x.w.WrapperRefused, match=r"preflight: VOID conditions \[3\]"):
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert _spent(tmp_path, x.args) == [] and not x.args["out"].exists()
    # the control re-receipted at the verified S1: the same look now runs once and scores
    receipt = json.loads(x.args["control_receipt"].read_text(encoding="utf-8"))
    x.args["control_receipt"].write_text(json.dumps(dict(receipt, b_scorer_sha256=x.s1_sha)), encoding="utf-8")
    assert x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)["decision"]["verdict"] == "PASS"


@pytest.mark.spawns
def test_a_void_2_on_a_non_scorer_hash_is_the_scorers_own_rule_and_spends_nothing(tmp_path, monkeypatch):
    """mg2_look.json's rule sha differs: the preflight's VOID 2 is exactly ``bound_hash_problems``' list."""
    x = _s1_world(tmp_path, monkeypatch)
    look = json.loads(x.args["mg2_look"].read_text(encoding="utf-8"))
    x.args["mg2_look"].write_text(json.dumps(dict(look, rule_sha256="0" * 64)), encoding="utf-8")
    _, fields = x.scorer.read_rule(x.args["rule"])
    own = x.scorer.bound_hash_problems(dict(fields, b_scorer_sha256=x.s1_sha), mg2_rule=x.args["mg2_rule"],
                                       release_binding=x.args["release_binding"], mg2_look=x.args["mg2_look"],
                                       vectors=x.args["vectors"], root=x.args["root"])
    assert own == ["mg2_look.rule_sha256"]
    with pytest.raises(x.w.WrapperRefused, match=r"preflight: VOID conditions \[2\]") as refused:
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert repr(own) in str(refused.value)
    assert _spent(tmp_path, x.args) == [] and not x.args["out"].exists()


# ----------------------------------------------------------------------------- VOIDs that still spend the look

@pytest.mark.spawns
def test_a_substantive_void_still_spends_the_look_through_the_wrapper(tmp_path, monkeypatch):
    """VOID 4 (a recorded pre-look read) is not in the preflight: b_scorer records it and the look is spent."""
    x = _s1_world(tmp_path, monkeypatch)
    look = json.loads(x.args["mg2_look"].read_text(encoding="utf-8"))
    x.args["mg2_look"].write_text(json.dumps(dict(look, pre_look_reads=["labels 2026-11-01"])), encoding="utf-8")
    out = x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert out["decision"]["verdict"] == "VOID" and out["decision"]["conditions"] == [4]
    assert len(_spent(tmp_path, x.args)) == 3


@pytest.mark.spawns
def test_a_void_5_entry_mismatch_spends_the_look(tmp_path, monkeypatch):
    """S1 and the pin record one entry sha, MG-1's receipt carries another: VOID 5, spent, not a refusal."""
    x = _s1_world(tmp_path, monkeypatch, recorded="c" * 64)
    out = x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert out["decision"]["verdict"] == "VOID" and out["decision"]["conditions"] == [5]
    assert len(_spent(tmp_path, x.args)) == 3
    assert _wrapper_receipt(x.args)["b_decision"]["conditions"] == [5]


@pytest.mark.spawns
def test_an_abort_after_the_look_is_consumed_writes_an_aborted_wrapper_receipt(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch)

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(x.scorer, "mg2_void_problems", boom)  # runs after look_guard, never in the preflight
    with pytest.raises(RuntimeError, match="boom"):
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    receipt = _wrapper_receipt(x.args)
    assert receipt["b_decision"]["verdict"] == "ABORTED" and "boom" in receipt["b_decision"]["error"]
    assert receipt["b_look_receipt_sha256"] == _sha((x.args["out"] / b.RECEIPT).read_bytes())
    assert len(_spent(tmp_path, x.args)) == 3


# ----------------------------------------------------------------------------- the repository wrapper and its CLI

def test_the_wrapper_without_an_mg1_receipt_refuses_first(tmp_path):
    with pytest.raises(wrapper.WrapperRefused, match="MG-1's look receipt does not exist"):
        wrapper.look(s0=tmp_path / "none.py", rule=tmp_path / "none.md", mg2_rule=None, release_binding=None,
                     layout_root=None, vectors=None, mg2_look=None, transfer=None, drop_list=None,
                     control_receipt=None, mg1_look_receipt=tmp_path / "absent.json", out=tmp_path / "out")


def _cli_args(tmp_path, receipt):
    s0 = tmp_path / "b_scorer_s0.py"
    s0.write_bytes(_s0_bytes())
    missing = tmp_path / "missing"
    return ["look", "--s0", str(s0), "--rule", str(DESIGN), "--mg2-rule", str(missing),
            "--release-binding", str(missing), "--layout", str(missing), "--vectors", str(missing),
            "--mg2-look", str(missing), "--transfer", str(missing), "--drop-list", str(missing),
            "--control-receipt", str(missing), "--mg1-look-receipt", str(receipt), "--out", str(tmp_path / "out")]


def test_the_cli_on_the_default_scorer_refuses_until_s1_is_pinned(tmp_path, capsys):
    """``main`` with the bound rule and S0, the checkout's scorer as S1: the UNSET pin refuses (exit 2)."""
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")  # only its existence is checked before the pins refuse
    assert wrapper.main(_cli_args(tmp_path, receipt)) == 2
    assert "MG1_LOOK_ENTRY_PIN is UNSET" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_the_cli_without_an_mg1_receipt_refuses(tmp_path, capsys):
    assert wrapper.main(_cli_args(tmp_path, tmp_path / "absent.json")) == 2
    assert "MG-1's look receipt does not exist" in capsys.readouterr().err


@pytest.mark.spawns
def test_the_running_scorer_is_executed_from_the_verified_bytes(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch)
    assert x.scorer is not b and x.scorer.__name__.startswith("weather.calibration._b_scorer_s1_")
    assert x.scorer.MG1_LOOK_ENTRY_SHA256 == mg1_look.module_sha256()
    assert Path(x.scorer.__file__) == x.s1
    assert getattr(x.scorer, "B_LOOK_WRAPPER_ENTRY_EDIT")["s1_sha256"] == x.s1_sha


def test_the_wrapper_touches_no_b_bound_file():
    """The wrapper is a new module; b_scorer.py stays the bound S0 bytes (or S0 plus the one constant line)."""
    src = Path(b.__file__).read_bytes()
    if _sha(src) != _bound_s0_sha():
        s0 = CONSTANT_LINE.sub(SENTINEL_LINE, src.decode("utf-8"), count=1).encode("utf-8")
        assert entry_edit.s1_problems(s0, src)[0] == []
    assert Path(wrapper.__file__).name == "b_look_wrapper.py"
    assert Path(wrapper.__file__).resolve() not in {(ROOT / rel).resolve() for rel in mg2.RELEASE_FILES}


# ----------------------------------------------------------------------------- concurrency and the rule bytes

@pytest.mark.spawns
def test_a_held_lock_refuses_a_second_run_on_the_same_out_and_spends_nothing(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch)
    x.args["out"].mkdir()
    (x.args["out"] / wrapper.LOCK).write_text("{}\n", encoding="utf-8")  # a run in flight on this --out
    with pytest.raises(x.w.WrapperRefused, match="another wrapper run holds this --out"):
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert _spent(tmp_path, x.args) == []
    assert sorted(p.name for p in x.args["out"].iterdir()) == [wrapper.LOCK]  # the other run's lock is untouched


@pytest.mark.spawns
def test_the_look_reads_a_private_rule_copy_and_releases_the_lock(tmp_path, monkeypatch):
    """The caller's rule path is read once; b_scorer.look gets the copy inside --out, so a later edit of the
    caller's file cannot reach look_guard."""
    x = _s1_world(tmp_path, monkeypatch)
    seen, original = {}, x.scorer.look

    def look_after_the_caller_edits_the_rule(**kwargs):
        x.args["rule"].write_bytes(x.args["rule"].read_bytes() + b"\nedited after the pins were checked\n")
        seen["rule"] = kwargs["rule"]
        return original(**kwargs)

    monkeypatch.setattr(x.scorer, "look", look_after_the_caller_edits_the_rule)
    out = x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert out["decision"]["verdict"] == "PASS"
    assert Path(seen["rule"]) == x.args["out"] / wrapper.RULE_COPY
    receipt = _wrapper_receipt(x.args)
    assert receipt["rule_copy"]["unchanged"] and receipt["rule_copy"]["sha256_after_look"] == receipt["rule_sha256"]
    assert not (x.args["out"] / wrapper.LOCK).exists()


@pytest.mark.spawns
def test_a_rule_copy_changed_during_the_look_is_recorded_and_raised(tmp_path, monkeypatch):
    x = _s1_world(tmp_path, monkeypatch)
    original = x.scorer.look

    def look_then_tamper(**kwargs):
        payload = original(**kwargs)
        Path(kwargs["rule"]).write_bytes(b"tampered")
        return payload

    monkeypatch.setattr(x.scorer, "look", look_then_tamper)
    with pytest.raises(RuntimeError, match="changed while b_scorer.look ran"):
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    receipt = _wrapper_receipt(x.args)
    assert receipt["rule_copy"]["unchanged"] is False and receipt["b_decision"]["verdict"] == "PASS"
    assert not (x.args["out"] / wrapper.LOCK).exists()


@pytest.mark.spawns
@pytest.mark.parametrize("whose", ["another_out", "before_this_call"])
def test_an_abort_after_another_run_consumed_the_look_is_not_attributed_to_this_call(tmp_path, monkeypatch, whose):
    """Overlapping runs: B sees A's fixed marker. Only a marker naming this call's --out, consumed at or after this
    call started, makes this call's failure an ABORTED look."""
    x = _s1_world(tmp_path, monkeypatch)

    def another_run_consumed_then_this_one_fails(**kwargs):
        fixed = x.scorer.rule_marker(_sha(Path(kwargs["rule"]).read_bytes()))
        fixed.parent.mkdir(parents=True, exist_ok=True)
        marker = {"out": str((tmp_path / "out_of_run_a").resolve()), "consumed_at_utc": "2999-01-01T00:00:00+00:00"}
        if whose == "before_this_call":
            marker = {"out": str(Path(kwargs["out"]).resolve()), "consumed_at_utc": "2000-01-01T00:00:00+00:00"}
        fixed.write_text(json.dumps(marker), encoding="utf-8")
        raise x.scorer.BRefused("the B look was already consumed: exactly one look")

    monkeypatch.setattr(x.scorer, "look", another_run_consumed_then_this_one_fails)
    with pytest.raises(x.scorer.BRefused):
        x.w.look(s0=x.s0, s1=x.s1, scorer=x.scorer, **x.args)
    assert not (x.args["out"] / wrapper.RECEIPT).exists()
    assert not (x.args["out"] / wrapper.LOCK).exists()
