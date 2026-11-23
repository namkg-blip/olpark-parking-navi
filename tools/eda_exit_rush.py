"""2024-07 입출차 기록으로 날짜별 출차 집중(공연 종료 러시)을 확인한다."""
import pandas as pd

D = r"C:\Users\nam_k\contests\2026-ksponco-publicdata\data"

io = pd.read_csv(fr"{D}\올림픽공원_입출차정보_20240731.csv", encoding="cp949")
io["in"] = pd.to_datetime(io["입차일시"])
io["out"] = pd.to_datetime(io["출차일시"], errors="coerce")

ev = pd.read_csv(fr"{D}\영문_공연정보_20260901.csv", encoding="cp949")
ev["date"] = pd.to_datetime(ev["공연일자"], errors="coerce").dt.date
ev_by_day = ev.groupby("date")["공연제목"].apply(lambda s: " / ".join(s.str.slice(0, 40)))

exits = io.dropna(subset=["out"]).copy()
exits = exits[exits["out"].dt.month == 7]
exits["slot"] = exits["out"].dt.floor("15min")
per_slot = exits.groupby("slot").size()

rows = []
for day, s in per_slot.groupby(per_slot.index.date):
    peak_slot = s.idxmax()
    rows.append({
        "date": day,
        "weekday": pd.Timestamp(day).day_name()[:3],
        "exits_total": int(s.sum()),
        "peak_15min": int(s.max()),
        "peak_time": peak_slot.strftime("%H:%M"),
        "events(EN list)": ev_by_day.get(day, ""),
    })
daily = pd.DataFrame(rows)

baseline = daily["peak_15min"].median()
daily["peak_x_median"] = (daily["peak_15min"] / baseline).round(1)

pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 70)
print(f"출차 기록 {len(exits):,}건, 15분 최대 출차 수 중앙값 {baseline:.0f}대")
print(daily.sort_values("peak_15min", ascending=False).head(12).to_string(index=False))

dur = (io["out"] - io["in"]).dt.total_seconds() / 3600
print("\n주차 시간(시간) 분포:", dur.describe(percentiles=[.5, .9]).round(2).to_dict())

daily.to_csv(fr"{D}\..\eda_daily_exit_peaks_2024-07.csv", index=False, encoding="utf-8-sig")
