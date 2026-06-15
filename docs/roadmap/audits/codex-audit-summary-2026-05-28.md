# Codex Audit Summary (2026-05-28)

- Verification run: `.\venv\Scripts\python.exe -m pytest -q` passed with 24 tests.
- Verification run: `.\venv\Scripts\python.exe -m compileall -q app.py src tests`
  passed.
- Verification run: `.\venv\Scripts\python.exe -m src.eccc_swob_history compare`
  generated SWOB/WU comparison artifacts over 51 raw SWOB XML files, 51
  normalized hourly rows, 3 local daily summaries, and 2 scored target-window
  days.
- Verification run: `.\venv\Scripts\python.exe -m src.wu_history audit` passed,
  checking 533 WU hourly partitions against manifest row counts and checksums.
- Verification run: `.\venv\Scripts\python.exe src\data_auditor.py` found 3
  missing WU target-window days (`2000-06-01`, `2000-06-02`, `2000-06-03`) and
  1 sparse WU day (`2019-05-29`, 5 rows).
- Historical repo note: at the time of this 2026-05-28 audit,
  `C:\Users\micha\Desktop\github\weather` was not observed as a Git repository,
  so that audit used filesystem contents, generated artifacts, and runnable
  checks rather than commit history. Superseded by the 2026-05-31 audit, which
  observed a normal Git working tree with live snapshot files already modified.
