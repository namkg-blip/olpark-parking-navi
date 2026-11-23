"""2025 입출차 원본 페이지(JSON)를 정리된 표 하나로 합친다."""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "KEY_INOUT_2025"
PAT = re.compile(r"입구:(?P<in_gate>[^,]*),\s*입차시간:(?P<in_ts>[^,]*),\s*출구:(?P<out_gate>[^,]*),\s*출차시간:(?P<out_ts>.*)")

rows, bad = [], 0
for f in sorted(RAW.glob("p*.json")):
    for it in json.loads(f.read_text(encoding="utf-8")):
        m = PAT.match(it.get("DESCRIPTION") or "")
        if not m:
            bad += 1
            continue
        rows.append(m.groupdict())

df = pd.DataFrame(rows)
for c in ("in_ts", "out_ts"):
    df[c] = pd.to_datetime(df[c].str.strip(), errors="coerce")
for c in ("in_gate", "out_gate"):
    df[c] = df[c].str.strip()
df = df.drop_duplicates()
df.to_pickle(ROOT / "data" / "inout_2025.pkl")

print(f"행 {len(df):,} (파싱 실패 {bad:,}), 기간 {df['in_ts'].min()} ~ {df['in_ts'].max()}")
print("출차시각 없음:", df["out_ts"].isna().sum())
print("\n입구별:\n", df["in_gate"].value_counts().head(15).to_string())
print("\n출구별:\n", df["out_gate"].value_counts().head(15).to_string())
