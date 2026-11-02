"use strict";

// ---------- storage: per-browser, never required ----------
const local = {
  get(key, fallback) {
    try { const v = localStorage.getItem("tt:" + key); return v ? JSON.parse(v) : fallback; }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("tt:" + key, JSON.stringify(value)); } catch { /* private mode */ }
  },
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PAGE = 48;
const FIRST_YEAR = 2007;

const state = {
  data: null,
  byId: new Map(),
  facetName: new Map(),
  mode: local.get("mode", "taste"),
  chip: "all",
  sort: "top",
  q: "",
  liked: new Set(local.get("liked", [])),
  hidden: new Set(local.get("hidden", [])),
  watched: new Set(local.get("watched", [])),
  list: [],
  shown: 0,
  open: null,
  lastYear: new Date().getFullYear(),
};

function save() {
  local.set("liked", [...state.liked]);
  local.set("hidden", [...state.hidden]);
  local.set("watched", [...state.watched]);
  local.set("mode", state.mode);
}

// ---------- formatting ----------
function duration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

function thumb(id) {
  // hq2.jpg is YouTube's auto-generated frame from the middle of the video.
  return `https://i.ytimg.com/vi/${encodeURIComponent(id)}/hq2.jpg`;
}

function strip(v, big) {
  const years = new Set(v.yr || []);
  const n = state.lastYear - FIRST_YEAR + 1;
  const w = big ? 9 : 5, gap = big ? 3 : 2, h = big ? 18 : 12;
  let bars = "";
  for (let i = 0; i < n; i++) {
    const y = FIRST_YEAR + i;
    bars += `<rect x="${i * (w + gap)}" y="0" width="${w}" height="${h}" rx="1"${years.has(y) ? ' class="on"' : ""}><title>${y}</title></rect>`;
  }
  const months = v.mo === 1 ? "1 month" : `${v.mo} months`;
  const span = v.yr && v.yr.length ? `, ${v.yr[0]}–${v.yr[v.yr.length - 1]}` : "";
  const label = big
    ? `Recommended on Hacker News in ${months} by ${v.n} ${v.n === 1 ? "person" : "people"}${span}`
    : `HN, ${months}`;
  return `<div class="strip"><svg viewBox="0 0 ${n * (w + gap) - gap} ${h}" width="${n * (w + gap) - gap}" aria-hidden="true">${bars}</svg><span>${esc(label)}</span></div>`;
}

function fitDots(f) {
  if (!f) return "";
  return `<span class="fit" role="img" aria-label="Fit ${f} of 3">${[1, 2, 3].map((i) => `<i class="${i <= f ? "on" : ""}"></i>`).join("")}</span>`;
}

// ---------- ranking ----------
function affinity() {
  const fa = {}, ch = {}, ca = {};
  let n = 0;
  for (const id of state.liked) {
    const v = state.byId.get(id);
    if (!v) continue;
    n++;
    for (const f of v.fa) fa[f] = (fa[f] || 0) + 1;
    ch[v.ch] = (ch[v.ch] || 0) + 1;
    ca[v.c] = (ca[v.c] || 0) + 1;
  }
  return { fa, ch, ca, n };
}

function base(v) {
  return state.mode === "taste" ? v.ts : Math.log2(1 + v.s);
}

function compute() {
  const { data } = state;
  let vs = data.videos.filter((v) => !state.hidden.has(v.id));
  if (state.mode === "taste") vs = vs.filter((v) => v.f > 0);
  const chip = state.chip;
  if (chip.startsWith("facet:")) vs = vs.filter((v) => v.fa.includes(chip.slice(6)));
  if (chip.startsWith("cat:")) vs = vs.filter((v) => v.c === chip.slice(4));
  if (state.q) {
    const words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    vs = vs.filter((v) => words.every((w) => v._hay.includes(w)));
  }
  if (chip === "foryou") {
    const a = affinity();
    if (a.n) {
      vs = vs.filter((v) => !state.liked.has(v.id) && !state.watched.has(v.id));
      const score = (v) => {
        const facet = v.fa.reduce((s, f) => s + (a.fa[f] || 0), 0) / a.n;
        return base(v) * (1 + facet + 0.8 * (a.ch[v.ch] || 0) / a.n + 0.4 * (a.ca[v.c] || 0) / a.n);
      };
      vs = vs.map((v) => [score(v), v]).sort((x, y) => y[0] - x[0]).map((p) => p[1]);
      return vs;
    }
  }
  const sorters = {
    top: (x, y) => base(y) - base(x) || y.s - x.s,
    hn: (x, y) => y.s - x.s || base(y) - base(x),
    new: (x, y) => (y.y || 0) - (x.y || 0) || base(y) - base(x),
  };
  return vs.sort(sorters[state.sort]);
}

