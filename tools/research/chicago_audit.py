"""Retired Chicago live audit probe.

Use `python -m weather.reporting.promotion.promotion_refresh` for promotion evidence and
`python -m weather.reporting.casebooks.disagreement_casebook` for model-surprise cases.
"""

from __future__ import annotations

import argparse


RESEARCH_STATUS = "retired"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Retired Chicago live audit probe.")
    parser.parse_args(argv)
    print(
        "chicago_audit.py is retired. Use `python -m weather.reporting.promotion.promotion_refresh` "
        "and `python -m weather.reporting.casebooks.disagreement_casebook` for current diagnostics."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
