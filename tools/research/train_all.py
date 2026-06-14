import subprocess
import sys
import os

sys.path.insert(0, os.path.abspath("src"))
from market_registry import REGISTRY
markets = list(REGISTRY.keys())
scripts = ["src/feature_model.py", "src/intraday_calibration.py"]

env = os.environ.copy()
env["PYTHONPATH"] = "src"

for market in markets:
    print(f"\n{'='*50}")
    print(f"TRAINING PIPELINE FOR: {market.upper()}")
    print(f"{'='*50}")
    for script in scripts:
        print(f"\n--- Running {script} for {market} ---")
        try:
            subprocess.run([sys.executable, script, "--market", market], check=True, env=env)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: {script} failed for {market}: {e}")
            sys.exit(1)

print("\nPIPELINE COMPLETED SUCCESSFULLY!")
