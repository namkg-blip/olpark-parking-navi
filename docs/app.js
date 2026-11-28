const PARKING_API = "https://www.ksponco.or.kr/online/main/parkingorsApi.do?apiKey=PARKING21803504";
const SLOT = 15;
let M = null;
let chart = null;
let chart2 = null;

const $ = (id) => document.getElementById(id);
const pad = (n) => String(n).padStart(2, "0");
const num = (n) => Math.round(n).toLocaleString();
const num1 = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 });
const toMin = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
const fmt = (min) => { min = ((Math.round(min) % 1440) + 1440) % 1440; return `${pad(Math.floor(min / 60))}:${pad(min % 60)}`; };
const fmtDay = (min) => (min >= 1440 ? "다음 날 " : "") + fmt(min);
const dayOf = (dateStr) => new Date(dateStr + "T00:00:00");
const isWeekend = (dateStr) => { const d = dayOf(dateStr).getDay(); return d === 0 || d === 6; };
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const kind = (weekend) => (weekend ? "주말" : "평일");
const hm = (min) => { min = Math.abs(Math.round(min)); const h = Math.floor(min / 60), m = min % 60; return (h ? `${h}시간 ` : "") + (m || !h ? `${m}분` : "").trim(); };
// 지속 시간 표기: 측정 단위가 15분이라 15의 배수가 아니면 앞뒤 눈금으로 구간을 적는다
const durLabel = (v) => {
  if (Math.abs(v / SLOT - Math.round(v / SLOT)) < 1e-9) return `${Math.round(v)}분`;
  const lo = Math.floor(v / SLOT) * SLOT;
  return `${lo}~${lo + SLOT}분`;
};

async function loadLive() {
  const z = M.zone;
  try {
    const r = await fetch(PARKING_API, { cache: "no-store" });
    const n = JSON.parse(await r.text())[0].parking_sum;
    $("liveCount").textContent = `${n.toLocaleString()}대`;
    const now = new Date();
    const level = n >= z.occ_p99 ? "2025년 상위 1% 수준 이상으로 매우 붐빔" : n >= z.occ_p95 ? "2025년 상위 5% 수준 이상으로 붐빔" : "2025년 상위 5% 수준 미만";
    $("liveNote").textContent =
      `${pad(now.getHours())}:${pad(now.getMinutes())} 현재 주차 중. 기관 안내 주차면 ${z.spaces_official.toLocaleString()}대의 ${Math.round((n / z.spaces_official) * 100)}%. ${level}.`;
  } catch (e) {
    $("liveNote").textContent = "실시간 주차현황을 불러오지 못했습니다.";
  }
  $("liveScope").textContent =
    `이 값은 올림픽공원 전체가 아니라 ${z.gates.join("·")} 구역의 주차 대수입니다(기관 안내 ${z.spaces_official.toLocaleString()}대). ` +
    `비교 기준은 2025년 같은 세 문 입차분만으로 추정한 15분 단위 점유로, 상위 5%는 ${z.occ_p95.toLocaleString()}대, 상위 1%는 ${z.occ_p99.toLocaleString()}대였습니다. ` +
    `추정 점유는 입차와 출차 기록의 차이라서 기관이 세는 주차면 수와 범위가 다를 수 있습니다.`;
}

// 예측 화면의 평소 선: 2025년 같은 달의 공연 없는 유효 평일. 그 달이 없으면 뒤따르는 가장 가까운 달
function baselineFor(dateStr) {
  const want = dayOf(dateStr).getMonth() + 1;
  let m = want;
  const key = (mm) => `${mm}-wd`;
  for (let i = 0; i < 12 && !M.baseline[key(m)]; i++) m = (m % 12) + 1;
  return { arr: M.baseline[key(m)], month: m, want, days: M.baseline_days[key(m)] };
}

// 초과 곡선. 관객 수를 쓰면 곡선의 양(+) 부분을 관객 수에 맞춰 늘이거나 줄인다
function profileFor(g, audience) {
  const k0 = M.rel_slots.indexOf(0);
  if (!g.use_audience || !(audience > 0) || g.excess_profile[k0] <= 0) return g.excess_profile;
  const e = g.audience_model.excess;
  const peakExcess = clamp(e.b0 + e.b1 * audience, e.min, e.max);
  return g.excess_profile.map((x) => (x > 0 ? (x * peakExcess) / g.excess_profile[k0] : x));
}

