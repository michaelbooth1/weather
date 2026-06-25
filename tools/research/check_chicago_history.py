"""Retired Chicago historical probe.

Use maintained package reports for current promotion and disagreement evidence.
"""

from __future__ import annotations

import argparse


RESEARCH_STATUS = "retired"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Retired Chicago historical probe.")
    parser.parse_args(argv)
    print(
        "check_chicago_history.py is retired. Use `python -m weather.reporting.promotion.promotion_refresh` "
        "and `python -m weather.reporting.casebooks.disagreement_casebook` for current diagnostics."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
