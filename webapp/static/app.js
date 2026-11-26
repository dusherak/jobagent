/* Job Agent front end — vanilla JS, no build step. */
"use strict";

/* ================= utilities ================= */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (url, body) => {
  const r = await fetch(url, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `Request failed (${r.status})`);
  return d;
};
const today0 = () => new Date(new Date().toDateString());
const days = iso => iso ? Math.round((today0() - new Date(iso.slice(0, 10))) / 864e5) : null;
const ago = iso => { const d = days(iso); return d === null ? "" : d <= 0 ? "today" : d === 1 ? "yesterday" : d < 30 ? `${d}d ago` : `${Math.round(d / 30)}mo ago`; };
const until = iso => { const d = -days(iso); return d < 0 ? "passed" : d === 0 ? "today" : d === 1 ? "tomorrow" : `in ${d}d`; };
const fmt = iso => iso ? new Date(iso.slice(0, 10)).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "";
const hue = s => { let h = 0; for (const c of s || "") h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
const initials = s => (s || "?").replace(/\(.*?\)/g, "").replace(/&/g, " ").split(/\s+/).filter(w => /^[A-Za-z0-9]/.test(w)).slice(0, 2).map(w => w[0]).join("").toUpperCase() || "?";
const av = (name, cls = "") => `<span class="av ${cls}" style="--h:${hue(name)}">${esc(initials(name))}</span>`;
const icon = (n, cls = "") => `<svg class="${cls}"><use href="#i-${n}"/></svg>`;
const STAGES = ["Saved", "Applied", "Assessment", "Interview", "Offer", "Rejected"];
const SC = s => `var(--s-${(s || "saved").toLowerCase()})`;
const stagePill = s => `<span class="pill" style="--c:${SC(s)}"><i></i>${esc(s)}</span>`;
const words = s => (s.match(/\S+/g) || []).length;
const matches = (hay, q) => { const h = hay.toLowerCase(); return q.toLowerCase().split(/\s+/).filter(Boolean).every(w => h.includes(w)); };
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

function toast(msg, action) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<span>${esc(msg)}</span>${action ? `<button>${esc(action.label)}</button>` : ""}`;
  if (action) el.querySelector("button").onclick = () => { action.fn(); el.remove(); };
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), action ? 6000 : 3200);
}

/* ================= state ================= */
const S = {
  me: { name: "", city: "London", file_prefix: "My" },   // from /api/settings (user folder settings.json)
  jobs: { jobs: [] }, apps: [], gmail: { updates: [], new: [], actions: [] }, tasks: {},
  tab: "home", jf: "All", jsort: "rec", jq: "", af: "Active", aq: "",
  closed: new Set(["Rejected"]), openJobs: new Set(), drawerId: null, studioId: null, studioView: "cv", studioData: null,
};
const store = { get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
                set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
Object.assign(S, store.get("ui", {}));
S.closed = new Set(store.get("closed", ["Rejected"]));
const saveUI = () => store.set("ui", { jf: S.jf, jsort: S.jsort, af: S.af });
const appById = id => S.apps.find(a => a.id === id);
const lastAt = a => (a.history?.length ? a.history[a.history.length - 1].at : a.applied) || "";

/* ================= loading ================= */
async function loadJobs() { S.jobs = await api("/api/jobs"); renderJobs(); renderHome(); }
async function loadApps() { const d = await api("/api/applications"); S.apps = d.applications; S.generalFiles = d.general_files || []; renderApps(); renderHome(); renderDocs(); if (S.drawerId) renderDrawer(); }
async function loadGmail() { S.gmail = await api("/api/gmail"); renderReview(); renderHome(); badge(); }
function badge() {
  const n = (S.gmail.updates?.length || 0) + (S.gmail.new?.length || 0);
  $("appsBadge").hidden = !n; $("appsBadge").textContent = n;
}

/* ================= tabs + theme ================= */
function showTab(t) {
  if (!["home", "jobs", "apps", "docs", "live"].includes(t)) t = "home";
  S.tab = t;
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  document.querySelectorAll(".page").forEach(p => p.classList.toggle("on", p.id === "pg-" + t));
  if (location.hash !== "#" + t) history.replaceState(null, "", "#" + t);
  window.scrollTo(0, 0);
  if (t === "live") livePoll();
}
function applyTheme() {
  const t = store.get("themeChoice", "auto");
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  try { t === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", t); } catch {}
  $("themeBtn").innerHTML = icon(t === "dark" ? "moon" : t === "light" ? "sun" : "auto");
  $("themeBtn").title = `Theme: ${t} (click to change)`;
}

/* ================= HOME ================= */
function greeting() { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; }
function renderHome() {
  const jobs = S.jobs.jobs.filter(j => !j.dismissed);
  const fresh = jobs.filter(j => fitOK(j) && !j.undated && days(j.date) <= 3);
  const soon = jobs.filter(j => fitOK(j) && j.deadline && -days(j.deadline) >= 0 && -days(j.deadline) <= 7);
  const active = S.apps.filter(a => !["Rejected", "Offer"].includes(a.stage));
  const todos = [];
  (S.gmail.actions || []).forEach(x => todos.push({ ic: "alert", c: x.deadline && -days(x.deadline) <= 3 ? "red" : "amber",
    t: `${x.company}: ${x.action}`, s: x.deadline ? `Due ${fmt(x.deadline)} · ${until(x.deadline)}` : "From Gmail", go: () => { showTab("apps"); } }));
  const nSugg = (S.gmail.updates?.length || 0) + (S.gmail.new?.length || 0);
  if (nSugg) todos.push({ ic: "mail", c: "blue", t: `Review ${nSugg} update${nSugg > 1 ? "s" : ""} found in Gmail`, s: `Checked ${ago(S.gmail.checked)}`, go: () => showTab("apps") });
  S.apps.filter(a => a.stage === "Saved" && a.deadline && -days(a.deadline) <= 7 && -days(a.deadline) >= 0)
    .forEach(a => todos.push({ ic: "clock", c: "red", t: `Apply to ${a.company}`, s: `${a.role || ""} · closes ${until(a.deadline)}`, go: () => openDrawer(a.id) }));
  S.apps.filter(a => a.stage === "Interview").forEach(a => todos.push({ ic: "check", c: "blue", t: `Prepare: ${a.company} interview`, s: a.status, go: () => openDrawer(a.id) }));
  S.apps.filter(a => a.stage === "Saved" && !a.deadline).slice(0, 3).forEach(a => todos.push({ ic: "bookmark", c: "", t: `Saved: ${a.company}`, s: a.role || "Decide and apply", go: () => openDrawer(a.id) }));

  const top = jobs.filter(j => fitOK(j) && j.fit !== "check" && !j.app_id && !j.undated && (j.dream || j.tier === "grad") && days(j.date) <= 7)
    .sort((a, b) => b.dream - a.dream || (b.date || "").localeCompare(a.date || "")).slice(0, 7);

  const counts = STAGES.map(s => [s, S.apps.filter(a => a.stage === s).length]).filter(([, n]) => n);
  const events = S.apps.flatMap(a => (a.history || []).map(h => ({ ...h, a }))).filter(h => h.at)
    .sort((x, y) => y.at.localeCompare(x.at)).slice(0, 7);
  const feed = S.tasks.feed || {};

  $("pg-home").innerHTML = `
    <div class="page-head"><div><h1>${greeting()}, ${esc(S.me.name)}</h1>
      <p class="sub">${new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })} · ${active.length} active applications</p></div></div>
    <div class="kpis">
      <div class="kpi" data-go="jobs:Last 3 days"><b>${fresh.length}</b><span>Roles posted in the last 3 days</span></div>
      <div class="kpi ${soon.length ? "hot" : ""}" data-go="jobs:deadline"><b>${soon.length}</b><span>Closing within 7 days</span></div>
      <div class="kpi" data-go="apps:Active"><b>${active.length}</b><span>Active applications</span></div>
      <div class="kpi" data-go="apps:Interview"><b>${S.apps.filter(a => a.stage === "Interview").length}</b><span>Interviews</span></div>
    </div>
    <div class="home-grid">
      <div>
        <div class="card"><div class="card-h"><h2>Needs your attention</h2><span class="muted small">${todos.length || ""}</span></div>
          ${todos.length ? todos.slice(0, 8).map((t, i) => `<div class="todo" data-todo="${i}"><span class="ic ${t.c}">${icon(t.ic)}</span>
            <div class="tx"><div>${esc(t.t)}</div><div>${esc(t.s || "")}</div></div></div>`).join("") :
            `<div class="empty" style="padding:28px"><b>All clear</b>Nothing urgent right now.</div>`}
        </div>
        <div class="card"><div class="card-h"><h2>Fresh roles worth a look</h2><button class="btn ghost sm" data-go="jobs:All">All jobs</button></div>
          ${top.length ? top.map(j => `<div class="mini">${av(j.company)}<div class="main"><div><b>${j.dream ? "★ " : ""}${esc(j.company)}</b> · ${esc(j.title)}</div>
            <div>${esc(j.summary || `Posted ${ago(j.date)}`)}${j.deadline ? ` · closes ${fmt(j.deadline)}` : ""}</div></div>
            <a class="btn ghost sm" href="${esc(j.url)}" target="_blank" rel="noopener" title="Open posting">${icon("ext")}</a>
            <button class="btn sm" data-save="${j.id}">${icon("bookmark")}Save</button></div>`).join("") :
            `<div class="empty" style="padding:28px">No new graduate or dream-firm roles this week.</div>`}
        </div>
      </div>
      <div>
        <div class="card"><div class="card-h"><h2>Pipeline</h2><span class="muted small">${S.apps.length} total</span></div>
          <div class="card-b"><div class="pipe">${counts.map(([s, n]) => `<span style="--c:${SC(s)};flex:${n}" title="${s}: ${n}" data-go="apps:${s}"></span>`).join("")}</div>
          <div class="legend">${counts.map(([s, n]) => `<span data-go="apps:${s}"><i class="dot" style="--c:${SC(s)}"></i>${s} <b>${n}</b></span>`).join("")}</div></div>
        </div>
        <div class="card"><div class="card-h"><h2>Job feed</h2></div>
          <div class="card-b t2 small">${feed.running ? `<span class="spin" style="display:inline-block;vertical-align:-2px"></span> ${esc(feed.progress || "Updating…")}` :
            S.jobs.updated ? `Last updated ${ago(S.jobs.updated)} at ${S.jobs.updated.slice(11, 16)} · ${S.jobs.jobs.length} roles in the last ${S.jobs.max_age_days} days` : "Not run yet."}
            <div style="margin-top:10px"><button class="btn sm" data-act="updateJobs" ${feed.running ? "disabled" : ""}>${icon("refresh")}Update now</button></div></div>
        </div>
        <div class="card"><div class="card-h"><h2>Recent activity</h2></div>
          ${events.map(e => `<div class="mini" data-open="${e.a.id}" style="cursor:pointer">${av(e.a.company)}<div class="main">
            <div><b>${esc(e.a.company)}</b> · ${esc(e.event || e.stage || "")}</div><div>${esc(e.status || "")} ${e.status ? "·" : ""} ${ago(e.at)}</div></div></div>`).join("") || `<div class="empty">No activity yet.</div>`}
        </div>
      </div>
    </div>`;
  renderHome.todos = todos;
}

/* ================= JOBS ================= */
const fitOK = j => j.fit !== "not_eligible" && j.want !== "no";   // eligible AND a role the user would want
const noSpon = j => (j.flags || []).some(f => f.key === "no_sponsorship");
const JF = {
  All: j => fitOK(j), "Last 3 days": j => fitOK(j) && !j.undated && days(j.date) <= 3, "★ Dream": j => fitOK(j) && j.dream,
  Graduate: j => fitOK(j) && j.tier === "grad", Internships: j => fitOK(j) && j.tier === "intern", AI: j => fitOK(j) && j.ai,
  "Sponsor-friendly": j => fitOK(j) && j.visa === "yes" && !noSpon(j), Other: j => fitOK(j) && j.tier === "other",
  "Not a fit": j => !fitOK(j),
};
function visaLabel(j) {
  if (noSpon(j)) return `<span class="due">No sponsorship</span>`;
  if ((j.flags || []).some(f => f.key === "sponsors")) return `<span style="color:var(--good)">Sponsorship mentioned</span>`;
  if (!j.has_details) return `<span>Licence ${esc(j.visa)}</span>`;
  return j.visa === "yes" ? `<span title="Employer holds a Skilled Worker licence; this posting doesn't mention sponsorship">Licence ✓ · posting silent</span>` : `<span>No licence found</span>`;
}
function jobDetails(j) {
  const flags = j.flags || [];
  return `<div class="jd">
    ${j.fit === "not_eligible" ? `<div class="verdict-line bad">${icon("x")}<span><b>Not a fit.</b> ${esc(j.reason)}</span></div>` :
      j.want === "no" ? `<div class="verdict-line bad">${icon("x")}<span><b>Not your kind of role.</b> ${esc(j.want_reason || "")}</span></div>` :
      j.fit === "check" && j.reason ? `<div class="verdict-line warnl">${icon("alert")}<span><b>Check:</b> ${esc(j.reason)}</span></div>` :
      j.fit === "eligible" ? `<div class="verdict-line ok">${icon("check")}<span><b>Looks eligible.</b> ${esc(j.reason || "")}</span></div>` : ""}
    ${j.summary ? `<p class="jd-sum">${esc(j.summary)}</p>` : j.excerpt ? `<p class="jd-sum muted">${esc(j.excerpt)}…</p>` :
      `<p class="jd-sum muted">${j.has_details === false ? "Couldn't read this posting automatically. Open it to check." : "Details not read yet. Press Update jobs."}</p>`}
    ${(j.requirements || []).length ? `<ul class="jd-req">${j.requirements.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    ${flags.filter(f => f.key !== "sponsors" || true).length ? `<div class="jd-flags">${flags.map(f => `<div class="jd-flag ${f.hard ? "hard" : f.key === "sponsors" ? "good" : "soft"}">
      <b>${esc(f.label)}</b>${f.quote ? `<span>“${esc(f.quote)}”</span>` : ""}</div>`).join("")}</div>` : ""}
    <div class="jd-foot">${j.start ? `<span class="muted small">Start: ${esc(j.start)}</span>` : ""}<span class="grow"></span>
      <a class="btn sm" href="${esc(j.url)}" target="_blank" rel="noopener">${icon("ext")}Open posting</a>
      ${j.app_id ? "" : `<button class="btn sm" data-save="${j.id}">${icon("bookmark")}Save</button>
      ${fitOK(j) ? `<button class="btn accent sm" data-tailorjob="${j.id}">${icon("spark")}Tailor</button>` : ""}`}</div>
  </div>`;
}
const TIER = { grad: "Graduate & entry-level", intern: "Internships · check eligibility", other: "Other relevant roles" };
function renderJobs() {
  const feed = S.tasks.feed || {};
  $("updateJobs").disabled = !!feed.running;
  $("updateJobs").innerHTML = feed.running ? `<span class="spin"></span>Updating…` : `${icon("refresh")}Update jobs`;
  $("jobsSub").textContent = feed.running ? (feed.progress || "Updating… (4–8 min). You can keep working.") :
    S.jobs.updated ? `${esc(S.me.city)} roles posted in the last ${S.jobs.max_age_days} days · updated ${ago(S.jobs.updated)}, ${S.jobs.updated.slice(11, 16)}` : "Press Update jobs to fetch roles.";
  const pool = S.jobs.jobs.filter(j => $("showDismissed").checked || !j.dismissed);
  $("jobSeg").innerHTML = Object.entries(JF).map(([k, f]) => `<button class="${k === S.jf ? "on" : ""}" data-jf="${k}">${k} <b>${pool.filter(f).length}</b></button>`).join("");
  const term = S.jq.toLowerCase();
  const TR = { grad: 0, intern: 1, other: 2 };
  let rows = pool.filter(JF[S.jf] || JF.All).filter(j => !term || matches(`${j.company} ${j.title} ${j.location}`, term));
  if (S.jsort === "new") rows.sort((a, b) => a.undated - b.undated || (b.date || "").localeCompare(a.date || ""));
  else if (S.jsort === "deadline") rows.sort((a, b) => (a.deadline || "9999").localeCompare(b.deadline || "9999"));
  else rows.sort((a, b) => TR[a.tier] - TR[b.tier] || a.undated - b.undated || b.dream - a.dream || (b.date || "").localeCompare(a.date || ""));
  let html = "", last = null;
  for (const j of rows) {
    if (S.jsort === "rec" && S.jf !== "Not a fit" && j.tier !== last) { last = j.tier; html += `<div class="group-h" style="cursor:default">${TIER[j.tier]} <span class="count">${rows.filter(r => r.tier === j.tier).length}</span></div>`; }
    const dl = j.deadline ? -days(j.deadline) : null;
    const open = S.openJobs.has(j.id), hard = (j.flags || []).find(f => f.hard);
    html += `<div class="jobwrap ${open ? "open" : ""}"><div class="item ${j.dismissed ? "dim" : ""}" data-job="${j.id}" tabindex="0" aria-expanded="${open}">${av(j.company)}
      <div class="main"><div class="l1"><span class="co">${esc(j.company)}</span>${j.dream ? '<span class="tag star">★ Dream</span>' : ""}
        ${j.ai ? '<span class="tag ai">AI</span>' : ""}${j.new && !j.undated ? '<span class="tag new">New</span>' : ""}
        ${hard ? `<span class="tag danger">${esc(hard.label)}</span>` : j.fit === "not_eligible" ? `<span class="tag danger" title="${esc(j.reason)}">Not a fit</span>` : j.want === "no" ? `<span class="tag danger" title="${esc(j.want_reason || "")}">Not for you</span>` : (j.flags || []).some(f => !f.hard && f.key !== "sponsors") ? '<span class="tag warn">Check level</span>' : j.fit === "eligible" ? '<span class="tag good">Eligible</span>' : ""}</div>
        <a class="title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
        <div class="l3"><span>${j.undated ? "Date unknown" : `Posted ${ago(j.date)}${j.posted ? "" : "*"}`}</span>
          ${j.deadline ? `<span class="${dl !== null && dl <= 7 ? "due" : ""}">Closes ${fmt(j.deadline)}${dl !== null && dl <= 7 ? ` · ${until(j.deadline)}` : ""}</span>` : ""}
          <span>${esc(j.location.slice(0, 42))}</span>${visaLabel(j)}</div></div>
      <div class="side">${j.app_id ? `<button class="btn sm" data-open="${j.app_id}">${icon("check")}In tracker</button>` : `
        ${fitOK(j) ? `<div class="acts"><button class="btn sm" data-tailorjob="${j.id}" title="Save and write a tailored CV + cover letter">${icon("spark")}Tailor</button></div>` : ""}
        <button class="btn sm" data-save="${j.id}" title="Save to tracker">${icon("bookmark")}Save</button>`}
        <button class="icon-btn" data-dismiss="${j.id}" title="${j.dismissed ? "Restore" : "Not interested"}">${icon(j.dismissed ? "refresh" : "x")}</button>
        <span class="caret">${icon("chev")}</span></div></div>
      ${open ? jobDetails(j) : ""}</div>`;
  }
  $("jobList").innerHTML = html || `<div class="empty"><b>${S.jobs.jobs.length ? "Nothing matches" : "No jobs yet"}</b>${S.jobs.jobs.length ? "Try another filter or search." : "Press Update jobs."}</div>`;
  const nf = S.jobs.jobs.filter(j => !fitOK(j)).length;
  $("jobFoot").textContent = S.jobs.updated ? `${rows.length} shown · ${nf} hidden as not eligible or not your kind of role (see the "Not a fit" filter) · click a row for the full breakdown · * date first seen` +
    (S.jobs.errors?.length ? ` · ${S.jobs.errors.length} source(s) failed last run` : "") : "";
}
async function saveJob(id, tailorToo) {
  const j = S.jobs.jobs.find(x => x.id === id);
  const app = await api("/api/jobs/save", { ...j, tailor: !!tailorToo });
  j.app_id = app.id;
  await loadApps();
  renderJobs();
  if (tailorToo) { poll(); openStudio(app.id); }
  else toast(`Saved ${j.company} to Applications`, { label: "Open", fn: () => openDrawer(app.id) });
}

