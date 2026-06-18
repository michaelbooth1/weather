"""Retired bulk training wrapper."""

from __future__ import annotations

import argparse


RESEARCH_STATUS = "retired"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Retired bulk training wrapper.")
    parser.parse_args(argv)
    print("train_all.py is retired. Use weather.operations.nightly_retrain or daily_refresh.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

