"""Rule B-1 end to end: the rule bound at S0, the scorer at S1, one look through ``look_guard``.

Guards finding D4-1 of the 2026-11-01 formal review (adversarially confirmed by master): B's single look is a
deterministic VOID as built. B-1 binds ``b_scorer_sha256`` = S0 (``B_FORWARD_TEST_DESIGN.md`` b_rule_v1 block); the
only permitted post-binding scorer edit sets ``MG1_LOOK_ENTRY_SHA256`` (S0 to S1, B-1 clarification of 2026-10-26
section 4, checked by ``b_scorer_entry_edit``); that clarification says the control is re-run at S1 and the look runs
at S1. Run directly, ``b_scorer.look`` then fires VOID 2 (``module_sha256()`` is S1, the rule says S0) and VOID 3 (the
control ran at S1, the rule says S0); left at S0 it fires VOID 5 (the sentinel matches no receipt).

Everything here is synthetic and lives under ``tmp_path``: a temp copy of the scorer edited to S1 by exactly the
permitted constant line, a fixture git commit holding the MG-2 release files, a receipt written by ``mg1_look``
running as the registered entry point, a synthetic transfer and drop list, and the one-look markers. No sha
constant is monkeypatched: S1 carries the recorded MG-1 entry sha in its own bytes, and the rule carries S0.
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


def _s0_s1(tmp_path):
    """S0 = the bound scorer bytes; S1 = S0 with the one permitted constant line set to the MG-1 entry sha."""
    src = Path(b.__file__).read_bytes()
    text = src.decode("utf-8")
    s0 = src if _sha(src) == _bound_s0_sha() else CONSTANT_LINE.sub(SENTINEL_LINE, text, count=1).encode("utf-8")
    assert _sha(s0) == _bound_s0_sha(), "cannot reconstruct the bound S0 scorer bytes"
    recorded = mg1_look.module_sha256()  # what the dated MG-1 scoring clarification records
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
    """A receipt written by ``mg1_look`` running as the registered entry point (its clock reads MG1_LOOKED)."""
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


def _markers(scorer, args):
    rule_sha, _ = scorer.read_rule(args["rule"])
    return [scorer.rule_marker(rule_sha), *scorer.consumed_markers(args["transfer"], args["mg2_look"])]


# ----------------------------------------------------------------------------- the look as prescribed

@pytest.mark.spawns
def test_b_look_end_to_end_rule_at_s0_scorer_at_s1_control_at_s1_scores(tmp_path, monkeypatch):
    """The look day as B-1 and its 2026-10-26 clarification prescribe it must reach a verdict, not a VOID."""
    s0_path, s1_path = _s0_s1(tmp_path)
    s0_sha, s1_sha = _sha(s0_path.read_bytes()), _sha(s1_path.read_bytes())
    scorer = _load(s1_path, "b_scorer_s1_copy")
    assert scorer.module_sha256() == s1_sha != s0_sha
    monkeypatch.setattr(scorer, "CONSUMED_ROOT", tmp_path / "_b_look")  # a path, never a sha
    args = _world(tmp_path, monkeypatch, s0_sha=s0_sha, control_sha=s1_sha)  # control re-run at S1 (B-1 cl. s4)

    out = scorer.look(**args)  # today's only look path: b_scorer look, through look_guard

    decision = out["decision"]
    assert decision["verdict"] != "VOID", f"deterministic VOID: {decision}"
    assert decision["verdict"] == "PASS" and out["surviving_dates"] == 45
