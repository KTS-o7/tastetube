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
const MODE_LABEL = { easy: "Easy watch", focused: "Focused watch", study: "Study session" };

const state = {
  data: null,
  byId: new Map(),
  facetName: new Map(),
  mode: local.get("mode", "taste"),
  chip: "all",
  sort: "top",
  len: "any",
  q: "",
  liked: new Set(local.get("liked", [])),
  hidden: new Set(local.get("hidden", [])),
  watched: new Set(local.get("watched", [])),
  done: new Set(local.get("done", [])), // lectures finished inside courses
  list: [],
  shown: 0,
  open: null,
  playing: null,
  lastYear: new Date().getFullYear(),
};

function save() {
  local.set("liked", [...state.liked]);
  local.set("hidden", [...state.hidden]);
  local.set("watched", [...state.watched]);
  local.set("done", [...state.done]);
  local.set("mode", state.mode);
}

// ---------- formatting ----------
function clock(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

function hours(sec) {
  const h = sec / 3600;
  return h >= 10 ? `${Math.round(h)} hours` : `${h.toFixed(1).replace(/\.0$/, "")} hours`;
}

function length(v) {
  if (v.cr) return v.d ? `${v.it} lectures, ${hours(v.d)}` : `${v.it} lectures`;
  return v.d ? clock(v.d) : "";
}

function thumb(id) {
  // hq2.jpg is YouTube's auto-generated frame from the middle of the video.
  return `https://i.ytimg.com/vi/${encodeURIComponent(id)}/hq2.jpg`;
}

function progress(v) {
  if (!v.cr) return 0;
  return v.ls.filter((l) => state.done.has(l.id)).length;
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

const LENGTH = {
  any: () => true,
  h1: (v) => !v.cr && v.d < 3600,
  h2: (v) => !v.cr && v.d >= 3600 && v.d <= 7200,
  long: (v) => !v.cr && v.d > 7200,
  course: (v) => v.cr,
};

function compute() {
  let vs = state.data.videos.filter((v) => !state.hidden.has(v.id) && LENGTH[state.len](v));
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
      return vs.map((v) => [score(v), v]).sort((x, y) => y[0] - x[0]).map((p) => p[1]);
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
  const watched = state.watched.has(v.id);
  const done = progress(v);
  const badge = v.cr && done ? `<span class="seen">${done} of ${v.it} done</span>` : watched ? `<span class="seen">Watched</span>` : "";
  return `<article class="card${watched && !v.cr ? " watched" : ""}" tabindex="0" data-i="${i}" aria-label="${esc(v.t)}">
    <div class="thumb${v.cr ? " stack" : ""}">
      <img loading="lazy" src="${thumb(v.th)}" alt="" onerror="this.onerror=null;this.src='https://i.ytimg.com/vi/${esc(v.th)}/hqdefault.jpg'">
      ${length(v) ? `<span class="dur">${esc(length(v))}</span>` : ""}
      ${badge}
    </div>
    <h3>${state.liked.has(v.id) ? '<span class="liked-mark" aria-label="Liked">♥ </span>' : ""}${esc(v.t)}</h3>
    <p class="by">${esc(by)}${v.md ? ` <span class="md md-${esc(v.md)}">${MODE_LABEL[v.md] || ""}</span>` : ""}</p>
    ${v.w && v.f ? `<p class="why">${fitDots(v.f)}<span>${esc(v.w)}</span></p>` : ""}
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
  if (state.mode === "taste") {
    chips.push(["foryou", "For you", "you"], ["all", "Everything for us"]);
    for (const f of state.data.meta.facets || []) chips.push(["facet:" + f.id, f.name]);
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
  const fmt = (n) => Number(n || 0).toLocaleString("en-IN");
  return state.mode === "taste"
    ? `<span class="n-us">${fmt(c.ours)}</span> courses we built from <span class="n-hn">${fmt(c.videos)}</span> long-form talks and lectures Hacker News kept recommending.`
    : `<span class="n-hn">${fmt(c.videos)}</span> long-form talks, lectures and documentaries Hacker News kept recommending, ${FIRST_YEAR} to ${state.lastYear}.`;
}

function pressed(selector, attr, value) {
  document.querySelectorAll(selector).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset[attr] === value)));
}

function render() {
  state.list = compute();
  state.shown = 0;
  $("#grid").innerHTML = "";
  $("#headline").innerHTML = headline();
  pressed(".mode button", "mode", state.mode);
  pressed("#sort button", "sort", state.sort);
  pressed("#len button", "len", state.len);
  $("#sort").hidden = state.chip === "foryou" && state.liked.size > 0;
  renderChips();
  const n = state.list.length;
  $("#count").textContent = `${n.toLocaleString("en-IN")} ${n === 1 ? "item" : "items"}`;
  const empty = $("#empty");
  empty.hidden = n > 0;
  if (!n) {
    if (state.chip === "foryou") empty.textContent = "Like a few videos (open one and press Like, or select it and press L). For you then ranks the rest by what you liked.";
    else if (state.q) empty.textContent = `Nothing matches “${state.q}”. Clear the search, pick Any length, or switch to All of HN.`;
    else empty.textContent = "Nothing here yet. Pick Any length, switch to All of HN, or reset hidden videos below.";
  }
  if (state.chip === "foryou" && !state.liked.size && n) {
    empty.hidden = false;
    empty.textContent = "Like a few videos and For you will learn from them. Until then it shows the best picks.";
  }
  renderMore();
}

// ---------- player ----------
function embed(id, start) {
  const params = new URLSearchParams({ autoplay: "1", rel: "0" });
  if (start) params.set("start", String(start));
  return `<iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?${params}" title="Video player" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`;
}

function play(id, start = 0) {
  const v = state.open;
  state.playing = id;
  $("#p-yt").href = `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;
  $("#p-frame").innerHTML = v.e || v.cr
    ? embed(id, start)
    : `<div class="noembed"><img src="${thumb(id)}" alt=""><p>The owner turned off playback on other sites. <a href="https://www.youtube.com/watch?v=${esc(id)}&amp;t=${start}" target="_blank" rel="noopener">Watch it on YouTube</a>.</p></div>`;
  if (v.cr) renderCourse(v);
}

function nextLecture(v) {
  return v.ls.find((l) => !state.done.has(l.id)) || v.ls[0];
}

function renderCourse(v) {
  const done = progress(v);
  $("#p-progress").textContent = done ? `${done} of ${v.it} lectures done` : length(v);
  const next = nextLecture(v);
  const pos = v.ls.indexOf(next) + 1;
  $("#p-continue").textContent = done ? `Continue with lecture ${pos}` : "Start lecture 1";
  $("#p-continue").hidden = state.playing === next.id || done === v.ls.length;
  $("#p-lectures").innerHTML = v.ls.map((l, i) => `<li class="${state.done.has(l.id) ? "done" : ""}${state.playing === l.id ? " now" : ""}">
      <input type="checkbox" id="lec-${i}" data-done="${esc(l.id)}" ${state.done.has(l.id) ? "checked" : ""} aria-label="Mark lecture ${i + 1} done">
      <button type="button" data-play="${esc(l.id)}">${esc(l.t)}</button>
      <span>${l.d ? clock(l.d) : esc(l.ch || "")}</span>
    </li>`).join("");
}

function openVideo(v) {
  state.open = v;
  if (!v.cr) { state.watched.add(v.id); save(); }
  $("#p-title").textContent = v.t;
  $("#p-by").textContent = [v.ch, v.y, length(v)].filter(Boolean).join(", ");
  $("#p-why").textContent = v.w || "";
  $("#p-why").hidden = !v.w;
  $("#p-sum").textContent = v.su || "";
  const rows = [];
  if (v.tk) rows.push(["You come away with", v.tk]);
  if (v.pr) rows.push(["Know first", v.pr]);
  if (v.md) rows.push(["How to watch", MODE_LABEL[v.md] || v.md]);
  $("#p-card").innerHTML = rows.map(([k, val]) => `<dt>${esc(k)}</dt><dd>${esc(val)}</dd>`).join("");
  const tags = v.fa.map((f) => state.facetName.get(f) || f);
  if (state.mode === "all" || !tags.length) tags.push(v.c);
  $("#p-tags").innerHTML = tags.map((t) => `<span>${esc(t)}</span>`).join("");
  likeButton(v);
  $("#p-course").hidden = !v.cr;
  $("#p-chapters").hidden = !(v.cp && v.cp.length);
  $("#p-chapter-list").innerHTML = (v.cp || []).map(([sec, t]) => `<li><button type="button" data-seek="${sec}"><span>${clock(sec)}</span> ${esc(t)}</button></li>`).join("");
  $("#p-strip").innerHTML = strip(v, true);
  $("#p-quotes").innerHTML = (v.m || []).map((m) => `<li>${esc(m.x)}<span class="who">${esc(m.a)}, ${esc(m.y)}${m.st ? `, in “${esc(m.st)}”` : ""}. <a href="https://news.ycombinator.com/item?id=${encodeURIComponent(m.c)}" target="_blank" rel="noopener">Read on HN</a></span></li>`).join("");
  play(v.cr ? nextLecture(v).id : v.id);
  $("#player").showModal();
}

function likeButton(v) {
  const on = state.liked.has(v.id);
  $("#p-like").setAttribute("aria-pressed", String(on));
  $("#p-like").textContent = on ? "Liked" : "Like";
}

function toggleLike(v) {
  if (state.liked.has(v.id)) state.liked.delete(v.id); else state.liked.add(v.id);
  save();
  if (state.open === v) likeButton(v);
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

function group(selector, key, after) {
  document.querySelectorAll(selector).forEach((b) => b.addEventListener("click", () => {
    if (b.disabled) return;
    state[key] = b.dataset[key];
    if (after) after();
    render();
  }));
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
  group(".mode button", "mode", () => { state.chip = "all"; save(); });
  group("#sort button", "sort");
  group("#len button", "len");
  let t;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 120);
  });
  $("#player").addEventListener("close", () => {
    $("#p-frame").innerHTML = "";
    const v = state.open;
    state.open = null;
    state.playing = null;
    const i = state.list.indexOf(v);
    refreshKeepingFocus(i < 0 ? 0 : i);
  });
  $("#player").addEventListener("click", (e) => {
    const v = state.open;
    if (!v) return;
    const seek = e.target.closest("[data-seek]");
    if (seek) play(v.id, Number(seek.dataset.seek));
    const lec = e.target.closest("[data-play]");
    if (lec) play(lec.dataset.play);
  });
  $("#player").addEventListener("change", (e) => {
    const box = e.target.closest("[data-done]");
    if (!box || !state.open) return;
    if (box.checked) state.done.add(box.dataset.done); else state.done.delete(box.dataset.done);
    save();
    renderCourse(state.open);
  });
  $("#p-continue").addEventListener("click", () => state.open && play(nextLecture(state.open).id));
  $("#p-like").addEventListener("click", () => state.open && toggleLike(state.open));
  $("#p-hide").addEventListener("click", () => {
    if (!state.open) return;
    state.hidden.add(state.open.id);
    save();
    $("#player").close();
  });
  $("#help-open").addEventListener("click", () => $("#help").showModal());
  $("#reset").addEventListener("click", () => {
    state.liked.clear(); state.hidden.clear(); state.watched.clear(); state.done.clear();
    save();
    render();
  });
  new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) renderMore();
  }, { rootMargin: "800px" }).observe($("#more"));

  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const typing = e.target.matches("input[type=search], textarea");
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
      case "n": if (inPlayer && v && v.cr && state.playing) {
        state.done.add(state.playing); save(); play(nextLecture(v).id);
      } break;
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
  const r = await fetch("data/videos.json", { cache: "no-cache" });
  if (!r.ok) throw new Error("No data file found. Run `tastetube hackertube --data DIR` to create site/data/videos.json.");
  return r.json();
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
    v.ls = v.ls || [];
    v.th = v.th || v.id;
    v.it = v.it || v.ls.length;
    state.byId.set(v.id, v);
    v._hay = [v.t, v.ch, v.su, v.w, v.tk, v.c, ...v.fa.map((f) => state.facetName.get(f) || f),
      ...(v.m || []).map((m) => m.st), ...v.ls.map((l) => l.t), ...(v.cp || []).map((c) => c[1])]
      .filter(Boolean).join(" ").toLowerCase();
    for (const y of v.yr || []) state.lastYear = Math.max(state.lastYear, y);
  }
  if (!data.meta.counts.ours) {
    state.mode = "all";
    const b = document.querySelector('.mode button[data-mode="taste"]');
    b.disabled = true;
    b.title = "Add courses to courses.yaml to fill Our taste.";
  }
  if (data.meta.durations === false) {
    document.querySelectorAll("#len button").forEach((b) => {
      if (b.dataset.len === "any" || b.dataset.len === "course") return;
      b.disabled = true;
      b.title = "Video lengths are not loaded yet.";
    });
    if (state.len !== "course") state.len = "any";
  }
  const banner = $("#banner");
  banner.hidden = false;
  banner.innerHTML = 'Videos, summaries and Hacker News quotes come from <a href="https://hackertube.org/data">HackerTube’s open data</a> (ODC-By 1.0). The courses are our own picks and order.';
  render();
}

main();
