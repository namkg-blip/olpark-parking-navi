"""기획서용 그림을 docs/data/model.json 과 data/gate_matrix_2025.csv 에서 다시 만든다.

fig1_weekday_exit_curve.png : 평일 공연일과 평소의 출차 곡선(최고점 기준 정렬, 다음 날 03:00 까지)
fig2_gate_zones.png         : 입차 문별 출차 문 비율, 문별 공연일 저녁 15분 출차 최고값
fig3_demo_full.png, fig3a_demo_predict.png, fig3b_demo_validation.png, fig3c_demo_gates.png
                            : 서비스 화면(로컬 정적 서버 + Edge/Chrome 헤드리스 캡처). --no-shots 로 건너뛴다.
"""
import functools
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
M = json.loads((ROOT / "docs" / "data" / "model.json").read_text(encoding="utf-8"))
OUT = ROOT / "proposal" / "fig"
OUT.mkdir(parents=True, exist_ok=True)
DEMO_QUERY = "date=2026-12-17&start=19:30&dur=150&venue=0&aud=15000&replay=2025-07-11"   # 평일 19:30 시작, 150분
BLUE, GRAY, GREEN, RED = "#1f6feb", "#5b6470", "#2a9d8f", "#d1495b"

# ---------------------------------------------------------------------------
# 그림 1
# ---------------------------------------------------------------------------
wd = [r for r in M["replay"] if not r["weekend"]]
g_wd = next(g for g in M["groups"] if not g["weekend"])
REL = M["rel_slots"]
FROM = M["replay_from_slot"]


def aligned(r, key):
    row = []
    for k in REL:
        j = r["peak_slot"] - FROM + k
        v = r[key][j] if 0 <= j < len(r[key]) else None
        row.append(np.nan if v is None else v)
    return row


act = np.nanmedian([aligned(r, "actual") for r in wd], axis=0)
base = np.nanmedian([aligned(r, "base") for r in wd], axis=0)
labels = [("최고점" if k == 0 else f"{k * 15:+d}분") for k in REL]
ref = M["reference"]

fig, ax = plt.subplots(figsize=(9, 4.9), dpi=200)
x = np.arange(len(labels))
ax.bar(x, act, color=BLUE, label=f"평일 공연일 실제 출차 (구간별 중앙값, {len(wd)}건)")
ax.plot(x, base, color=GRAY, lw=2, label="평소 (앞뒤 3주 같은 요일의 공연 없는 날, 모자라면 앞뒤 4주 평일)")
ax.axhline(ref["observed_max_15m"]["value"], color=RED, ls="--", lw=1.2,
           label=f"{ref['observed_max_15m']['label']} {ref['observed_max_15m']['value']}대")
ax.axhline(ref["weekday_18h_median"]["value"], color=GREEN, ls=":", lw=1.4,
           label=f"{ref['weekday_18h_median']['label']} {ref['weekday_18h_median']['value']:.0f}대")
ax.set_xticks(x[::2], labels[::2], fontsize=10)
ax.tick_params(axis="y", labelsize=10)
ax.set_xlabel(f"각 공연의 출차 최고점 기준 상대 시각 (평일 최고점 시각 중앙값 {g_wd['peak_time_med']})")
ax.set_ylabel("15분 출차 대수")
ax.set_title(f"평일 공연일 출차: 최고점 15분 중앙값 {g_wd['peak_exits_med']:g}대, 같은 시각 평소 {g_wd['base_at_peak_med']:g}대 "
             f"(사례별 배율 중앙값 {g_wd['peak_ratio_case_med']:.1f}배)", fontsize=11)
ax.set_ylim(0, ref["observed_max_15m"]["value"] * 1.08)
ax.legend(fontsize=9.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "fig1_weekday_exit_curve.png")
plt.close(fig)

# ---------------------------------------------------------------------------
# 그림 2
# ---------------------------------------------------------------------------
names = [g["name"] for g in M["gates"]]
gm = pd.read_csv(ROOT / "data" / "gate_matrix_2025.csv")
mat = (gm[gm["in_gate"].isin(names) & gm["out_gate"].isin(names)]
       .assign(pct=lambda x: 100.0 * x["n"] / x["in_total"])
       .pivot(index="in_gate", columns="out_gate", values="pct").reindex(index=names, columns=names).fillna(0))

fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.8), dpi=200, gridspec_kw={"width_ratios": [1, 1.1]})
a1.imshow(mat.to_numpy(), cmap="Blues", vmin=0, vmax=100)
a1.set_xticks(range(len(names)), names, fontsize=10)
a1.set_yticks(range(len(names)), names, fontsize=10)
for i in range(len(names)):
    for j in range(len(names)):
        v = mat.iat[i, j]
        if v >= 0.05:
            # 비율 표시 규칙(원고·화면과 같음): 99% 이상은 소수 둘째 자리, 그 밖은 첫째 자리
            a1.text(j, i, f"{v:.2f}" if v >= 99 else f"{v:.1f}", ha="center", va="center", fontsize=8.5,
                    color="white" if v > 55 else "black")