/* ================= APPLICATIONS ================= */
const GROUP_ORDER = ["Interview", "Assessment", "Applied", "Saved", "Offer", "Rejected"];
function renderApps() {
  const g = S.tasks.gmail || {};
  $("checkGmail").disabled = !!g.running;
  $("checkGmail").innerHTML = g.running ? `<span class="spin"></span>Reading Gmail…` : `${icon("mail")}Check Gmail`;
  const active = S.apps.filter(a => a.stage !== "Rejected");
  $("appsSub").textContent = `${S.apps.length} applications · ${active.length} active · ${S.apps.reduce((n, a) => n + (a.files?.length || 0), 0)} documents`;
  const segs = ["Active", ...STAGES, "All"];
  const count = k => k === "Active" ? active.length : k === "All" ? S.apps.length : S.apps.filter(a => a.stage === k).length;
  $("appSeg").innerHTML = segs.filter(k => count(k) || k === "Active" || k === "All").map(k =>
    `<button class="${k === S.af ? "on" : ""}" data-af="${k}">${k} <b>${count(k)}</b></button>`).join("");
  const term = S.aq.toLowerCase();
  const pool = (S.af === "Active" ? active : S.af === "All" ? S.apps : S.apps.filter(a => a.stage === S.af))
    .filter(a => !term || matches(`${a.company} ${a.role} ${a.status} ${a.notes}`, term));
  const grouped = S.af === "Active" || S.af === "All";
  let html = "";
  for (const st of grouped ? GROUP_ORDER : [S.af]) {
    const rows = pool.filter(a => a.stage === st).sort((a, b) => lastAt(b).localeCompare(lastAt(a)));
    if (!rows.length) continue;
    const closed = grouped && S.closed.has(st) && !term;
    if (grouped) html += `<div class="group-h ${closed ? "closed" : ""}" data-group="${st}">${icon("chev")}<i class="dot" style="--c:${SC(st)}"></i>${st} <span class="count">${rows.length}</span></div>`;
    if (closed) continue;
    html += rows.map(a => `<div class="item" data-open="${a.id}" tabindex="0">${av(a.company)}
      <div class="main"><div class="l1"><span class="co">${esc(a.company)}</span>${a.referral ? '<span class="tag good">Referred</span>' : ""}
        ${a.tailored ? `<span class="tag ai">${icon("spark")}Tailored</span>` : ""}</div>
        <span class="title t2">${esc(a.role) || '<span class="muted">Role not recorded</span>'}</span>
        <div class="l3">${a.applied ? `<span>Applied ${fmt(a.applied)}</span>` : ""}<span>Updated ${ago(lastAt(a))}</span>
          ${a.files?.length ? `<span>${icon("file")} ${a.files.length}</span>` : ""}
          ${a.deadline ? `<span class="${-days(a.deadline) <= 7 && -days(a.deadline) >= 0 ? "due" : ""}">Closes ${fmt(a.deadline)}</span>` : ""}
          ${a.status ? `<span style="max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a.status)}</span>` : ""}</div></div>
      <div class="side">${stagePill(a.stage)}</div></div>`).join("");
  }
  $("appList").innerHTML = html || `<div class="empty"><b>Nothing here</b>${term ? "No applications match your search." : "Add one, or save a role from Jobs."}</div>`;
}

/* ---------- Gmail review ---------- */
function renderReview() {
  const G = S.gmail, ups = G.updates || [], news = G.new || [], acts = G.actions || [];
  const n = ups.length + news.length;
  if (!G.checked || (!n && !acts.length)) { $("review").innerHTML = G.checked ? `<p class="muted small" style="margin:-6px 0 14px">Gmail checked ${ago(G.checked)} · nothing new.</p>` : ""; return; }
  const open = store.get("reviewOpen", true);
  $("review").innerHTML = `<div class="card review"><div class="card-h"><h2>${icon("mail")} From Gmail <span class="muted" style="font-weight:400">· ${n} suggestion${n === 1 ? "" : "s"} · checked ${ago(G.checked)}</span></h2>
      <div style="display:flex;gap:6px">${ups.length > 1 && open ? `<button class="btn sm" data-gm="applyAll">Apply all ${ups.length}</button>` : ""}
      <button class="btn ghost sm" data-gm="toggle">${open ? "Hide" : "Review"}</button></div></div>
    ${open ? `${G.warning ? `<div class="note">${esc(G.warning)}</div>` : ""}
      ${acts.map(x => `<div class="sugg"><span class="tag warn">To do</span><div class="main"><b>${esc(x.company)}</b> · ${esc(x.action)}${x.deadline ? ` · <span class="due">due ${fmt(x.deadline)}</span>` : ""}<div class="ev">${esc(x.evidence)}</div></div></div>`).join("")}
      ${ups.map((u, i) => { const a = appById(u.id); return a ? `<div class="sugg">${av(a.company)}<div class="main"><b>${esc(a.company)}</b> <span class="muted">${esc(a.role || "")}</span><br>
        ${stagePill(a.stage)}<span class="arrow">→</span>${stagePill(u.stage)} <span class="t2">${esc(u.status)}</span>
        ${u.confidence && u.confidence !== "high" ? `<span class="tag warn">${esc(u.confidence)} confidence</span>` : ""}<div class="ev">${esc(u.evidence)}</div></div>
        <div style="display:flex;gap:4px"><button class="btn sm" data-gm="apply" data-i="${i}">Apply</button><button class="btn ghost sm" data-gm="ignore" data-i="${i}">Ignore</button></div></div>` : ""; }).join("")}
      ${news.length ? `<div class="group-h" style="cursor:default">Not in your tracker <span class="count">${news.length}</span></div>` + news.map((x, i) => `<div class="sugg">${av(x.company)}
        <div class="main"><b>${esc(x.company)}</b> <span class="muted">${esc(x.role || "")}</span><br>${stagePill(x.stage)} <span class="t2">${esc(x.status)}</span><div class="ev">${esc(x.evidence)}</div></div>
        <div style="display:flex;gap:4px"><button class="btn sm" data-gm="add" data-i="${i}">Add</button><button class="btn ghost sm" data-gm="skip" data-i="${i}">Ignore</button></div></div>`).join("") : ""}` : ""}
  </div>`;
}
async function resolveGmail(list, index) { S.gmail = await api("/api/gmail/resolve", { list, index }); renderReview(); badge(); renderHome(); }
async function applyUpdate(i) {
  const u = S.gmail.updates[i];
  await api(`/api/applications/${u.id}`, { stage: u.stage, status: u.status, _source: "gmail" });
  await resolveGmail("updates", i);
  await loadApps();
}

/* ================= DRAWER ================= */
function openDrawer(id) { S.drawerId = id; renderDrawer(); $("drawer").classList.add("on"); $("scrim").classList.add("on"); }
function closeDrawer() { S.drawerId = null; $("drawer").classList.remove("on"); $("scrim").classList.remove("on"); }
function renderDrawer() {
  const a = appById(S.drawerId); if (!a) return closeDrawer();
  const t = S.tasks[`tailor:${a.id}`] || {};
  $("drawer").innerHTML = `
    <div class="d-head">${av(a.company, "lg")}<div class="main">
        <input class="bare co-in" data-field="company" value="${esc(a.company)}" aria-label="Company">
        <input class="bare role-in" data-field="role" value="${esc(a.role)}" placeholder="Add role title" aria-label="Role"></div>
      <button class="icon-btn" data-act="closeDrawer" title="Close (Esc)">${icon("x")}</button></div>
    <div class="d-body">
      <div class="d-sec"><h3>Stage</h3>
        <div class="stages">${STAGES.map(s => `<button class="${s === a.stage ? "on" : ""}" style="--c:${SC(s)}" data-stage="${s}"><i class="dot" style="--c:${SC(s)}"></i>${s}</button>`).join("")}</div>
        <div class="fields">
          <label class="full">Latest status<input type="text" data-field="status" value="${esc(a.status)}" placeholder="e.g. Online test invited, due 20 Oct"></label>
          <label>Applied<input type="date" data-field="applied" value="${esc(a.applied || "")}"></label>
          <label>Deadline<input type="date" data-field="deadline" value="${esc(a.deadline || "")}"></label>
          <label class="full">Posting link<input type="url" data-field="link" value="${esc(a.link || "")}" placeholder="https://…"></label>
        </div></div>
      ${(() => { const j = a.link && S.jobs.jobs.find(x => x.url === a.link); return j && (j.summary || (j.flags || []).length) ? `<div class="d-sec"><h3>About this role</h3>${jobDetails({ ...j, app_id: a.id })}</div>` : ""; })()}
      <div class="d-sec"><h3>Documents <span>${a.tailored ? `<button class="btn ghost sm" data-studio="${a.id}">${icon("spark")}Open studio</button>` : ""}</span></h3>
        <div class="files">${(a.files || []).map(f => `<a class="file" href="/files/${encodeURIComponent(f.name)}" target="_blank" rel="noopener">
            <span class="k ${f.kind === "CV" ? "" : "cl"}">${f.kind === "CV" ? "CV" : f.kind === "Cover letter" ? "CL" : "DOC"}</span><span>${esc(f.label || f.name)}</span>${icon("ext")}</a>`).join("") ||
            `<p class="muted small" style="margin:0">No documents attached yet.</p>`}</div>
        <label class="drop" id="drop">Drop a PDF or Word file here, or click to attach<input type="file" accept=".pdf,.doc,.docx" hidden id="fileIn"></label>
        <div style="margin-top:10px">${t.running ? `<button class="btn" disabled><span class="spin"></span>${esc(t.progress || "Tailoring…")}</button>` :
          `<button class="btn accent" data-tailor="${a.id}">${icon("spark")}${a.tailored ? "Regenerate tailored CV & letter" : "Tailor CV & cover letter"}</button>`}
          ${!a.link ? `<p class="muted small" style="margin:6px 0 0">Tip: add the posting link first so the documents match the job description.</p>` : ""}
          ${t.ok === false ? `<p class="due small" style="margin:6px 0 0">Last attempt failed: ${esc(t.message)}</p>` : ""}</div></div>
      <div class="d-sec"><h3>Notes</h3><textarea class="inp" data-field="notes" rows="3" placeholder="Contacts, referral, interview prep…">${esc(a.notes || "")}</textarea></div>
      <div class="d-sec"><h3>Timeline</h3><div class="timeline">
        ${[...(a.history || [])].reverse().map(h => `<div class="tl" style="--c:${h.stage ? SC(h.stage) : "var(--muted)"}">
          <div class="when">${esc((h.at || "").replace("T", " · "))}${h.source && h.source !== "manual" ? ` · ${esc(h.source)}` : ""}</div>
          <div class="what">${h.stage ? `<b>${esc(h.stage)}</b>` : ""} ${esc(h.event || h.status || "")}</div></div>`).join("") || `<p class="muted small">No history yet.</p>`}
      </div></div>
    </div>
    <div class="d-foot"><button class="btn ghost danger sm" data-act="deleteApp">${icon("trash")}Delete</button>
      ${a.link ? `<a class="btn sm" href="${esc(a.link)}" target="_blank" rel="noopener">${icon("ext")}Open posting</a>` : ""}</div>`;
  const drop = $("drop"), fin = $("fileIn");
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => e.dataTransfer.files[0] && upload(a.id, e.dataTransfer.files[0]));
  fin.addEventListener("change", () => fin.files[0] && upload(a.id, fin.files[0]));
}
async function patchApp(id, patch, quiet) {
  const app = await api(`/api/applications/${id}`, patch);
  Object.assign(appById(id), app);
  renderApps(); renderHome();
  if (!quiet) renderDrawer();
}
async function upload(id, file) {
  const r = await fetch(`/api/applications/${id}/upload?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
  const d = await r.json();
  if (!r.ok) return toast(d.error || "Upload failed");
  Object.assign(appById(id), d); renderDrawer(); renderApps(); toast(`Attached ${file.name}`);
}

/* ================= DOCUMENTS ================= */
function renderDocs() {
  const packs = S.apps.filter(a => a.tailored).sort((a, b) => lastAt(b).localeCompare(lastAt(a)));
  const running = Object.entries(S.tasks).filter(([k, t]) => k.startsWith("tailor:") && t.running).map(([k]) => appById(k.slice(7))).filter(Boolean);
  $("docsBody").innerHTML = `
    ${running.length ? `<div class="list" style="margin-bottom:14px">${running.map(a => `<div class="item" data-studio="${a.id}">${av(a.company)}<div class="main">
      <div class="l1"><span class="co">${esc(a.company)}</span></div><span class="title t2">${esc(a.role)}</span></div>
      <div class="side"><span class="spin"></span><span class="small t2">${esc(S.tasks["tailor:" + a.id].progress || "Working…")}</span></div></div>`).join("")}</div>` : ""}
    ${packs.length ? `<div class="list">${packs.map(a => { const cv = (a.files || []).find(f => f.kind === "CV" && /tailored/.test(f.name)), cl = (a.files || []).find(f => f.kind === "Cover letter" && /tailored/.test(f.name));
      return `<div class="item" data-studio="${a.id}">${av(a.company)}<div class="main"><div class="l1"><span class="co">${esc(a.company)}</span></div>
        <span class="title t2">${esc(a.role)}</span><div class="l3"><span>Updated ${ago(lastAt(a))}</span>${stagePill(a.stage)}</div></div>
        <div class="side">${cv ? `<a class="btn sm" href="/files/${encodeURIComponent(cv.name)}" target="_blank" rel="noopener">${icon("down")}CV</a>` : ""}
          ${cl ? `<a class="btn sm" href="/files/${encodeURIComponent(cl.name)}" target="_blank" rel="noopener">${icon("down")}Letter</a>` : ""}
          <button class="btn sm">${icon("spark")}Open</button></div></div>`; }).join("")}</div>` :
    `<div class="card"><div class="empty"><b>No tailored documents yet</b>Press <b>Tailor</b> on any job, or <b>Tailor CV &amp; cover letter</b> inside an application.<br>
      You get a one-page CV that keeps your format, a ~350-word letter, an honest fit assessment, ATS keyword check and sources for every company fact.</div></div>`}
    <p class="muted small" style="margin-top:14px">Master CV: <code>cv/master.json</code> in your user folder · Voice: your past letters (<code>cv/own_letters.md</code>).
      ${(S.generalFiles || []).map(f => `<a href="/files/${encodeURIComponent(f.name)}" target="_blank" rel="noopener">Open master CV PDF</a>`).join("")}</p>`;
}

/* ================= TAILOR STUDIO ================= */
async function openStudio(id) {
  S.studioId = id; S.studioData = null; closeDrawer();
  $("studio").classList.add("on"); document.body.style.overflow = "hidden";
  renderStudio();
  try { S.studioData = await api(`/api/tailor/${id}`); } catch { S.studioData = null; }
  renderStudio();
}
function closeStudio() { S.studioId = null; $("studio").classList.remove("on"); document.body.style.overflow = ""; }
function renderStudio() {
  const a = appById(S.studioId); if (!a) return closeStudio();
  const t = S.tasks[`tailor:${a.id}`] || {}, D = S.studioData, stamp = Date.now();
  const head = `<div class="st-head"><button class="icon-btn" data-act="closeStudio" title="Back (Esc)">${icon("x")}</button>${av(a.company)}
    <div class="main"><b>${esc(a.company)}</b> <span class="t2">${esc(a.role)}</span></div>
    ${D && !t.running ? `<a class="btn sm" href="/files/${encodeURIComponent(`${S.me.file_prefix} resume ${a.company.replace(/[^\w &.-]/g, "").trim()} (tailored).pdf`)}" target="_blank" rel="noopener">${icon("down")}CV PDF</a>
      <a class="btn sm" href="/files/${encodeURIComponent(`${S.me.file_prefix} Cover Letter ${a.company.replace(/[^\w &.-]/g, "").trim()} (tailored).pdf`)}" target="_blank" rel="noopener">${icon("down")}Letter PDF</a>
      <button class="btn sm" data-tailor="${a.id}" title="Write fresh versions">${icon("refresh")}Regenerate</button>
      <button class="btn primary sm" data-act="saveStudio">${icon("check")}Save &amp; rebuild PDFs</button>` : ""}</div>`;
  if (t.running || !D) {
    $("studio").innerHTML = head + `<div class="wait">${t.running ? `<span class="spin"></span><div><b>${esc(t.progress || "Working…")}</b><br><span class="muted small">Reading the posting, researching ${esc(a.company)}, then writing. Usually 1–3 minutes. You can close this; it keeps going.</span></div>` :
      t.ok === false ? `<div><b>That didn't work</b><br><span class="muted">${esc(t.message)}</span></div><button class="btn accent" data-tailor="${a.id}">${icon("spark")}Try again</button>` :
      `<div><b>No tailored documents yet</b></div><button class="btn accent" data-tailor="${a.id}">${icon("spark")}Tailor CV & cover letter</button>`}</div>`;
    return;
  }
  const M = D.meta || {}, CL = D.cover_letter || {}, CV = D.cv || {};
  const clWords = (CL.paragraphs || []).reduce((n, p) => n + words(p), 0);
  $("studio").innerHTML = head + `<div class="st-body">
    <div class="st-prev"><div class="seg"><button class="${S.studioView === "cv" ? "on" : ""}" data-view="cv">CV</button><button class="${S.studioView === "cl" ? "on" : ""}" data-view="cl">Cover letter</button></div>
      <iframe id="prev" src="/api/tailor/${a.id}/${S.studioView}.html?t=${stamp}" title="Preview"></iframe></div>
    <div class="st-side">
      ${M.warnings?.length ? `<div class="d-sec"><h3>Check these</h3><div class="warnbox"><ul>${M.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div></div>` : ""}
      ${M.render?.overflow ? `<div class="d-sec"><div class="warnbox">The CV is still slightly over one page at 90% size. Trim a bullet below.</div></div>` : ""}
      <div class="d-sec"><h3>Honest assessment</h3><div class="verdict">${esc(M.honest_assessment || "—")}</div></div>
      <div class="d-sec"><h3>ATS keywords</h3><div class="kw">${(M.ats?.matched || []).map(k => `<span class="tag good">${esc(k)}</span>`).join("")}
        ${(M.ats?.missing || []).map(k => `<span class="tag danger" title="In the posting, not in your CV">${esc(k)}</span>`).join("")}</div>
        <p class="muted small" style="margin:6px 0 0">Green = now in your CV · red = in the posting but you genuinely lack it.</p></div>
      <div class="d-sec"><h3>Cover letter <span class="wc">${clWords} words</span></h3>
        <input type="text" id="clSal" value="${esc(CL.salutation || "Dear Sir or Madam,")}" style="margin-bottom:8px">
        ${(CL.paragraphs || []).map((p, i) => `<textarea class="inp para" data-para="${i}">${esc(p)}</textarea>`).join("")}</div>
      <div class="d-sec"><h3>Company facts used</h3><ul>${(M.fact_check || []).map(f => `<li>${esc(f.claim)} <span class="muted">— ${/^https?:/.test(f.source) ? `<a href="${esc(f.source)}" target="_blank" rel="noopener">source</a>` : esc(f.source)}</span></li>`).join("") || "<li>None</li>"}</ul></div>
      <div class="d-sec"><h3>What changed in the CV</h3><ul>${(M.changes || []).map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>
      <div class="d-sec"><details><summary><h3 style="margin:0">Edit CV bullets ${icon("chev")}</h3></summary><div style="margin-top:10px">
        ${(CV.sections || []).map((s, si) => s.entries.map((e, ei) => `<div class="bul-entry"><div>${esc(e.org)} <span class="muted" style="font-weight:400">· ${esc(s.title)}</span></div>
          ${(e.bullets || []).map((b, bi) => `<textarea class="inp" data-bul="${si}.${ei}.${bi}">${esc(b)}</textarea>`).join("")}</div>`).join("")).join("")}
        <p class="muted small">Leave a bullet empty to remove it. Only use facts from your master CV.</p></div></details></div>
    </div></div>`;
}
async function saveStudio() {
  const D = S.studioData; if (!D) return;
  const cl = { ...D.cover_letter, salutation: $("clSal").value, paragraphs: [...document.querySelectorAll("[data-para]")].map(t => t.value) };
  const cv = JSON.parse(JSON.stringify(D.cv));
  document.querySelectorAll("[data-bul]").forEach(t => { const [s, e, b] = t.dataset.bul.split(".").map(Number); cv.sections[s].entries[e].bullets[b] = t.value; });
  cv.sections.forEach(s => s.entries.forEach(e => e.bullets = e.bullets.filter(b => b.trim())));
  await api(`/api/tailor/${S.studioId}/save`, { cv, cover_letter: cl });
  S.studioData = null; poll(); renderStudio();
}

/* ================= modals ================= */
function modal(html, onSubmit) {
  $("modalBox").innerHTML = html; $("modal").classList.add("on");
  const f = $("modalBox").querySelector("form");
  f?.querySelector("input")?.focus();
  f?.addEventListener("submit", async e => { e.preventDefault(); try { await onSubmit(Object.fromEntries(new FormData(f))); closeModal(); } catch (err) { toast(err.message); } });
}
function closeModal() { $("modal").classList.remove("on"); }
function addAppModal() {
  modal(`<form><h2>Add application</h2><p class="sub small">Log something you applied to outside the Jobs tab.</p>
    <div class="fields"><label class="full">Company<input type="text" name="company" required></label><label class="full">Role<input type="text" name="role"></label>
      <label>Stage<select class="sel" name="stage">${STAGES.map(s => `<option ${s === "Applied" ? "selected" : ""}>${s}</option>`).join("")}</select></label>
      <label>Applied on<input type="date" name="applied" value="${new Date().toISOString().slice(0, 10)}"></label>
      <label class="full">Posting link<input type="url" name="link" placeholder="https://…"></label></div>
    <div class="acts"><button type="button" class="btn ghost" data-act="closeModal">Cancel</button><button class="btn primary">Add</button></div></form>`,
    async v => { const a = await api("/api/applications/new", v); await loadApps(); toast(`Added ${a.company}`, { label: "Open", fn: () => openDrawer(a.id) }); });
}
function tailorModal() {
  modal(`<form><h2>Tailor for a role</h2><p class="sub small">Paste the posting link. Claude reads it, researches the firm and writes a one-page CV and cover letter from your real experience.</p>
    <div class="fields"><label class="full">Company<input type="text" name="company" required></label><label class="full">Role<input type="text" name="role" required></label>
      <label class="full">Posting link<input type="url" name="link" placeholder="https://…" required></label></div>
    <div class="acts"><button type="button" class="btn ghost" data-act="closeModal">Cancel</button><button class="btn accent">${icon("spark")}Tailor</button></div></form>`,
    async v => { const a = await api("/api/applications/new", { ...v, stage: "Saved", status: "Tailoring documents" }); await api(`/api/tailor/${a.id}`, {}); await loadApps(); poll(); openStudio(a.id); });
}
function confirmModal(text, okLabel, fn) {
  modal(`<form><h2>${esc(text)}</h2><p class="sub small">This can't be undone.</p><div class="acts"><button type="button" class="btn ghost" data-act="closeModal">Cancel</button>
    <button class="btn" style="color:var(--danger)">${esc(okLabel)}</button></div></form>`, fn);
}

/* ================= LIVE ================= */
const LIVE = { p: {}, seen: new Set() };
const elapsed = (a, b) => { const s = Math.max(0, Math.round(((b ? new Date(b) : new Date()) - new Date(a)) / 1000)); return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`; };
const clock = iso => iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "";
let liveTimer;
async function livePoll() {
  clearTimeout(liveTimer);
  try { LIVE.p = await api("/api/progress"); } catch { }
  renderLive();
  $("liveDot").hidden = !LIVE.p.running;
  if (LIVE.p.running && !LIVE.wasRunning) LIVE.seen.clear();
  if (LIVE.wasRunning && !LIVE.p.running) { loadJobs(); loadGmail(); }
  LIVE.wasRunning = LIVE.p.running;
  liveTimer = setTimeout(livePoll, S.tab === "live" && LIVE.p.running ? 1000 : LIVE.p.running ? 4000 : 15000);
}
function renderLive() {
  const p = LIVE.p, c = p.counts || {}, busy = S.tasks.morning?.running || S.tasks.feed?.running || S.tasks.gmail?.running;
  $("runSearch").innerHTML = p.running || busy ? `<span class="spin"></span>Running…` : `${icon("refresh")}Run search now`;
  $("runSearch").disabled = !!(p.running || busy);
  if (!p.started) { $("liveSub").textContent = "Watch the job search and Gmail check as they run."; $("liveBody").innerHTML = `<div class="empty">No run recorded yet. The next one starts automatically every other morning at 07:30, or press “Run search now”.</div>`; return; }
  $("liveSub").innerHTML = p.running ? `<span class="live-on"></span>Running since ${clock(p.started)} · ${elapsed(p.started)}`
    : `Last run ${fmt(p.started)} ${clock(p.started)} · took ${elapsed(p.started, p.finished)} · ${p.ok ? esc(p.summary) : `<span style="color:var(--danger)">${esc(p.summary)}</span>`}`;
  const bar = (d, t) => t ? `<div class="lv-bar"><i style="width:${Math.min(100, Math.round(100 * (d || 0) / t))}%"></i></div><span class="lv-n">${d || 0}/${t}</span>` : "";
  const extra = { discover: bar(c.discover_done, c.discover_total), boards: bar(c.boards_done, c.boards_total), read: bar(c.read_done, c.read_total), screen: bar(c.screen_done, c.screen_total),
    gmail: c.searches || c.emails ? `<span class="lv-n">${c.searches || 0} searches · ${c.emails || 0} threads read</span>` : "" };
  const st = s => s.state === "done" ? icon("check") : s.state === "failed" ? icon("x") : s.state === "active" ? `<span class="spin"></span>` : "<i></i>";
  const stat = (n, l) => `<div class="lv-stat"><b>${n === undefined ? "–" : Number(n).toLocaleString()}</b><span>${l}</span></div>`;
  const ev = p.events || [], pass = ev.filter(e => e.kind === "pass").reverse(), fail = ev.filter(e => e.kind === "fail").reverse(), mail = ev.filter(e => e.kind === "mail").reverse();
  const row = e => { const k = e.t + e.title + e.kind, isNew = !LIVE.seen.has(k); LIVE.seen.add(k);
    return `<div class="lv-ev ${e.kind}${isNew ? " in" : ""}">${e.company ? av(e.company, "sm") : ""}<div><b>${esc(e.company)}</b>${e.kind === "mail" ? "" : ` · ${esc(e.title)}`}<div class="t2 small">${esc(e.kind === "mail" ? e.text : e.text || "")}</div></div></div>`; };
  $("liveBody").innerHTML = `
    <div class="lv-stats">${stat(c.postings, "postings scanned")}${stat(c.recent, `${S.me.city} roles, 14 days`)}${stat(c.new, "new since last run")}${stat(c.passed ?? (pass.length || undefined), "pass your filters")}</div>
    ${p.running && p.current ? `<div class="lv-now"><span class="live-on"></span><span class="t2">Now:</span> ${esc(p.current)}</div>` : ""}
    <div class="lv-stages">${(p.stages || []).map(s => `<div class="lv-stage ${s.state}"><span class="lv-ic">${st(s)}</span><div class="lv-l"><b>${esc(s.label)}</b><span class="t2 small">${esc(s.detail || "")}</span></div><div class="lv-x">${s.state === "pending" ? "" : extra[s.key] || ""}</div></div>`).join("")}</div>
    <div class="lv-cols">
      <div><h3>Passed <span class="count">${pass.length}</span></h3>${pass.map(row).join("") || `<p class="muted small">Roles that pass both checks appear here as they're screened.</p>`}</div>
      <div><h3>Ruled out <span class="count">${fail.length}</span></h3>${fail.map(row).join("") || `<p class="muted small">Rejected roles and the reason.</p>`}</div>
    </div>
    ${mail.length ? `<div class="lv-mail"><h3>From Gmail</h3>${mail.map(row).join("")}</div>` : ""}`;
}

/* ================= background tasks ================= */
let pollTimer;
async function poll() {
  clearTimeout(pollTimer);
  const prev = S.tasks;
  try { S.tasks = await api("/api/tasks"); } catch { pollTimer = setTimeout(poll, 8000); return; }
  const running = Object.entries(S.tasks).filter(([, t]) => t.running);
  const label = { feed: "Updating jobs", gmail: "Reading Gmail", morning: "Searching" };
  $("taskPill").classList.toggle("show", running.length > 0);
  $("taskPill").innerHTML = running.length ? `<span class="spin"></span>${running.map(([k, t]) => k.startsWith("tailor:") ? `Tailoring ${esc(appById(k.slice(7))?.company || "")}` : label[k]).join(" · ")}` : "";
  for (const [k, t] of Object.entries(S.tasks)) {
    if (!(prev[k]?.running && !t.running)) continue;
    if (k === "feed") { await loadJobs(); toast(t.ok ? "Jobs updated" : `Job update failed: ${t.message}`); }
    else if (k === "gmail") { await loadGmail(); toast(t.ok ? `Gmail checked: ${t.message}` : `Gmail check failed: ${t.message}`); }
    else if (k.startsWith("tailor:")) {
      const id = k.slice(7), a = appById(id);
      await loadApps();
      if (S.studioId === id) { S.studioData = t.ok ? await api(`/api/tailor/${id}`).catch(() => null) : null; renderStudio(); }
      toast(t.ok ? `Documents ready: ${a?.company || ""}` : `Tailoring failed: ${t.message}`, t.ok && S.studioId !== id ? { label: "Open", fn: () => openStudio(id) } : null);
    }
  }
  // only re-render when task state actually changed (keeps hover/focus stable)
  const sig = JSON.stringify(Object.entries(S.tasks).map(([k, t]) => [k, t.running, t.progress, t.ok]));
  if (sig !== poll.sig) {
    poll.sig = sig;
    renderJobs(); renderApps(); renderDocs();
    if (S.tab === "home") renderHome();
    if (S.drawerId) { const ae = document.activeElement; if (!ae || !$("drawer").contains(ae) || ae.tagName === "BUTTON") renderDrawer(); }
    if (S.studioId && (running.some(([k]) => k === `tailor:${S.studioId}`) || !S.studioData)) renderStudio();
  }
  if (running.some(([k]) => ["feed", "gmail", "morning"].includes(k)) && !LIVE.p.running) livePoll();
  pollTimer = setTimeout(poll, running.length ? 2500 : 12000);
}

/* ================= events ================= */
document.addEventListener("click", async e => {
  const el = e.target.closest("[data-tab],[data-go],[data-jf],[data-af],[data-group],[data-save],[data-tailorjob],[data-dismiss],[data-open],[data-studio],[data-tailor],[data-stage],[data-gm],[data-act],[data-view],[data-todo],[data-job]");
  if (!el) return;
  const d = el.dataset;
  try {
    if (d.tab) return showTab(d.tab);
    if (d.go) { const [tab, f] = d.go.split(":"); showTab(tab); if (tab === "jobs") { if (f === "deadline") { S.jsort = "deadline"; $("jsort").value = "deadline"; S.jf = "All"; } else S.jf = f; renderJobs(); } else { S.af = f; renderApps(); } saveUI(); return; }
    if (d.todo) return renderHome.todos[+d.todo].go();
    if (d.jf) { S.jf = d.jf; saveUI(); return renderJobs(); }
    if (d.af) { S.af = d.af; saveUI(); return renderApps(); }
    if (d.group) { S.closed.has(d.group) ? S.closed.delete(d.group) : S.closed.add(d.group); store.set("closed", [...S.closed]); return renderApps(); }
    if (d.save) { e.stopPropagation(); return saveJob(d.save, false); }
    if (d.tailorjob) { e.stopPropagation(); return saveJob(d.tailorjob, true); }
    if (d.dismiss) {
      e.stopPropagation();
      const j = S.jobs.jobs.find(x => x.id === d.dismiss), was = j.dismissed;
      await api("/api/jobs/dismiss", { id: j.id, undo: was }); j.dismissed = !was; renderJobs(); renderHome();
      if (!was) toast(`Dismissed ${j.company}`, { label: "Undo", fn: async () => { await api("/api/jobs/dismiss", { id: j.id, undo: true }); j.dismissed = false; renderJobs(); } });
      return;
    }
    if (d.open) { e.stopPropagation(); return openDrawer(d.open); }
    if (d.studio) return openStudio(d.studio);
    if (d.job) { if (e.target.closest("a")) return; S.openJobs.has(d.job) ? S.openJobs.delete(d.job) : S.openJobs.add(d.job); return renderJobs(); }
    if (d.tailor) { await api(`/api/tailor/${d.tailor}`, {}); if (S.studioId !== d.tailor) openStudio(d.tailor); else { S.studioData = null; } return poll(); }
    if (d.stage) return patchApp(S.drawerId, { stage: d.stage, status: appById(S.drawerId).status });
    if (d.view) { S.studioView = d.view; return renderStudio(); }
    if (d.gm) {
      const i = +d.i;
      if (d.gm === "toggle") { store.set("reviewOpen", !store.get("reviewOpen", true)); return renderReview(); }
      if (d.gm === "apply") { await applyUpdate(i); return toast("Updated"); }
      if (d.gm === "ignore") return resolveGmail("updates", i);
      if (d.gm === "skip") return resolveGmail("new", i);
      if (d.gm === "add") { const x = S.gmail.new[i]; await api("/api/applications/new", { ...x, status: x.status }); await resolveGmail("new", i); await loadApps(); return toast(`Added ${x.company}`); }
      if (d.gm === "applyAll") { let n = 0; while ((S.gmail.updates || []).some(u => appById(u.id))) { const i2 = S.gmail.updates.findIndex(u => appById(u.id)); await applyUpdate(i2); n++; } return toast(`Applied ${n} updates`); }
    }
    const act = d.act;
    if (act === "updateJobs") { await api("/api/jobs/update", {}); return poll(); }
    if (act === "closeDrawer") return closeDrawer();
    if (act === "closeStudio") return closeStudio();
    if (act === "closeModal") return closeModal();
    if (act === "saveStudio") return saveStudio();
    if (act === "deleteApp") { const a = appById(S.drawerId); return confirmModal(`Delete ${a.company}?`, "Delete", async () => { await api(`/api/applications/${a.id}/delete`, {}); closeDrawer(); await loadApps(); toast(`Deleted ${a.company}`); }); }
  } catch (err) { toast(err.message); }
});
$("tabs").addEventListener("click", e => { const b = e.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab); });
$("updateJobs").onclick = async () => { await api("/api/jobs/update", {}); poll(); };
$("checkGmail").onclick = async () => { await api("/api/gmail/check", {}); poll(); };
$("runSearch").onclick = async () => { LIVE.seen.clear(); await api("/api/search/run", {}); poll(); setTimeout(livePoll, 800); };
$("taskPill").onclick = () => showTab("live");
$("addApp").onclick = addAppModal;
$("newTailor").onclick = tailorModal;
$("themeBtn").onclick = () => { const order = ["auto", "light", "dark"], c = store.get("themeChoice", "auto"); store.set("themeChoice", order[(order.indexOf(c) + 1) % 3]); applyTheme(); };
$("scrim").onclick = closeDrawer;
$("modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });
$("jq").addEventListener("input", debounce(e => { S.jq = e.target.value; renderJobs(); }, 120));
$("aq").addEventListener("input", debounce(e => { S.aq = e.target.value; renderApps(); }, 120));
$("jsort").addEventListener("change", e => { S.jsort = e.target.value; saveUI(); renderJobs(); });
$("showDismissed").addEventListener("change", renderJobs);
// drawer field edits: save on change (inputs) / blur (notes)
$("drawer").addEventListener("change", e => { const f = e.target.dataset.field; if (f) patchApp(S.drawerId, { [f]: e.target.value }, true); });
$("drawer").addEventListener("keydown", e => { if (e.key === "Enter" && e.target.matches("input[data-field]")) e.target.blur(); });
document.addEventListener("keydown", e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
  if (e.key === "Escape") { if ($("modal").classList.contains("on")) return closeModal(); if (S.studioId) return closeStudio(); if (S.drawerId) return closeDrawer(); if (typing) document.activeElement.blur(); }
  if (typing || e.metaKey || e.ctrlKey) return;
  if (e.key === "/") { e.preventDefault(); (S.tab === "apps" ? $("aq") : (showTab("jobs"), $("jq"))).focus(); }
  if (e.key === "Enter" && document.activeElement?.dataset.open) openDrawer(document.activeElement.dataset.open);
  if ((e.key === "Enter" || e.key === " ") && document.activeElement?.dataset.job) { e.preventDefault(); document.activeElement.click(); }
  const n = { 1: "home", 2: "jobs", 3: "apps", 4: "docs", 5: "live" }[e.key]; if (n) showTab(n);
});
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

/* ================= boot ================= */
applyTheme();
showTab(location.hash.slice(1) || "home");
$("jsort").value = S.jsort;
api("/api/settings").then(me => { S.me = me; }).catch(() => {})
  .then(() => Promise.all([loadJobs(), loadApps()])).then(loadGmail).then(poll).then(livePoll).catch(err => toast(err.message));
