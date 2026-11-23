const PARKING_API = "https://www.ksponco.or.kr/online/main/parkingorsApi.do?apiKey=PARKING21803504";
const SLOT = 15;
let M = null;
let chart = null;
let chart2 = null;

const $ = (id) => document.getElementById(id);
const pad = (n) => String(n).padStart(2, "0");
const toMin = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
const fmt = (min) => { min = ((Math.round(min) % 1440) + 1440) % 1440; return `${pad(Math.floor(min / 60))}:${pad(min % 60)}`; };
const dayOf = (dateStr) => new Date(dateStr + "T00:00:00");
const isWeekend = (dateStr) => { const d = dayOf(dateStr).getDay(); return d === 0 || d === 6; };
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

async function loadLive() {
  try {
    const r = await fetch(PARKING_API, { cache: "no-store" });
    const n = JSON.parse(await r.text())[0].parking_sum;
    $("liveCount").textContent = `${n.toLocaleString()}대`;
    const now = new Date();
    const level = n >= M.full_occ_warn ? "만차에 가까움" : n >= M.full_occ_warn * 0.8 ? "혼잡" : "여유";
    $("liveNote").textContent = `현재 주차 중 · ${level} (${pad(now.getHours())}:${pad(now.getMinutes())} 기준, 2025년 상위 1% 점유 ${M.full_occ_warn.toLocaleString()}대 대비)`;
  } catch (e) {
    $("liveNote").textContent = "실시간 주차현황을 불러오지 못했습니다.";
  }
}

function baselineFor(dateStr, weekend) {
  let m = dayOf(dateStr).getMonth() + 1;
  const key = (mm) => `${mm}-${weekend ? "we" : "wd"}`;
  for (let i = 0; i < 12 && !M.baseline[key(m)]; i++) m = (m % 12) + 1;
  return M.baseline[key(m)];
}

function predict(dateStr, weekend, endMin) {
  const g = M.groups.find((x) => x.weekend === weekend);
  const base = baselineFor(dateStr, weekend);
  const peakSlot = Math.floor(endMin / SLOT) + M.peak_after_end_slots;
  const out = base.slice();
  M.rel_slots.forEach((k, i) => {
    const s = peakSlot + k;
    if (s >= 0 && s < 96) out[s] = Math.min(M.exit_capacity_15m, Math.max(0, base[s] + g.excess_profile[i]));
  });
  const peakMin = peakSlot * SLOT;
  return { g, base, out, peakMin, arrivalPeak: peakMin - g.arrival_lead_med };
}

function drawChart(canvas, labels, datasets, existing) {
  if (existing) existing.destroy();
  return new Chart(canvas, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: cssVar("--sub") } } },
      scales: {
        x: { ticks: { color: cssVar("--sub"), maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }, grid: { display: false } },
        y: { ticks: { color: cssVar("--sub") }, grid: { color: cssVar("--line") }, title: { display: true, text: "15분 출차 대수", color: cssVar("--sub") } },
      },
    },
  });
}

const range = (a, b) => { const r = []; for (let i = Math.max(0, a); i < Math.min(96, b); i++) r.push(i); return r; };

