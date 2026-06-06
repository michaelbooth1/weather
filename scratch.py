import json

with open('locations.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

locations = [l for l in data['locations'] if l['country'] in ('Canada', 'United States') and l['id'] not in ('toronto', 'nyc')]

specs = []
for l in locations:
    var_name = l['id'].upper().replace('-', '_')
    wu_hist = l['settlement']['station_id'] + (":9:US" if l['country'] == "United States" else ":9:CA")
    coastal = l['id'] in ("miami", "seattle", "san-francisco", "los-angeles", "boston", "houston")
    spec = f"""{var_name} = MarketSpec(
    id="{l['id']}",
    city_label="{l['city']}",
    slug_prefix="{l['polymarket']['event_slug_prefix']}",
    timezone="{l['timezone']}",
    display_unit="{l['market_unit']}",
    wu_history_id="{wu_hist}",
    icao="{l['settlement']['station_id']}",
    lat={l['coordinates']['lat']},
    lon={l['coordinates']['lon']},
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo"),
    leading_obs="metar",
    coastal={coastal},
)"""
    specs.append(spec)

print("\n\n".join(specs))
ids = ["TORONTO", "NYC"] + [l['id'].upper().replace('-', '_') for l in locations]
print("\nREGISTRY = {spec.id: spec for spec in (" + ", ".join(ids) + ")}")
