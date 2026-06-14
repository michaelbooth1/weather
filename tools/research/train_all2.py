import subprocess
import sys
import os

markets = ["toronto", "nyc", "chicago", "atlanta", "miami"]
env = os.environ.copy()
env["PYTHONPATH"] = "src"

for market in markets:
    print(f"\n========================================")
    print(f"Running feature_model.py for {market}...")
    try:
        subprocess.run([sys.executable, "src/feature_model.py", "--market", market], check=True, env=env)
    except subprocess.CalledProcessError as e:
        print(f"Failed feature_model.py for {market}: {e}")

print("All done!")
