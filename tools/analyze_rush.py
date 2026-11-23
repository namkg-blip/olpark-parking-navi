"""2025 공연일 출차 러시 분석: 평일·주말 기준선 대비 초과 출차, 해소 시간, 출구별 분담."""
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
SLOT = "15min"

io = pd.read_pickle(D / "inout_2025.pkl")
io = io.dropna(subset=["out_ts"])
io = io[io["out_ts"].dt.year == 2025]
io["out_gate_grp"] = io["out_gate"].str.extract(r"^(.*?문)", expand=False).fillna(io["out_gate"])
io["in_gate_grp"] = io["in_gate"].str.extract(r"^(.*?문)", expand=False).fillna(io["in_gate"])

ev = pd.read_csv(D / "events_2025.csv")
ev["date"] = pd.to_datetime(ev["date"]).dt.date
ev_day = ev.groupby("date").agg(audience=("audience", "max"), event=("event", "first")).reset_index()
last_day = io["out_ts"].max().date()
ev_day = ev_day[ev_day["date"] < last_day]
event_dates = set(ev_day["date"])

io["slot"] = io["out_ts"].dt.floor(SLOT)
exits = io.groupby("slot").size().rename("exits").to_frame()
full = pd.date_range("2025-01-01", pd.Timestamp(last_day) - pd.Timedelta(SLOT), freq=SLOT)
exits = exits.reindex(full, fill_value=0)
exits["date"] = exits.index.date
exits["tod"] = exits.index.strftime("%H:%M")
exits["weekend"] = exits.index.dayofweek >= 5
exits["event_day"] = exits["date"].isin(event_dates)
exits["month"] = exits.index.month

exits["dow"] = exits.index.dayofweek
by_day = exits.pivot_table(index="date", columns="tod", values="exits", aggfunc="sum")
dates = pd.Series(pd.to_datetime(by_day.index), index=by_day.index)
normal = [d for d in by_day.index if d not in event_dates]
normal_ts = pd.to_datetime(pd.Series(normal))


def local_baseline(d):
    """같은 요일, 앞뒤 21일 이내, 공연 없는 날의 시간대별 중앙값."""
    ts = pd.Timestamp(d)
    near = [n for n, t in zip(normal, normal_ts)
            if t.dayofweek == ts.dayofweek and abs((t - ts).days) <= 21]
    if len(near) < 2:
        near = [n for n, t in zip(normal, normal_ts)
                if (t.dayofweek >= 5) == (ts.dayofweek >= 5) and abs((t - ts).days) <= 21]
    return by_day.loc[near].median()


base_rows = {d: local_baseline(d) for d in event_dates}
exits["baseline"] = [
    base_rows[d][t] if d in base_rows else np.nan for d, t in zip(exits["date"], exits["tod"])
]
exits["excess"] = exits["exits"] - exits["baseline"]

rows = []
for d in sorted(event_dates):
    day = exits[exits["date"] == d]
    eve = day[day.index.hour >= 17]
    thr = np.maximum(25, eve["baseline"] * 0.3).to_numpy()
    exc = eve["excess"].to_numpy()
    peak_i = int(np.argmax(exc))
    if exc[peak_i] <= thr[peak_i]:
        continue
    lo = peak_i
    while lo > 0 and exc[lo - 1] > thr[lo - 1]:
        lo -= 1
    hi = peak_i
    while hi < len(exc) - 1 and exc[hi + 1] > thr[hi + 1]:
        hi += 1
    hot = eve.iloc[lo:hi + 1]
    peak_ts = eve.index[peak_i]
    start, end = hot.index.min(), hot.index.max() + pd.Timedelta(SLOT)
    rows.append({
        "date": d,
        "weekend": bool(day["weekend"].iloc[0]),
        "peak_time": peak_ts.strftime("%H:%M"),
        "peak_exits_15m": int(eve["exits"].max()),
        "baseline_at_peak": float(eve.loc[peak_ts, "baseline"]),
        "surge_start": start.strftime("%H:%M"),
        "surge_end": end.strftime("%H:%M"),
        "clear_minutes": int((end - start).total_seconds() / 60),
        "excess_cars": int(hot["excess"].clip(lower=0).sum()),
    })
rush = pd.DataFrame(rows).merge(ev_day, on="date", how="left")
rush.to_csv(D / "rush_2025.csv", index=False, encoding="utf-8-sig")

print(f"공연일 {len(event_dates)}일 중 출차 러시 감지 {len(rush)}일")
print(rush[["peak_exits_15m", "clear_minutes", "excess_cars", "audience"]].describe().round(1).to_string())
c = rush[["audience", "excess_cars", "clear_minutes", "peak_exits_15m"]].corr().round(2)
print("\n상관계수:\n", c.to_string())
print("\n상위 10일:\n", rush.sort_values("excess_cars", ascending=False)
      .head(10)[["date", "weekend", "peak_time", "peak_exits_15m", "surge_start", "surge_end",
                 "clear_minutes", "excess_cars", "audience"]].to_string(index=False))

# 출구별 처리 능력: 15분 출차 수 상위 1% 값
io = io[io["out_gate_grp"].str.endswith("문")]
g = io.groupby(["out_gate_grp", "slot"]).size()
cap = g.groupby(level=0).quantile(0.99).round(0)
share_event = (io[io["slot"].dt.date.isin(event_dates) & (io["slot"].dt.hour >= 18)]
               ["out_gate_grp"].value_counts(normalize=True).round(3))
print("\n출구별 15분 처리량(상위 1%):\n", cap.sort_values(ascending=False).head(10).to_string())
print("\n공연일 18시 이후 출구 분담:\n", share_event.head(10).to_string())
pd.DataFrame({"cap_15m_p99": cap, "event_evening_share": share_event}).to_csv(
    D / "gate_stats_2025.csv", encoding="utf-8-sig")

