/* job-match dashboard. Vanilla JS, no dependencies. Every string from the data lands in
   the DOM through textContent or an attribute set on an element we created: nothing from
   the database is ever parsed as HTML. */
(function () {
  "use strict";

  var SECTIONS = ["strong", "eligible", "stretch"];
  var TABS = ["jobs", "leads", "runs"];
  var HTTP = /^https?:\/\//i;

  var raw = document.getElementById("data");
  var data;
  try {
    data = JSON.parse(raw.textContent);
  } catch (err) {
    document.getElementById("main").textContent = "The embedded data could not be read.";
    return;
  }
  var jobs = data.jobs || [];
  var leads = data.leads || [];
  var runs = data.runs || [];
  var thresholds = data.thresholds || { strong: 70, min_score: 60 };

  /* ---------- small DOM helpers ---------- */

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "text") node.textContent = String(v);
        else if (k === "class") node.className = v;
        else node.setAttribute(k, v === true ? "" : String(v));
      });
    }
    if (children) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (c === null || c === undefined || c === false) return;
        node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
      });
    }
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function link(url, label) {
    if (!url || !HTTP.test(url)) return el("span", { class: "unknown", text: "—" });
    return el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: label });
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  }

  function fmtDateTime(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
      timeZone: "UTC", timeZoneName: "short"
    });
  }

  function fmtYears(y) {
    if (y === null || y === undefined) return null;
    return Number.isInteger(y) ? String(y) : String(y);
  }

  function fmtAmount(amount, currency) {
    if (amount === null || amount === undefined) return null;
    var unit = "";
    var n = amount;
    if (n >= 1e9) { n = n / 1e9; unit = " bn"; }
    else if (n >= 1e6) { n = n / 1e6; unit = " M"; }
    else if (n >= 1e3) { n = n / 1e3; unit = " k"; }
    var s = (Math.round(n * 10) / 10).toString();
    var cur = currency === "EUR" ? "€" : currency === "USD" ? "$" : currency === "GBP" ? "£" : (currency || "");
    return s + unit + (cur ? (cur.length === 1 ? cur : " " + cur) : "");
  }

  function dayOf(iso) {
    return iso ? iso.slice(0, 10) : "";
  }

  /* ---------- theme ---------- */

  var themeBtn = byId("theme-toggle");

  function storedTheme() {
    try { return localStorage.getItem("job-match-theme"); } catch (e) { return null; }
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || systemTheme();
  }

  function applyTheme(theme, persist) {
    document.documentElement.setAttribute("data-theme", theme);
    themeBtn.textContent = theme === "dark" ? "Light mode" : "Dark mode";
    themeBtn.setAttribute("aria-pressed", theme === "light" ? "true" : "false");
    if (persist) {
      try { localStorage.setItem("job-match-theme", theme); } catch (e) { /* private window */ }
    }
  }

  applyTheme(storedTheme() === "light" || storedTheme() === "dark" ? storedTheme() : systemTheme(), false);
  themeBtn.addEventListener("click", function () {
    applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
  });

  /* ---------- tabs ---------- */

  var tabButtons = Array.prototype.slice.call(document.querySelectorAll(".tab"));

  function showTab(name, focus) {
    if (TABS.indexOf(name) < 0) name = "jobs";
    tabButtons.forEach(function (b) {
      var on = b.getAttribute("data-tab") === name;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    TABS.forEach(function (t) {
      byId("panel-" + t).hidden = t !== name;
    });
    currentTab = name;
    syncHash();
  }

  var currentTab = "jobs";
  var applyingHash = false;

  /* The hash carries the tab and the job filters (#jobs?q=...&hide=...), so a view can be
     shared or reloaded. Every value is validated before it touches the state. */
  function syncHash() {
    if (applyingHash) return;
    var parts = [];
    if (currentTab === "jobs") {
      if (state.q) parts.push("q=" + encodeURIComponent(state.q));
      var off = SECTIONS.filter(function (s) { return !state.sections[s]; });
      if (off.length) parts.push("hide=" + off.join(","));
      if (state.department) parts.push("dept=" + encodeURIComponent(state.department));
      if (state.minScore) parts.push("min=" + state.minScore);
      if (state.from) parts.push("from=" + state.from);
      if (state.to) parts.push("to=" + state.to);
      if (state.sortKey !== "score" || state.sortDir !== "desc") parts.push("sort=" + state.sortKey + ":" + state.sortDir);
    }
    var next = "#" + currentTab + (parts.length ? "?" + parts.join("&") : "");
    if (location.hash !== next) {
      try { history.replaceState(null, "", next); } catch (e) { /* file:// */ }
    }
  }

  function parseHash() {
    var h = location.hash.replace(/^#/, "");
    var q = h.indexOf("?");
    var tab = q < 0 ? h : h.slice(0, q);
    var params = {};
    if (q >= 0) {
      h.slice(q + 1).split("&").forEach(function (kv) {
        var i = kv.indexOf("=");
        if (i < 0) return;
        try { params[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* bad escape */ }
      });
    }
    return { tab: TABS.indexOf(tab) >= 0 ? tab : "jobs", params: params };
  }

  tabButtons.forEach(function (b, i) {
    b.addEventListener("click", function () { showTab(b.getAttribute("data-tab"), false); });
    b.addEventListener("keydown", function (ev) {
      var next = null;
      if (ev.key === "ArrowRight") next = (i + 1) % tabButtons.length;
      if (ev.key === "ArrowLeft") next = (i - 1 + tabButtons.length) % tabButtons.length;
      if (ev.key === "Home") next = 0;
      if (ev.key === "End") next = tabButtons.length - 1;
      if (next !== null) {
        ev.preventDefault();
        showTab(tabButtons[next].getAttribute("data-tab"), true);
      }
    });
  });

  window.addEventListener("hashchange", function () {
    applyHash();
  });

  /* ---------- jobs ---------- */

  var state = {
    q: "",
    sections: { strong: true, eligible: true, stretch: true },
    department: "",
    minScore: 0,
    from: "",
    to: "",
    sortKey: "score",
    sortDir: "desc",
    expanded: {}
  };

  var searchInput = byId("f-search");
  var deptSelect = byId("f-department");
  var minScoreInput = byId("f-min-score");
  var minScoreOut = byId("f-min-score-out");
  var fromInput = byId("f-from");
  var toInput = byId("f-to");
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip[data-section]"));
  var jobsBody = byId("jobs-body");

  byId("min-score-hint").textContent = "(digest ≥ " + thresholds.min_score + ", strong ≥ " + thresholds.strong + ")";

  function fillDepartments() {
    var counts = {};
    var unknown = 0;
    jobs.forEach(function (j) {
      if (j.department) counts[j.department] = (counts[j.department] || 0) + 1;
      else unknown += 1;
    });
    Object.keys(counts).sort().forEach(function (d) {
      deptSelect.appendChild(el("option", { value: d, text: d + " (" + counts[d] + ")" }));
    });
    if (unknown) deptSelect.appendChild(el("option", { value: "?", text: "? unknown (" + unknown + ")" }));
  }

  function matches(j) {
    if (!state.sections[j.section]) return false;
    if (state.minScore > 0 && (j.score === null || j.score < state.minScore)) return false;
    if (state.department) {
      if (state.department === "?" ? !!j.department : j.department !== state.department) return false;
    }
    var day = dayOf(j.posted_at);
    if (state.from && day < state.from) return false;
    if (state.to && day > state.to) return false;
    if (state.q) {
      var hay = ((j.title || "") + " " + (j.company || "")).toLowerCase();
      if (hay.indexOf(state.q) < 0) return false;
    }
    return true;
  }

  function compare(a, b) {
    var k = state.sortKey;
    var av = a[k], bv = b[k];
    var aNull = av === null || av === undefined || av === "";
    var bNull = bv === null || bv === undefined || bv === "";
    if (aNull && bNull) return 0;
    if (aNull) return 1;          /* unknowns last whatever the direction */
    if (bNull) return -1;
    var r;
    if (typeof av === "number" && typeof bv === "number") r = av - bv;
    else r = String(av).localeCompare(String(bv), undefined, { sensitivity: "base", numeric: true });
    return state.sortDir === "asc" ? r : -r;
  }

  function cell(cls, label, child) {
    var td = el("td", { class: cls, "data-label": label });
    if (child !== undefined && child !== null) {
      if (typeof child === "string") td.textContent = child;
      else td.appendChild(child);
    }
    return td;
  }

  function scoreCell(j) {
    var wrap = el("span", { class: "score score-" + j.section });
    var bar = el("span", { class: "score-bar", "aria-hidden": "true" });
    var fill = el("i");
    fill.style.width = (j.score === null ? 0 : Math.max(0, Math.min(100, j.score))) + "%";
    bar.appendChild(fill);
    wrap.appendChild(bar);
    wrap.appendChild(el("span", { text: j.score === null ? "—" : String(j.score) }));
    return wrap;
  }

  function detailsFor(j) {
    var td = el("td", { colspan: "9" });
    var box = el("div", { class: "details" });
    var meta = [];
    if (j.location) meta.push(j.location);
    if (j.source) meta.push("source: " + j.source);
    if (!j.published_at) meta.push("no posting date from the source");
    if (j.collected_at) meta.push("collected " + fmtDate(j.collected_at));
    var stretchLine = null;
    var others = [];
    (j.explanations || []).forEach(function (line) {
      if (line.indexOf("stretch:") === 0 && !stretchLine) stretchLine = line;
      else others.push(line);
    });
    if (j.experience_status && !stretchLine) meta.push("experience parse: " + j.experience_status.toLowerCase());
    box.appendChild(el("p", { class: "meta", text: meta.join(" · ") }));
    if (stretchLine) box.appendChild(el("p", { class: "stretch-note", text: stretchLine }));

    var grid = el("div", { class: "details-grid" });
    var left = el("div");
    left.appendChild(el("h3", { text: "Explanations" }));
    if (others.length) {
      left.appendChild(el("ul", null, others.map(function (t) { return el("li", { text: t }); })));
    } else {
      left.appendChild(el("p", { class: "note", text: "No explanation stored for this job." }));
    }
    grid.appendChild(left);

    var right = el("div");
    function tags(title, items, cls) {
      if (!items || !items.length) return;
      right.appendChild(el("h3", { text: title }));
      right.appendChild(el("div", { class: "tags" }, items.map(function (t) {
        return el("span", { class: "tag " + cls, text: t });
      })));
    }
    tags("Matched", j.positive, "tag-pos");
    tags("Negative", j.negative, "tag-neg");
    tags("Missing preferences", j.missing, "tag-miss");
    if (!right.childNodes.length) right.appendChild(el("p", { class: "note", text: "No skill matches recorded." }));
    grid.appendChild(right);
    box.appendChild(grid);
    td.appendChild(box);
    return el("tr", { class: "details", id: "job-details-" + j.id }, td);
  }

  function toggleRow(j, row) {
    var open = !state.expanded[j.id];
    state.expanded[j.id] = open;
    row.setAttribute("aria-expanded", open ? "true" : "false");
    row.querySelector(".expand").setAttribute("aria-expanded", open ? "true" : "false");
    var existing = byId("job-details-" + j.id);
    if (open && !existing) row.parentNode.insertBefore(detailsFor(j), row.nextSibling);
    if (!open && existing) existing.parentNode.removeChild(existing);
  }

  function renderJobs() {
    var shown = jobs.filter(matches).sort(compare);
    var counts = { strong: 0, eligible: 0, stretch: 0 };
    shown.forEach(function (j) { counts[j.section] += 1; });
    byId("kpi-strong").textContent = counts.strong;
    byId("kpi-eligible").textContent = counts.eligible;
    byId("kpi-stretch").textContent = counts.stretch;
    byId("kpi-shown").textContent = shown.length;
    byId("kpi-total").textContent = jobs.length;
    byId("jobs-rowcount").textContent = shown.length + " of " + jobs.length + " jobs · sorted by " +
      state.sortKey.replace("_", " ") + (state.sortDir === "asc" ? " ↑" : " ↓");

    clear(jobsBody);
    byId("jobs-empty").hidden = shown.length > 0;
    var frag = document.createDocumentFragment();
    shown.forEach(function (j) {
      var row = el("tr", { class: "row row-" + j.section, tabindex: "0", "aria-expanded": state.expanded[j.id] ? "true" : "false" });
      var btn = el("button", {
        type: "button", class: "expand", "aria-expanded": state.expanded[j.id] ? "true" : "false",
        "aria-controls": "job-details-" + j.id
      }, [el("span", { class: "dot dot-" + j.section, "aria-hidden": "true" }), el("span", { class: "title-text", text: j.title || "—" })]);
      row.appendChild(cell("col-title", "Title", btn));
      row.appendChild(cell("col-company", "Company", j.company || "—"));
      row.appendChild(cell("col-dept", "Dept", j.department || "?"));
      row.appendChild(cell("col-contract", "Contract", j.contract || "UNKNOWN"));
      row.appendChild(cell("num col-score", "Score", scoreCell(j)));
      var years = fmtYears(j.required_years);
      row.appendChild(cell("num col-years", "Years", el("span", { class: years === null ? "unknown years" : "years", text: years === null ? "—" : years + "y" })));
      row.appendChild(cell("col-date", "Posted", fmtDate(j.posted_at)));
      var age = typeof j.age_days === "number" ? j.age_days : null;
      row.appendChild(cell("num col-age", "Age", el("span", { class: age === null ? "unknown" : "", text: age === null ? "—" : age + "d" })));
      row.appendChild(cell("link-col", "Link", link(j.url, "Open")));

      row.addEventListener("click", function (ev) {
        if (ev.target.closest("a")) return;
        toggleRow(j, row);
      });
      row.addEventListener("keydown", function (ev) {
        if (ev.target !== row) return;
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleRow(j, row); }
      });
      frag.appendChild(row);
      if (state.expanded[j.id]) frag.appendChild(detailsFor(j));
    });
    jobsBody.appendChild(frag);
  }

  var debounce;
  searchInput.addEventListener("input", function () {
    clearTimeout(debounce);
    debounce = setTimeout(function () {
      state.q = searchInput.value.trim().toLowerCase();
      renderJobs();
      syncHash();
    }, 120);
  });

  chips.forEach(function (c) {
    c.addEventListener("click", function () {
      var s = c.getAttribute("data-section");
      state.sections[s] = !state.sections[s];
      c.setAttribute("aria-pressed", state.sections[s] ? "true" : "false");
      renderJobs();
      syncHash();
    });
  });

  deptSelect.addEventListener("change", function () {
    state.department = deptSelect.value;
    renderJobs();
    syncHash();
  });

  minScoreInput.addEventListener("input", function () {
    state.minScore = Number(minScoreInput.value) || 0;
    minScoreOut.textContent = state.minScore;
    renderJobs();
    syncHash();
  });

  fromInput.addEventListener("change", function () { state.from = fromInput.value; renderJobs(); syncHash(); });
  toInput.addEventListener("change", function () { state.to = toInput.value; renderJobs(); syncHash(); });

  byId("f-reset").addEventListener("click", function () {
    state.q = ""; searchInput.value = "";
    SECTIONS.forEach(function (s) { state.sections[s] = true; });
    chips.forEach(function (c) { c.setAttribute("aria-pressed", "true"); });
    state.department = ""; deptSelect.value = "";
    state.minScore = 0; minScoreInput.value = "0"; minScoreOut.textContent = "0";
    state.from = ""; fromInput.value = "";
    state.to = ""; toInput.value = "";
    renderJobs();
    syncHash();
    searchInput.focus();
  });

  var headers = Array.prototype.slice.call(document.querySelectorAll("#jobs-table th[aria-sort]"));
  headers.forEach(function (th) {
    var btn = th.querySelector(".sort");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var key = btn.getAttribute("data-key");
      if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      else { state.sortKey = key; state.sortDir = (key === "score" || key === "posted_at") ? "desc" : "asc"; }
      markSortHeader();
      renderJobs();
      syncHash();
    });
  });

  function markSortHeader() {
    headers.forEach(function (h) {
      var b = h.querySelector(".sort");
      h.setAttribute("aria-sort", b && b.getAttribute("data-key") === state.sortKey
        ? (state.sortDir === "asc" ? "ascending" : "descending") : "none");
    });
  }

  var SORT_KEYS = ["title", "company", "department", "contract", "score", "required_years", "posted_at", "age_days"];
  var DAY = /^\d{4}-\d{2}-\d{2}$/;

  function applyHash() {
    var parsed = parseHash();
    var p = parsed.params;
    applyingHash = true;
    state.q = (p.q || "").trim().toLowerCase();
    searchInput.value = p.q || "";
    SECTIONS.forEach(function (s) { state.sections[s] = true; });
    (p.hide || "").split(",").forEach(function (s) { if (SECTIONS.indexOf(s) >= 0) state.sections[s] = false; });
    chips.forEach(function (c) { c.setAttribute("aria-pressed", state.sections[c.getAttribute("data-section")] ? "true" : "false"); });
    var deptOk = p.dept && Array.prototype.some.call(deptSelect.options, function (o) { return o.value === p.dept; });
    state.department = deptOk ? p.dept : "";
    deptSelect.value = state.department;
    var min = parseInt(p.min, 10);
    state.minScore = min >= 0 && min <= 100 ? min : 0;
    minScoreInput.value = String(state.minScore);
    minScoreOut.textContent = String(state.minScore);
    state.from = DAY.test(p.from || "") ? p.from : "";
    fromInput.value = state.from;
    state.to = DAY.test(p.to || "") ? p.to : "";
    toInput.value = state.to;
    var sort = (p.sort || "score:desc").split(":");
    state.sortKey = SORT_KEYS.indexOf(sort[0]) >= 0 ? sort[0] : "score";
    state.sortDir = sort[1] === "asc" ? "asc" : "desc";
    markSortHeader();
    renderJobs();
    showTab(parsed.tab, false);
    applyingHash = false;
    syncHash();
  }

  /* ---------- leads ---------- */

  function leadDetails(l) {
    var td = el("td", { colspan: "7" });
    var box = el("div", { class: "details" });
    var meta = [];
    if (l.reason) meta.push(l.reason);
    if (l.country) meta.push(l.country);
    if (l.source) meta.push("source: " + l.source);
    if (l.article_title) meta.push(l.article_title);
    box.appendChild(el("p", { class: "meta", text: meta.join(" · ") }));
    var grid = el("div", { class: "details-grid" });
    var left = el("div");
    left.appendChild(el("h3", { text: "Evidence" }));
    var keys = Object.keys(l.evidence || {});
    if (keys.length) {
      left.appendChild(el("ul", null, keys.map(function (k) {
        return el("li", null, [el("b", { text: k + ": " }), l.evidence[k]]);
      })));
    } else {
      left.appendChild(el("p", { class: "note", text: "No evidence sentence stored." }));
    }
    grid.appendChild(left);
    var right = el("div");
    if (l.investors && l.investors.length) {
      right.appendChild(el("h3", { text: "Investors" }));
      right.appendChild(el("div", { class: "tags" }, l.investors.map(function (t) { return el("span", { class: "tag", text: t }); })));
    }
    right.appendChild(el("h3", { text: "Eligible open jobs" }));
    right.appendChild(el("p", { class: "note", text: String(l.open_jobs || 0) + " canonical eligible job(s) at this company in the dedup window" }));
    grid.appendChild(right);
    box.appendChild(grid);
    td.appendChild(box);
    return el("tr", { class: "details", id: "lead-details-" + l.id }, td);
  }

  function renderLeads() {
    var body = byId("leads-body");
    clear(body);
    byId("leads-rowcount").textContent = leads.length + " funding leads · high priority first";
    byId("leads-empty").hidden = leads.length > 0;
    var frag = document.createDocumentFragment();
    leads.forEach(function (l) {
      var row = el("tr", { class: "row", tabindex: "0", "aria-expanded": "false" });
      var btn = el("button", { type: "button", class: "expand", "aria-expanded": "false", "aria-controls": "lead-details-" + l.id },
        [el("span", { class: "dot " + (l.priority === "high" ? "dot-strong" : ""), "aria-hidden": "true" }), el("span", { class: "title-text", text: l.company || "—" })]);
      row.appendChild(cell("col-title", "Company", btn));
      row.appendChild(cell("col-priority", "Priority", el("span", { class: "badge" + (l.priority === "high" ? " badge-high" : ""), text: l.priority || "normal" })));
      var raise = [fmtAmount(l.amount, l.currency), l.round].filter(Boolean).join(" · ");
      row.appendChild(cell("col-raise", "Raise", raise ? el("span", { class: "mono", text: raise }) : el("span", { class: "unknown", text: "—" })));
      row.appendChild(cell("col-hiring", "Hiring", l.hiring ? l.hiring : el("span", { class: "unknown", text: "—" })));
      row.appendChild(cell("num col-open", "Open jobs", el("span", { class: "mono", text: String(l.open_jobs || 0) })));
      row.appendChild(cell("col-date", "Published", fmtDate(l.published_at || l.created_at)));
      row.appendChild(cell("link-col", "Article", link(l.article_url, "Read")));
      var open = false;
      function toggle() {
        open = !open;
        row.setAttribute("aria-expanded", open ? "true" : "false");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        var existing = byId("lead-details-" + l.id);
        if (open && !existing) row.parentNode.insertBefore(leadDetails(l), row.nextSibling);
        if (!open && existing) existing.parentNode.removeChild(existing);
      }
      row.addEventListener("click", function (ev) { if (!ev.target.closest("a")) toggle(); });
      row.addEventListener("keydown", function (ev) {
        if (ev.target !== row) return;
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); }
      });
      frag.appendChild(row);
    });
    body.appendChild(frag);
  }

  /* ---------- runs ---------- */

  function seg(cls, value, total, label, inner) {
    var s = el("div", { class: "seg " + cls, role: "img", "aria-label": label + ": " + value });
    s.style.width = total > 0 ? (100 * value / total) + "%" : "0%";
    s.title = label + ": " + value;
    if (inner) s.appendChild(inner);
    return s;
  }

  function stat(label, value) {
    return el("span", null, [label + " ", el("b", { text: String(value) })]);
  }

  function renderRuns() {
    var list = byId("runs-list");
    clear(list);
    byId("runs-rowcount").textContent = runs.length + " most recent job runs · newest first";
    byId("runs-empty").hidden = runs.length > 0;
    runs.forEach(function (r) {
      var card = el("article", { class: "run" });
      var head = el("div", { class: "run-head" });
      head.appendChild(el("span", { class: "run-date", text: fmtDateTime(r.started_at) }));
      if (r.pipeline === "jobs_reprocess") head.appendChild(el("span", { class: "badge badge-reprocess", text: "reprocess" }));
      if (r.errors) head.appendChild(el("span", { class: "badge", text: r.errors + " error(s)" }));
      head.appendChild(el("span", { class: "run-fetched" }, [r.pipeline === "jobs_reprocess" ? "read " : "fetched ", el("b", { text: String(r.fetched) })]));
      card.appendChild(head);

      var total = r.fetched || 0;
      var funnel = el("div", { class: "funnel" });
      funnel.appendChild(seg("seg-rejected", r.rejected, total, "Rejected"));
      funnel.appendChild(seg("seg-duplicates", r.duplicates, total, r.pipeline === "jobs_reprocess" ? "New duplicate links" : "Duplicates"));
      var strongInner = el("i", { title: "Strong: " + r.strong });
      strongInner.style.width = r.eligible > 0 ? (100 * r.strong / r.eligible) + "%" : "0%";
      funnel.appendChild(seg("seg-eligible", r.eligible, total, "Eligible (" + r.strong + " strong)", strongInner));
      funnel.appendChild(seg("seg-stretch", r.stretch, total, "Stretch"));
      card.appendChild(funnel);

      var stats = el("p", { class: "run-stats" });
      stats.appendChild(stat("rejected", r.rejected));
      stats.appendChild(stat(r.pipeline === "jobs_reprocess" ? "new links" : "duplicates", r.duplicates));
      stats.appendChild(stat("eligible", r.eligible));
      stats.appendChild(stat("strong", r.strong));
      stats.appendChild(stat("stretch", r.stretch));
      if (r.api_calls) stats.appendChild(stat("API calls", r.api_calls));
      if (r.checked) stats.appendChild(stat("checked at source", r.checked));
      if (r.closed) stats.appendChild(stat("closed", r.closed));
      if (r.self_links_dropped) stats.appendChild(stat("self-links dropped", r.self_links_dropped));
      if (r.stale_links_dropped) stats.appendChild(stat("stale links dropped", r.stale_links_dropped));
      card.appendChild(stats);

      var reasons = Object.keys(r.rejected_by_reason || {}).sort(function (a, b) {
        return r.rejected_by_reason[b] - r.rejected_by_reason[a];
      });
      if (reasons.length) {
        var p = el("p", { class: "run-reasons" }, ["Rejected by reason (a job may fail several gates): "]);
        reasons.forEach(function (k, i) {
          if (i) p.appendChild(document.createTextNode(" · "));
          p.appendChild(document.createTextNode(k.toLowerCase() + " "));
          p.appendChild(el("b", { text: String(r.rejected_by_reason[k]) }));
        });
        card.appendChild(p);
      }

      var sources = Object.keys(r.by_source || {}).sort();
      if (sources.length > 1 || (sources.length === 1 && r.pipeline === "jobs")) {
        var sp = el("p", { class: "run-sources" });
        sources.forEach(function (name) {
          var s = r.by_source[name] || {};
          sp.appendChild(el("span", null, [
            name + ": ",
            el("b", { text: String(s.fetched || 0) }), " fetched, ",
            el("b", { text: String(s.eligible || 0) }), " eligible, ",
            el("b", { text: String(s.calls || 0) }), " calls"
          ]));
        });
        card.appendChild(sp);
      }
      list.appendChild(card);
    });
  }

  /* ---------- boot ---------- */

  byId("generated-at").textContent = "snapshot " + fmtDateTime(data.generated_at);
  byId("count-jobs").textContent = jobs.length;
  byId("count-leads").textContent = leads.length;
  byId("count-runs").textContent = runs.length;
  fillDepartments();
  renderLeads();
  renderRuns();
  if (window.innerWidth <= 768) byId("jobs-controls").removeAttribute("open");
  applyHash();
})();
