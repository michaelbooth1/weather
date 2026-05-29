# Toronto Weather Market

Projects the settlement of Polymarket **"highest temperature in Toronto on
&lt;date&gt;"** markets for Toronto Pearson (CYYZ). It pulls live weather from
several sources, blends an empirical climatology prior with a feature-based ML
model, and surfaces the model's bucket distribution against live market prices
in a Streamlit dashboard. Market resolution is modeled as the highest
whole-degree Celsius value that Wunderground/Weather.com history prints for
CYYZ on the target date.

## Setup

Requires Python 3.11+.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

`scikit-learn` is pinned exactly because `src/feature_model_hgb.pkl` is a
pickled model and will not unpickle across versions.

## Run the dashboard

```powershell
.\venv\Scripts\python.exe -m streamlit run app.py
```

The dashboard auto-selects today's Toronto market. Override the target date
with the `TORONTO_MARKET_DATE` env var (ISO format, e.g. `2026-05-29`).

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

## Configuration

| Env var | Purpose |
| --- | --- |
| `TORONTO_MARKET_DATE` | Override the target market date (ISO `YYYY-MM-DD`). Defaults to today in America/Toronto. |
| `WEATHER_COM_API_KEY` | Weather.com API key. Defaults to the public browser key. |

## Command-line tools

All run from the repo root with the venv interpreter:

```powershell
# Wunderground/Weather.com history: collect, rebuild, audit, climatology
.\venv\Scripts\python.exe -m src.wu_history backfill --start 2015-01-01 --end 2026-05-27
.\venv\Scripts\python.exe -m src.wu_history audit

# ECCC SWOB observation layer
.\venv\Scripts\python.exe -m src.eccc_swob_history run

# Forecast archive (migrate schema, backfill ECCC, learn source bias)
.\venv\Scripts\python.exe -m src.forecast_archive analyze <snapshot-folder>

# Capture market/model odds snapshots (one-shot or --loop)
.\venv\Scripts\python.exe -m src.snapshot_tracker --force

# Analytics over a snapshot tape
.\venv\Scripts\python.exe -m src.snapshot_analytics

# Calibrate empirical intraday blend weights
.\venv\Scripts\python.exe -m src.intraday_calibration

# Train the feature model + late-day continuation models
.\venv\Scripts\python.exe src\feature_model.py

# Data-quality audit (missing/sparse days, duplicates, impossible values)
.\venv\Scripts\python.exe src\data_auditor.py
```

## Data layout

```text
data/
  wunderground/cyyz/   # settlement-proxy history (raw/, hourly/, daily/, manifest)
  eccc_swob/cyyz/      # official station observations (non-resolution)
  metar/cyyz/          # aviation reports (sanity check)
  snapshots/<slug>/    # per-market odds + forecast tapes and analytics
```

Raw provider payloads (`data/**/raw/`) are regenerable and git-ignored; the
normalized `hourly/` and `daily/` artifacts are tracked.

## Documentation

- [ROADMAP.md](ROADMAP.md) — feature roadmap and audit history.
- [HISTORY_DATA_DESIGN.md](HISTORY_DATA_DESIGN.md) — the Wunderground history data layer.