function clearFor(g, audience) {
  if (!g.use_audience || !(audience > 0)) return { mid: g.clear_med, byAudience: false };
  const c = g.audience_model.clear;
  return { mid: clamp(Math.round((c.c0 + c.c1 * audience) / SLOT) * SLOT, c.min, c.max), byAudience: true };
}

// 평소 값에 초과분을 더하되 2025년 평일 공연일의 최고점 15분 출차 최댓값(cap)을 넘기지 않는다.
// 평소 값이 cap보다 크면 평소 값을 둔다. 분석 사례 안의 관측 범위를 벗어나지 않게 하는 상한이며 출구의 처리 한계가 아니다.
const capped = (base, e, cap) => { const v = Math.max(0, base + e); return v > cap ? Math.max(cap, Math.min(v, base)) : v; };

function predict(dateStr, endMin, audience) {
  const g = M.groups.find((x) => !x.weekend);
  const b = baselineFor(dateStr);
  const peakSlot = clamp(Math.floor(endMin / SLOT) + M.peak_after_end_slots, 0, M.ext_slots - 1);
  const prof = profileFor(g, audience);
  const out = b.arr.slice();
  M.rel_slots.forEach((k, i) => {
    const s = peakSlot + k;
    if (s >= 0 && s < M.ext_slots) out[s] = capped(b.arr[s], prof[i], g.peak_exits_max);
  });
  const raw = Math.max(0, b.arr[peakSlot] + prof[M.rel_slots.indexOf(0)]);
  // 가장 붐비는 구간: 예상 출차가 예상 최고점의 절반 이상인, 최고점 앞뒤로 이어진 구간
  const half = out[peakSlot] * 0.5;
  let busyFrom = peakSlot, busyTo = peakSlot;
  while (busyFrom - 1 >= 0 && out[busyFrom - 1] >= half) busyFrom--;
  while (busyTo + 1 < M.ext_slots && out[busyTo + 1] >= half) busyTo++;
  return { g, b, out, peakSlot, peakMin: peakSlot * SLOT, arrivalPeak: peakSlot * SLOT - g.arrival_lead_med,
           clear: clearFor(g, audience), capHit: raw > g.peak_exits_max, busyFrom, busyTo };
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
        y: { beginAtZero: true, ticks: { color: cssVar("--sub") }, grid: { color: cssVar("--line") }, title: { display: true, text: "15분 출차 대수", color: cssVar("--sub") } },
      },
    },
  });
}

const range = (a, b) => { const r = []; for (let i = Math.max(0, a); i < Math.min(M.ext_slots, b); i++) r.push(i); return r; };
const setKpi = (n, t, v, d) => { $(`kT${n}`).textContent = t; $(`kV${n}`).textContent = v; $(`kD${n}`).textContent = d; };