// ---------- rendering ----------
function card(v, i) {
  const by = [v.ch, v.y].filter(Boolean).join(", ");
  const why = state.mode === "taste" || v.f ? v.w : "";
  const watched = state.watched.has(v.id);
  return `<article class="card${watched ? " watched" : ""}" tabindex="0" data-i="${i}" aria-label="${esc(v.t)}">
    <div class="thumb">
      <img loading="lazy" src="${thumb(v.id)}" alt="" onerror="this.onerror=null;this.src='https://i.ytimg.com/vi/${esc(v.id)}/hqdefault.jpg'">
      ${v.d ? `<span class="dur">${duration(v.d)}</span>` : ""}
      ${watched ? `<span class="seen">Watched</span>` : ""}
    </div>
    <h3>${state.liked.has(v.id) ? '<span class="liked-mark" aria-label="Liked">♥ </span>' : ""}${esc(v.t)}</h3>
    <p class="by">${esc(by)}</p>
    ${why ? `<p class="why">${fitDots(v.f)}<span>${esc(why)}</span></p>` : ""}
    ${strip(v, false)}
  </article>`;
}

function renderMore() {
  const next = state.list.slice(state.shown, state.shown + PAGE);
  if (!next.length) return;
  $("#grid").insertAdjacentHTML("beforeend", next.map((v, k) => card(v, state.shown + k)).join(""));
  state.shown += next.length;
}

function renderChips() {
  const chips = [];
  const facets = state.data.meta.facets || [];
  if (state.mode === "taste") {
    chips.push(["foryou", "For you", "you"], ["all", "Everything for us"]);
    for (const f of facets) chips.push(["facet:" + f.id, f.name]);
  } else {
    chips.push(["foryou", "For you", "you"], ["all", "Everything"]);
    const counts = {};
    for (const v of state.data.videos) counts[v.c] = (counts[v.c] || 0) + 1;
    Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([c]) => chips.push(["cat:" + c, c]));
  }
  $("#chips").innerHTML = chips
    .map(([id, name, cls]) => `<button type="button" class="chip ${cls || ""}" data-chip="${esc(id)}" aria-pressed="${state.chip === id}">${esc(name)}</button>`)
    .join("");
}

function headline() {
  const c = state.data.meta.counts;
  const all = c.videos.toLocaleString("en-IN");
  if (state.mode === "taste") {
    return `<span class="n-hn">${all}</span> videos Hacker News kept recommending. <span class="n-us">${c.ours.toLocaleString("en-IN")}</span> fit our taste.`;
  }
  return `<span class="n-hn">${all}</span> videos Hacker News kept recommending, ${FIRST_YEAR} to ${state.lastYear}.`;
}

