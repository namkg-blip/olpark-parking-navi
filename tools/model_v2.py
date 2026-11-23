"""사례 기반 예측 모델: 2025 공연일 실측(출차 러시 해소 시간, 주차장 차는 시각, 최대 점유)을
요일 유형 x 관객 규모 구간별로 묶어 web/data/model.json 으로 내보낸다."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
SLOT = pd.Timedelta("15min")
REL = list(range(-8, 13))          # 최고점 기준 상대 슬롯 (-2시간 ~ +3시간)
AUD_BINS = [0, 5000, 10000, 15000, 40000]
AUD_LABELS = ["5천 명 이하", "5천~1만 명", "1만~1만5천 명", "1만5천 명 이상"]

io = pd.read_pickle(D / "inout_2025.pkl")
io = io[(io["in_ts"].dt.year == 2025) & (io["out_ts"] >= io["in_ts"])]
io = io[(io["out_ts"] - io["in_ts"]) < pd.Timedelta("2D")]
last_day = io["out_ts"].max().floor("D")
full = pd.date_range("2025-01-01", last_day - SLOT, freq=SLOT)

outs = io["out_ts"].dt.floor(SLOT).value_counts().reindex(full, fill_value=0)
ins = io["in_ts"].dt.floor(SLOT).value_counts().reindex(full, fill_value=0)
occ = pd.read_pickle(D / "occupancy_2025.pkl")["occ"].reindex(full)

f = pd.DataFrame({"out": outs, "in": ins, "occ": occ})
f["date"] = f.index.date
f["slot"] = f.index.hour * 4 + f.index.minute // 15
f["dow"] = f.index.dayofweek
f["weekend"] = f["dow"] >= 5
f["month"] = f.index.month

daily_total = f.groupby("date")["out"].sum()
valid_days = set(daily_total[daily_total >= daily_total.median() * 0.4].index)

ev = pd.read_csv(D / "events_2025.csv")
ev_day = ev.groupby("date").agg(audience=("audience", "max"), event=("event", "first"))
ev_day.index = pd.to_datetime(ev_day.index).date
ev_day = ev_day[[d in valid_days for d in ev_day.index]]
event_dates = set(ev_day.index)

out_by_day = f.pivot_table(index="date", columns="slot", values="out", aggfunc="sum")
in_by_day = f.pivot_table(index="date", columns="slot", values="in", aggfunc="sum")
occ_by_day = f.pivot_table(index="date", columns="slot", values="occ", aggfunc="last")
normal = [d for d in out_by_day.index if d not in event_dates and d in valid_days]
normal_ts = pd.to_datetime(pd.Series(normal))


def local_baseline(d, table=None):
    table = out_by_day if table is None else table
    ts = pd.Timestamp(d)
    near = [n for n, t in zip(normal, normal_ts) if t.dayofweek == ts.dayofweek and abs((t - ts).days) <= 21]
    if len(near) < 2:
        near = [n for n, t in zip(normal, normal_ts)
                if (t.dayofweek >= 5) == (ts.dayofweek >= 5) and abs((t - ts).days) <= 28]
    return table.loc[near].median()


cases = []
for d, r in ev_day.iterrows():
    act = out_by_day.loc[d]
    base = local_baseline(d)
    ratio_evening = (act - base).loc[68:95]                   # 17:00 이후 초과 출차
    if ratio_evening.isna().all():
        continue
    peak = int(ratio_evening.idxmax())
    if act[peak] - base[peak] < 25:
        continue
    clear = 0
    for s in range(peak + 1, 96):
        if act[s] <= base[s] * 1.3 + 10:
            clear = (s - peak) * 15
            break
    else:
        clear = (96 - peak) * 15
    o = occ_by_day.loc[d]
    day_max = float(o.loc[40:peak].max())                     # 10:00 ~ 최고점
    reach = next((s for s in range(40, peak + 1) if o[s] >= 0.8 * day_max), peak)
    in_exc = (in_by_day.loc[d] - local_baseline(d, in_by_day)).loc[max(0, peak - 24):peak - 4]
    arr_peak = int(in_exc.idxmax()) if not in_exc.isna().all() else peak - 12
    cases.append({
        "date": str(d), "event": r["event"], "audience": int(r["audience"]),
        "weekend": bool(pd.Timestamp(d).dayofweek >= 5),
        "peak_slot": peak, "peak_time": f"{peak // 4:02d}:{peak % 4 * 15:02d}",
        "clear_minutes": int(clear), "occ_max": int(day_max),
        "fill80_before_peak_min": int((peak - reach) * 15),
        "arrival_peak_before_exit_peak_min": int((peak - arr_peak) * 15),
        "arrival_peak_time": f"{arr_peak // 4:02d}:{arr_peak % 4 * 15:02d}",
        "rel_actual": [int(act.get(peak + k, 0)) if 0 <= peak + k < 96 else None for k in REL],
        "rel_base": [round(float(base.get(peak + k, 0)), 1) if 0 <= peak + k < 96 else None for k in REL],
        "actual_15_24": [int(act.get(s, 0)) for s in range(60, 96)],
        "base_15_24": [round(float(base.get(s, 0)), 1) for s in range(60, 96)],
    })
cases = pd.DataFrame(cases)
cases["aud_bin"] = pd.cut(cases["audience"], AUD_BINS, labels=AUD_LABELS)


def excess_of(rows):
    return np.nanmedian([[a - b if a is not None and b is not None else np.nan for a, b in zip(ra, rb)]
                         for ra, rb in zip(rows["rel_actual"], rows["rel_base"])], axis=0)


# 교차검증: 각 공연을 빼고 같은 요일 유형의 나머지 공연으로 만든 초과 프로파일로 그 공연을 예측
loo = []
for i, r in cases.iterrows():
    others = cases[(cases["weekend"] == r["weekend"]) & (cases.index != i)]
    ex = np.nan_to_num(excess_of(others))
    pred = [min(421, max(0, b + e)) if b is not None else None for b, e in zip(r["rel_base"], ex)]
    pairs = [(p, a) for p, a in zip(pred, r["rel_actual"]) if p is not None and a is not None]
    mae = np.mean([abs(p - a) for p, a in pairs])
    base_mae = np.mean([abs(b - a) for b, a in zip(r["rel_base"], r["rel_actual"]) if b is not None and a is not None])
    clear_others = others["clear_minutes"].median()
    loo.append({"mae": mae, "base_mae": base_mae, "clear_err": abs(clear_others - r["clear_minutes"]),
                "peak_err": abs(max(p for p, _ in pairs) - max(a for _, a in pairs))})
loo = pd.DataFrame(loo)
cases = pd.concat([cases, loo], axis=1)
validation = {
    "mae_15m": round(float(loo["mae"].median()), 1),
    "baseline_only_mae_15m": round(float(loo["base_mae"].median()), 1),
    "improvement_pct": round(float((1 - loo["mae"].median() / loo["base_mae"].median()) * 100), 0),
    "peak_err_med": round(float(loo["peak_err"].median()), 0),
    "clear_err_med": round(float(loo["clear_err"].median()), 0),
    "clear_within_15_pct": round(float((loo["clear_err"] <= 15).mean() * 100), 0),
}
print("교차검증:", validation)
cases.drop(columns=["rel_actual", "rel_base", "actual_15_24", "base_15_24"]).to_csv(D / "cases_2025.csv", index=False, encoding="utf-8-sig")

groups = []
for wk, g in cases.groupby("weekend"):
    ratio = np.nanmedian([[a / b if a is not None and b else np.nan for a, b in zip(ra, rb)]
                          for ra, rb in zip(g["rel_actual"], g["rel_base"])], axis=0)
    excess = np.nanmedian([[a - b if a is not None and b is not None else np.nan for a, b in zip(ra, rb)]
                           for ra, rb in zip(g["rel_actual"], g["rel_base"])], axis=0)
    groups.append({
        "weekend": bool(wk),
        "n": int(len(g)),
        "arrival_lead_med": int(g["arrival_peak_before_exit_peak_min"].median()),
        "peak_time_med": g["peak_time"].sort_values().iloc[len(g) // 2],
        "peak_exits_med": int(np.median([max(x for x in ra if x is not None) for ra in g["rel_actual"]])),
        "clear_med": int(g["clear_minutes"].median()), "clear_p75": int(g["clear_minutes"].quantile(0.75)),
        "fill80_med": int(g["fill80_before_peak_min"].median()),
        "occ_max_med": int(g["occ_max"].median()), "occ_max_p90": int(g["occ_max"].quantile(0.9)),
        "ratio_profile": [round(float(x), 2) for x in np.nan_to_num(ratio, nan=1.0)],
        "excess_profile": [round(float(x), 1) for x in np.nan_to_num(excess, nan=0.0)],
    })

base_month = (f[[d not in event_dates and d in valid_days for d in f["date"]]]
              .groupby(["month", "weekend", "slot"])["out"].median())
baseline = {f"{m}-{'we' if w else 'wd'}": base_month.loc[(m, w)].round(1).tolist()
            for m in sorted(f["month"].unique()) for w in (False, True) if (m, w) in base_month.index}

gates = pd.read_csv(D / "gate_stats_2025.csv", index_col=0).dropna()
gates = gates[gates.index.str.endswith("문")]
gates["load_ratio"] = gates["event_evening_share"] / (gates["cap_15m_p99"] / gates["cap_15m_p99"].sum())
gate_list = [{"name": n, "event_share": round(float(r.event_evening_share), 3), "cap15": int(r.cap_15m_p99),
              "load_ratio": round(float(r.load_ratio), 2)}
             for n, r in gates.sort_values("event_evening_share", ascending=False).iterrows()]

replay = [{k: (v if not isinstance(v, (np.integer, np.floating)) else v.item()) for k, v in c.items()
           if k in ("date", "event", "audience", "weekend", "peak_time", "clear_minutes", "occ_max",
                    "actual_15_24", "base_15_24", "peak_slot", "mae")}
          for c in cases.sort_values("date").to_dict("records")]

model = {
    "generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    "data_range": f"2025-01-01 ~ {(last_day - pd.Timedelta('1D')).date()}",
    "n_records": int(len(io)), "n_cases": int(len(cases)), "validation": validation,
    "rel_slots": REL, "peak_after_end_slots": 1,
    "full_occ_warn": int(np.nanpercentile(occ.dropna(), 99)),
    "exit_capacity_15m": int(gates["cap_15m_p99"].sum()),
    "groups": groups, "baseline": baseline, "gates": gate_list, "replay": replay,
    "venues": [
        {"name": "KSPO DOME (체조경기장)", "default_audience": 15000},
        {"name": "티켓링크 라이브 아레나 (핸드볼경기장)", "default_audience": 5000},
        {"name": "올림픽홀", "default_audience": 3000},
        {"name": "우리금융아트홀", "default_audience": 1200},
        {"name": "88잔디마당 (야외 페스티벌)", "default_audience": 10000},
        {"name": "뮤즈라이브", "default_audience": 500},
    ],
}
(ROOT / "docs" / "data").mkdir(parents=True, exist_ok=True)
(ROOT / "docs" / "data" / "model.json").write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")

print(f"유효일 {len(valid_days)}일, 공연일(유효) {len(event_dates)}일, 사례 {len(cases)}건")
print("만차 경고 기준(점유 상위 1%):", model["full_occ_warn"], "출구 처리 합계(15분):", model["exit_capacity_15m"])
print(pd.DataFrame(groups).drop(columns=["ratio_profile"]).to_string(index=False))
print("\n최고점 시각 분포(평일/주말):")
print(cases.groupby("weekend")["peak_time"].agg(lambda s: s.value_counts().head(5).to_dict()).to_string())
