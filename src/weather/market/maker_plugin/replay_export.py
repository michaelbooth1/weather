"""CLI facade; filesystem orchestration belongs outside the pure weather providers."""
from weather.market.maker_replay_night import main


if __name__ == "__main__":
    raise SystemExit(main())
