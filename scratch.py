"""Compatibility shim for the relocated market-spec generator."""

from pathlib import Path
import runpy


runpy.run_path(
    str(Path(__file__).resolve().parent / "tools" / "generate_market_specs_from_locations.py"),
    run_name="__main__",
)

