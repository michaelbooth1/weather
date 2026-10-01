# 95d bulk inventory: where it lives and how to fetch it

Owner decision 8 of the 2026-09-26 repo-health audit keeps the 95d bulk files off `master`. This directory carries
the small evidence files and [`SHA256SUMS.txt`](SHA256SUMS.txt), which still hashes all twelve files. The four bulk
files live only in commit `8c683766d26fe0aec4c1b38334532e6e49e619d4` on branch
`codex/weather-market-universe-20260924` (the branch must be kept or archive-tagged, never deleted bare):

| File | Bytes |
| --- | --- |
| `markets.csv` | 23,867,601 |
| `events.csv` | 2,001,359 |
| `families.json` | 611,023 |
| `book_samples.json` | 522,030 |

Fetch and verify into the ignored data root (`data/research/weather-market-universe-20260924/`):

```powershell
git fetch origin codex/weather-market-universe-20260924
.\venv\Scripts\python.exe tools\weather_market_universe.py fetch-evidence
.\venv\Scripts\python.exe tools\weather_market_universe.py verify
```

`fetch-evidence` copies the tracked files, reads the bulk files from the pinned commit, and fails unless every file
matches `SHA256SUMS.txt`. `rebuild` also writes to the data root by default, so a rebuild never re-adds bulk files
here. [`README.md`](README.md) is the unchanged, hashed data dictionary; where it says the committed inventory, read
the fetched copy.
