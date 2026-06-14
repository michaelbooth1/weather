from market_registry import CHICAGO
from toronto_model import TorontoHighTempModel
import numpy as np
import sys
import os

# fix pythonpath for the imports to work
sys.path.insert(0, os.path.abspath("src"))
from toronto_model import TorontoHighTempModel

model = TorontoHighTempModel(market_id='chicago')
cache = model.historical_target_cache()
hits = []
for date, daily in cache['daily'].items():
    rows_day = cache['by_date'][date]
    temp_12 = [r['temp_c'] for r in rows_day if 660 <= r['minute_of_day'] <= 780]
    temp_7 = [r['temp_c'] for r in rows_day if 360 <= r['minute_of_day'] <= 480]
    if temp_12 and temp_7:
        t12 = np.max(temp_12)
        t7 = temp_7[-1]
        rise = t12 - t7
        if 80 <= t12 <= 84 and 12 <= rise <= 18:
            hits.append(daily['max_temp_c'])
print(f'Found {len(hits)} matching days. Mean high: {np.mean(hits):.1f}. 86+: {sum(1 for h in hits if h >= 86)/len(hits)*100:.1f}%')