function run() {
  const date = $("date").value;
  const weekend = isWeekend(date);
  const startMin = toMin($("start").value);
  const endMin = startMin + Number($("dur").value);
  const audience = Number($("aud").value);
  const p = predict(date, weekend, endMin);
  const g = p.g;

  const arriveBy = Math.min(p.arrivalPeak - 30, startMin - 30);
  $("kArrive").textContent = `${fmt(arriveBy)} 이전`;
  $("kArriveD").textContent = `공연일 입차는 ${fmt(p.arrivalPeak)} 전후에 가장 몰립니다`;
  $("kWait").textContent = `약 ${g.clear_med}분`;
  $("kWaitD").textContent = `종료 ${fmt(endMin)} 직후 출발 기준, 길면 ${g.clear_p75}분 (출차 최고점 ${fmt(p.peakMin)} 전후)`;
  $("kLeave").textContent = `${fmt(p.peakMin + g.clear_p75)} 이후`;
  $("kLeaveD").textContent = "러시가 끝나 평소 수준으로 돌아오는 시각";
  const gate = M.gates.filter((x) => x.event_share >= 0.04).reduce((a, b) => (b.load_ratio < a.load_ratio ? b : a));
  $("kGate").textContent = gate.name;
  $("kGateD").textContent = `공연일 저녁 출차 비중 ${(gate.event_share * 100).toFixed(0)}% · 처리량 대비 여유가 큼`;

  const riskHigh = audience >= 10000 || g.occ_max_p90 >= M.full_occ_warn;
  $("basis").textContent =
    `근거: 2025년 ${weekend ? "주말" : "평일"} 공연일 ${g.n}회 실측 (입출차 ${M.n_records.toLocaleString()}건). ` +
    `공연 직후 15분 동안 평소보다 약 ${Math.round(Math.max(...g.excess_profile))}대가 더 빠져나가며, 출구 전체 처리 한계는 15분 약 ${M.exit_capacity_15m}대입니다. ` +
    (riskHigh ? `관객 ${audience.toLocaleString()}명 규모는 만차 가능성이 있어 대중교통(5·8호선 올림픽공원역·몽촌토성역)을 권합니다.` : "");

  $("result").hidden = false;
  const idx = range(Math.floor(endMin / SLOT) - 8, Math.floor(endMin / SLOT) + 13);
  chart = drawChart($("chart"), idx.map((i) => fmt(i * SLOT)), [
    { type: "line", label: "평소 (공연 없는 같은 달·요일 유형)", data: idx.map((i) => p.base[i]), borderColor: cssVar("--sub"), pointRadius: 0, borderWidth: 2 },
    { label: "공연일 예상 출차", data: idx.map((i) => Math.round(p.out[i])), backgroundColor: cssVar("--accent") },
  ], chart);
  if (!new URLSearchParams(location.search).has("date")) $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function replay() {
  const r = M.replay[Number($("replay").value)];
  const g = M.groups.find((x) => x.weekend === r.weekend);
  const pred = r.base_15_24.slice();
  M.rel_slots.forEach((k, i) => {
    const j = r.peak_slot + k - 60;
    if (j >= 0 && j < pred.length) pred[j] = Math.min(M.exit_capacity_15m, Math.max(0, r.base_15_24[j] + g.excess_profile[i]));
  });
  const idx = range(60, 96);
  chart2 = drawChart($("chart2"), idx.map((i) => fmt(i * SLOT)), [
    { type: "line", label: "평소 (앞뒤 3주 같은 요일)", data: r.base_15_24, borderColor: cssVar("--sub"), pointRadius: 0, borderWidth: 1.5 },
    { type: "line", label: "모델 예측", data: pred.map(Math.round), borderColor: cssVar("--warn"), pointRadius: 0, borderWidth: 2 },
    { label: "실제 출차", data: r.actual_15_24, backgroundColor: cssVar("--accent") },
  ], chart2);
  $("replayNote").textContent = `${r.date} · ${r.event} · 관람객 ${r.audience.toLocaleString()}명 · 실제 최고점 ${r.peak_time}, 러시 ${r.clear_minutes}분 (같은 유형 중앙값 ${g.clear_med}분)`;
}

async function init() {
  M = await (await fetch("data/model.json")).json();
  const vSel = $("venue");
  M.venues.forEach((v, i) => vSel.add(new Option(v.name, i)));
  const syncAud = () => {
    const v = M.venues[Number(vSel.value)];
    $("aud").value = v.default_audience;
    $("audHint").textContent = `${v.name} 기본값 ${v.default_audience.toLocaleString()}명 (공연장 규모 기준 추정). 같은 날 다른 공연장 공연이 있으면 합산해 입력하세요.`;
  };
  vSel.addEventListener("change", syncAud);
  syncAud();
  const t = new Date();
  $("date").value = `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
  $("go").addEventListener("click", run);

  const rSel = $("replay");
  M.replay.forEach((r, i) => rSel.add(new Option(`${r.date} (${r.weekend ? "주말" : "평일"}) ${r.event.slice(0, 40)}`, i)));
  rSel.addEventListener("change", replay);
  const typical = M.replay.map((r, i) => ({ r, i })).filter(({ r }) => !r.weekend && r.audience >= 10000 && r.peak_slot <= 92);
  const pick = typical.length ? typical.reduce((a, b) => (b.r.mae < a.r.mae ? b : a)).i : 0;
  rSel.value = String(pick);
  replay();
  const v = M.validation;
  $("validation").textContent = `교차검증(해당 공연을 빼고 만든 모델로 예측): 러시 지속 시간은 ${v.clear_within_15_pct}%가 15분 이내 오차, ` +
    `최고점 출차량 오차 중앙값 ${v.peak_err_med}대, 15분 출차량 오차는 '평소대로' 예측보다 ${v.improvement_pct}% 작습니다.`;
  loadLive();
  setInterval(loadLive, 60000);

  // 공유용 링크: ?date=2026-12-17&start=19:30&dur=150&venue=0&aud=15000
  const q = new URLSearchParams(location.search);
  if (q.has("date")) {
    $("date").value = q.get("date");
    if (q.has("venue")) { vSel.value = q.get("venue"); syncAud(); }
    if (q.has("start")) $("start").value = q.get("start");
    if (q.has("dur")) $("dur").value = q.get("dur");
    if (q.has("aud")) $("aud").value = q.get("aud");
    run();
  }
}
init();