function run() {
  const date = $("date").value;
  if (!date) return;
  const startMin = toMin($("start").value);
  const endMin = startMin + Number($("dur").value);
  const audience = Number($("aud").value);
  $("result").hidden = false;
  if (isWeekend(date)) runWeekend(endMin);
  else runWeekday(date, startMin, endMin, audience);
  if (!new URLSearchParams(location.search).has("date")) $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function runWeekday(date, startMin, endMin, audience) {
  const p = predict(date, endMin, audience);
  const g = p.g;
  const v = M.validation.weekday;
  const vv = g.use_audience ? v.aud : v.plain;
  const ref = M.reference;
  $("resultTitle").textContent = "평일 예측 결과";
  $("k4").hidden = false;

  const arriveBy = Math.min(p.arrivalPeak - 30, startMin - 30);
  const lead = startMin - p.arrivalPeak;
  setKpi(1, "권장 도착", `${fmt(arriveBy)} 이전`,
    `입차는 ${fmt(p.arrivalPeak)} 전후에 가장 몰릴 것으로 봅니다(${lead > 0 ? `공연 시작 ${hm(lead)} 전` : "공연 시작 무렵"}). ` +
    `2025년 평일 공연일의 입차 최고점(출차 최고점 6시간 전~1시간 전 가운데 입차가 평소보다 가장 많이 늘어난 15분)은 출차 최고점보다 ${hm(g.arrival_lead_med)} 앞이었고(중앙값), ` +
    `이 간격을 종료 시각에서 거꾸로 뺀 값입니다. 공연 시간이 2025년 사례와 다르면 어긋날 수 있습니다. 시작 30분 전보다 늦게 잡히지는 않습니다.`);

  setKpi(2, "출차 최고점 예상", `${fmtDay(p.peakMin)} 전후`,
    `15분에 약 ${num(p.out[p.peakSlot])}대 출차 예상(평소 같은 시각 ${num(p.b.arr[p.peakSlot])}대). ` +
    (p.capHit ? `더한 값이 2025년 평일 공연일 ${g.n}건의 최고점 15분 출차 최댓값 ${g.peak_exits_max}대를 넘어 그 값으로 맞췄습니다. ` : "") +
    `종료 ${fmtDay(endMin)} 뒤 15분쯤에 최고점이 온다는 가정이며, 실제 종료 시각 자료가 없어 확인하지 못했습니다.`);

  const after = p.busyTo + 1;
  setKpi(3, "가장 붐비는 구간을 피하는 시각", `${fmtDay(after * SLOT)} 이후`,
    `예상 출차가 최고점의 절반 이상인 구간은 ${fmtDay(p.busyFrom * SLOT)}~${fmtDay(after * SLOT)}입니다. ` +
    (after < M.ext_slots ? `그 뒤 15분에는 약 ${num(p.out[after])}대(평소 ${num(p.b.arr[after])}대)가 나갈 것으로 봅니다. ` : "") +
    `가장 붐비는 구간은 보통 공연 종료 구간부터 시작하므로, 이 시각 뒤에 나가면 가장 몰리는 구간을 피합니다. 2025년 평일 사례에서 최고점의 절반 이상 출차가 이어진 시간은 중앙값 ${g.half_med_label}이었습니다.`);

  const endAt = p.peakMin + p.clear.mid;
  setKpi(4, "평소 수준 가까이 내려오는 시각", `${fmtDay(endAt)} 무렵`,
    `출차가 '평소 x 1.3 + 10대' 이하로 내려올 때까지를 러시로 보면 최고점부터 ` +
    (p.clear.byAudience ? `약 ${p.clear.mid}분(관객 ${audience.toLocaleString()}명 기준 추정, 교차검증 ${v.n}건 중 ${vv.clear_within_15_n}건이 15분 이내로 맞음). `
      : `${g.clear_med_label}(2025년 평일 ${g.n}건 중앙값). `) +
    `심야에는 이 기준이 15분 약 ${num(g.rush_end_threshold_med)}대라 최고점 뒤 잔여 출차까지 포함한 시간입니다. 2025년 평일 사례에서 러시 동안 늘어난 출차의 약 ${Math.round(g.excess_share_first30_med * 100)}%(중앙값)는 최고점부터 30분 안에 나갔습니다.`);

  // 구간별 예상 출차
  const rows = range(p.peakSlot - 2, Math.min(M.ext_slots, p.peakSlot + 9));
  $("slotHead").innerHTML = `<tr><th>시각</th>${rows.map((i) => `<th>${fmt(i * SLOT)}</th>`).join("")}</tr>`;
  $("slotBody").innerHTML =
    `<tr><td>예상 출차</td>${rows.map((i) => `<td${i >= p.busyFrom && i <= p.busyTo ? ' style="font-weight:700"' : ""}>${num(p.out[i])}</td>`).join("")}</tr>` +
    `<tr><td>평소</td>${rows.map((i) => `<td>${num(p.b.arr[i])}</td>`).join("")}</tr>`;
  $("slotWrap").hidden = false;
  $("slotNote").textContent = `굵은 칸이 가장 붐비는 구간(예상 출차가 예상 최고점의 절반 이상)입니다. 다음 날 시각은 00:00부터 다시 셉니다.`;

  const days = M.event_days.filter((d) => !d.weekend);
  const over = (rows_) => rows_.filter((d) => d.occ3_daymax >= M.zone.spaces_official).length;
  const big = days.filter((d) => d.audience >= audience);
  let occText = `2025년 평일 공연일 ${days.length}일 중 ${over(days)}일은 ${M.zone.gates.join("·")} 구역의 추정 주차 대수가 기관 안내 ${M.zone.spaces_official.toLocaleString()}대를 넘었습니다`;
  if (audience > 0 && big.length >= 3 && big.length < days.length) occText += `(관객 수가 ${audience.toLocaleString()}명 이상이던 ${big.length}일로 좁히면 ${over(big)}일)`;
  const audText = g.use_audience
    ? `관객 수로 최고점 크기와 러시 지속 시간을 조정합니다(2025년 평일 ${g.n}건에서 관객 수와 초과 출차 최고점의 상관 ${M.audience_corr.weekday.peak_excess.pearson}, 조정한 최고점 크기와 지속 시간은 2025년 평일 사례에서 본 범위 안으로 자름). `
    : `관객 수는 예측에 쓰지 않습니다. `;
  const thin = p.b.days < 5 ? ` 이 달은 공연 없는 평일이 ${p.b.days}일뿐이라 평소 선이 흔들릴 수 있습니다.` : "";
  $("basis").textContent =
    `근거: 2025년 평일 공연일 ${g.n}건. 최고점 15분 출차의 중앙값은 ${num1(g.peak_exits_med)}대, 같은 시각 평소 중앙값은 ${num1(g.base_at_peak_med)}대이고 사례별 배율의 중앙값은 ${Number(g.peak_ratio_case_med).toFixed(1)}배입니다. ` +
    audText + `공연장은 관객 수 기본값을 채우는 데만 씁니다. ` + occText + `.` + thin + ` ` +
    `참고: ${ref.observed_max_15m.label} ${ref.observed_max_15m.value}대, ${ref.weekday_18h_median.label} ${num(ref.weekday_18h_median.value)}대. ` +
    `대중교통은 5·9호선 올림픽공원역, 8호선 몽촌토성역이 가깝습니다.`;

  const endSlot = Math.floor(endMin / SLOT);
  const idx = range(endSlot - 8, endSlot + 13);
  const baseLabel = `평소 (2025년 ${p.b.month}월 공연 없는 평일 ${p.b.days}일 중앙값)`;
  chart = drawChart($("chart"), idx.map((i) => fmt(i * SLOT)), [
    { type: "line", label: baseLabel, data: idx.map((i) => p.b.arr[i]), borderColor: cssVar("--sub"), pointRadius: 0, borderWidth: 2 },
    { label: "공연일 예상 출차", data: idx.map((i) => Math.round(p.out[i])), backgroundColor: cssVar("--accent") },
  ], chart);
  $("chartNote").textContent =
    `막대: 15분마다 빠져나가는 예상 차량 수. 회색 선: ${M.meta.baseline_predict}` +
    (p.b.month !== p.b.want ? ` 이번에는 ${p.b.want}월에 공연 없는 유효 평일이 없어 ${p.b.month}월 값을 썼습니다.` : "");
}

function runWeekend(endMin) {
  const w = M.weekend_obs;
  $("resultTitle").textContent = "주말: 2025년 주말 공연일 실측 (예측 아님)";
  $("k4").hidden = true;
  $("slotWrap").hidden = true;
  setKpi(1, "저녁 최고 15분 출차", `${num(w.peak_exits_med)}대`,
    `2025년 주말 공연일 ${w.n}일의 ${w.peak_window} 15분 출차 최고값 중앙값입니다. 절반은 ${num(w.peak_exits_q25)}~${num(w.peak_exits_q75)}대, 가장 많았던 날은 ${w.peak_exits_max}대(${w.peak_exits_max_date} ${w.peak_exits_max_time}).`);
  setKpi(2, "최고점 시각", `${w.peak_time_med} 전후`,
    `같은 ${w.n}일의 중앙값이며 절반은 ${w.peak_time_q25}~${w.peak_time_q75}에 왔습니다. 입력한 종료 시각(${fmtDay(endMin)})은 쓰지 않았습니다.`);
  setKpi(3, "최고점의 절반 이상 출차가 이어진 시간", w.half_med_label,
    `${w.half_definition}. 중앙값이며 75%는 ${w.half_p75_label} 이내, 가장 길었던 날은 ${w.half_max}분이었습니다.`);
  $("basis").textContent =
    `${M.meta.weekend_rule} 그래서 주말에는 '평소보다 몇 대 더'나 러시가 끝나는 시각을 내지 않습니다. ` +
    `2025년 주말 공연일 ${w.event_days_valid}일 중 ${w.occ3_over_spaces_n}일은 ${M.zone.gates.join("·")} 구역의 추정 주차 대수가 기관 안내 ${M.zone.spaces_official.toLocaleString()}대를 넘었습니다. ` +
    `대중교통은 5·9호선 올림픽공원역, 8호선 몽촌토성역이 가깝습니다.`;
  const from = w.curve_from_slot;
  const idx = range(from, M.ext_slots);
  const at = (arr, i) => arr[i - from];
  chart = drawChart($("chart"), idx.map((i) => fmt(i * SLOT)), [
    { type: "line", label: "하위 25%", data: idx.map((i) => at(w.curve_q25, i)), borderColor: cssVar("--sub"), borderDash: [4, 3], pointRadius: 0, borderWidth: 1.5 },
    { type: "line", label: "상위 25%", data: idx.map((i) => at(w.curve_q75, i)), borderColor: cssVar("--warn"), borderDash: [4, 3], pointRadius: 0, borderWidth: 1.5 },
    { label: `2025년 주말 공연일 ${w.n}일 중앙값`, data: idx.map((i) => at(w.curve_med, i)), backgroundColor: cssVar("--accent") },
  ], chart);
  $("chartNote").textContent = `시각별 15분 출차(15:00부터 다음 날 03:00까지). 막대는 주말 공연일 ${w.n}일의 중앙값, 점선은 하위·상위 25%입니다. 공연마다 끝나는 시각이 달라 최고점이 여러 시각에 흩어져 있습니다.`;
}

function renderGates() {
  // 비율 표시 규칙: 99% 이상은 소수 둘째 자리, 그 밖은 첫째 자리
  const pct = (x) => (x.pct >= 99 ? `${x.pct.toFixed(2)}%` : `${x.pct.toFixed(1)}%`);
  $("gateRows").innerHTML = M.gates.map((x) =>
    `<tr><td>${x.name}</td><td>${x.exits_to.map((t) => `${t.gate} ${pct(t)}`).join(", ")}</td>` +
    `<td>${num1(x.event_weekday_peak15_med)}대 (${Number(x.event_weekday_vs_normal).toFixed(2)}배) / ${num1(x.event_weekend_peak15_med)}대</td><td>${num1(x.normal_peak15_med)}대</td></tr>`).join("");
  const mixed = M.gates.filter((x) => x.mixed_zone);
  const wd = mixed.slice().sort((a, b) => a.event_weekday_peak15_med - b.event_weekday_peak15_med);
  const we = mixed.slice().sort((a, b) => a.event_weekend_peak15_med - b.event_weekend_peak15_med);
  const top = mixed.slice().sort((a, b) => b.event_weekday_vs_normal - a.event_weekday_vs_normal)[0];
  const weGap = (we[we.length - 1].event_weekend_peak15_med - we[0].event_weekend_peak15_med) / we[we.length - 1].event_weekend_peak15_med;
  $("gateMixed").textContent =
    `나갈 문을 고를 수 있는 곳은 서로 섞이는 ${mixed.map((x) => x.name).join("·")} 구역뿐입니다. ` +
    `평일 공연일 저녁 15분 출차 최고는 ${wd.map((x) => `${x.name} ${num1(x.event_weekday_peak15_med)}대`).join(", ")}로 ${wd[0].name}이 가장 적지만, ` +
    `공연 없는 평일 대비로는 ${top.name}이 ${Number(top.event_weekday_vs_normal).toFixed(2)}배로 가장 크게 늘었습니다. 평소 한산한 문에 공연일 출차가 몰린다는 뜻이라 어느 문이 낫다고 단정하지 않습니다. ` +
    `주말 공연일은 ${we.map((x) => `${x.name} ${num1(x.event_weekend_peak15_med)}대`).join(", ")}` +
    (weGap < 0.15 ? `로 차이가 15% 미만입니다.` : `입니다.`) + ` 주말은 공연 없는 주말이 없어 평소 대비 배율을 내지 않습니다.`;
  $("gateDef").textContent =
    `${M.meta.gate_peak_definition} 괄호는 공연 없는 평일 대비 배율입니다. 유효 공연일 ${M.meta.event_days_valid}일(평일 ${M.meta.event_days_valid_weekday}, 주말 ${M.meta.event_days_valid_weekend}) 기준. ` +
    `나오는 문 비율은 2025년 입출차 기록(중복 제거 뒤 ${M.meta.n_records_dedup.toLocaleString()}건) 전체에서 센 값이며, 99% 이상은 소수 둘째 자리까지 적습니다.`;
}

function replay() {
  const r = M.replay[Number($("replay").value)];
  const from = M.replay_from_slot;
  const idx = range(from, M.ext_slots);
  if (r.weekend) {
    const w = M.weekend_obs;
    chart2 = drawChart($("chart2"), idx.map((i) => fmt(i * SLOT)), [
      { type: "line", label: `2025년 주말 공연일 ${w.n}일 중앙값`, data: w.curve_med, borderColor: cssVar("--sub"), pointRadius: 0, borderWidth: 1.5 },
      { label: "실제 출차", data: r.actual, backgroundColor: cssVar("--accent") },
    ], chart2);
    $("replayNote").textContent =
      `${r.date} (주말), ${r.event}, 관람객 ${r.audience.toLocaleString()}명(같은 시간대 공연 합계). 저녁 최고 ${r.peak_time}, 최고점의 절반 이상 출차가 이어진 시간 ${r.half_minutes}분. ` +
      `주말은 공연 없는 주말이 없어 평소 선과 모델 곡선이 없고, 회색 선은 주말 공연일끼리의 중앙값입니다.`;
    return;
  }
  const g = M.groups.find((x) => !x.weekend);
  const prof = profileFor(g, r.audience);
  const pred = r.base.slice();
  M.rel_slots.forEach((k, i) => {
    const j = r.peak_slot + k - from;
    if (j >= 0 && j < pred.length && r.base[j] !== null) pred[j] = capped(r.base[j], prof[i], g.peak_exits_max);
  });
  const baseLabel = r.base_kind === "같은 요일 21일"
    ? `평소 (앞뒤 3주 같은 요일의 공연 없는 날 ${r.base_n_days}일 중앙값)`
    : `평소 (같은 요일이 모자라 앞뒤 4주 공연 없는 평일 ${r.base_n_days}일 중앙값으로 대체)`;
  chart2 = drawChart($("chart2"), idx.map((i) => fmt(i * SLOT)), [
    { type: "line", label: baseLabel, data: r.base, borderColor: cssVar("--sub"), pointRadius: 0, borderWidth: 1.5 },
    { type: "line", label: "모델 곡선 (실제 최고점 시각에 맞춤)", data: pred.map((x) => (x === null ? null : Math.round(x))), borderColor: cssVar("--warn"), pointRadius: 0, borderWidth: 2 },
    { label: "실제 출차", data: r.actual, backgroundColor: cssVar("--accent") },
  ], chart2);
  $("replayNote").textContent =
    `${r.date} (평일), ${r.event}, 관람객 ${r.audience.toLocaleString()}명(같은 시간대 공연 합계). 실제 최고점 ${r.peak_time}, 러시 지속 ${r.clear_minutes}분` +
    (r.clear_censored ? "(다음 날이 기록 부족일이라 자정에서 측정을 멈춘 하한값)" : "") +
    `. 평일 중앙값은 ${g.clear_med_label}. 그래프는 15:00부터 다음 날 03:00까지이며, 모델 곡선은 이 공연도 포함해 만든 것이라 아래 교차검증 수치와는 다릅니다.`;
}

function renderValidation() {
  const v = M.validation.weekday;
  const row = (a, name) =>
    `<tr><td>${name}</td>` +
    `<td>${a.clear_within_15_n}건 (${a.clear_within_15_pct}%)</td><td>${a.clear_err_med}분</td>` +
    `<td>${a.known.peak_err_med}대</td><td>${a.blind.peak_err_med}대</td>` +
    `<td>${a.known.mae_med}대 / ${a.blind.mae_med}대 / ${v.baseline_only_mae_med}대</td>` +
    `<td>${v.blind_peak_time.err_med_min}분</td></tr>`;
  $("valRows").innerHTML = row(v.use_audience ? v.aud : v.plain, `평일 ${v.n}건${v.use_audience ? " (관객 수 사용)" : ""}`) +
    (v.use_audience ? row(v.plain, `평일 ${v.n}건 (관객 수 미사용)`) : "");
  $("validation").textContent =
    `교차검증은 해당 공연을 빼고 만든 모델로 그 공연을 예측한 결과이며 평일만 합니다(주말은 평소 기준선이 없음). '아는 조건'은 실제 최고점 시각에 곡선을 맞춘 것이고, ` +
    `'모르는 조건'은 연계 데이터가 그날 공연을 표시한 마지막 시각에 다른 공연들의 지연 중앙값을 더해 최고점 시각을 예측한 것입니다. ` +
    `연계 데이터의 시각은 1시간 단위 표시 구간일 뿐 실제 종료 시각이 아닙니다. ${M.meta.baseline_validation}`;
}

function renderLimits() {
  const m = M.meta;
  $("limits").innerHTML =
    `<li>러시 정의: ${m.rush_definition}</li><li>표기: ${m.duration_rule} ${m.busy_rule}</li><li>상한: ${m.peak_cap_rule}</li>` + m.limits.map((t) => `<li>${t}</li>`).join("") +
    `<li>건수: 문별 나오는 문 비율은 중복 제거 뒤 ${m.n_records_dedup.toLocaleString()}건, 15분 집계와 모델은 그중 입차가 2025년이고 출차가 입차 뒤 2일 안인 ${m.n_records_analyzed.toLocaleString()}건 기준입니다.</li>` +
    `<li>참고 수치: ${M.reference.observed_max_15m.label} ${M.reference.observed_max_15m.value}대(${M.reference.observed_max_15m.when}), ` +
    `${M.reference.weekday_18h_median.label} ${num(M.reference.weekday_18h_median.value)}대(${M.reference.weekday_18h_median.definition}, ${M.reference.weekday_18h_median.n_days}일). 둘 다 관측값이며 상한이 아닙니다.</li>`;
}

async function init() {
  M = await (await fetch("data/model.json")).json();
  const vSel = $("venue");
  M.venues.forEach((v, i) => vSel.add(new Option(v.name, i)));
  const audUse = M.groups[0].use_audience
    ? "관객 수는 평일 예측에 반영됩니다. 주말은 공연 없는 주말이 없어 예측하지 않고 2025년 주말 공연일 실측만 보여 줍니다."
    : "관객 수는 예측에 쓰이지 않고 주차 대수 안내 문구에만 쓰입니다.";
  const syncAud = () => {
    const v = M.venues[Number(vSel.value)];
    $("aud").value = v.default_audience;
    $("audHint").textContent =
      `${v.name} 기본값 ${v.default_audience.toLocaleString()}명(공연장 규모로 어림한 값). 공연장은 이 기본값을 채우는 데만 쓰고 예측에는 쓰지 않습니다. ` +
      audUse + ` 관객 수는 같은 시간대 공연 관람객 합계입니다. 같은 시간대에 공연이 여럿이면 모두 더해 넣으세요(2025년 자료와 같은 기준).`;
  };
  vSel.addEventListener("change", syncAud);
  syncAud();
  const t = new Date();
  $("date").value = `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
  $("go").addEventListener("click", run);

  const rSel = $("replay");
  M.replay.forEach((r, i) => rSel.add(new Option(`${r.date} (${kind(r.weekend)}) ${r.event}`, i)));
  rSel.addEventListener("change", replay);
  // 검증 화면에서 처음 보일 날짜: ?replay=2025-07-11 처럼 지정할 수 있고, 없으면 첫 사례
  const want = new URLSearchParams(location.search).get("replay");
  rSel.value = String(Math.max(0, M.replay.findIndex((r) => r.date === want)));
  replay();
  renderGates();
  renderValidation();
  renderLimits();
  $("valIntro").textContent =
    `2025년 입출차 기록 ${M.meta.n_records_analyzed.toLocaleString()}건에서 평일 공연일 ${M.meta.n_cases}건의 출차 러시를 찾아 모델을 만들었습니다. 평일을 고르면 그날 실제 출차와 평소 선, 모델 곡선을 겹쳐 보고, 주말을 고르면 실제 출차와 주말 공연일 중앙값을 겹쳐 봅니다.`;
  loadLive();
  setInterval(loadLive, 60000);

  // 공유용 링크: ?date=2026-12-17&start=19:30&dur=150&venue=0&aud=15000&replay=2025-07-11
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
