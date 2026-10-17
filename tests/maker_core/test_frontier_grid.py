"""Item 330 build 3 (c): the frozen informed-v1 grid is deterministic, order-invariant and hashed."""
from decimal import Decimal as D
from pathlib import Path
import random

import pytest

from maker_core.frontier import grid
from weather.schema_registry import SCHEMA_LITERAL_RE

PINNED_GRID_HASH = "17b85a248542c45a886228a25f63dce78bf150f7ad5d5fc12e09d5e7643bd457"


def test_grid_hash_is_pinned():
    # A changed grid needs a new preregistration. Update this pin only alongside a new prereg draft.
    assert grid.GRID_HASH == PINNED_GRID_HASH == grid.grid_hash()
    assert len(grid.GRID) == 5 * 4 * 3 * 2 == 120


def test_grid_is_order_invariant():
    rng = random.Random(330)
    for _ in range(20):
        axes = {}
        for name, values in grid.AXES.items():
            shuffled = list(values) + list(values[:2])  # duplicates collapse too
            rng.shuffle(shuffled)
            axes[name] = shuffled
        assert grid.build(axes) == grid.GRID
        assert grid.grid_hash(grid.build(axes)) == PINNED_GRID_HASH
    shuffled = list(grid.GRID)
    rng.shuffle(shuffled)
    assert grid.grid_hash(shuffled) == PINNED_GRID_HASH


def test_any_change_changes_the_hash():
    smaller = dict(grid.AXES, size=(20, 30, 50))
    assert grid.grid_hash(grid.build(smaller)) != PINNED_GRID_HASH
    assert grid.grid_hash(grid.GRID[:-1]) != PINNED_GRID_HASH


def test_baselines_and_fixed_rules():
    assert grid.BASELINES == ("no-quote", "blind_re1", "informed-v0")
    assert grid.FIXED["centre"] == "size_qualified_mid" and grid.FIXED["skew"] == "none"
    manifest = grid.manifest()
    assert manifest["baselines"] == list(grid.BASELINES) and len(manifest["points"]) == 120
    assert grid.GRID[0] == grid.GridPoint(D("1.0"), 20, "depth_only", "hold_to_settlement")


@pytest.mark.parametrize("axes,reason", [
    (dict(grid.AXES, band_rule=("depth_only", "skew_to_model")), "unknown_band_rule"),
    (dict(grid.AXES, width_cents=("0.1",)), "width_out_of_range"),
    (dict(grid.AXES, size=(0,)), "size_out_of_range"),
    ({k: v for k, v in grid.AXES.items() if k != "inventory"}, "grid_axes_mismatch"),
])
def test_invalid_axes_are_refused(axes, reason):
    with pytest.raises(ValueError, match=reason):
        grid.build(axes)


def test_frontier_sources_carry_no_schema_registry_literals():
    root = Path(__file__).parents[2] / "src" / "maker_core" / "frontier"
    for path in root.glob("*.py"):
        assert not SCHEMA_LITERAL_RE.findall(path.read_text(encoding="utf-8")), path.name


def test_frontier_package_edges():
    """frontier imports only contracts, evidence, quoting, replay and itself; no other core module imports it."""
    import ast

    src = Path(__file__).parents[2] / "src" / "maker_core"
    allowed = ("maker_core.contracts", "maker_core.evidence", "maker_core.quoting", "maker_core.replay",
               "maker_core.frontier")
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and not n.level]
        names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        inside = path.parent.name == "frontier"
        for name in names:
            if inside and name.startswith("maker_core"):
                assert name.startswith(allowed), (path.name, name)
            if not inside:
                assert not name.startswith("maker_core.frontier"), (str(path), name)
