"""15분 단위 주차 점유 대수(그 시각에 입차했고 아직 출차 안 한 차량)를 계산해 공연일과 평소를 비교한다."""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
io = pd.read_pickle(D / "inout_2025.pkl")
io = io[(io["in_ts"].dt.year == 2025) & (io["out_ts"] >= io["in_ts"])]
io = io[(io["out_ts"] - io["in_ts"]) < pd.Timedelta("2D")]
last_day = io["out_ts"].max().floor("D")
full = pd.date_range("2025-01-01", last_day - pd.Timedelta("15min"), freq="15min")

ins = io["in_ts"].dt.floor("15min").value_counts().reindex(full, fill_value=0)
outs = io["out_ts"].dt.floor("15min").value_counts().reindex(full, fill_value=0)
occ = (ins.cumsum() - outs.cumsum()).shift(1, fill_value=0) + ins
occ.to_frame("occ").to_pickle(D / "occupancy_2025.pkl")

ev = pd.read_csv(D / "events_2025.csv")
ev_day = ev.groupby("date")["audience"].max()
ev_day.index = pd.to_datetime(ev_day.index).date

f = occ.to_frame("occ")
f["date"] = f.index.date
f["weekend"] = f.index.dayofweek >= 5
f["event"] = f["date"].isin(set(ev_day.index))
daymax = f.groupby(["date", "weekend", "event"])["occ"].max().reset_index()
print("일별 최대 점유 대수 분포:")
print(daymax.groupby(["weekend", "event"])["occ"].describe(percentiles=[.5, .9]).round(0).to_string())
print("\n연중 최대 점유 상위 1% 값:", int(np.percentile(f["occ"], 99)), " 최댓값:", int(f["occ"].max()))

em = daymax[daymax["event"]].copy()
em["audience"] = em["date"].map(ev_day)
print("\n공연일 최대 점유 vs 관람객 상관:", round(em[["occ", "audience"]].corr().iloc[0, 1], 2))
em["aud_bin"] = pd.cut(em["audience"], [0, 5000, 10000, 15000, 30000])
print(em.groupby("aud_bin", observed=True)["occ"].describe(percentiles=[.5]).round(0).to_string())
