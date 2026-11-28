"""사례 기반 예측 모델: 2025 공연일 실측(출차 러시, 입차 집중, 주차 점유)을 요일 유형별로 묶어
docs/data/model.json 으로 내보낸다. 표본 탈락 내역은 data/sample_attrition_2025.md 로 남긴다.

정의(바꾸지 않음)
- 평소 기준선: 공연일마다 앞뒤 21일 안의 공연 없는 같은 요일 유효일의 구간별 중앙값.
  그런 날이 2일 미만이면 앞뒤 28일 안의 공연 없는 같은 요일 유형(평일/주말) 유효일로 대체한다.
- 출차 최고점: 17:00~23:45 중 (실제 출차 - 기준선)이 가장 큰 15분 구간. 그 초과가 25대 미만이면 사례에서 뺀다.
- 러시 지속: 최고점 구간 시작부터, 그 뒤 처음으로 출차가 (기준선 x 1.3 + 10대) 이하가 된 구간 시작까지의 시간.

2026-11-28 수정
- 출차 시계열을 다음 날 03:00 까지 이어 붙여 러시 종료를 잰다(이전에는 24:00 에서 끊겼다).
- 예측을 421대로 자르던 처리를 없앴다. 421은 한계가 아니다.
- 교차검증을 평일·주말로 나누고, 최고점 시각을 모르는 조건을 추가했다.

2026-11-29 수정
- build_events.py 가 줄바꿈 있는 공연명을 읽게 되면서 2025 공연일이 136일이 됐고, 공연 없는 유효 주말이 사실상 없어졌다.
  그래서 주말은 평소 기준선·초과·러시·교차검증을 하지 않고, 주말 공연일끼리의 실측 분포(저녁 최고 15분 출차,
  최고점 시각, 최고점의 절반 이상 출차가 이어진 시간)만 집계한다(weekend_obs). 기준선·교차검증·예측은 평일만.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
SLOT = pd.Timedelta("15min")
DAY = 96                           # 하루 15분 구간 수
EXT = 108                          # 당일 00:00 ~ 다음 날 03:00
REL = list(range(-8, 13))          # 최고점 기준 상대 구간 (-2시간 ~ +3시간)
PEAK_FROM = 68                     # 17:00
RUSH_RATIO, RUSH_ADD, MIN_EXCESS = 1.3, 10, 25
SENS = (1.5, 20)                   # 감도 확인용 러시 끝 기준(기준선 x 1.5 + 20대)
ARR_FROM, ARR_TO = 24, 4
# 2025년 공휴일(대체공휴일·임시공휴일 포함). 분석은 요일로만 평일/주말을 나누므로 평일 공휴일 사례를 표시만 한다
HOLIDAYS = {"2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30", "2025-03-01", "2025-03-03",
            "2025-05-05", "2025-05-06", "2025-06-03", "2025-06-06", "2025-08-15", "2025-10-03", "2025-10-05",
            "2025-10-06", "2025-10-07", "2025-10-08", "2025-10-09", "2025-12-25"}           # 입차 최고점을 찾는 창: 출차 최고점 24구간(6시간) 전 ~ 4구간(1시간) 전
OLD_CAP = 421                      # 폐기한 수치. 초과 구간 수를 기록하려고만 둔다
ZONE3 = ["동2문", "북2문", "남2문"]
ZONE3_SPACES = 2200                # 기관 주차 안내의 해당 구역 주차면 수
REPLAY_FROM = 60                   # 검증 화면 그래프 시작 15:00
PEAK_AFTER_END_SLOTS = 1           # 서비스가 쓰는 가정: 종료 시각이 속한 구간의 다음 구간이 최고점
HALF = 0.5                         # 기준선 없이 재는 지속: 최고점의 50% 이상 출차가 이어진 시간(주말 실측, 화면의 붐비는 구간)


def hhmm(slot):
    m = int(slot) * 15
    return f"{(m // 60) % 24:02d}:{m % 60:02d}" + (" (다음 날)" if m >= 1440 else "")


def dur_label(v):
    """지속 시간 표기 규칙: 측정 단위가 15분이므로 15의 배수면 'N분', 아니면 앞뒤 15분 눈금으로 '30~45분'."""
    v = float(v)
    if abs(v / 15 - round(v / 15)) < 1e-9:
        return f"{int(round(v))}분"
    lo = int(np.floor(v / 15) * 15)
    return f"{lo}~{lo + 15}분"


def q(s, p):
    return float(np.nanquantile(np.asarray(s, dtype=float), p))


io = pd.read_pickle(D / "inout_2025.pkl")
n_raw = len(io)
io = io[(io["in_ts"].dt.year == 2025) & (io["out_ts"] >= io["in_ts"])]
io = io[(io["out_ts"] - io["in_ts"]) < pd.Timedelta("2D")]
last_day = io["out_ts"].max().floor("D")
full = pd.date_range("2025-01-01", last_day - SLOT, freq=SLOT)

outs = io["out_ts"].dt.floor(SLOT).value_counts().reindex(full, fill_value=0)
ins = io["in_ts"].dt.floor(SLOT).value_counts().reindex(full, fill_value=0)
occ_df = pd.read_pickle(D / "occupancy_2025.pkl").reindex(full)

f = pd.DataFrame({"out": outs, "in": ins, "occ": occ_df["occ"], "occ3": occ_df["occ3"]})
f["date"] = f.index.date
f["slot"] = f.index.hour * 4 + f.index.minute // 15
f["weekend"] = f.index.dayofweek >= 5

daily_total = f.groupby("date")["out"].sum()
valid_cut = daily_total.median() * 0.4
valid_days = set(daily_total[daily_total >= valid_cut].index)
all_days = sorted(daily_total.index)

ev = pd.read_csv(D / "events_2025.csv")
ev["date"] = pd.to_datetime(ev["date"]).dt.date


def all_titles(s):
    """그날 표시된 공연명을 모두 적는다. 같은 시간대 공연은 연계 데이터가 'A, B'로 합쳐 표시하므로,
    다른 행의 공연명에 이미 들어 있는 이름은 빼고 ' / '로 잇는다."""
    names = list(dict.fromkeys(s))
    keep = [n for n in names if not any(n != m and n in m for m in names)]
    return " / ".join(keep)


# 관객 수: 연계 데이터의 그날 공연관람객수 최댓값. 같은 시간대에 공연이 여럿이면 연계 데이터가 공연명을 'A, B'로
# 합쳐 표시하고 관람객 수도 합친 값을 준다(예: 2025-03-01 11,575 + 4,578 = 16,153). 즉 같은 시간대 공연 관람객 합계다.
ev_all = ev.groupby("date").agg(audience=("audience", "max"), event=("event", all_titles),
                                first_hour=("first_hour", "min"), last_hour=("last_hour", "max"),
                                n_titles=("event", "nunique"))
# 관객 수 최댓값이 나온 행의 공연명이 'A, B'처럼 합쳐 표시된 날(같은 시간대 공연 합계가 관객 수가 된 날)
ev_all["aud_combined"] = ev.loc[ev.groupby("date")["audience"].idxmax()].set_index("date")["event"].str.contains(", ").reindex(ev_all.index)
ev_day = ev_all[[d in valid_days for d in ev_all.index]]
event_dates = set(ev_day.index)

out_by_day = f.pivot_table(index="date", columns="slot", values="out", aggfunc="sum")
in_by_day = f.pivot_table(index="date", columns="slot", values="in", aggfunc="sum")
occ_by_day = f.pivot_table(index="date", columns="slot", values="occ", aggfunc="last")
occ3_by_day = f.pivot_table(index="date", columns="slot", values="occ3", aggfunc="last")


def extend(table):
    """날짜별 96구간 표에 다음 날 00:00~03:00(12구간)을 이어 붙인다. 다음 날이 유효일이 아니면 비워 둔다."""
    nxt = table.shift(-1).iloc[:, :EXT - DAY]
    nxt_valid = [(pd.Timestamp(d) + pd.Timedelta("1D")).date() in valid_days for d in table.index]
    nxt = nxt.where(pd.Series(nxt_valid, index=table.index), np.nan, axis=0)
    nxt.columns = range(DAY, EXT)
    return pd.concat([table, nxt], axis=1)


out_ext = extend(out_by_day)
normal = [d for d in out_by_day.index if d not in event_dates and d in valid_days]
normal_ts = pd.to_datetime(pd.Series(normal))


def baseline_days(d):
    ts = pd.Timestamp(d)
    near = [n for n, t in zip(normal, normal_ts) if t.dayofweek == ts.dayofweek and abs((t - ts).days) <= 21]
    kind = "같은 요일 21일"
    if len(near) < 2:
        near = [n for n, t in zip(normal, normal_ts)
                if (t.dayofweek >= 5) == (ts.dayofweek >= 5) and abs((t - ts).days) <= 28]
        kind = "요일 유형 28일"
    return near, kind


# ---------------------------------------------------------------------------
# 사례 추출과 표본 탈락 기록
# ---------------------------------------------------------------------------
normal_we = [d for d in normal if pd.Timestamp(d).dayofweek >= 5]
valid_we = [d for d in valid_days if pd.Timestamp(d).dayofweek >= 5]


def half_len(act, peak):
    """기준선 없이 재는 지속: 최고점 구간 시작부터 출차가 최고점의 50% 이하가 된 첫 구간 시작까지(분)."""
    lim = act[peak] * HALF
    for s in range(peak + 1, EXT):
        if np.isnan(act[s]):
            return (s - peak) * 15, True
        if act[s] <= lim:
            return (s - peak) * 15, False
    return (EXT - peak) * 15, True


attr = []      # 연계 데이터 공연일 각각의 처리 결과
cases = []     # 평일 분석 사례(기준선 있음)
we_obs = []    # 주말 공연일 실측(기준선 없음)
late_peak = 0  # 자정 이후 초과가 17:00~23:45 최고점보다 큰 사례 수(정의는 그대로 두고 수만 센다)
for d, r in ev_all.iterrows():
    wk = bool(pd.Timestamp(d).dayofweek >= 5)
    rec = {"date": d, "weekend": wk, "month": pd.Timestamp(d).month, "dow": pd.Timestamp(d).dayofweek}
    if d not in daily_total.index:
        attr.append({**rec, "stage": "0 자료 구간 밖"})
        continue
    if d not in valid_days:
        attr.append({**rec, "stage": "1 유효일 아님(하루 출차 합계가 중앙값의 40% 미만)", "daily_out": int(daily_total[d])})
        continue
    if wk:
        act = out_ext.loc[d]
        peak = int(act.loc[PEAK_FROM:DAY - 1].idxmax())
        hl, hc = half_len(act, peak)
        we_obs.append({"date": str(d), "event": r["event"], "audience": int(r["audience"]), "peak_slot": peak,
                       "peak_time": hhmm(peak), "peak_exits": int(act[peak]), "half_minutes": int(hl), "half_censored": bool(hc),
                       "last_hour": int(r["last_hour"]), "lag_from_last_hour_min": int(peak * 15 - r["last_hour"] * 60),
                       "after_midnight_exits": None if np.isnan(act.loc[DAY:EXT - 1]).any() else int(act.loc[DAY:EXT - 1].sum()),
                       "act_ext": act.to_numpy(dtype=float)})
        attr.append({**rec, "stage": "2 주말(공연 없는 유효 주말이 없어 평소 기준선을 세울 수 없음, 실측 분포만 집계)"})
        continue
    near, kind = baseline_days(d)
    if not near:
        attr.append({**rec, "stage": "3 기준선 없음(앞뒤 28일 안에 공연 없는 평일 유효일이 없음)"})
        continue
    act = out_ext.loc[d]
    base = out_ext.loc[near].median()
    exc_eve = (act - base).loc[PEAK_FROM:DAY - 1]
    peak = int(exc_eve.idxmax())
    peak_excess = float(act[peak] - base[peak])
    if peak_excess < MIN_EXCESS:
        attr.append({**rec, "stage": f"4 초과 출차 최고점 {MIN_EXCESS}대 미만", "peak_excess": round(peak_excess, 1)})
        continue
    if np.nanmax((act - base).loc[DAY:EXT - 1].to_numpy(dtype=float), initial=-np.inf) > peak_excess:
        late_peak += 1

    def rush_len(limit):
        for s in range(peak + 1, limit):
            if np.isnan(act[s]) or np.isnan(base[s]):
                return (s - peak) * 15, True
            if act[s] <= base[s] * RUSH_RATIO + RUSH_ADD:
                return (s - peak) * 15, False
        return (limit - peak) * 15, True

    clear, censored = rush_len(EXT)
    clear_cut24, cut24 = rush_len(DAY)
    end_slot = peak + clear // 15
    end_threshold = (float(base[end_slot] * RUSH_RATIO + RUSH_ADD)
                     if end_slot < EXT and not np.isnan(base[end_slot]) else np.nan)

    def rush_len_alt(ratio, add):
        """감도 확인용: 러시 끝 기준만 바꿔 다시 잰다."""
        for s in range(peak + 1, EXT):
            if np.isnan(act[s]) or np.isnan(base[s]):
                return (s - peak) * 15, True
            if act[s] <= base[s] * ratio + add:
                return (s - peak) * 15, False
        return (EXT - peak) * 15, True

    clear_alt, censored_alt = rush_len_alt(*SENS)
    hl, hc = half_len(act, peak)
    end_s = peak + clear // 15
    exc_run = np.clip((act - base).loc[peak:end_s - 1].to_numpy(dtype=float), 0, None)
    first30 = float(exc_run[:2].sum() / exc_run.sum()) if exc_run.sum() > 0 else np.nan

    o = occ_by_day.loc[d]
    day_max = float(o.loc[40:peak].max())                     # 10:00 ~ 최고점
    reach = next((s for s in range(40, peak + 1) if o[s] >= 0.8 * day_max), peak)
    in_exc = (in_by_day.loc[d] - in_by_day.loc[near].median()).loc[max(0, peak - ARR_FROM):peak - ARR_TO]
    arr_peak = int(in_exc.idxmax()) if not in_exc.isna().all() else peak - 12
    cases.append({
        "date": str(d), "event": r["event"], "audience": int(r["audience"]), "weekend": wk,
        "peak_slot": peak, "peak_time": hhmm(peak),
        "peak_exits": int(act[peak]), "base_at_peak": round(float(base[peak]), 1),
        "peak_excess": round(peak_excess, 1), "peak_ratio": round(float(act[peak] / base[peak]), 2) if base[peak] else None,
        "clear_minutes": int(clear), "clear_censored": bool(censored),
        "clear_minutes_cut24": int(clear_cut24), "cut24_hit": bool(cut24),
        "rush_end_threshold": None if np.isnan(end_threshold) else round(end_threshold, 1),
        "clear_minutes_alt": int(clear_alt), "clear_alt_censored": bool(censored_alt),
        "rush_end_slot_alt": int(peak + clear_alt // 15),
        "rush_end_time": hhmm(peak + clear // 15),
        "rush_end_exits": None if end_s >= EXT or np.isnan(act[end_s]) else int(act[end_s]),
        "exits_plus60": None if peak + 4 >= EXT or np.isnan(act[peak + 4]) else int(act[peak + 4]),
        "excess_share_first30": None if np.isnan(first30) else round(first30, 3),
        "half_minutes": int(hl), "half_censored": bool(hc),
        "occ_max": int(day_max), "occ3_max": int(occ3_by_day.loc[d].loc[40:peak].max()),
        "fill80_before_peak_min": int((peak - reach) * 15),
        "arrival_peak_before_exit_peak_min": int((peak - arr_peak) * 15),
        "arrival_peak_time": hhmm(arr_peak),
        "base_kind": kind, "base_n_days": len(near),
        "last_hour": int(r["last_hour"]), "first_hour": int(r["first_hour"]),
        "lag_from_last_hour_min": int(peak * 15 - r["last_hour"] * 60),
        "act_ext": act.to_numpy(dtype=float), "base_ext": base.to_numpy(dtype=float),
    })
    attr.append({**rec, "stage": "5 분석 사례(평일)", "base_kind": kind})
attr = pd.DataFrame(attr)
cases = pd.DataFrame(cases)
we_obs = pd.DataFrame(we_obs)


def rel(arr, peak):
    return np.array([arr[peak + k] if 0 <= peak + k < EXT else np.nan for k in REL], dtype=float)


def excess_profile(rows):
    return np.nanmedian([rel(a, p) - rel(b, p) for a, b, p in zip(rows["act_ext"], rows["base_ext"], rows["peak_slot"])], axis=0)


# ---------------------------------------------------------------------------
# 교차검증: 각 공연을 빼고 같은 요일 유형의 나머지 공연으로 만든 초과 곡선으로 그 공연을 예측한다.
# 최고점 시각 조건
#  known   : 실제 최고점 구간에 곡선을 맞춘다(최고점 시각을 아는 조건).
#  blind   : 연계 데이터가 그날 공연을 표시한 마지막 시각(last_hour)에 나머지 공연의 지연 중앙값을 더해 예측한다.
#  typical : 그날 정보 없이 나머지 공연의 최고점 구간 중앙값을 쓴다.
# 곡선 크기
#  plain : 나머지 공연의 초과 곡선 중앙값 그대로.
#  aud   : 나머지 공연으로 (관객 수 -> 초과 출차 최고점, 러시 지속) 직선을 맞춰 곡선의 양(+) 부분과 지속 시간을 조정한다.
# 오차는 모든 조건에서 실제 최고점 -2시간 ~ +3시간 구간에서 잰다. 예측을 자르는 상한은 없다.
# ---------------------------------------------------------------------------
K0 = REL.index(0)


def fit_audience(rows):
    b1, b0 = np.polyfit(rows["audience"], rows["peak_excess"], 1)
    c1, c0 = np.polyfit(rows["audience"], rows["clear_minutes"], 1)
    return {"excess": {"b0": float(b0), "b1": float(b1), "min": float(rows["peak_excess"].min()), "max": float(rows["peak_excess"].max())},
            "clear": {"c0": float(c0), "c1": float(c1), "min": 15, "max": int(rows["clear_minutes"].max())}}


def audience_excess(m, aud):
    e = m["excess"]
    return float(min(e["max"], max(e["min"], e["b0"] + e["b1"] * aud)))


def audience_clear(m, aud):
    c = m["clear"]
    return int(min(c["max"], max(c["min"], round((c["c0"] + c["c1"] * aud) / 15) * 15)))


def scaled(ex, peak_excess):
    """초과 곡선의 양(+) 부분만 최고점 값이 peak_excess 가 되도록 늘이거나 줄인다."""
    if peak_excess is None or ex[K0] <= 0:
        return ex
    return np.where(ex > 0, ex * peak_excess / ex[K0], ex)


def capped(base_v, e, cap):
    """평소 값에 초과분을 더하되, 2025년 같은 요일 유형 공연일의 최고점 15분 출차 최댓값(cap)을 넘기지 않는다.
    평소 값 자체가 cap보다 크면 평소 값을 둔다(가산 모델이 관측 범위를 벗어나지 않게 하는 상한)."""
    v = max(0.0, base_v + e)
    return max(min(v, cap), min(v, base_v)) if v > cap else v


loo = []
for i, r in cases.iterrows():
    others = cases[(cases["weekend"] == r["weekend"]) & (cases.index != i)]
    ex = np.nan_to_num(excess_profile(others))
    am = fit_audience(others)
    win = [s for s in (r["peak_slot"] + k for k in REL) if 0 <= s < EXT
           and not np.isnan(r["act_ext"][s]) and not np.isnan(r["base_ext"][s])]
    a = r["act_ext"][win]
    b = r["base_ext"][win]
    lag_slots = int(round(others["lag_from_last_hour_min"].median() / 15))
    peaks = {"known": int(r["peak_slot"]),
             "blind": int(min(EXT - 1, max(0, r["last_hour"] * 4 + lag_slots))),
             "typical": int(round(others["peak_slot"].median()))}
    clears = {"plain": float(others["clear_minutes"].median()), "aud": float(audience_clear(am, r["audience"]))}
    uppers = {"plain": float(np.ceil(q(others["clear_minutes"], .75) / 15) * 15), "aud": clears["aud"] + 15}
    sizes = {"plain": None, "aud": audience_excess(am, r["audience"])}
    cap = float(others["peak_exits"].max())    # 상한: 나머지 공연의 최고점 15분 출차 최댓값
    row = {"base_mae": float(np.mean(np.abs(b - a))), "blind_peak_slot": peaks["blind"]}
    for v in ("plain", "aud"):
        row[f"{v}_clear_pred"] = clears[v]
        row[f"{v}_clear_err"] = abs(clears[v] - r["clear_minutes"])
        row[f"{v}_upper_covers"] = bool(r["clear_minutes"] <= uppers[v])
        exv = scaled(ex, sizes[v])
        for cond, pk in peaks.items():
            pred = r["base_ext"].copy()
            for k, e in zip(REL, exv):
                if 0 <= pk + k < EXT:
                    pred[pk + k] = capped(r["base_ext"][pk + k], e, cap)
            p = pred[win]
            row[f"{cond}_{v}_mae"] = float(np.mean(np.abs(p - a)))
            row[f"{cond}_{v}_peak_err"] = float(abs(p.max() - a.max()))
            row[f"{cond}_{v}_rush_end_err"] = abs(pk * 15 + clears[v] - (r["peak_slot"] * 15 + r["clear_minutes"]))
    for cond in ("blind", "typical"):
        row[f"{cond}_peak_time_err"] = abs(peaks[cond] - r["peak_slot"]) * 15
    loo.append(row)
loo = pd.DataFrame(loo)
cases = pd.concat([cases, loo], axis=1)


def val_block(g):
    out = {"n": int(len(g)), "baseline_only_mae_med": round(float(g["base_mae"].median()), 1)}
    for cond in ("blind", "typical"):
        out[f"{cond}_peak_time"] = {"err_med_min": round(float(g[f"{cond}_peak_time_err"].median()), 1),
                                    "within_15_n": int((g[f"{cond}_peak_time_err"] <= 15).sum()),
                                    "within_15_pct": round(float((g[f"{cond}_peak_time_err"] <= 15).mean() * 100), 0)}
    for v in ("plain", "aud"):
        o = {"clear_within_15_n": int((g[f"{v}_clear_err"] <= 15).sum()),
             "clear_within_15_pct": round(float((g[f"{v}_clear_err"] <= 15).mean() * 100), 0),
             "clear_err_med": round(float(g[f"{v}_clear_err"].median()), 1),
             "upper_covers_n": int(g[f"{v}_upper_covers"].sum())}
        for cond in ("known", "blind", "typical"):
            o[cond] = {
                "peak_err_med": round(float(g[f"{cond}_{v}_peak_err"].median()), 1),
                "mae_med": round(float(g[f"{cond}_{v}_mae"].median()), 1),
                "mae_vs_baseline_pct": round(float((1 - g[f"{cond}_{v}_mae"].median() / g["base_mae"].median()) * 100), 0),
                "better_than_baseline_n": int((g[f"{cond}_{v}_mae"] < g["base_mae"]).sum()),
                "rush_end_err_med_min": round(float(g[f"{cond}_{v}_rush_end_err"].median()), 1),
            }
        out[v] = o
    # 관객 수 직선을 쓰는 기준: 최고점 시각을 아는 조건의 교차검증에서
    # 최고점 오차 중앙값과 15분 구간 평균 오차 중앙값이 둘 다 줄고, 지속 시간 15분 이내 건수가 줄지 않을 때만 쓴다.
    # 이 선택은 성능을 보고하는 같은 교차검증 결과로 했다(선택 편향이 있음). 모르는 조건 결과는 기준에 넣지 않았다.
    out["use_audience"] = bool(out["aud"]["known"]["peak_err_med"] < out["plain"]["known"]["peak_err_med"]
                               and out["aud"]["known"]["mae_med"] < out["plain"]["known"]["mae_med"]
                               and out["aud"]["clear_within_15_n"] >= out["plain"]["clear_within_15_n"])
    return out


validation = {"weekday": val_block(cases)}   # 평일만. 주말은 기준선이 없어 교차검증하지 않는다

# 종료 시각 정보: 연계 데이터는 1시간 단위로 공연명을 표시한 구간만 준다. 실제 종료 시각이 아니다.
lag = {}
for wk, g in cases.groupby("weekend"):
    s = g["lag_from_last_hour_min"]
    lag["weekend" if wk else "weekday"] = {"n": int(len(g)), "q25": q(s, .25), "median": q(s, .5), "q75": q(s, .75),
                                           "min": int(s.min()), "max": int(s.max())}
ev_span = (ev["last_hour"] - ev["first_hour"])
end_info = {
    "definition": "지연 = 출차 최고점 구간 시작 - 연계 데이터가 그날 공연명을 표시한 마지막 시각(last_hour)의 정시. 단위 분",
    "lag_from_last_hour_min": lag,
    "rows": int(len(ev)), "rows_single_hour": int((ev_span == 0).sum()), "rows_five_hours": int((ev_span == 4).sum()),
    "days_multi_title": int((ev_all["n_titles"] > 1).sum()),
    "verdict": "연계 데이터에는 실제 종료 시각이 없다. 공연명이 1시간 단위로 붙은 구간만 있어 "
               "'종료 뒤 1구간(15분)에 최고점' 가정은 이 자료로 확인할 수 없다.",
}

cases_out = cases.drop(columns=["act_ext", "base_ext"])
cases_out.to_csv(D / "cases_2025.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------------------
# 요일 유형별 요약
# ---------------------------------------------------------------------------
# 구역 점유는 기준선이 필요 없으므로 유효 공연일 전체(분석 사례보다 많음)로 센다
occ3_daymax = f[f["slot"] >= 40].groupby("date")["occ3"].max()
ev_occ3 = pd.DataFrame({"occ3": [occ3_daymax[d] for d in ev_day.index],
                        "weekend": [pd.Timestamp(d).dayofweek >= 5 for d in ev_day.index]}, index=ev_day.index)

groups = []
for wk, g in cases.groupby("weekend"):
    eo = ev_occ3[ev_occ3["weekend"] == wk]["occ3"]
    cm = g["clear_minutes"]
    groups.append({
        "weekend": bool(wk), "n": int(len(g)),
        "arrival_lead_med": int(g["arrival_peak_before_exit_peak_min"].median()),
        "peak_time_med": g.sort_values("peak_slot")["peak_time"].iloc[len(g) // 2],
        "peak_exits_med": float(g["peak_exits"].median()), "base_at_peak_med": float(g["base_at_peak"].median()),
        "peak_excess_med": float(g["peak_excess"].median()), "peak_ratio_case_med": round(float(g["peak_ratio"].median()), 2),
        "peak_ratio_of_medians": round(float(g["peak_exits"].median() / g["base_at_peak"].median()), 2),
        "clear_med": q(cm, .5), "clear_p75": q(cm, .75), "clear_max": int(cm.max()),
        "clear_med_label": dur_label(q(cm, .5)), "clear_p75_label": dur_label(q(cm, .75)),
        "clear_p75_upper": int(np.ceil(q(cm, .75) / 15) * 15),
        "clear_censored_n": int(g["clear_censored"].sum()),
        "clear_cut24": {"med": q(g["clear_minutes_cut24"], .5), "p75": q(g["clear_minutes_cut24"], .75),
                        "max": int(g["clear_minutes_cut24"].max()), "cut_n": int(g["cut24_hit"].sum())},
        "event_days_valid": int(len(eo)), "occ3_daymax_med": int(eo.median()),
        "occ3_over_spaces_n": int((eo >= ZONE3_SPACES).sum()),
        "excess_profile": [round(float(x), 1) for x in np.nan_to_num(excess_profile(g), nan=0.0)],
        "use_audience": validation["weekday"]["use_audience"],
        "peak_exits_max": int(g["peak_exits"].max()),
        "peak_exits_max_date": str(g.loc[g["peak_exits"].idxmax(), "date"]),
        "peak_exits_max_time": str(g.loc[g["peak_exits"].idxmax(), "peak_time"]),
        "peak_exits_max_base": float(g.loc[g["peak_exits"].idxmax(), "base_at_peak"]),
        "peak_exits_max_audience": int(g.loc[g["peak_exits"].idxmax(), "audience"]),
        "dow_counts": {str(k): int(v) for k, v in pd.to_datetime(g["date"]).dt.dayofweek.value_counts().sort_index().items()},
        "fallback_n": int((g["base_kind"] == "요일 유형 28일").sum()),
        "rush_end_after_midnight_n": int(((g["peak_slot"] * 15 + g["clear_minutes"]) >= 1440).sum()),
        "rush_end_threshold_med": q(g["rush_end_threshold"].dropna(), .5),
        "rush_end_base_med": q([b[s] for b, s in zip(g["base_ext"], g["peak_slot"] + g["clear_minutes"] // 15)
                                if s < EXT and not np.isnan(b[s])], .5),
        "rush_end_exits_med": q(g["rush_end_exits"].dropna(), .5),
        "exits_plus60_med": q(g["exits_plus60"].dropna(), .5),
        "excess_share_first30_med": q(g["excess_share_first30"].dropna(), .5),
        "half_med": q(g["half_minutes"], .5), "half_p75": q(g["half_minutes"], .75), "half_max": int(g["half_minutes"].max()),
        "half_med_label": dur_label(q(g["half_minutes"], .5)), "half_p75_label": dur_label(q(g["half_minutes"], .75)),
        "aud_combined_n": int(sum(bool(ev_all.loc[pd.Timestamp(d).date(), "aud_combined"]) for d in g["date"])),
        "holiday_dates": [d for d in g["date"] if d in HOLIDAYS],
        "audience_model": {**fit_audience(g), "aud_min": int(g["audience"].min()), "aud_max": int(g["audience"].max()),
                           "upper_margin_min": 15},
    })

# 주말 공연일 실측 분포(기준선 없음). 공연 없는 유효 주말이 사실상 없어 '평소 대비'는 내지 않는다
eo_we = ev_occ3[ev_occ3["weekend"]]["occ3"]
we_curve = np.array([a[REPLAY_FROM:] for a in we_obs["act_ext"]], dtype=float)
hm_ = we_obs["half_minutes"]
weekend_obs = {
    "n": int(len(we_obs)), "valid_weekends": int(len(valid_we)), "normal_weekends": int(len(normal_we)),
    "normal_weekend_dates": [str(d) for d in sorted(normal_we)],
    "peak_window": "17:00~23:45",
    "peak_exits_med": float(we_obs["peak_exits"].median()), "peak_exits_q25": q(we_obs["peak_exits"], .25),
    "peak_exits_q75": q(we_obs["peak_exits"], .75), "peak_exits_min": int(we_obs["peak_exits"].min()),
    "peak_exits_max": int(we_obs["peak_exits"].max()),
    "peak_exits_max_date": str(we_obs.loc[we_obs["peak_exits"].idxmax(), "date"]),
    "peak_exits_max_time": str(we_obs.loc[we_obs["peak_exits"].idxmax(), "peak_time"]),
    "peak_time_med": we_obs.sort_values("peak_slot")["peak_time"].iloc[len(we_obs) // 2],
    "peak_time_q25": hhmm(int(np.floor(q(we_obs["peak_slot"], .25)))), "peak_time_q75": hhmm(int(np.ceil(q(we_obs["peak_slot"], .75)))),
    "peak_hour_counts": {f"{h:02d}": int(v) for h, v in (we_obs["peak_slot"] // 4).value_counts().sort_index().items()},
    "half_definition": f"최고점 구간 시작부터 출차가 그 최고점의 {int(HALF * 100)}% 이하로 처음 내려간 구간 시작까지(평소 기준선을 쓰지 않음)",
    "half_med": q(hm_, .5), "half_p75": q(hm_, .75), "half_max": int(hm_.max()),
    "half_med_label": dur_label(q(hm_, .5)), "half_p75_label": dur_label(q(hm_, .75)), "half_censored_n": int(we_obs["half_censored"].sum()),
    "lag_from_last_hour_med": q(we_obs["lag_from_last_hour_min"], .5),
    "audience_peak_pearson": round(float(we_obs["audience"].corr(we_obs["peak_exits"])), 2),
    "audience_min": int(we_obs["audience"].min()), "audience_max": int(we_obs["audience"].max()),
    "curve_from_slot": REPLAY_FROM,
    "curve_med": [None if np.isnan(x) else round(float(x), 1) for x in np.nanmedian(we_curve, axis=0)],
    "curve_q25": [None if np.isnan(x) else round(float(x), 1) for x in np.nanquantile(we_curve, .25, axis=0)],
    "curve_q75": [None if np.isnan(x) else round(float(x), 1) for x in np.nanquantile(we_curve, .75, axis=0)],
    "event_days_valid": int(len(eo_we)), "occ3_daymax_med": int(eo_we.median()),
    "occ3_over_spaces_n": int((eo_we >= ZONE3_SPACES).sum()),
}

# 예측 화면의 평소 기준선: 공연 없는 유효 평일을 달별로 묶은 구간별 중앙값(다음 날 03:00 까지). 주말은 만들지 않는다
nb = out_ext.loc[[d for d in normal if pd.Timestamp(d).dayofweek < 5]].copy()
nb["month"] = [pd.Timestamp(d).month for d in nb.index]
nb["weekend"] = [pd.Timestamp(d).dayofweek >= 5 for d in nb.index]
baseline, baseline_days_n = {}, {}
for (m, w), g in nb.groupby(["month", "weekend"]):
    key = f"{m}-{'we' if w else 'wd'}"
    baseline[key] = g.drop(columns=["month", "weekend"]).median().round(1).fillna(0).tolist()
    baseline_days_n[key] = int(len(g))

# 참고 수치(한계가 아니라 관측값)
vf = f[[d in valid_days for d in f["date"]]]
wd18 = vf[(~vf["weekend"]) & (vf["slot"] == 72) & ~vf["date"].isin(event_dates)]["out"]
over = f[f["out"] > OLD_CAP]
reference = {
    "observed_max_15m": {"label": "2025년 관측 최대(15분)", "value": int(f["out"].max()),
                         "when": f["out"].idxmax().strftime("%Y-%m-%d %H:%M")},
    "weekday_18h_median": {"label": "평일 18시 평소 출차 중앙값", "value": float(wd18.median()), "n_days": int(len(wd18)),
                           "definition": "공연 없는 유효 평일의 18:00~18:15 출차 대수 중앙값"},
    "retired_421": {"note": "421대는 출구별 15분 출차 상위 1% 값을 더한 수로, 처리 한계가 아니어서 폐기",
                    "slots_over": int(len(over)), "days_over": int(over["date"].nunique())},
}

zone = {
    "gates": ZONE3, "spaces_official": ZONE3_SPACES,
    "definition": "동2문·북2문·남2문으로 입차한 차량만의 15분 단위 추정 점유(입차 누계 - 출차 누계), 유효일 구간 기준",
    "occ_p50": int(np.percentile(vf["occ3"], 50)), "occ_p95": int(np.percentile(vf["occ3"], 95)),
    "occ_p99": int(np.percentile(vf["occ3"], 99)), "occ_max": int(vf["occ3"].max()),
    "occ_p95_all_slots": int(np.percentile(f["occ3"], 95)), "occ_p99_all_slots": int(np.percentile(f["occ3"], 99)),
    "slots_over_spaces_pct": round(float((vf["occ3"] >= ZONE3_SPACES).mean() * 100), 2),
    "all_gates_occ_p99_all_slots": int(np.percentile(f["occ"], 99)),
}

# 문 안내
gs = pd.read_csv(D / "gate_stats_2025.csv", index_col=0)
gm = pd.read_csv(D / "gate_matrix_2025.csv")
gate_names = [n for n in gs.sort_values("event_evening_share", ascending=False).index if n.endswith("문")]
gates = []
for n in gate_names:
    r = gs.loc[n]
    row = gm[gm["in_gate"] == n].sort_values("n", ascending=False)
    gates.append({
        "name": n, "mixed_zone": bool(r["mixed_zone"]), "exit_lanes": int(r["exit_lanes"]),
        "in_total": int(row["in_total"].iloc[0]),
        "exits_to": [{"gate": x.out_gate, "pct": round(100.0 * x.n / x.in_total, 3), "n": int(x.n)} for x in row.itertuples()
                     if x.pct_of_in_gate >= 0.05],
        "event_peak15_med": float(r["event_evening_peak15_median"]),
        "event_weekday_peak15_med": float(r["event_weekday_peak15_median"]),
        "event_weekend_peak15_med": float(r["event_weekend_peak15_median"]),
        "event_weekday_sum_med": float(r["event_weekday_sum_median"]),
        "event_weekend_sum_med": float(r["event_weekend_sum_median"]),
        "normal_peak15_med": float(r["normal_evening_peak15_median"]),
        "normal_days": int(r["normal_days"]), "normal_weekend_days": int(r["normal_weekend_days"]),
        "event_weekday_vs_normal": float(r["event_weekday_vs_normal_ratio"]),
        "event_share": float(r["event_evening_share"]),
    })

# 관객 수와의 상관(입력값으로 쓸 만한지 확인)
corr = {}
for name, g in (("weekday", cases),):
    corr[name] = {"n": int(len(g))}
    for col in ("peak_excess", "clear_minutes", "occ_max", "occ3_max"):
        corr[name][col] = {"pearson": round(float(g["audience"].corr(g[col])), 2),
                           "spearman": round(float(g["audience"].rank().corr(g[col].rank())), 2)}

replay = [{"date": c["date"], "event": c["event"], "audience": int(c["audience"]), "weekend": bool(c["weekend"]),
           "peak_slot": int(c["peak_slot"]), "peak_time": c["peak_time"], "clear_minutes": int(c["clear_minutes"]),
           "clear_censored": bool(c["clear_censored"]), "base_kind": c["base_kind"], "base_n_days": int(c["base_n_days"]),
           "blind_peak_slot": int(c["blind_peak_slot"]),
           "actual": [None if np.isnan(x) else int(x) for x in c["act_ext"][REPLAY_FROM:]],
           "base": [None if np.isnan(x) else round(float(x), 1) for x in c["base_ext"][REPLAY_FROM:]]}
          for c in cases.sort_values("date").to_dict("records")]
# 주말 공연일은 실제 출차만 보여 준다(평소 기준선·모델 곡선 없음)
replay += [{"date": c["date"], "event": c["event"], "audience": int(c["audience"]), "weekend": True,
            "peak_slot": int(c["peak_slot"]), "peak_time": c["peak_time"], "half_minutes": int(c["half_minutes"]),
            "actual": [None if np.isnan(x) else int(x) for x in c["act_ext"][REPLAY_FROM:]], "base": None}
           for c in we_obs.to_dict("records")]
replay.sort(key=lambda r: r["date"])

n_fallback = int((cases["base_kind"] == "요일 유형 28일").sum())
wdv = validation["weekday"]
if wdv["use_audience"]:
    aud_limit = ("관객 수는 평일 예측에만 씁니다. 주말은 평소 기준선이 없어 예측 자체를 하지 않습니다. "
                 "공연장은 관객 수 기본값을 채우는 데만 쓰고 예측에는 쓰지 않습니다.")
else:
    aud_limit = "공연장과 관객 수는 예측에 쓰지 않습니다. 교차검증에서 관객 수를 써도 오차가 줄지 않았습니다."
in_last = io["in_ts"].max()
groups_by = {"weekday": groups[0]}

# 러시 끝 기준 감도: 기준선 x 1.5 + 20대로 바꿨을 때(평일)
cm = cases["clear_minutes_alt"]
rush_sens = {"ratio": SENS[0], "add": SENS[1],
             "definition": f"러시 끝 기준을 '기준선 x {SENS[0]:g} + {SENS[1]}대 이하'로 바꿔 같은 사례를 다시 잰 값(최고점·기준선은 같음)",
             "weekday": {"n": int(len(cases)), "clear_med": q(cm, .5), "clear_p75": q(cm, .75), "clear_max": int(cm.max()),
                         "clear_med_label": dur_label(q(cm, .5)), "clear_p75_label": dur_label(q(cm, .75)),
                         "end_after_midnight_n": int((cases["rush_end_slot_alt"] >= DAY).sum()),
                         "censored_n": int(cases["clear_alt_censored"].sum()),
                         "base_definition": {"clear_med_label": groups[0]["clear_med_label"],
                                             "end_after_midnight_n": groups[0]["rush_end_after_midnight_n"]}}}

arrival_def = (f"입차 최고점은 공연일마다 출차 최고점 {ARR_FROM * 15 // 60}시간 전부터 {ARR_TO * 15 // 60}시간 전까지의 15분 구간 가운데 "
               "입차가 평소 기준선을 가장 크게 넘은 구간입니다. 예측 화면은 이 간격의 중앙값을 출차 최고점에서 거꾸로 빼서 입차가 몰리는 시각을 잡으므로, "
               "공연 시간이 2025년 사례와 다르면 시작 시각과의 간격이 실제와 어긋날 수 있습니다.")

hol = [c for c in cases.to_dict("records") if c["date"] in HOLIDAYS and not c["weekend"]]
holiday_note = ("평일/주말은 요일로만 나눴습니다. 평일 사례 가운데 " + ", ".join(f"{c['date']}(공휴일)" for c in hol)
                + "도 평일로 셌습니다.") if hol else "평일 사례에 공휴일은 없습니다."

g0 = groups[0]
missing_months = [m for m in range(1, 13) if f"{m}-wd" not in baseline_days_n]
thin_months = [m for m in range(1, 13) if 0 < baseline_days_n.get(f"{m}-wd", 0) < 5]
weekend_rule = (f"주말은 평소 대비 분석을 하지 않습니다. 2025년 유효 주말 {len(valid_we)}일 가운데 공연이 없는 날이 {len(normal_we)}일이라 "
                "'공연 없는 주말' 기준선을 세울 수 없기 때문입니다. 주말은 공연일끼리의 실측 분포(저녁 최고 15분 출차, 최고점 시각, "
                f"최고점의 {int(HALF * 100)}% 이상 출차가 이어진 시간)만 보여 주고, 예측·교차검증은 평일만 합니다.")
gm_in = pd.read_csv(D / "gate_matrix_2025.csv").drop_duplicates("in_gate").set_index("in_gate")["in_total"]
gm_in = gm_in[[n.endswith("문") for n in gm_in.index]]
mixed_share = round(float(gm_in[ZONE3].sum() / gm_in.sum() * 100), 1)
model = {
    "generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    "meta": {
        "data_range": f"2025-01-01 ~ {(last_day - pd.Timedelta('1D')).date()}",
        "last_entry_record": in_last.strftime("%Y-%m-%d %H:%M"),
        "days_in_range": int(len(all_days)), "valid_days": int(len(valid_days)),
        "valid_rule": "하루 출차 합계가 전체 날짜 중앙값의 40% 이상인 날",
        "n_records_dedup": int(n_raw), "n_records_analyzed": int(len(io)),
        "n_records_note": "n_records_dedup: 내려받은 2025 입출차정보에서 중복을 지운 건수(문별 입출 비율은 이 기준). "
                          "n_records_analyzed: 그중 입차가 2025년이고 출차가 입차 이후 2일 안인 기록(15분 집계와 모델은 이 기준)",
        "rush_sensitivity": rush_sens,
        "arrival_definition": arrival_def,
        "peak_cap_rule": (f"예측 출차는 2025년 평일 공연일 {len(cases)}건의 최고점 15분 출차 최댓값 {g0['peak_exits_max']}대"
                          f"({g0['peak_exits_max_date']} {g0['peak_exits_max_time']}, 같은 시각 평소 {g0['peak_exits_max_base']:g}대)를 넘지 않게 자릅니다. "
                          "분석 사례 안에서 본 가장 큰 값일 뿐이며, 평소 값에 초과분을 더하는 방식이 관측 범위를 벗어나지 않게 하려는 상한입니다. "
                          "출구의 처리 한계가 아닙니다."),
        "holiday_note": holiday_note,
        "mixed_zone_in_share_pct": mixed_share,
        "event_days_linked": int(len(ev_all)), "event_days_valid": int(len(event_dates)), "n_cases": int(len(cases)),
        "event_days_valid_weekday": int(sum(pd.Timestamp(d).dayofweek < 5 for d in event_dates)),
        "event_days_valid_weekend": int(sum(pd.Timestamp(d).dayofweek >= 5 for d in event_dates)),
        "valid_weekends": int(len(valid_we)), "normal_weekends": int(len(normal_we)),
        "normal_weekdays": int(sum(pd.Timestamp(d).dayofweek < 5 for d in normal)),
        "cases_fallback_baseline": n_fallback,
        "baseline_missing_months": missing_months, "baseline_thin_months": thin_months,
        "weekend_rule": weekend_rule,
        "rush_definition": "평소 기준선은 앞뒤 21일 안의 공연 없는 같은 요일의 15분 구간별 출차 중앙값입니다(그런 날이 2일 미만이면 앞뒤 28일 안의 공연 없는 평일). "
                           "출차 최고점은 17:00~23:45 가운데 실제 출차가 기준선을 가장 크게 넘은 15분 구간이며, 초과가 25대 미만인 날은 뺐습니다. "
                           f"러시 지속 시간은 최고점 구간 시작부터, 그 뒤 처음으로 출차가 '기준선 x {RUSH_RATIO:g} + {RUSH_ADD}대' 이하가 된 구간 시작까지이며, "
                           "다음 날 03:00까지 이어서 잽니다. 끝 기준은 심야에 15분 약 "
                           f"{g0['rush_end_threshold_med']:g}대(중앙값)라서 이 시간에는 최고점 뒤 잔여 출차가 포함됩니다.",
        "duration_rule": "지속 시간은 15분 단위로만 잴 수 있습니다. 중앙값이나 75% 값이 15의 배수가 아니면 앞뒤 눈금으로 '30~45분'처럼 구간으로 적습니다.",
        "busy_rule": f"가장 붐비는 구간은 예상 출차가 예상 최고점의 {int(HALF * 100)}% 이상인 최고점 앞뒤의 연속 구간입니다(화면 표시 규칙).",
        "baseline_predict": "예측 화면의 평소 선은 2025년 같은 달의 공연 없는 유효 평일 15분 구간별 출차 중앙값입니다. "
                            "그 달에 공연 없는 유효 평일이 없으면 뒤따르는 가장 가까운 달의 값을 씁니다.",
        "baseline_validation": "검증 화면의 평소 선은 그 공연일 앞뒤 21일 안의 공연 없는 같은 요일 중앙값입니다. "
                               "그런 날이 2일 미만이면 앞뒤 28일 안의 공연 없는 평일로 대체했습니다.",
        "gate_peak_definition": "문별 공연일 저녁 출차 집중도는 유효 공연일마다 18:00부터 다음 날 03:00까지 그 문의 15분 출차 최고값을 구해 "
                                "날짜들의 중앙값을 낸 값입니다. 통과 대수이며 대기 시간이 아닙니다.",
        "limits": [
            f"자료는 2025-01-01부터 {(last_day - pd.Timedelta('1D')).date()}까지이고(마지막 입차 기록 {in_last.strftime('%m-%d %H:%M')}), "
            f"{len(all_days)}일 가운데 기록이 충분한 유효일은 {len(valid_days)}일입니다. 8·9월은 입출차 기록이 크게 모자라 유효일이 하루도 없고, 그래서 이 두 달의 공연일은 분석에 들어가지 않았습니다.",
            f"연계 데이터의 공연일 {len(ev_all)}일 중 유효일은 {len(event_dates)}일(평일 {sum(pd.Timestamp(d).dayofweek < 5 for d in event_dates)}, "
            f"주말 {sum(pd.Timestamp(d).dayofweek >= 5 for d in event_dates)})이고, 평소 기준선을 세워 분석한 날은 평일 {len(cases)}일입니다.",
            weekend_rule,
            f"평일 {len(cases)}건 중 {n_fallback}건은 앞뒤 3주에 공연 없는 같은 요일이 모자라 앞뒤 4주의 공연 없는 평일 기준선으로 대체했습니다. "
            f"평일 사례 {len(cases)}건 중 {int((pd.to_datetime(cases['date']).dt.dayofweek == 4).sum())}건이 금요일입니다.",
            f"예측 화면의 평소 선은 달마다 공연 없는 유효 평일 수가 다릅니다. "
            + (f"{'·'.join(str(m) for m in missing_months)}월은 그런 날이 없어 뒤따르는 달 값을 쓰고, " if missing_months else "")
            + (f"{'·'.join(f'{m}월 {baseline_days_n[f'{m}-wd']}일' for m in thin_months)}은 날 수가 적어 흔들릴 수 있습니다." if thin_months else ""),
            "출차 대수는 출구를 통과한 차량 수입니다. 대기 시간이나 정체 길이를 직접 잰 값이 아닙니다.",
            "공연 종료 뒤 15분쯤에 출차 최고점이 온다는 가정은 실제 종료 시각 자료가 없어 확인하지 못했습니다.",
            aud_limit,
            "관객 수는 같은 시간대 공연 관람객 합계입니다. 연계 데이터는 같은 시간대에 공연이 여럿이면 공연명을 함께 표시하고 관람객 수를 합쳐 주며, "
            "그날 가장 큰 값을 썼습니다. 예측 화면에도 같은 시간대 공연의 관객 수를 모두 더해 넣어야 같은 기준이 됩니다.",
            "관객 수를 예측에 쓸지는 성능을 보고하는 같은 교차검증 결과로 정했습니다(선택 편향). 관객 수를 쓴 평일 결과는 낙관적일 수 있습니다.",
            "교차검증의 평소 기준선(앞뒤 21일 같은 요일)과 예측 화면의 평소 선(2025년 같은 달 평일)은 만드는 방법이 다릅니다. "
            "교차검증 수치는 예측 화면의 오차를 그대로 보여 주지 않습니다.",
            f"러시가 끝났다고 보는 기준(기준선 x {RUSH_RATIO:g} + {RUSH_ADD}대)은 평소 출차가 적은 심야에 15분 약 {g0['rush_end_threshold_med']:g}대(중앙값)입니다. "
            f"그래서 러시 지속 시간에는 최고점 뒤 잔여 출차가 포함됩니다. 기준을 '기준선 x {SENS[0]:g} + {SENS[1]}대'로 느슨하게 하면 평일 러시 중앙값은 "
            f"{rush_sens['weekday']['clear_med_label']}(지금 기준 {g0['clear_med_label']}), 자정 또는 그 뒤에 끝나는 평일 사례는 "
            f"{rush_sens['weekday']['end_after_midnight_n']}건(지금 기준 {g0['rush_end_after_midnight_n']}건)입니다.",
            arrival_def,
            holiday_note,
        ],
    },
    "reference": reference, "zone": zone, "end_info": end_info, "audience_corr": corr, "validation": validation,
    "rel_slots": REL, "peak_after_end_slots": PEAK_AFTER_END_SLOTS, "replay_from_slot": REPLAY_FROM, "ext_slots": EXT,
    "event_days": [{"date": str(d), "weekend": bool(ev_occ3.loc[d, "weekend"]), "audience": int(ev_day.loc[d, "audience"]),
                    "occ3_daymax": int(ev_occ3.loc[d, "occ3"])} for d in ev_day.index],
    "groups": groups, "weekend_obs": weekend_obs, "baseline": baseline, "baseline_days": baseline_days_n, "gates": gates, "replay": replay,
    # 공연장은 관객 수 기본값을 채우는 데만 쓴다(공연장 규모로 어림한 값, 예측에는 쓰지 않음)
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

# ---------------------------------------------------------------------------
# 표본 탈락 내역
# ---------------------------------------------------------------------------
DOW = ["월", "화", "수", "목", "금", "토", "일"]
L = ["# 표본 탈락 내역 (2025년 공연일)", "",
     f"만든 때: {model['generated']} (tools/model_v2.py 가 다시 만든다)", "",
     "## 단계별 건수", "",
     "| 단계 | 남은 날 | 빠진 날 | 사유 |", "|---|---|---|---|",
     f"| 연계 데이터에 공연명이 있는 날 | {len(ev_all)} | | |"]
left = len(ev_all)
for key in sorted(k for k in attr["stage"].unique() if not k.startswith("5")):
    sub = attr[attr["stage"] == key]
    left -= len(sub)
    L.append(f"| {key[2:]} | {left} | {len(sub)} | 평일 {int((~sub['weekend']).sum())}, 주말 {int(sub['weekend'].sum())} |")
L += ["", f"유효일 기준: 하루 출차 합계 {valid_cut:.0f}대 이상(전체 날짜 중앙값 {daily_total.median():.0f}대의 40%). "
          f"자료 구간 {len(all_days)}일 중 유효일 {len(valid_days)}일.", ""]
for key in sorted(k for k in attr["stage"].unique() if not k.startswith("5")):
    sub = attr[attr["stage"] == key]
    L += [f"### {key[2:]} ({len(sub)}일)", "",
          ", ".join(f"{d}({DOW[w]})" for d, w in zip(sub["date"], sub["dow"])), ""]
L += ["## 기준선 종류 (분석 사례)", "", "| 기준선 | 건수 | 평일 | 주말 |", "|---|---|---|---|"]
for k, g in cases.groupby("base_kind"):
    L.append(f"| {k} | {len(g)} | {int((~g['weekend']).sum())} | {int(g['weekend'].sum())} |")
L += ["", "같은 요일 21일: 앞뒤 21일 안의 공연 없는 같은 요일 유효일이 2일 이상. 요일 유형 28일: 그렇지 못해 앞뒤 28일 안의 평일/주말 유형 유효일로 대체.",
      "", "## 월별 사례 수", "", "| 월 | 연계 공연일 | 유효 공연일 | 분석 사례 | 그중 평일 | 그중 주말 |", "|---|---|---|---|---|---|"]
ok = attr[attr["stage"].str.startswith("5")]
va = attr[~attr["stage"].str[0].isin(["0", "1"])]
for m in range(1, 13):
    a, v, o = attr[attr["month"] == m], va[va["month"] == m], ok[ok["month"] == m]
    L.append(f"| {m} | {len(a)} | {len(v)} | {len(o)} | {int((~o['weekend']).sum())} | {int(o['weekend'].sum())} |")
L += ["", "## 요일별 사례 수", "", "| 요일 | 연계 공연일 | 유효 공연일 | 분석 사례 |", "|---|---|---|---|"]
for w in range(7):
    L.append(f"| {DOW[w]} | {int((attr['dow'] == w).sum())} | {int((va['dow'] == w).sum())} | {int((ok['dow'] == w).sum())} |")
L += ["", "## 참고", "",
      f"- 러시 종료가 다음 날 03:00 까지도 오지 않았거나 다음 날 자료가 없어 끝을 못 잰 사례: {int(cases['clear_censored'].sum())}건",
      f"- 자정 이후(00:00~03:00)의 초과 출차가 17:00~23:45 최고점보다 큰 사례: {late_peak}건 (최고점 정의는 바꾸지 않았다)",
      f"- 수정 전(24:00 절단) 기준으로 자정에 걸려 잘렸던 사례: 평일 {int(cases[~cases['weekend']]['cut24_hit'].sum())}건, "
      f"주말 {int(cases[cases['weekend']]['cut24_hit'].sum())}건", ""]
(D / "sample_attrition_2025.md").write_text("\n".join(L), encoding="utf-8")

# ---------------------------------------------------------------------------
print(f"자료 구간 {model['meta']['data_range']}, {len(all_days)}일 중 유효일 {len(valid_days)}일, 공연일 {len(ev_all)} / 유효 {len(event_dates)} / 사례 {len(cases)}")
print("탈락:", attr["stage"].value_counts().to_dict())
print("참고 수치:", json.dumps(reference, ensure_ascii=False))
print("구역 점유:", json.dumps(zone, ensure_ascii=False))
show = ["weekend", "n", "peak_time_med", "peak_exits_med", "base_at_peak_med", "peak_excess_med", "peak_ratio_case_med",
        "peak_ratio_of_medians", "clear_med", "clear_p75", "clear_max", "clear_med_label", "clear_p75_label",
        "clear_censored_n", "arrival_lead_med", "event_days_valid", "occ3_daymax_med", "occ3_over_spaces_n"]
print(pd.DataFrame(groups)[show].T.to_string())
print("수정 전(24:00 절단):", [g["clear_cut24"] for g in groups])
print("교차검증:", json.dumps(validation, ensure_ascii=False, indent=1))
print("종료 시각 정보:", json.dumps(end_info, ensure_ascii=False, indent=1))
print("관객 수 상관:", json.dumps(corr, ensure_ascii=False))
print("최고점 시각 분포:", cases.groupby("weekend")["peak_time"].agg(lambda s: s.value_counts().head(6).to_dict()).to_dict())
print(cases_out[["date", "weekend", "peak_time", "peak_exits", "base_at_peak", "clear_minutes", "clear_minutes_cut24",
                 "clear_censored", "last_hour", "lag_from_last_hour_min", "blind_peak_slot", "base_kind", "base_n_days",
                 "occ3_max", "audience"]].to_string())
