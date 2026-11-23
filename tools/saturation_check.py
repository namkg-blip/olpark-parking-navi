"""출구 포화(15분 출차가 처리 한계에 근접) 지속 시간을 공연일과 평소로 비교한다."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
io = pd.read_pickle(D / "inout_2025.pkl")
io = io[io["out_ts"].dt.year == 2025]
last_day = io["out_ts"].max().date()
ev = pd.read_csv(D / "events_2025.csv")
ev_day = ev.groupby("date")["audience"].max()
ev_day.index = pd.to_datetime(ev_day.index).date
ev_day = ev_day[ev_day.index < last_day]

slot = io["out_ts"].dt.floor("15min")
full = pd.date_range("2025-01-01", pd.Timestamp(last_day) - pd.Timedelta("15min"), freq="15min")
s = slot.value_counts().reindex(full, fill_value=0)
f = s.to_frame("n")
f["date"] = f.index.date
f["hour"] = f.index.hour
f["weekend"] = f.index.dayofweek >= 5
f["event"] = f["date"].isin(set(ev_day.index))

CAP = 420
for thr in (0.6, 0.7, 0.8):
    t = CAP * thr
    eve = f[f["hour"] >= 17]
    sat = eve.assign(sat=eve["n"] >= t).groupby(["date", "weekend", "event"])["sat"].sum() * 15
    g = sat.groupby(level=["weekend", "event"]).agg(["mean", "median", lambda x: (x > 0).mean()])
    g.columns = ["평균 포화분", "중앙값 포화분", "포화 발생 비율"]
    print(f"\n임계 {int(t)}대/15분 ({thr:.0%}):\n", g.round(2).to_string())

# 시간대별 평균 곡선 (17시 이후)
curve = f[f["hour"] >= 15].groupby(["weekend", "event", f[f["hour"] >= 15].index.strftime("%H:%M")])["n"].mean().unstack(level=[0, 1]).round(0)
curve.columns = [f"{'주말' if w else '평일'}-{'공연' if e else '평소'}" for w, e in curve.columns]
print("\n15분 평균 출차 (15시 이후):\n", curve.iloc[::2].to_string())
curve.to_csv(D / "exit_curve_event_vs_normal.csv", encoding="utf-8-sig")