function render() {
  state.list = compute();
  state.shown = 0;
  $("#grid").innerHTML = "";
  $("#headline").innerHTML = headline();
  document.querySelectorAll(".mode button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode)));
  document.querySelectorAll("#sort button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sort === state.sort)));
  $("#sort").hidden = state.chip === "foryou" && state.liked.size > 0;
  renderChips();
  const n = state.list.length;
  $("#count").textContent = `${n.toLocaleString("en-IN")} ${n === 1 ? "video" : "videos"}`;
  const empty = $("#empty");
  empty.hidden = n > 0;
  if (!n) {
    if (state.chip === "foryou") empty.textContent = "Like a few videos (open one and press Like, or select it and press L). For you then ranks the rest by what you liked.";
    else if (state.q) empty.textContent = `No videos match “${state.q}”. Clear the search or switch to All of HN.`;
    else empty.textContent = "No videos here yet. Switch to All of HN, or reset hidden videos below.";
  }
  if (state.chip === "foryou" && !state.liked.size && n) {
    empty.hidden = false;
    empty.textContent = "Like a few videos and For you will learn from them. Until then it shows the best picks.";
  }
  renderMore();
}

// ---------- player ----------
function openVideo(v) {
  state.open = v;
  state.watched.add(v.id);
  save();
  const frame = $("#p-frame");
  frame.innerHTML = v.e
    ? `<iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(v.id)}?autoplay=1&rel=0" title="${esc(v.t)}" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`
    : `<div class="noembed"><img src="${thumb(v.id)}" alt=""><p>The owner turned off playback on other sites. <a href="https://www.youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noopener">Watch it on YouTube</a>.</p></div>`;
  $("#p-title").textContent = v.t;
  $("#p-by").textContent = [v.ch, v.y, duration(v.d)].filter(Boolean).join(", ");
  $("#p-why").textContent = v.w || "";
  $("#p-why").hidden = !v.w;
  $("#p-sum").textContent = v.su || "";
  const tags = v.fa.map((f) => state.facetName.get(f) || f);
  if (state.mode === "all" || !tags.length) tags.push(v.c);
  $("#p-tags").innerHTML = tags.map((t) => `<span>${esc(t)}</span>`).join("");
  $("#p-like").setAttribute("aria-pressed", String(state.liked.has(v.id)));
  $("#p-like").textContent = state.liked.has(v.id) ? "Liked" : "Like";
  $("#p-yt").href = `https://www.youtube.com/watch?v=${encodeURIComponent(v.id)}`;
  $("#p-strip").innerHTML = strip(v, true);
  $("#p-quotes").innerHTML = (v.m || []).map((m) => `<li>${esc(m.x)}<span class="who">${esc(m.a)}, ${esc(m.y)}${m.st ? `, in “${esc(m.st)}”` : ""}. <a href="https://news.ycombinator.com/item?id=${encodeURIComponent(m.c)}" target="_blank" rel="noopener">Read on HN</a></span></li>`).join("");
  $("#player").showModal();
}

function toggleLike(v) {
  if (state.liked.has(v.id)) state.liked.delete(v.id); else state.liked.add(v.id);
  save();
  if (state.open === v) openVideoLikeButton(v);
}

function openVideoLikeButton(v) {
  const on = state.liked.has(v.id);
  $("#p-like").setAttribute("aria-pressed", String(on));
  $("#p-like").textContent = on ? "Liked" : "Like";
}

function refreshKeepingFocus(index) {
  render();
  while (state.shown <= index && state.shown < state.list.length) renderMore();
  const el = document.querySelector(`.card[data-i="${Math.min(index, state.list.length - 1)}"]`);
  if (el) el.focus({ preventScroll: false });
}

// ---------- events ----------
function selectedIndex() {
  const el = document.activeElement;
  return el && el.classList.contains("card") ? Number(el.dataset.i) : -1;
}

function move(delta) {
  const i = Math.max(0, Math.min(state.list.length - 1, selectedIndex() + delta));
  while (state.shown <= i && state.shown < state.list.length) renderMore();
  const el = document.querySelector(`.card[data-i="${i}"]`);
  if (el) { el.focus({ preventScroll: true }); el.scrollIntoView({ block: "nearest" }); }
}

function wire() {
  $("#grid").addEventListener("click", (e) => {
    const el = e.target.closest(".card");
    if (el) openVideo(state.list[Number(el.dataset.i)]);
  });
  $("#chips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    state.chip = b.dataset.chip;
    render();
  });
  document.querySelectorAll(".mode button").forEach((b) => b.addEventListener("click", () => {
    if (b.disabled) return;
    state.mode = b.dataset.mode;
    state.chip = "all";
    save();
    render();
  }));
  document.querySelectorAll("#sort button").forEach((b) => b.addEventListener("click", () => {
    state.sort = b.dataset.sort;
    render();
  }));
  let t;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 120);
  });
  $("#player").addEventListener("close", () => {
    $("#p-frame").innerHTML = "";
    const v = state.open;
    state.open = null;
    const i = state.list.indexOf(v);
    refreshKeepingFocus(i < 0 ? 0 : i);
  });
  $("#p-like").addEventListener("click", () => state.open && toggleLike(state.open));
  $("#p-hide").addEventListener("click", () => {
    if (!state.open) return;
    state.hidden.add(state.open.id);
    save();
    $("#player").close();
  });
  $("#help-open").addEventListener("click", () => $("#help").showModal());
  $("#reset").addEventListener("click", () => {
    state.liked.clear(); state.hidden.clear(); state.watched.clear();
    save();
    render();
  });
  new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) renderMore();
  }, { rootMargin: "800px" }).observe($("#more"));

  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const typing = e.target.matches("input, textarea");
    if (typing) { if (e.key === "Escape") e.target.blur(); return; }
    if ($("#help").open) return;
    const inPlayer = $("#player").open;
    const v = inPlayer ? state.open : state.list[selectedIndex()];
    switch (e.key) {
      case "/": e.preventDefault(); $("#q").focus(); break;
      case "j": if (!inPlayer) move(1); break;
      case "k": if (!inPlayer) move(-1); break;
      case "Enter": if (!inPlayer && v) { e.preventDefault(); openVideo(v); } break;
      case "l": if (v) { toggleLike(v); if (!inPlayer) refreshKeepingFocus(selectedIndex()); } break;
      case "x": if (v) {
        state.hidden.add(v.id); save();
        if (inPlayer) $("#player").close(); else refreshKeepingFocus(selectedIndex());
      } break;
      case "w": if (v && !inPlayer) {
        if (state.watched.has(v.id)) state.watched.delete(v.id); else state.watched.add(v.id);
        save(); refreshKeepingFocus(selectedIndex());
      } break;
      case "f": if (!inPlayer) { state.chip = "foryou"; render(); } break;
      case "t": if (!inPlayer && !document.querySelector('.mode button[data-mode="taste"]').disabled) {
        state.mode = state.mode === "taste" ? "all" : "taste"; state.chip = "all"; save(); render();
      } break;
      case "?": $("#help").showModal(); break;
    }
  });
}