a1.set_xlabel("나올 때 쓴 문", fontsize=11)
a1.set_ylabel("들어간 문", fontsize=11)
a1.set_title(f"들어간 문별 나온 문 비율(%), 2025년 {M['meta']['n_records_dedup']:,}건", fontsize=11)

xx = np.arange(len(names))
a2.bar(xx - 0.27, [g["event_weekday_peak15_med"] for g in M["gates"]], 0.27, color=BLUE, label="평일 공연일")
a2.bar(xx, [g["event_weekend_peak15_med"] for g in M["gates"]], 0.27, color=GREEN, label="주말 공연일")
a2.bar(xx + 0.27, [g["normal_peak15_med"] for g in M["gates"]], 0.27, color="#c3c8cf", label="공연 없는 평일")
for xi, g in zip(xx, M["gates"]):
    if g["mixed_zone"]:
        top = max(g["event_weekday_peak15_med"], g["event_weekend_peak15_med"], g["normal_peak15_med"])
        a2.text(xi, top + 3, f"x{g['event_weekday_vs_normal']:.2f}", ha="center", fontsize=10, color=BLUE, fontweight="bold")
a2.set_xticks(xx, names, fontsize=10)
a2.tick_params(axis="y", labelsize=10)
a2.set_ylabel("15분 출차 대수", fontsize=11)
a2.set_title("문별 저녁 15분 출차 최고값의 중앙값 (18:00~다음 날 03:00)\n세 문 위 파란 숫자: 평일 공연일의 공연 없는 평일 대비 배율", fontsize=11)
a2.legend(fontsize=9.5, frameon=False, loc="upper right")
a2.set_ylim(0, 140)
a2.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "fig2_gate_zones.png")
plt.close(fig)
print("그림 1, 2 저장. 평일 정렬 곡선 최고:", int(np.nanmax(act)), "같은 구간 평소:", round(float(base[int(np.nanargmax(act))]), 1))


# ---------------------------------------------------------------------------
# 그림 3: 서비스 화면 캡처
# ---------------------------------------------------------------------------
def find_browser():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(p).exists():
            return p
    return None


# 기획서용 캡처: 화면 코드는 그대로 두고, 캡처할 때만 다른 카드를 숨기는 스타일을 덧붙인 페이지를 찍는다
SHOT_CSS = {
    # 그림: 예측 결과 카드(네 가지 수치와 15분 단위 그래프). 입력값은 그림 설명에 적는다
    "predict": "header,main>section:not(#result),footer,.kpi .d,#basis,#chartNote{display:none!important}",
    # 그림: 2025년 실제 공연일 검증 그래프(교차검증 표는 기획서 본문 표로 옮김)
    "validation": "header,main>section:not(:nth-of-type(5)),footer,main>section:nth-of-type(5) table,#validation,#valIntro{display:none!important}",
}
SHOT_WIDTH = {"predict": 920, "validation": 760}
SHOT_FILES = {"predict": "fig3a_demo_predict.png", "validation": "fig3b_demo_validation.png"}


def shots():
    from PIL import Image

    exe = find_browser()
    if not exe:
        print("브라우저를 찾지 못해 화면 캡처를 건너뜁니다.")
        return
    index = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            name = self.path.split("?")[0].lstrip("/")
            if name.startswith("shot-") and name.endswith(".html"):
                css = SHOT_CSS[name[5:-5]]
                body = index.replace("</style>", css + "</style>").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    handler = functools.partial(Handler, directory=str(ROOT / "docs"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for key, fname in SHOT_FILES.items():
            raw = OUT / f"_raw_{key}.png"
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                            f"--window-size={SHOT_WIDTH[key]},2400", "--virtual-time-budget=10000", "--run-all-compositor-stages-before-draw",
                            f"--user-data-dir={ROOT / 'data' / 'edge-shot-profile'}", f"--screenshot={raw}",
                            f"http://127.0.0.1:{srv.server_address[1]}/shot-{key}.html?{DEMO_QUERY}"],
                           check=True, timeout=120, capture_output=True)
            im = Image.open(raw).convert("RGB")
            px = np.asarray(im).astype(int)
            bg = px[2, 2]
            rows = np.where((np.abs(px - bg).sum(axis=2) > 12).any(axis=1))[0]
            top, bottom = max(0, rows.min() - 16), min(px.shape[0], rows.max() + 16)
            im.crop((0, top, px.shape[1], bottom)).save(OUT / fname)
            raw.unlink()
            print("화면 캡처 저장:", fname, im.size, (top, bottom))
    finally:
        srv.shutdown()


if "--no-shots" not in sys.argv:
    shots()
print("saved", sorted(p.name for p in OUT.glob("*.png")))
