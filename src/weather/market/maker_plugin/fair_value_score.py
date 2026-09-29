"""Frozen T+1/T+2 scoring CLI; local bundle IO belongs to the caller layer."""
from weather.market.maker_fair_value_score import main


if __name__ == "__main__":
    raise SystemExit(main())
