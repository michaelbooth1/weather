"""Summarise IEM RAOB raw CSVs -> per-sounding summary + market-day coverage. Development data only."""
import gzip, glob, os, json, hashlib, math, io, datetime as dt
import pandas as pd, numpy as np
D = r'C:\swarm\data\soundings'
MAP = {  # market -> ordered RAOB candidates (distance km computed from IEM geojson)
 'KATL': ['KFFC','KBMX'], 'KAUS': ['KCRP','KFWD'], 'KBKF': ['KGJT','KLBF'], 'KDAL': ['KFWD'],
 'KHOU': ['KLCH','KCRP'], 'KLAX': ['KNKX','KVBG','KEDW'], 'KLGA': ['KOKX'], 'KMIA': ['KMFL'],
 'KORD': ['KILX','KDVN'], 'KSEA': ['KUIL','KSLE'], 'KSFO': ['KOAK']}
AVAIL_LAG_MIN = 60  # stated basis: 12Z -> 13:00Z (NWS launch ~11Z, ~90-120 min flight; no per-object receipt time in IEM)
frames = []
for fn in sorted(glob.glob(os.path.join(D, 'raw', '*.csv.gz'))):
    df = pd.read_csv(gzip.open(fn), na_values=['M'])
    if len(df): frames.append(df)
raw = pd.concat(frames, ignore_index=True)
raw['validUTC'] = pd.to_datetime(raw['validUTC'], utc=True)
assert (raw['validUTC'] < pd.Timestamp('2026-09-30', tz='UTC')).all(), 'row dated >= 2026-09-30'
assert (raw['validUTC'] >= pd.Timestamp('2026-05-01', tz='UTC')).all()
rows = []
def at(g, p):
    m = g[np.isclose(g['pressure_mb'], p)]
    m = m.dropna(subset=['tmpc'])
    return (m['tmpc'].iloc[0], m['height_m'].iloc[0]) if len(m) else (np.nan, np.nan)
for (st, v), g in raw.groupby(['station', 'validUTC']):
    g = g.sort_values('pressure_mb', ascending=False)
    gt = g.dropna(subset=['tmpc', 'pressure_mb'])
    if not len(gt):
        continue
    sfc = gt.iloc[0]
    t925, z925 = at(g, 925); t850, z850 = at(g, 850); t700, z700 = at(g, 700); t500, z500 = at(g, 500)
    ps = sfc['pressure_mb']
    def adiab(t, p):  # dry-adiabatic descent of level-p air to surface pressure (C)
        return (t + 273.15) * (ps / p) ** 0.2857 - 273.15 if (not np.isnan(t) and ps > p) else np.nan
    # max potential temperature in lowest 300 hPa brought to surface pressure (mixed-layer upper bound proxy)
    low = gt[gt['pressure_mb'] >= ps - 300]
    th_sfc = ((low['tmpc'] + 273.15) * (ps / low['pressure_mb']) ** 0.2857 - 273.15).max()
    rows.append(dict(raob=st, valid_utc=v.isoformat(), synoptic_hour=v.hour,
        available_utc_basis=(v + pd.Timedelta(minutes=AVAIL_LAG_MIN)).isoformat(),
        n_levels=len(g), n_temp_levels=len(gt), sfc_pres_mb=ps, sfc_hgt_m=sfc['height_m'], sfc_tmpc=sfc['tmpc'], sfc_dwpc=sfc['dwpc'],
        t925c=t925, z925m=z925, t850c=t850, z850m=z850, t700c=t700, z700m=z700, t500c=t500, z500m=z500,
        t850_adiab_sfc_c=adiab(t850, 850), t925_adiab_sfc_c=adiab(t925, 925), max_theta_low300_at_sfc_c=th_sfc,
        top_pres_mb=gt['pressure_mb'].min()))
S = pd.DataFrame(rows)
for c in ['t850_adiab_sfc_c', 't925_adiab_sfc_c', 'max_theta_low300_at_sfc_c', 'sfc_tmpc']:
    S[c.replace('_c', '_f') if c.endswith('_c') else c + '_f'] = S[c] * 9 / 5 + 32
S.to_csv(os.path.join(D, 'soundings_summary.csv.gz'), index=False, compression='gzip')
# coverage per market-day. Local date D for every US market: 00Z on UTC date D = evening of D-1 local (prior-evening
# sounding, available ~01Z D); 12Z D = morning of D; 18Z D = midday of D (several offices moved the day launch to 18Z).
dates = pd.date_range('2026-05-01', '2026-09-29', freq='D')
vd = pd.to_datetime(S.valid_utc)
have = {h: set(zip(S.raob[S.synoptic_hour == h], vd[S.synoptic_hour == h].dt.date)) for h in (0, 12, 18)}
cov = []
for mk, cands in MAP.items():
    for d in dates:
        r = {'market': mk, 'date': d.date().isoformat()}
        for i, c in enumerate(cands):
            r[f'raob{i+1}'] = c
            for h in (0, 12, 18):
                r[f'raob{i+1}_{h:02d}z'] = (c, d.date()) in have[h]
        n = len(cands)
        r['primary_12z'] = r['raob1_12z']
        r['primary_12z_or_18z'] = r['raob1_12z'] or r['raob1_18z']
        r['any_12z'] = any(r[f'raob{i+1}_12z'] for i in range(n))
        r['any_12z_or_18z'] = any(r[f'raob{i+1}_12z'] or r[f'raob{i+1}_18z'] for i in range(n))
        r['any_00z_prior_evening'] = any(r[f'raob{i+1}_00z'] for i in range(n))
        cov.append(r)
C = pd.DataFrame(cov); C.to_csv(os.path.join(D, 'coverage_market_day.csv'), index=False)
cols = ['primary_12z', 'primary_12z_or_18z', 'any_12z', 'any_12z_or_18z', 'any_00z_prior_evening']
summ = C.groupby('market')[cols].sum()
W = C[C.date >= '2026-07-25'].groupby('market')[cols].sum().add_suffix('_0725_0929')
summ = summ.join(W); summ.insert(0, 'days', 152); summ.insert(6, 'days_0725_0929', 67)
summ.to_csv(os.path.join(D, 'coverage_summary.csv'))
pd.set_option('display.width', 250)
print(summ.to_string())
print(pd.crosstab(S.raob, S.synoptic_hour).to_string())
