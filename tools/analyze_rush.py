"""2025 공연일 출차 러시 탐색(rush_2025.csv, 서비스에는 쓰지 않음)과 문 분석(gate_matrix_2025.csv, gate_stats_2025.csv)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

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

# ---------------------------------------------------------------------------
# 문(출입구) 분석. 주차 구역이 문별로 나뉘어 있어 "나갈 때 문을 고르는" 안내는 대부분 성립하지 않는다.
# (1) 입차 문 x 출차 문 행렬: 전체 기록(필터 없음) 기준 건수와 입차 문 기준 비율
# (2) 문별 공연일 저녁 출차 집중도: 유효 공연일마다 18:00부터 다음 날 03:00까지
#     그 문의 15분 출차 최고값을 구해 날짜들의 중앙값을 낸다. 공연 없는 유효일의 같은 값과 비교한다.
#     출차 대수는 통과량이며 대기 시간이 아니다.
# ---------------------------------------------------------------------------
allio = pd.read_pickle(D / "inout_2025.pkl")
allio["in_grp"] = allio["in_gate"].str.extract(r"^(.*?문)", expand=False).fillna(allio["in_gate"])
allio["out_grp"] = allio["out_gate"].str.extract(r"^(.*?문)", expand=False).fillna(allio["out_gate"])
mat = allio.groupby(["in_grp", "out_grp"]).size().rename("n").reset_index()
mat["in_total"] = mat.groupby("in_grp")["n"].transform("sum")
mat["pct_of_in_gate"] = (mat["n"] / mat["in_total"] * 100).round(2)
mat = mat.sort_values(["in_total", "n"], ascending=False).rename(columns={"in_grp": "in_gate", "out_grp": "out_gate"})
mat.to_csv(D / "gate_matrix_2025.csv", index=False, encoding="utf-8-sig")
wide = mat.pivot(index="in_gate", columns="out_gate", values="pct_of_in_gate").fillna(0).round(1)
print("\n입차 문 x 출차 문 (입차 문 기준 %):\n", wide.to_string())

MIX = ["동2문", "북2문", "남2문"]
in_mix = allio["in_grp"].isin(MIX)
print(f"\n세 문(동2·북2·남2) 입차 {in_mix.sum():,}대 중 세 문 밖 출차 {(in_mix & ~allio['out_grp'].isin(MIX)).sum():,}대,"
      f" 그중 서2문 출차 {(in_mix & (allio['out_grp'] == '서2문')).sum():,}대")

# 유효일(하루 출차 합계가 중앙값의 40% 이상)은 model_v2.py 와 같은 규칙
m = allio[(allio["in_ts"].dt.year == 2025) & (allio["out_ts"] >= allio["in_ts"])]
m = m[(m["out_ts"] - m["in_ts"]) < pd.Timedelta("2D")]
m = m[m["out_grp"].str.endswith("문")]
last = m["out_ts"].max().floor("D")
grid = pd.date_range("2025-01-01", last - pd.Timedelta(SLOT), freq=SLOT)
tot = m["out_ts"].dt.floor(SLOT).value_counts().reindex(grid, fill_value=0)
daily = tot.groupby(tot.index.date).sum()
valid = set(daily[daily >= daily.median() * 0.4].index)
evd = pd.read_csv(D / "events_2025.csv")
ev_dates = set(pd.to_datetime(evd["date"]).dt.date) & valid
per_gate = (m.assign(slot=m["out_ts"].dt.floor(SLOT)).groupby(["out_grp", "slot"]).size()
            .unstack(0).reindex(grid, fill_value=0).fillna(0))
lanes = allio[allio["out_gate"].str.contains("출구")].groupby("out_grp")["out_gate"].nunique()
ent_lanes = allio[allio["in_gate"].str.contains("입구") & allio["in_grp"].str.endswith("문")].groupby("in_grp")["in_gate"].nunique()

rows = []
for d in sorted(valid):
    t0 = pd.Timestamp(d) + pd.Timedelta("18h")
    w = per_gate.loc[t0:t0 + pd.Timedelta("9h") - pd.Timedelta(SLOT)]
    if len(w) < 36:
        continue
    for gname in per_gate.columns:
        rows.append({"date": d, "gate": gname, "event": d in ev_dates, "weekend": pd.Timestamp(d).dayofweek >= 5,
                     "peak15": int(w[gname].max()), "sum": int(w[gname].sum())})
gd = pd.DataFrame(rows)
e = gd[gd["event"]]
n_ = gd[~gd["event"]]
stats = pd.DataFrame({
    "exit_lanes": lanes,
    "entry_lanes": ent_lanes,
    "event_days": e.groupby("gate")["date"].nunique(),
    "event_evening_peak15_median": e.groupby("gate")["peak15"].median(),
    "event_evening_peak15_p90": e.groupby("gate")["peak15"].quantile(0.9).round(0),
    "event_evening_peak15_max": e.groupby("gate")["peak15"].max(),
    "event_weekday_peak15_median": e[~e["weekend"]].groupby("gate")["peak15"].median(),
    "event_weekend_peak15_median": e[e["weekend"]].groupby("gate")["peak15"].median(),
    "event_weekday_sum_median": e[~e["weekend"]].groupby("gate")["sum"].median(),
    "event_weekend_sum_median": e[e["weekend"]].groupby("gate")["sum"].median(),
    "normal_evening_peak15_median": n_.groupby("gate")["peak15"].median(),
    "normal_days": n_.groupby("gate")["date"].nunique(),
    "normal_weekend_days": n_[n_["weekend"]].groupby("gate")["date"].nunique().reindex(per_gate.columns, fill_value=0),
    "event_evening_share": (e.groupby("gate")["sum"].sum() / e["sum"].sum()).round(3),
})
stats["event_peak15_per_lane"] = (stats["event_evening_peak15_median"] / stats["exit_lanes"]).round(1)
stats["event_vs_normal_ratio"] = (stats["event_evening_peak15_median"] / stats["normal_evening_peak15_median"]).round(2)
# 공연 없는 유효일은 사실상 모두 평일이라(공연 없는 유효 주말 0일) 평소 값은 평일 평소로 읽고, 평일 공연일과의 배율을 따로 둔다
stats["event_weekday_vs_normal_ratio"] = (stats["event_weekday_peak15_median"] / stats["normal_evening_peak15_median"]).round(2)
stats["mixed_zone"] = stats.index.isin(MIX)
stats.index.name = "gate"
stats.to_csv(D / "gate_stats_2025.csv", encoding="utf-8-sig")
print(f"\n문별 공연일 저녁 출차 집중도 (유효 공연일 {len(ev_dates)}일, 18:00~다음 날 03:00, 15분 출차 최고값의 날짜 중앙값):\n",
      stats.to_string())
