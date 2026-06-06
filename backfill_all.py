import subprocess, time, os, sys

# List of new market ids (including any existing ones you want to backfill)
MARKETS = [
    "atlanta",
    "austin",
    "chicago",
    "dallas",
    "denver",
    "houston",
    "los-angeles",
    "miami",
    "san-francisco",
    "seattle",
    # Optional: existing markets for full history
    "toronto",
    "nyc",
]

# Define the overall backfill date range – from earliest known data to today
START_DATE = "2015-01-01"
END_DATE = "2026-06-06"  # today's date (adjust as needed)

PYTHON = os.path.join(os.getcwd(), "venv", "Scripts", "python.exe")
MODULE = "src.wu_history"

for market in MARKETS:
    cmd = [PYTHON, "-m", MODULE, "--market", market, "backfill", "--start", START_DATE, "--end", END_DATE]
    print(f"Running backfill for {market}...")
    try:
        subprocess.run(cmd, check=True)
        print(f"[DONE] Completed backfill for {market}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Backfill failed for {market}: {e}")
    # Simple rate limiting – pause 1 second between markets to avoid hammering the API
    time.sleep(1)

print("All backfills completed.")
