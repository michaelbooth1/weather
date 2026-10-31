"""Production serving with ``high_so_far_shadow_variant = None`` is byte-identical to master ``cda1acc3a``.

Guards: master's landing condition for the shadow-only high_so_far variant (ea449e9cc, f3b49fabb), relayed by
the coordinator on 2026-10-27. With the variant at its production value ``None``, the served output on captured
replay inputs must be byte-identical to master's serving path at ``cda1acc3a`` on every market. Also the
ratchet that no production module sets ``high_so_far_shadow_variant`` (see the test at the end).

Inputs: 36 captured ``replay_inputs.jsonl`` records of 2026-09-28 (all 12 built-in markets, the first snapshot
at or after 07:00, 10:00 and 14:00 host time), verbatim, in ``tests/fixtures/high_so_far_byte_identity``. No
outcome, label, price or settlement row is read. The served output of one record is ``served_output``: the
distribution, the active model kind, the calibration context, the component payload and the live features,
serialised canonically (``canonical_bytes``). The golden holds the sha256 of those bytes per record.

Environment, the same for the golden and the test: the record's captured sources, the tracked artifacts, an
empty data root (no local climatology history) and no active release pointer (``hermetic_model``). The tracked
HGB pickles are Git LFS objects. A checkout has them either materialized (the workstation and capture host) or
as pointers (CI, which runs ``lfs: false``), and serving differs between the two. So the golden has one tier per
state, each with the sha256 of every tracked artifact file it was made with. The test picks the tier whose
artifacts match the checkout byte for byte and fails, never skips, when neither does.

Regenerating the golden: run ``generate_golden`` against a checkout of the reference commit, through
``scripts/ops/workstation_heavy.ps1 -Kind pytest -Queue``, once per LFS state. It is not regenerated to make
this test pass: a moved output is a serving change and needs review.
"""
import gzip
import hashlib
import json
import math
import re
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "high_so_far_byte_identity"
RECORDS = FIXTURE / "records_2026-09-28.jsonl.gz"
GOLDEN = FIXTURE / "golden_cda1acc3a.json"
REFERENCE_COMMIT = "cda1acc3a7cb26142705464d65222e08794c9927"
GOLDEN_SCHEMA = "high_so_far_byte_identity_golden/1"
DAY = "2026-09-28"
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1\n"


# ----------------------------------------------------------------------------- shared with the generator

