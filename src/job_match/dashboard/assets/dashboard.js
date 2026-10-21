/* job-match dashboard. Vanilla JS, no dependencies. Every string from the data lands in
   the DOM through textContent or an attribute set on an element we created: nothing from
   the database is ever parsed as HTML. */
(function () {
  "use strict";

  var SECTIONS = ["strong", "eligible", "stretch"];
  var TABS = ["today", "jobs", "leads", "runs"];
  var HTTP = /^https?:\/\//i;
  var T = window.JMTracking;

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

  /* "19/10" for the tables; the full date goes in the cell's tooltip and the details. */
  function fmtShortDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
  }

  function dateCell(cls, label, iso) {
    var td = cell(cls, label, fmtShortDate(iso));
    if (iso) td.title = fmtDate(iso);
    return td;
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
    if (TABS.indexOf(name) < 0) name = "today";
    if (name === "today" && currentTab !== "today") renderToday();
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

  var currentTab = "";
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
      if (state.status) parts.push("st=" + state.status);
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
    return { tab: TABS.indexOf(tab) >= 0 ? tab : "today", params: params };
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
    status: "",
    minScore: 0,
    from: "",
    to: "",
    sortKey: "score",
    sortDir: "desc",
    expanded: {}
  };
  var todayExpanded = {};

  var searchInput = byId("f-search");
  var deptSelect = byId("f-department");
  var statusSelect = byId("f-status");
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

  function fillStatuses() {
    T.STATUSES.forEach(function (s) {
      statusSelect.appendChild(el("option", { value: s, text: T.STATUS_TEXT[s] }));
    });
  }

  function matches(j) {
    if (!state.sections[j.section]) return false;
    if (state.status && statusOfJob(j) !== state.status) return false;
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

  function sortValue(j, k) {
    return k === "status" ? T.STATUSES.indexOf(statusOfJob(j)) : j[k];
  }

  function compare(a, b) {
    var k = state.sortKey;
    var av = sortValue(a, k), bv = sortValue(b, k);
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

  /* ---------- tracking (D1 through /api/) ---------- */

  /* status: "off" (file:// or no fetch), "loading", "ready", "error". `apps` is what the page
     shows (optimistic), `confirmed` what the API last stored; a failed save goes back to it. */
  var track = { status: "off", apps: {}, confirmed: {}, decisions: {}, overrides: {}, seq: {}, pending: 0 };
  /* skill -> functions redrawing every "je maîtrise" control for it on screen */
  var overrideViews = {};

  /* Why a write failed, in words the reader can act on. */
  function failureText(err) {
    if (err && err.status === 401) return "your Access session expired, reload the page";
    if (err && err.status >= 500) return "the server failed";
    return (err && err.message) || "network error";
  }

  /* A note typed in the last moment, or a save still in flight, is not stored yet. */
  window.addEventListener("beforeunload", function (ev) {
    if (track.pending > 0) { ev.preventDefault(); ev.returnValue = ""; }
  });
  var badges = {};   /* job key -> status badges on screen, updated in place after a save */
  var api = (typeof window.fetch === "function") ? T.client(window.fetch.bind(window)) : null;

  function statusOfJob(j) {
    return T.statusOf(track.apps[j.key]);
  }

  function statusBadge(key) {
    var s = T.statusOf(track.apps[key]);
    var b = el("span", { class: "status status-" + s, text: T.STATUS_TEXT[s] });
    (badges[key] = badges[key] || []).push(b);
    return b;
  }

  function refreshBadges(key) {
    var s = T.statusOf(track.apps[key]);
    (badges[key] || []).forEach(function (b) {
      b.className = "status status-" + s;
      b.textContent = T.STATUS_TEXT[s];
    });
    updateTodayCounts();
  }

  function trackBanner() {
    var banner = byId("track-banner");
    var msg = byId("track-banner-text");
    var retry = byId("track-retry");
    if (track.status === "ready" || track.status === "loading") { banner.hidden = true; return; }
    banner.hidden = false;
    msg.textContent = track.status === "off"
      ? "Tracking is unavailable in a page opened from a file. Statuses and notes need the hosted dashboard."
      : "Tracking could not be loaded, so statuses show as “To review” and nothing can be saved.";
    retry.hidden = track.status !== "error";
  }

  function loadTracking() {
    if (!api || !/^https?:$/.test(location.protocol)) { track.status = "off"; trackBanner(); return; }
    track.status = "loading";
    trackBanner();
    api.list().then(function (res) {
      var apps = {};
      (res.applications || []).forEach(function (a) { if (a && a.job_key) apps[a.job_key] = a; });
      var decisions = {};
      (res.decisions || []).forEach(function (d) { if (d && d.job_key) decisions[d.job_key] = d.label; });
      var overrides = {};
      (res.skill_overrides || []).forEach(function (o) { if (o && o.skill) overrides[o.skill] = true; });
      track.overrides = overrides;
      track.apps = apps;
      track.confirmed = Object.assign({}, apps);
      track.decisions = decisions;
      track.status = "ready";
      trackBanner();
      renderJobs();
      renderToday();
    }).catch(function () {
      track.status = "error";
      trackBanner();
      renderJobs();
      renderToday();
    });
  }

  byId("track-retry").addEventListener("click", loadTracking);

  function fieldId(prefix, j, name) {
    return "t-" + prefix + "-" + j.id + "-" + name;
  }

  /* The tracking block at the top of a job's details: status, dates, CV link, note and the
     verdict buttons. Saves as soon as a field changes (the note after a pause); the page
     updates first and goes back to the stored values if the API refuses. */
  function trackForm(j, prefix) {
    var box = el("div", { class: "track" });
    if (!j.key) return box;
    if (track.status !== "ready") {
      box.appendChild(el("p", { class: "track-off", text: track.status === "loading"
        ? "Loading tracking…" : "Tracking unavailable: nothing can be saved from this page." }));
      return box;
    }
    var rec = T.blank(track.apps[j.key]);
    var controls = {};
    var errors = {};

    function field(name, label, control, extra) {
      control.id = fieldId(prefix, j, name);
      control.name = name;
      controls[name] = control;
      var err = el("span", { class: "field-error", id: control.id + "-err", "aria-live": "polite" });
      errors[name] = err;
      control.setAttribute("aria-describedby", err.id);
      return el("div", { class: "field track-" + name }, [
        el("label", { class: "field-label", for: control.id, text: label }), control, extra || null, err
      ]);
    }

    var status = el("select");
    T.STATUSES.forEach(function (s) { status.appendChild(el("option", { value: s, text: T.STATUS_TEXT[s] })); });
    var applied = el("input", { type: "date", autocomplete: "off" });
    var follow = el("input", { type: "date", autocomplete: "off" });
    var cv = el("input", { type: "url", inputmode: "url", autocomplete: "off", spellcheck: "false", placeholder: "https://…" });
    var cvOpen = el("a", { class: "cv-open", target: "_blank", rel: "noopener noreferrer", text: "Open" });
    var note = el("textarea", { rows: "3", maxlength: String(T.NOTE_MAX), placeholder: "Contact, salary, next step…" });
    var counter = el("span", { class: "note-count", "aria-hidden": "true" });

    var grid = el("div", { class: "track-grid" }, [
      field("status", "Status", status),
      field("applied_at", "Applied on", applied),
      field("follow_up_at", "Follow up on", follow),
      field("cv_url", "CV sent", cv, cvOpen),
      field("note", "Note", note, counter)
    ]);
    box.appendChild(grid);

    var verdicts = el("div", { class: "verdicts", role: "group", "aria-label": "Ton avis sur cette offre" });
    var verdictButtons = {};
    T.LABELS.forEach(function (label) {
      var b = el("button", { type: "button", class: "verdict", "aria-pressed": "false", text: T.LABEL_TEXT[label] });
      verdictButtons[label] = b;
      b.addEventListener("click", function () { decide(label); });
      verdicts.appendChild(b);
    });
    var saveState = el("span", { class: "save-state", role: "status" });
    var retry = el("button", { type: "button", class: "btn btn-retry", text: "Retry", hidden: true });
    box.appendChild(el("div", { class: "track-foot" }, [saveState, retry]));
    /* The verdicts live in the "Pourquoi cette offre ?" panel, next to the reasons they
       judge; detailsFor places this block there. */
    var vState = el("span", { class: "save-state", role: "status" });
    var vRetry = el("button", { type: "button", class: "btn btn-retry", text: "Retry", hidden: true });
    var verdictBlock = el("div", { class: "verdict-block" }, [verdicts, vState, vRetry]);
    box.verdictBlock = verdictBlock;

    function fill(r) {
      status.value = r.status;
      applied.value = r.applied_at;
      follow.value = r.follow_up_at;
      cv.value = r.cv_url;
      note.value = r.note;
      syncExtras();
    }

    function syncExtras() {
      var ok = T.isHttpsUrl(cv.value);
      cvOpen.hidden = !ok;
      if (ok) cvOpen.setAttribute("href", cv.value); else cvOpen.removeAttribute("href");
      counter.textContent = note.value.length > T.NOTE_MAX - 200 ? note.value.length + " / " + T.NOTE_MAX : "";
      var current = track.decisions[j.key];
      T.LABELS.forEach(function (label) {
        verdictButtons[label].setAttribute("aria-pressed", current === label ? "true" : "false");
      });
    }

    function read() {
      return {
        status: status.value,
        applied_at: applied.value,
        follow_up_at: follow.value,
        note: note.value,
        cv_url: cv.value.trim()
      };
    }

    function setState(kind, text, onRetry) {
      box.setAttribute("data-state", kind);
      saveState.textContent = text;
      retry.hidden = !onRetry;
      retry.onclick = onRetry || null;
    }

    function showErrors(errs) {
      Object.keys(errors).forEach(function (name) {
        errors[name].textContent = errs[name] || "";
        if (errs[name]) controls[name].setAttribute("aria-invalid", "true");
        else controls[name].removeAttribute("aria-invalid");
      });
    }

    function send(next) {
      var key = j.key;
      var seq = (track.seq[key] || 0) + 1;
      track.seq[key] = seq;
      track.apps[key] = Object.assign({ job_key: key }, track.apps[key] || {}, next);
      refreshBadges(key);
      setState("saving", "Saving…");
      track.pending += 1;
      api.save(key, next).finally(function () { track.pending -= 1; }).then(function (res) {
        if (track.seq[key] !== seq) return;          /* a later edit is in flight */
        track.apps[key] = track.confirmed[key] = res.application;
        refreshBadges(key);
        setState("saved", "Saved");
      }).catch(function (err) {
        if (track.seq[key] !== seq) return;
        var prev = track.confirmed[key];
        if (prev) track.apps[key] = prev; else delete track.apps[key];
        refreshBadges(key);
        fill(T.blank(prev));
        setState("error", "Not saved (" + failureText(err) + "). The fields show the last saved values.", function () {
          fill(next);
          send(next);
        });
      });
    }

    function commit() {
      var next = read();
      var errs = T.validateRecord(next);
      showErrors(errs);
      if (Object.keys(errs).length) {
        setState("error", "Fix the highlighted field; nothing was saved.");
        return;
      }
      send(next);
    }

    function setVerdictState(kind, text, onRetry) {
      verdictBlock.setAttribute("data-state", kind);
      vState.textContent = text;
      vRetry.hidden = !onRetry;
      vRetry.onclick = onRetry || null;
    }

    /* The score goes with the verdict: `job-match calibrate` compares the two later. */
    function decide(label) {
      var key = j.key;
      var before = track.decisions[key];
      track.decisions[key] = label;
      syncExtras();
      setVerdictState("saving", "Saving verdict…");
      api.decide(key, label, typeof j.score === "number" ? j.score : null).then(function () {
        setVerdictState("saved", "Verdict saved");
      }).catch(function (err) {
        if (before) track.decisions[key] = before; else delete track.decisions[key];
        syncExtras();
        setVerdictState("error", "Verdict not saved (" + failureText(err) + ").", function () { decide(label); });
      });
    }
    verdictBlock.addEventListener("click", function (ev) { ev.stopPropagation(); });
    verdictBlock.addEventListener("keydown", function (ev) { ev.stopPropagation(); });

    var noteTimer;
    [status, applied, follow, cv].forEach(function (c) { c.addEventListener("change", commit); });
    cv.addEventListener("input", syncExtras);
    note.addEventListener("input", function () {
      syncExtras();
      if (!noteTimer) track.pending += 1;
      clearTimeout(noteTimer);
      noteTimer = setTimeout(flushNote, 800);
    });
    /* Leaving the field saves at once; if the pause already saved it, nothing is resent. */
    note.addEventListener("change", function () { if (noteTimer) flushNote(); });
    function flushNote() {
      if (noteTimer) { clearTimeout(noteTimer); noteTimer = null; track.pending -= 1; }
      commit();
    }
    /* Clicks and keys inside the form must not toggle the row it belongs to. */
    box.addEventListener("click", function (ev) { ev.stopPropagation(); });
    box.addEventListener("keydown", function (ev) { ev.stopPropagation(); });

    fill(rec);
    return box;
  }

  /* ---------- "Pourquoi cette offre ?" ---------- */

  var BASIS_TEXT = {
    explicit: "chiffre explicite",
    seniority: "mot-clé de séniorité",
    unknown: "inconnu",
    not_mentioned: "non mentionné"
  };

  function weightText(w) {
    return typeof w === "number" ? (w > 0 ? "+" + w : String(w)) : null;
  }

  /* One skill: its pill, its weight, then the sentence of the offer it was found in. */
  function evidenceItem(cls, name, weight, snippet, control) {
    var head = el("div", { class: "why-head" }, [
      el("span", { class: "tag " + cls, text: name }),
      weight === null ? null : el("span", { class: "why-weight", text: weight }),
      control || null
    ]);
    return el("li", { class: "why-item" }, [head, snippet ? el("q", { class: "evidence", text: snippet }) : null]);
  }

  /* "je maîtrise": saved in D1, merged into the profile on the next run. Optimistic, like the
     other writes; every control for the same skill on screen follows the change. */
  function overrideControl(skill) {
    if (track.status !== "ready" || !api) return null;
    var wrap = el("span", { class: "override" });
    var add = el("button", { type: "button", class: "btn btn-override", text: "je maîtrise" });
    var done = el("span", { class: "override-done", text: "Ajouté — compté au prochain run" });
    var undo = el("button", { type: "button", class: "link-btn", text: "Annuler" });
    var state = el("span", { class: "override-state", role: "status" });
    var retry = el("button", { type: "button", class: "btn btn-retry", text: "Retry", hidden: true });
    [add, done, undo, state, retry].forEach(function (n) { wrap.appendChild(n); });

    function sync() {
      var on = !!track.overrides[skill];
      add.hidden = on;
      done.hidden = !on;
      undo.hidden = !on;
    }
    (overrideViews[skill] = overrideViews[skill] || []).push({ node: wrap, sync: sync });
    function syncAll() {
      overrideViews[skill] = overrideViews[skill].filter(function (v) { return v.node === wrap || document.contains(v.node); });
      overrideViews[skill].forEach(function (v) { v.sync(); });
    }

    function set(on) {
      var before = !!track.overrides[skill];
      if (on) track.overrides[skill] = true; else delete track.overrides[skill];
      syncAll();
      wrap.setAttribute("data-state", "saving");
      state.textContent = "Saving…";
      retry.hidden = true;
      track.pending += 1;
      api.overrideSkill(skill, on).finally(function () { track.pending -= 1; }).then(function () {
        wrap.setAttribute("data-state", "saved");
        state.textContent = "";
      }).catch(function (err) {
        if (before) track.overrides[skill] = true; else delete track.overrides[skill];
        syncAll();
        wrap.setAttribute("data-state", "error");
        state.textContent = "Not saved (" + failureText(err) + ").";
        retry.hidden = false;
        retry.onclick = function () { set(on); };
      });
    }
    add.addEventListener("click", function () { set(true); });
    undo.addEventListener("click", function () { set(false); });
    sync();
    return wrap;
  }

  function experienceBody(e) {
    if (!e) return [el("p", { class: "note", text: "Aucune analyse stockée pour cette offre." })];
    var years = fmtYears(e.required_years);
    var text = years === null
      ? (e.basis === "explicit" ? "Pas de minimum chiffré" : "Années requises inconnues")
      : years === "0" ? "Aucune année exigée"
        : years + (years === "1" ? " an requis" : " ans requis");
    var basis = e.basis && BASIS_TEXT[e.basis] ? e.basis : "none";
    var out = [el("div", { class: "why-head" }, [
      el("span", { class: "why-years", text: text }),
      el("span", { class: "confidence confidence-" + basis, text: basis === "none" ? "non recalculé" : BASIS_TEXT[basis] })
    ])];
    if (e.sentence) out.push(el("q", { class: "evidence", text: e.sentence }));
    if (e.excludes_apprenticeship) out.push(el("span", { class: "tag tag-flag", text: "hors stage et alternance" }));
    return out;
  }

  function whyPanel(j, verdictBlock) {
    var w = j.why || { skills: [], unlisted: [], lowered: [], experience: null };
    var panel = el("section", { class: "why", "aria-label": "Pourquoi cette offre ?" });
    panel.appendChild(el("h3", { class: "why-title", text: "Pourquoi cette offre ?" }));
    var grid = el("div", { class: "why-grid" });
    /* Skills on the left; the shorter blocks stack on the right; the verdict spans both. */
    var left = el("div", { class: "why-col" });
    var right = el("div", { class: "why-col" });
    var target = left;
    function block(name, title, body) {
      target.appendChild(el("div", { class: "why-block why-" + name }, [el("h4", { text: title })].concat(body)));
    }
    function list(items) { return el("ul", { class: "why-list" }, items); }

    var skills = [w.skills.length
      ? list(w.skills.map(function (s) { return evidenceItem("tag-pos", s.name, weightText(s.weight), s.snippet); }))
      : el("p", { class: "note", text: "Aucune compétence de ton profil trouvée dans l’offre." })];
    if (j.missing && j.missing.length) {
      skills.push(el("div", { class: "why-aside" }, [
        el("span", { text: "Absentes de l’offre, sans effet sur le score :" }),
        el("span", { class: "tags" }, j.missing.map(function (t) { return el("span", { class: "tag tag-miss", text: t }); }))
      ]));
    }
    block("skills", "Compétences détectées", skills);
    target = right;

    block("unlisted", "Non trouvé dans ton profil", [w.unlisted.length
      ? list(w.unlisted.map(function (u) { return evidenceItem("tag-miss", u.name, null, u.snippet, overrideControl(u.name)); }))
      : el("p", { class: "note", text: "L’offre ne cite pas d’autre compétence connue." })]);

    block("experience", "Expérience", experienceBody(w.experience));

    block("lowered", "Ce qui a baissé le score", [w.lowered.length
      ? list(w.lowered.map(function (s) { return evidenceItem("tag-neg", s.name, weightText(s.weight), s.snippet); }))
      : el("p", { class: "note", text: "Rien n’a baissé le score." })]);

    grid.appendChild(left);
    grid.appendChild(right);
    target = grid;
    block("verdict", "Ton avis", [verdictBlock ||
      el("p", { class: "note", text: "Les avis s’enregistrent depuis le tableau de bord hébergé." })]);

    panel.appendChild(grid);
    /* Clicks inside the panel (buttons, folded explanations) must not toggle the row. */
    panel.addEventListener("click", function (ev) { ev.stopPropagation(); });
    panel.addEventListener("keydown", function (ev) { ev.stopPropagation(); });
    return panel;
  }

  function detailsFor(j, prefix, colspan) {
    var td = el("td", { colspan: String(colspan) });
    var box = el("div", { class: "details" });
    var form = trackForm(j, prefix);
    box.appendChild(form);
    var meta = [];
    if (j.location) meta.push(j.location);
    if (j.source) meta.push("source: " + j.source);
    if (!j.published_at) meta.push("no posting date from the source");
    if (j.posted_at) meta.push("posted " + fmtDate(j.posted_at));
    if (j.collected_at) meta.push("collected " + fmtDate(j.collected_at));
    var stretchLine = null;
    var others = [];
    (j.explanations || []).forEach(function (line) {
      if (line.indexOf("stretch:") === 0 && !stretchLine) stretchLine = line;
      else others.push(line);
    });
    box.appendChild(el("p", { class: "meta", text: meta.join(" · ") }));
    if (stretchLine) box.appendChild(el("p", { class: "stretch-note", text: stretchLine }));

    var panel = whyPanel(j, form.verdictBlock || null);
    if (others.length) {
      panel.appendChild(el("details", { class: "explain-all" }, [
        el("summary", { text: "Toutes les explications (" + others.length + ")" }),
        el("ul", null, others.map(function (t) { return el("li", { text: t }); }))
      ]));
    }
    box.appendChild(panel);
    td.appendChild(box);
    return el("tr", { class: "details", id: prefix + "-details-" + j.id }, td);
  }

  /* Cell builders shared by the Jobs table and the Aujourd'hui queue. */
  var COLUMNS = {
    title: function (j, prefix, expanded) {
      return cell("col-title", "Title", el("button", {
        type: "button", class: "expand", "aria-expanded": expanded ? "true" : "false",
        "aria-controls": prefix + "-details-" + j.id
      }, [el("span", { class: "dot dot-" + j.section, "aria-hidden": "true" }), el("span", { class: "title-text", text: j.title || "—", title: j.title || null })]));
    },
    company: function (j) {
      var td = cell("col-company", "Company", j.company || "—");
      if (j.company) td.title = j.company;
      return td;
    },
    department: function (j) { return cell("col-dept", "Dept", j.department || "?"); },
    contract: function (j) { return cell("col-contract", "Contract", j.contract || "UNKNOWN"); },
    score: function (j) { return cell("num col-score", "Score", scoreCell(j)); },
    required_years: function (j) {
      var years = fmtYears(j.required_years);
      return cell("num col-years", "Years", el("span", { class: years === null ? "unknown years" : "years", text: years === null ? "—" : years + "y" }));
    },
    status: function (j) { return cell("col-status", "Status", statusBadge(j.key)); },
    posted_at: function (j) { return dateCell("col-date", "Posted", j.posted_at); },
    age_days: function (j) {
      var age = typeof j.age_days === "number" ? j.age_days : null;
      return cell("num col-age", "Age", el("span", { class: age === null ? "unknown" : "", text: age === null ? "—" : age + "d" }));
    },
    link: function (j) { return cell("link-col", "Link", link(j.url, "Open")); }
  };
  var JOB_COLUMNS = ["title", "company", "department", "contract", "score", "required_years", "status", "posted_at", "age_days", "link"];
  var TODAY_COLUMNS = ["title", "company", "department", "score", "status", "posted_at", "link"];

  function jobRows(list, prefix, columns, expandedMap) {
    var frag = document.createDocumentFragment();
    list.forEach(function (j) {
      var open = !!expandedMap[j.id];
      var row = el("tr", { class: "row row-" + j.section, tabindex: "0", "aria-expanded": open ? "true" : "false" });
      columns.forEach(function (c) { row.appendChild(COLUMNS[c](j, prefix, open)); });
      function toggle() {
        var now = !expandedMap[j.id];
        expandedMap[j.id] = now;
        row.setAttribute("aria-expanded", now ? "true" : "false");
        row.querySelector(".expand").setAttribute("aria-expanded", now ? "true" : "false");
        var existing = byId(prefix + "-details-" + j.id);
        if (now && !existing) row.parentNode.insertBefore(detailsFor(j, prefix, columns.length), row.nextSibling);
        if (!now && existing) existing.parentNode.removeChild(existing);
      }
      row.addEventListener("click", function (ev) {
        if (ev.target.closest("a")) return;
        toggle();
      });
      row.addEventListener("keydown", function (ev) {
        if (ev.target !== row) return;
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); }
      });
      frag.appendChild(row);
      if (open) frag.appendChild(detailsFor(j, prefix, columns.length));
    });
    return frag;
  }

  function dropBadges(root) {
    /* Badges inside a table about to be cleared stop being updated. */
    Object.keys(badges).forEach(function (k) {
      badges[k] = badges[k].filter(function (b) { return !root.contains(b); });
    });
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

    dropBadges(jobsBody);
    clear(jobsBody);
    byId("jobs-empty").hidden = shown.length > 0;
    jobsBody.appendChild(jobRows(shown, "jobs", JOB_COLUMNS, state.expanded));
  }

  /* ---------- aujourd'hui ---------- */

  function updateTodayCounts() {
    var items = T.todayItems(jobs, track.apps, T.localDay());
    var toApply = items.queue.filter(function (j) { return statusOfJob(j) === "to_apply"; }).length;
    byId("kpi-today-apply").textContent = toApply;
    byId("kpi-today-review").textContent = items.queue.length - toApply;
    byId("kpi-today-due").textContent = items.followups.length;
    byId("count-today").textContent = items.queue.length + items.followups.length;
  }

  function followupRow(f) {
    var j = f.job;
    var row = el("tr", { class: "row row-followup" + (j ? " row-" + j.section : "") });
    var title = j
      ? el("span", { class: "followup-title" }, [el("span", { class: "dot dot-" + j.section, "aria-hidden": "true" }), el("span", { class: "title-text", text: j.title || "—" })])
      : el("span", { class: "unknown", text: f.key + " · offer no longer listed" });
    var titleCell = cell("col-title", "Title", title);
    if (j && j.title) titleCell.title = j.title;
    row.appendChild(titleCell);
    row.appendChild(cell("col-company", "Company", j ? (j.company || "—") : "—"));
    row.appendChild(cell("col-status", "Status", statusBadge(f.key)));
    var due = el("span", { class: "due" + (f.late > 0 ? " due-late" : "") }, [
      fmtShortDate(f.app.follow_up_at), el("span", { class: "due-late-text", text: f.late > 0 ? " · " + f.late + "d late" : " · today" })
    ]);
    row.appendChild(cell("col-due", "Follow up", due));
    row.appendChild(cell("link-col", "Link", j ? link(j.url, "Open") : el("span", { class: "unknown", text: "—" })));
    if (j) {
      /* Opens the job in the queue below or, when it has left the queue, in Jobs. */
      row.setAttribute("tabindex", "0");
      var go = function () { openInJobs(j); };
      row.addEventListener("click", function (ev) { if (!ev.target.closest("a")) go(); });
      row.addEventListener("keydown", function (ev) {
        if (ev.target === row && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); go(); }
      });
    }
    return row;
  }

  function openInJobs(j) {
    state.q = (j.title || "").toLowerCase();
    searchInput.value = j.title || "";
    state.status = ""; statusSelect.value = "";
    state.expanded[j.id] = true;
    renderJobs();
    showTab("jobs", false);
    var row = byId("jobs-details-" + j.id);
    if (row) row.scrollIntoView({ block: "center" });
  }

  function renderToday() {
    var today = T.localDay();
    var items = T.todayItems(jobs, track.apps, today);
    updateTodayCounts();

    var fBody = byId("today-followups-body");
    dropBadges(fBody);
    clear(fBody);
    byId("today-followups").hidden = items.followups.length === 0;
    items.followups.forEach(function (f) { fBody.appendChild(followupRow(f)); });

    var qBody = byId("today-body");
    dropBadges(qBody);
    clear(qBody);
    byId("today-empty").hidden = items.queue.length > 0;
    byId("today-rowcount").textContent = items.queue.length + " jobs to review or apply to · “To apply” first, then by score";
    qBody.appendChild(jobRows(items.queue, "today", TODAY_COLUMNS, todayExpanded));
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

  statusSelect.addEventListener("change", function () {
    state.status = statusSelect.value;
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
    state.status = ""; statusSelect.value = "";
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

  var SORT_KEYS = ["title", "company", "department", "contract", "score", "required_years", "status", "posted_at", "age_days"];
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
    state.status = T.STATUSES.indexOf(p.st) >= 0 ? p.st : "";
    statusSelect.value = state.status;
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
  fillStatuses();
  renderLeads();
  renderRuns();
  if (window.innerWidth <= 768) byId("jobs-controls").removeAttribute("open");
  applyHash();
  loadTracking();
})();
