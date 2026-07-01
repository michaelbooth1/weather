"""Retired compatibility wrapper for the canonical model/market disagreement analysis."""

from __future__ import annotations

try:
    from .research_harness import retired_stub_main
except ImportError:
    from research_harness import retired_stub_main


RESEARCH_STATUS = "retired"


def main(argv=None) -> int:
    return retired_stub_main(
        __file__,
        argv,
        description=(
            "Retired compatibility wrapper; use "
            "python -m weather.reporting.candidate_lifecycle.model_market_disagreement_analysis."
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
