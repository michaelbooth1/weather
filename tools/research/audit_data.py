from weather.market.market_registry import all_specs


def main() -> int:
    print("--- Data Audit ---")
    for spec in all_specs():
        base = spec.data_root / "daily"
        count = 0
        if base.exists():
            count = len(list(base.glob("*.csv")))
        print(f"{spec.id} ({spec.icao}): {count} days of data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
