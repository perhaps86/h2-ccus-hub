/* 수소·암모니아·CCUS 인텔리전스 — 렌더링과 필터.
 *
 * 데이터는 data/news.json 과 data/insights.json 에서 읽는다.
 * needs_review 로 표시된 항목은 화면에 띄우지 않는다. 자동 분류가
 * 검증을 통과하지 못한 건을 그대로 공개하지 않기 위한 장치다.
 */

const AXES = [
  { key: "category", el: "filter-category", values: ["정책·규제", "프로젝트·계약", "투자·금융", "기술", "시장·가격"] },
  { key: "region", el: "filter-region", values: ["국내", "해외"] },
  { key: "chain", el: "filter-chain", values: ["수소생산", "암모니아", "CCUS", "운송·저장", "활용"] },
  { key: "importance", el: "filter-importance", values: ["상", "중"] },
];

const state = { category: null, region: null, chain: null, importance: null, q: "" };
let items = [];

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function formatDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

function buildFilters() {
  for (const axis of AXES) {
    const host = $(axis.el);
    host.innerHTML = "";
    const all = chip("전체", true, () => setAxis(axis.key, null));
    all.dataset.value = "";
    host.appendChild(all);
    for (const value of axis.values) {
      const button = chip(value, false, () => setAxis(axis.key, value));
      button.dataset.value = value;
      host.appendChild(button);
    }
  }
}

function chip(label, pressed, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "chip";
  button.textContent = label;
  button.setAttribute("aria-pressed", String(pressed));
  button.addEventListener("click", onClick);
  return button;
}

function setAxis(key, value) {
  state[key] = state[key] === value ? null : value;
  syncChips();
  render();
}

function syncChips() {
  for (const axis of AXES) {
    const selected = state[axis.key];
    for (const button of $(axis.el).querySelectorAll(".chip")) {
      const value = button.dataset.value || null;
      button.setAttribute("aria-pressed", String(value === selected));
    }
  }
}

function matches(item) {
  if (item.needs_review) return false;
  if (state.category && item.category !== state.category) return false;
  if (state.region && item.region !== state.region) return false;
  if (state.chain && !(item.chain || []).includes(state.chain)) return false;
  if (state.importance && item.importance !== state.importance) return false;
  if (state.q) {
    const haystack = [item.title, item.summary, item.source, ...(item.tags || [])]
      .join(" ").toLowerCase();
    if (!haystack.includes(state.q)) return false;
  }
  return true;
}

function render() {
  const visible = items.filter(matches);
  const list = $("news");
  list.innerHTML = visible.map(renderItem).join("");
  $("empty").hidden = visible.length > 0;
  $("count").textContent = visible.length
    ? `${visible.length}건 표시 중`
    : "";
}

function renderItem(item) {
  const chainBadges = (item.chain || [])
    .map((c) => `<span class="badge chain">${escapeHtml(c)}</span>`).join("");
  const importance = item.importance === "상"
    ? '<span class="badge high">중요</span>' : "";
  const tags = (item.tags || []).length
    ? ` · ${(item.tags || []).map(escapeHtml).join(", ")}` : "";

  return `
    <li class="item">
      <div class="item-head">
        <div class="badges">
          ${importance}
          <span class="badge">${escapeHtml(item.category)}</span>
          <span class="badge">${escapeHtml(item.region)}</span>
          ${chainBadges}
        </div>
        <h3><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a></h3>
      </div>
      <p class="summary">${escapeHtml(item.summary)}</p>
      <p class="src">${formatDate(item.published_at)} · ${escapeHtml(item.source)}${escapeHtml(tags)}</p>
    </li>`;
}

function renderInsight(insights) {
  const latest = (insights.items || [])[0];
  if (!latest) return;
  const body = (latest.body || "")
    .split(/\n{2,}/)
    .map((p) => `<p>${escapeHtml(p)}</p>`)
    .join("");
  $("insight").innerHTML = `
    <h3>${escapeHtml(latest.title)}</h3>
    ${body}
    <p class="insight-date">${escapeHtml(latest.date)}</p>`;
  $("insight-section").hidden = false;
}

async function loadJson(path) {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

async function init() {
  buildFilters();

  $("search").addEventListener("input", (event) => {
    state.q = event.target.value.trim().toLowerCase();
    render();
  });

  $("reset").addEventListener("click", () => {
    for (const axis of AXES) state[axis.key] = null;
    state.q = "";
    $("search").value = "";
    syncChips();
    render();
  });

  try {
    const news = await loadJson("data/news.json");
    items = news.items || [];
    const shown = items.filter((item) => !item.needs_review).length;
    $("meta").textContent =
      `${shown}건 수록 · 최근 갱신 ${formatDate(news.generated_at)} · 하루 1회 자동 수집`;
    render();
  } catch (error) {
    $("meta").textContent = "데이터를 불러오지 못했습니다.";
    console.error(error);
  }

  try {
    renderInsight(await loadJson("data/insights.json"));
  } catch (error) {
    // 코멘트는 없을 수 있다. 섹션을 숨긴 채 둔다.
  }
}

init();
