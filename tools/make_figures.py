"""기획서용 그림: (1) 평일 공연일 vs 평소 출차 곡선 (2) 출구별 공연일 분담과 처리 능력."""
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
M = json.loads((ROOT / "docs" / "data" / "model.json").read_text(encoding="utf-8"))
OUT = ROOT / "proposal" / "fig"
OUT.mkdir(parents=True, exist_ok=True)

wd = [r for r in M["replay"] if not r["weekend"]]
REL = range(-8, 9)


def aligned(r, key):
    return [r[key][r["peak_slot"] - 60 + k] if 0 <= r["peak_slot"] - 60 + k < 36 else np.nan for k in REL]


act = np.nanmedian([aligned(r, "actual_15_24") for r in wd], axis=0)
base = np.nanmedian([aligned(r, "base_15_24") for r in wd], axis=0)
labels = [("최고점" if k == 0 else f"{k * 15:+d}분") for k in REL]

fig, ax = plt.subplots(figsize=(9, 4), dpi=200)
x = np.arange(len(labels))
ax.bar(x, act, color="#1f6feb", label=f"평일 공연일 실제 출차 (중앙값, {len(wd)}회)")
ax.plot(x, base, color="#5b6470", lw=2, label="평소 (앞뒤 3주 같은 요일, 공연 없는 날)")
ax.axhline(M["exit_capacity_15m"], color="#d1495b", ls="--", lw=1.2, label=f"출구 7곳 처리 한계 약 {M['exit_capacity_15m']}대")
ax.set_xticks(x[::2], labels[::2])
ax.set_xlabel("각 공연의 출차 최고점 기준 상대 시각 (평일 최고점 중앙값 22:45)")
ax.set_ylabel("15분 출차 대수")
peak_i = len(labels) // 2
ax.set_title(f"평일 공연일 출차: 종료 직후 15분 {int(act[peak_i])}대, 평소({int(base[peak_i])}대)의 약 {act[peak_i] / base[peak_i]:.0f}배")
ax.set_ylim(0, M["exit_capacity_15m"] * 1.25)
ax.legend(fontsize=8, loc="upper right", frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "fig1_weekday_exit_curve.png")

g = M["gates"]
fig, ax = plt.subplots(figsize=(9, 3.6), dpi=200)
names = [x["name"] for x in g]
share = [x["event_share"] * 100 for x in g]
cap = [x["cap15"] / M["exit_capacity_15m"] * 100 for x in g]
xx = np.arange(len(names))
ax.bar(xx - 0.2, share, 0.4, color="#1f6feb", label="공연일 18시 이후 출차 비중 (%)")
ax.bar(xx + 0.2, cap, 0.4, color="#2a9d8f", label="15분 처리 능력 비중 (%)")
ax.set_xticks(xx, names)
ax.set_title("출구별 공연일 이용 비중 vs 처리 능력: 동2·북2문 쏠림")
ax.legend(fontsize=8, frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "fig2_gate_share_vs_capacity.png")
print("saved", list(p.name for p in OUT.glob("*.png")))
print("평일 중앙값 최고:", int(act.max()), "평소 같은 시각:", int(base[int(np.argmax(act))]), "시각:", labels[int(np.argmax(act))])