// ---------- boot ----------
async function load() {
  for (const url of ["data/videos.json", "data/demo.json"]) {
    try {
      const r = await fetch(url, { cache: "no-cache" });
      if (r.ok) return await r.json();
    } catch { /* try the next file */ }
  }
  throw new Error("No data file found. Run `tastetube build` to create site/data/videos.json.");
}

async function main() {
  wire();
  try {
    state.data = await load();
  } catch (err) {
    $("#headline").textContent = err.message;
    return;
  }
  const { data } = state;
  for (const f of data.meta.facets || []) state.facetName.set(f.id, f.name);
  for (const v of data.videos) {
    v.fa = v.fa || [];
    state.byId.set(v.id, v);
    v._hay = [v.t, v.ch, v.su, v.w, v.c, ...v.fa.map((f) => state.facetName.get(f) || f), ...(v.m || []).map((m) => m.st)]
      .filter(Boolean).join(" ").toLowerCase();
    for (const y of v.yr || []) state.lastYear = Math.max(state.lastYear, y);
  }
  if (!data.meta.counts.ours) {
    state.mode = "all";
    const b = document.querySelector('.mode button[data-mode="taste"]');
    b.disabled = true;
    b.title = "Run `tastetube judge` to rank videos for our taste.";
  }
  if (data.meta.demo) {
    const banner = $("#banner");
    banner.hidden = false;
    banner.textContent = "Demo data. The titles are real videos, but the scores and quotes are made up. Run the pipeline to fill this page with real picks.";
  }
  render();
}

main();