def _plain(value):
    """JSON-ready copy; refuses any type whose rendering could depend on the process (no ``repr`` fallback)."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(v) for v in value)
    item = getattr(value, "item", None)  # numpy scalars
    if callable(item) and type(value).__module__ == "numpy":
        return _plain(item())
    raise TypeError(f"served output holds an unserialisable {type(value).__name__}")


def canonical_bytes(payload):
    return json.dumps(_plain(payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_records(path=RECORDS):
    return [json.loads(line) for line in gzip.decompress(Path(path).read_bytes()).splitlines() if line.strip()]


def hermetic_model(market_id, empty_root, monkeypatch):
    """A serving model whose only inputs are the tracked artifacts and the captured sources."""
    from weather import paths
    from weather.release_serving import get_process_active_serving_bundle
    from weather.model.toronto_model import TorontoHighTempModel

    data = Path(empty_root) / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "DATA_ROOT", data)  # spec.data_root resolves through it at call time
    bundle = get_process_active_serving_bundle(pointer_path=Path(empty_root) / "no-release" / "current_release.json",
                                               releases_root=Path(empty_root) / "no-release")
    return TorontoHighTempModel(market_id=market_id, serving_bundle=bundle)


def served_output(model, record):
    from weather.backtesting.replay import parse_built_at, record_target_date

    sources = record.get("sources") or {}
    model.set_target_date(record_target_date(record))
    now = parse_built_at(record)
    result = model.estimate_distribution_result(sources, now=now)
    context = result.calibration_context or {}
    cutoff = context.get("cutoff_hour")
    features = model.extract_live_features(sources, cutoff, now=now) if cutoff is not None else None
    return {"distribution": result.distribution, "active_model_kind": result.active_model_kind,
            "calibration_context": context, "component_payload": result.component_payload,
            "features": features}


def tracked_artifacts(root):
    """sha256 of every artifact file the reference checkout tracks (the generator lists them with git)."""
    import subprocess

    names = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "artifacts"], check=True,
                           capture_output=True).stdout.decode("utf-8").split("\0")
    return {n: hashlib.sha256((Path(root) / n).read_bytes()).hexdigest() for n in sorted(names) if n}


def lfs_state(root, artifacts):
    pickles = [n for n in artifacts if re.fullmatch(r"artifacts/models/hgb/[^/]+\.pkl", n)]
    pointers = {(Path(root) / n).read_bytes()[:len(LFS_POINTER)] == LFS_POINTER for n in pickles}
    if pointers == {True}:
        return "lfs_pointers"
    if pointers == {False}:
        return "lfs_materialized"
    raise RuntimeError("the HGB pickles are partly materialized and partly LFS pointers")


def generate_golden(root, out, monkeypatch, tmp_path):
    """Write (or extend with one LFS-state tier) the golden from the checkout at ``root``; see the docstring."""
    import weather

    assert Path(weather.__file__).resolve().is_relative_to(Path(root).resolve() / "src"), weather.__file__
    artifacts = tracked_artifacts(root)
    state = lfs_state(root, artifacts)
    raw = gzip.decompress(RECORDS.read_bytes())
    models, outputs, kinds = {}, {}, {}
    for record in read_records():
        market = record["event_slug"].split("highest-temperature-in-")[1].split("-on-")[0]
        if market not in models:
            models[market] = hermetic_model(market, tmp_path / market, monkeypatch)
        payload = served_output(models[market], record)
        outputs[record["snapshot_id"]] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        kinds[record["snapshot_id"]] = [market, payload["active_model_kind"]]
    golden = json.loads(Path(out).read_text(encoding="utf-8")) if Path(out).is_file() else {
        "schema": GOLDEN_SCHEMA, "reference_commit": None, "day": DAY,
        "records_sha256": hashlib.sha256(raw).hexdigest(), "tiers": {}}
    assert golden["records_sha256"] == hashlib.sha256(raw).hexdigest()
    golden["reference_commit"] = REFERENCE_COMMIT
    golden["tiers"][state] = {"artifacts_sha256": artifacts, "served_output_sha256": outputs,
                              "market_and_model_kind": kinds}
    Path(out).write_bytes((json.dumps(golden, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    return state


# ----------------------------------------------------------------------------- the test

def _checkout_tier(golden):
    """The tier whose artifact files match this checkout's byte for byte, else a failure naming the drift."""
    drift = {}
    for state, tier in golden["tiers"].items():
        moved = [n for n, sha in tier["artifacts_sha256"].items()
                 if not (ROOT / n).is_file() or hashlib.sha256((ROOT / n).read_bytes()).hexdigest() != sha]
        if not moved:
            return state, tier
        drift[state] = moved[:5] + ([f"... {len(moved) - 5} more"] if len(moved) > 5 else [])
    pytest.fail(f"no golden tier matches this checkout's tracked artifacts (artifacts moved since "
                f"{golden['reference_commit']}): {drift}")


def test_the_fixture_is_one_captured_day_on_every_built_in_market():
    from weather.market.market_registry import BUILTIN_SPECS

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    raw = gzip.decompress(RECORDS.read_bytes())
    assert golden["schema"] == GOLDEN_SCHEMA and golden["reference_commit"] == REFERENCE_COMMIT
    assert hashlib.sha256(raw).hexdigest() == golden["records_sha256"]
    records = read_records()
    assert {str(r["target_date"])[:10] for r in records} == {DAY} and DAY <= "2026-09-29"
    markets = {r["event_slug"].split("highest-temperature-in-")[1].split("-on-")[0] for r in records}
    assert markets == {spec.id for spec in BUILTIN_SPECS} and len(markets) == 12
    assert set(golden["tiers"]) == {"lfs_pointers", "lfs_materialized"}
    for tier in golden["tiers"].values():
        assert set(tier["served_output_sha256"]) == {r["snapshot_id"] for r in records}


def test_variant_none_serves_byte_identical_output_to_master(tmp_path, monkeypatch):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    state, tier = _checkout_tier(golden)
    models, differ = {}, []
    for record in read_records():
        market = record["event_slug"].split("highest-temperature-in-")[1].split("-on-")[0]
        if market not in models:
            models[market] = hermetic_model(market, tmp_path / market, monkeypatch)
            assert models[market].high_so_far_shadow_variant is None
        payload = served_output(models[market], record)
        assert payload["active_model_kind"] == tier["market_and_model_kind"][record["snapshot_id"]][1]
        if hashlib.sha256(canonical_bytes(payload)).hexdigest() != tier["served_output_sha256"][record["snapshot_id"]]:
            differ.append(f"{market} {record['snapshot_id']}")
    assert differ == [], f"served output differs from {REFERENCE_COMMIT} ({state}) on {differ}"


