"""연계 데이터(공연명·관람객수, 시간대별)에서 2025 공연일 목록을 만든다."""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
lk = json.loads((ROOT / "data" / "raw" / "KEY_LINKED_2025" / "p00001.json").read_text(encoding="utf-8"))

# 공연명 안에 줄바꿈이 들어 있는 행이 있어 re.S 로 줄바꿈까지 공연명으로 읽고, 공백은 하나로 줄인다
# 공연명의 둥근 따옴표는 곧은 따옴표로 통일(표기만, 수치 영향 없음)
QUOTES = str.maketrans({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})
rows = []
for x in lk:
    m = re.match(r"공연명:(.*),공연관람객수:(\d+)", x["TITLE"], re.S)
    if not m or not m.group(1).strip():
        continue
    rows.append({"ts": pd.Timestamp(x["ISSUED_DATE"]), "event": " ".join(m.group(1).split()).translate(QUOTES), "audience": int(m.group(2))})
df = pd.DataFrame(rows)
df["date"] = df["ts"].dt.date

ev = (df.groupby(["date", "event"])
        .agg(audience=("audience", "max"), first_hour=("ts", "min"), last_hour=("ts", "max"))
        .reset_index())
ev["first_hour"] = ev["first_hour"].dt.hour
ev["last_hour"] = ev["last_hour"].dt.hour
ev["weekday"] = pd.to_datetime(ev["date"]).dt.dayofweek
ev.to_csv(ROOT / "data" / "events_2025.csv", index=False, encoding="utf-8-sig")

print(f"2025 공연일 {ev['date'].nunique()}일, 공연-일 {len(ev)}건")
print("관람객 수 분포:", ev["audience"].describe().round(0).to_dict())
print(ev.sort_values("audience", ascending=False).head(12).to_string(index=False))
