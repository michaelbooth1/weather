import sys,pathlib,weather,weather.paths as p,weather.backtesting.metar_v4_lockin_replay as m,weather.model.model_distribution_constants as c,weather.model.model_constants as k
W=pathlib.Path(r'C:\tmp\wt-b-replay')
D=pathlib.Path(r'C:\Users\micha\Desktop\github\weather\data')
print(sys.version.split()[0], p.__file__, m.__file__, p.REPO_ROOT, pathlib.Path(p.data_path()).resolve(), c.LATE_DAY_LOCKIN_ANCHOR_VERSION, k.ML_MODEL_VERSION)
assert pathlib.Path(p.__file__).resolve()==W/'src'/'weather'/'paths.py'
assert pathlib.Path(m.__file__).resolve()==W/'src'/'weather'/'backtesting'/'metar_v4_lockin_replay.py'
assert p.REPO_ROOT==W
assert pathlib.Path(p.data_path()).resolve()==D.resolve()
assert c.LATE_DAY_LOCKIN_ANCHOR_VERSION=='lockin-anchor-v4' and k.ML_MODEL_VERSION=='v0.5.11'
print('IMPORT-OK')