def test_a_moved_output_is_caught(tmp_path, monkeypatch):
    """The comparison is sensitive: one ulp in one probability changes the bytes."""
    record = read_records()[0]
    market = record["event_slug"].split("highest-temperature-in-")[1].split("-on-")[0]
    payload = served_output(hermetic_model(market, tmp_path, monkeypatch), record)
    key = max(payload["distribution"], key=payload["distribution"].get)
    moved = dict(payload, distribution=dict(payload["distribution"]))
    moved["distribution"][key] = math.nextafter(moved["distribution"][key], 2.0)
    assert canonical_bytes(moved) != canonical_bytes(payload)
    with pytest.raises(TypeError):
        canonical_bytes({"x": object()})


# ----------------------------------------------------------------------------- no production setter

VARIANT_ATTRIBUTE = "high_so_far_shadow_variant"
# Every src/ module allowed to assign the attribute, each with its reason. Nothing else may, so no capture,
# serving or release entry point can turn the shadow on.
ALLOWED_SETTERS = {
    "src/weather/model/model_base.py": "the class default, and it must stay exactly None",
    "src/weather/calibration/high_so_far_parity_shadow.py": "the research shadow replay: sets the variant on "
                                                            "its own model instance and resets it to None",
}


def variant_assignments(source, name="<src>"):
    """``(line, value-or-None)`` for every assignment of the attribute: ``x.attr = v``, annotated or augmented
    assignment, a bare ``attr = v`` (a class body), and ``setattr(x, "attr", v)``."""
    import ast

    found = []
    for node in ast.walk(ast.parse(source, filename=name)):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            for t in ast.walk(target):
                if (isinstance(t, ast.Attribute) and t.attr == VARIANT_ATTRIBUTE) or (
                        isinstance(t, ast.Name) and t.id == VARIANT_ATTRIBUTE):
                    found.append((node.lineno, getattr(node, "value", None)))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setattr"
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == VARIANT_ATTRIBUTE):
            found.append((node.lineno, node.args[2] if len(node.args) > 2 else None))
    return found


def _setters(root=ROOT):
    out = {}
    for path in sorted((root / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if VARIANT_ATTRIBUTE in text:
            found = variant_assignments(text, str(path))
            if found:
                out[path.relative_to(root).as_posix()] = found
    return out


def test_no_production_module_sets_the_shadow_variant():
    import ast

    setters = _setters()
    assert set(setters) <= set(ALLOWED_SETTERS), f"unexpected setters: {sorted(set(setters) - set(ALLOWED_SETTERS))}"
    default = setters["src/weather/model/model_base.py"]
    assert len(default) == 1 and isinstance(default[0][1], ast.Constant) and default[0][1].value is None
    assert setters["src/weather/calibration/high_so_far_parity_shadow.py"]  # still the one research setter


def test_the_setter_ratchet_catches_a_planted_assignment(tmp_path):
    nl = chr(10)
    for planted in ('model.high_so_far_shadow_variant = "metar_running_max_since_midnight_v1"',
                    'setattr(model, "high_so_far_shadow_variant", VARIANT)',
                    nl.join(['class M:', '    high_so_far_shadow_variant: str = "x"']),
                    'a = model.high_so_far_shadow_variant = None',
                    'model.high_so_far_shadow_variant += "x"'):
        assert variant_assignments(planted + nl), planted
    assert variant_assignments(nl.join(['if model.high_so_far_shadow_variant is None:', '    pass', ''])) == []
    assert variant_assignments('x = model.high_so_far_shadow_variant' + nl) == []
    root = tmp_path / "repo"
    (root / "src/weather/collection").mkdir(parents=True)
    (root / "src/weather/collection/snapshot_tracker.py").write_text(nl.join([
        "def build(model):", "    model.high_so_far_shadow_variant = 'metar_running_max_since_midnight_v1'", ""]),
        encoding="utf-8")
    assert set(_setters(root)) == {"src/weather/collection/snapshot_tracker.py"}
    assert not set(_setters(root)) <= set(ALLOWED_SETTERS)
