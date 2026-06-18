import json

from weather.paths import config_path

def main() -> int:
    with config_path("locations.json").open("r", encoding="utf-8") as f:
        data = json.load(f)

    locations = [
        item
        for item in data["locations"]
        if item["country"] in ("Canada", "United States") and item["id"] not in ("toronto", "nyc")
    ]

    specs = []
    for item in locations:
        var_name = item["id"].upper().replace("-", "_")
        wu_hist = item["settlement"]["station_id"] + (
            ":9:US" if item["country"] == "United States" else ":9:CA"
        )
        coastal = item["id"] in ("miami", "seattle", "san-francisco", "los-angeles", "boston", "houston")
        spec = f"""{var_name} = MarketSpec(
    id="{item['id']}",
    city_label="{item['city']}",
    slug_prefix="{item['polymarket']['event_slug_prefix']}",
    timezone="{item['timezone']}",
    display_unit="{item['market_unit']}",
    wu_history_id="{wu_hist}",
    icao="{item['settlement']['station_id']}",
    lat={item['coordinates']['lat']},
    lon={item['coordinates']['lon']},
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo"),
    leading_obs="metar",
    coastal={coastal},
)"""
        specs.append(spec)

    print("\n\n".join(specs))
    ids = ["TORONTO", "NYC"] + [item["id"].upper().replace("-", "_") for item in locations]
    print("\nREGISTRY = {spec.id: spec for spec in (" + ", ".join(ids) + ")}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
