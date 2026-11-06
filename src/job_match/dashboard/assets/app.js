/* job-match dashboard core: the data, the shared helpers, the theme, the views and the hash,
   the tracking state and its form, the toast and the optimistic save, the record panel, the
   palette commands and the global keys. The screens live in list.js, why.js, tri.js, board.js,
   leads.js and runs.js; dashboard.js boots them. Everything from the data lands in the DOM
   through textContent or an attribute set on an element we created: nothing from the database
   is ever parsed as HTML. */
window.JM = window.JM || {};
(function (JM) {
  "use strict";

  /* From the other files (app.js first; the screens after it): values are read once,
     functions through the namespace at call time, so the load order never matters. */
  var applyHash = function () { return JM.applyHash.apply(null, arguments); };
  var listKeys = function () { return JM.listKeys.apply(null, arguments); };
  var canTriage = function () { return JM.canTriage.apply(null, arguments); };
  var documentsBlock = function () { return JM.documentsBlock.apply(null, arguments); };
  var dueKeys = function () { return JM.dueKeys.apply(null, arguments); };
  var ensureSelection = function () { return JM.ensureSelection.apply(null, arguments); };
  var markSelected = function () { return JM.markSelected.apply(null, arguments); };
  var recordActions = function () { return JM.recordActions.apply(null, arguments); };
  var listedCount = function () { return JM.listedCount.apply(null, arguments); };
  var sourceText = function () { return JM.sourceText.apply(null, arguments); };
  var flushRetry = function () { return JM.flushRetry.apply(null, arguments); };
  var focusTriCard = function () { return JM.focusTriCard.apply(null, arguments); };
  var overlayPending = function () { return JM.overlayPending.apply(null, arguments); };
  var postingsBlock = function () { return JM.postingsBlock.apply(null, arguments); };
  var preloadRenderer = function () { return JM.preloadRenderer.apply(null, arguments); };
  var renderAiRuns = function () { return JM.renderAiRuns.apply(null, arguments); };
  var renderApps = function () { return JM.renderApps.apply(null, arguments); };
  var renderJobs = function () { return JM.renderJobs.apply(null, arguments); };
  var renderPending = function () { return JM.renderPending.apply(null, arguments); };
  var renderTri = function () { return JM.renderTri.apply(null, arguments); };
  var setRecord = function () { return JM.setRecord.apply(null, arguments); };
  var triKeys = function () { return JM.triKeys.apply(null, arguments); };
  var undoLast = function () { return JM.undoLast.apply(null, arguments); };
  var whyPanel = function () { return JM.whyPanel.apply(null, arguments); };

  var SECTIONS = ["strong", "eligible", "stretch"];
  var TABS = ["tri", "candidatures", "offres", "leads", "executions"];
  /* Hashes from before M23 still open the right view. */
  var TAB_ALIASES = { today: "tri", jobs: "offres", runs: "executions" };
  var HTTP = /^https?:\/\//i;
  var T = window.JMTracking;

  var raw = document.getElementById("data");
  var data;
  try {
    data = JSON.parse(raw.textContent);
  } catch (err) {
    document.getElementById("main").textContent = "Les données intégrées sont illisibles.";
    return;
  }
  var jobs = data.jobs || [];
  var tracked = data.tracked || [];
  var rows = T.groupJobs(jobs);
  var SORT_TEXT = {
    title: "titre", company: "entreprise", department: "département", contract: "contrat",
    score: "score", required_years: "années", status: "statut", posted_at: "publication",
    age_days: "âge", source: "source"
  };
  var leads = data.leads || [];
  var runs = data.runs || [];
  var thresholds = data.thresholds || { strong: 70, min_score: 60 };

  /* ---------- small DOM helpers (ui.js) ---------- */

  var U = window.JMUI;
  var S = window.JMScore;
  var D = window.JMDesc;
  var P = window.JMPalette;
  var el = U.el;
  var clear = U.clear;

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
    return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
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
    return d.toLocaleString("fr-FR", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
      timeZone: "UTC", timeZoneName: "short"
    });
  }

  function fmtYears(y) {
    if (y === null || y === undefined) return null;
    return Number.isInteger(y) ? String(y) : String(y);
  }

  var YEARS_NUM = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
  /* The triage card's experience fact: "3 ans requis", "1,5 an requis" (French: singular
     below 2), or that the posting states no number. */
  function yearsText(y) {
    if (typeof y !== "number" || !isFinite(y)) return "Années non précisées";
    if (y === 0) return "Aucune année exigée";
    return YEARS_NUM.format(y) + (y < 2 ? " an" : " ans") + " requis";
  }

  function fmtAmount(amount, currency) {
    if (amount === null || amount === undefined) return null;
    var unit = "";
    var n = amount;
    if (n >= 1e9) { n = n / 1e9; unit = " Md"; }
    else if (n >= 1e6) { n = n / 1e6; unit = " M"; }
    else if (n >= 1e3) { n = n / 1e3; unit = " k"; }
    var s = (Math.round(n * 10) / 10).toString();
    var cur = currency === "EUR" ? "€" : currency === "USD" ? "$" : currency === "GBP" ? "£" : (currency || "");
    return s + unit + (cur ? (cur.length === 1 ? cur : " " + cur) : "");
  }

  function cell(cls, label, child) {
    var td = el("td", { class: cls, "data-label": label });
    if (child !== undefined && child !== null) {
      if (typeof child === "string") td.textContent = child;
      else td.appendChild(child);
    }
    return td;
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

  /* The system setting by default, the toggle remembered; theme-color follows the applied theme. */
  var DARK_ONLY = false;
  var THEME_COLOR = { dark: "#111113", light: "#fcfcfd" };

  function applyTheme(theme, persist) {
    if (DARK_ONLY) theme = "dark";
    document.documentElement.setAttribute("data-theme", theme);
    themeBtn.textContent = theme === "dark" ? "Mode clair" : "Mode sombre";
    themeBtn.setAttribute("aria-pressed", theme === "light" ? "true" : "false");
    byId("theme-color").setAttribute("content", THEME_COLOR[theme]);
    if (persist) {
      try { localStorage.setItem("job-match-theme", theme); } catch (e) { /* private window */ }
    }
  }

  applyTheme(storedTheme() === "light" || storedTheme() === "dark" ? storedTheme() : systemTheme(), false);
  themeBtn.hidden = DARK_ONLY;
  themeBtn.addEventListener("click", function () {
    applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
  });

  /* ---------- views: sidebar, tab bar, View Transitions ---------- */

  var navLinks = Array.prototype.slice.call(document.querySelectorAll("[data-tab]"));
  navLinks.forEach(function (a) {
    var icon = a.getAttribute("data-icon");
    if (icon) a.insertBefore(U.icon(icon), a.firstChild);
    /* A plain click keeps the Offres filters (they live in the hash); modifier and middle
       clicks open the view in a new tab as any link does. */
    a.addEventListener("click", function (ev) {
      if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      ev.preventDefault();
      showTab(a.getAttribute("data-tab"), false, true);
    });
  });

  /* `animate`: a View Transition from the current view (user navigation only). */
  function showTab(name, focus, animate) {
    if (TABS.indexOf(name) < 0) name = "tri";
    var entering = name !== V.tab;
    function swap() {
      navLinks.forEach(function (a) {
        if (a.getAttribute("data-tab") === name) a.setAttribute("aria-current", "page");
        else a.removeAttribute("aria-current");
      });
      TABS.forEach(function (t) { byId("panel-" + t).hidden = t !== name; });
      V.tab = name;
      byId("crumb-view").textContent = VIEW_TITLE[name];
      if (entering) {
        if (R.open && R.tab !== name) closeRecord(false);
        if (name === "candidatures") preloadRenderer();
        renderCurrent();
        byId("panel-" + name).scrollTop = 0;
      }
      syncHash();
      document.title = VIEW_TITLE[name] + " · job-match";
    }
    if (animate && entering && V.tab) U.transition(swap, ["view"]).then(afterEnter); else { swap(); if (entering) afterEnter(); }
    function afterEnter() {
      /* Tri opened with the pointer: the card takes focus so ← → decide at once (AUDIT P2-9). */
      if (name === "tri") focusTriCard();
      else if (focus) byId("main").focus({ preventScroll: true });
    }
  }
  var VIEW_TITLE = { tri: "Tri", candidatures: "Candidatures", offres: "Offres", leads: "Leads", executions: "Exécutions" };

  /* Shared, reassigned across files: the current view and the hash guard. */
  var V = JM.v = { tab: "", applyingHash: false, appsView: "kanban" };

  /* The hash carries the tab and the Offres filters (#offres?q=...&hide=...), whatever the
     tab: switching to Tri and back, or reloading, keeps them. Every value is validated before
     it touches the state. */
  var FILTERS_KEY = "jm.offres.v1";
  function syncHash() {
    if (V.applyingHash) return;
    var parts = [];
    {
      if (JM.state.q) parts.push("q=" + encodeURIComponent(JM.state.q));
      var off = SECTIONS.filter(function (s) { return !JM.state.sections[s]; });
      if (off.length) parts.push("hide=" + off.join(","));
      if (JM.state.department) parts.push("dept=" + encodeURIComponent(JM.state.department));
      if (JM.state.source) parts.push("src=" + encodeURIComponent(JM.state.source));
      if (JM.state.status) parts.push("st=" + JM.state.status);
      if (JM.state.ai) parts.push("ia=" + JM.state.ai);
      if (V.tab === "candidatures" && V.appsView === "table") parts.push("view=table");
      if (JM.state.minScore) parts.push("min=" + JM.state.minScore);
      if (JM.state.from) parts.push("from=" + JM.state.from);
      if (JM.state.to) parts.push("to=" + JM.state.to);
      if (JM.state.sortKey !== "score" || JM.state.sortDir !== "desc") parts.push("sort=" + JM.state.sortKey + ":" + JM.state.sortDir);
      /* The Offres filters and sort outlive the tab (list.js reads them back on a bare hash). */
      try { localStorage.setItem(FILTERS_KEY, parts.join("&")); } catch (e) { /* private window */ }
      /* The open record, so a link or a reload shows the same offer. */
      /* Not in Tri: a record there opens only on a click or Enter, never from a reload. */
      if (V.tab !== "tri" && typeof R.open !== "undefined" && R.open && R.job && R.job.key) parts.push("fiche=" + encodeURIComponent(R.job.key));
    }
    var next = "#" + V.tab + (parts.length ? "?" + parts.join("&") : "");
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
    tab = TAB_ALIASES[tab] || tab;
    return { tab: TABS.indexOf(tab) >= 0 ? tab : "tri", params: params };
  }

  window.addEventListener("hashchange", function () {
    applyHash();
  });

  /* ---------- tracking (D1 through /api/) ---------- */

  /* status: "off" (file:// or no fetch), "loading", "ready", "error". `apps` is what the page
     shows (optimistic), `confirmed` what the API last stored; a failed save goes back to it. */
  var track = { status: "off", apps: {}, confirmed: {}, decisions: {}, overrides: {}, ai: {}, aiRuns: [], documents: {}, budget: null, inbox: { to_confirm: [], history: [] }, seq: {}, pending: 0 };

  /* Candidatures as a Kanban or as a table (ADR 0017 part 4): remembered per browser, and in
     the hash (#candidatures?view=table) so a link opens the same view. */
  try { if (localStorage.getItem("jm.appsView") === "table") V.appsView = "table"; } catch (e) { /* private mode */ }
  function setAppsView(v, silent) {
    V.appsView = v === "table" ? "table" : "kanban";
    try { localStorage.setItem("jm.appsView", V.appsView); } catch (e) { /* private mode */ }
    ["kanban", "table"].forEach(function (x) {
      var b = byId("apps-view-" + x);
      if (b) b.setAttribute("aria-pressed", String(x === V.appsView));
    });
    if (!silent && V.tab === "candidatures") { renderApps(); syncHash(); }
  }
  ["kanban", "table"].forEach(function (v) {
    var b = byId("apps-view-" + v);
    if (b) b.addEventListener("click", function () { setAppsView(v); });
  });
  setAppsView(V.appsView, true);  /* the chips follow the remembered view, not the markup */
  /* skill -> functions redrawing every "je maîtrise" control for it on screen */
  var overrideViews = {};

  /* Why a write failed, in words the reader can act on. */
  function failureText(err) {
    if (err && err.status === 401) return "ta session Access a expiré, recharge la page";
    if (err && err.status >= 500) return "le serveur a échoué";
    return (err && err.message) || "erreur réseau";
  }

  /* A note typed in the last moment, or a save still in flight, is not stored yet. */
  window.addEventListener("beforeunload", function (ev) {
    if (track.pending > 0 || (JM.retry && JM.retry.size() > 0)) { ev.preventDefault(); ev.returnValue = ""; }
  });
  /* posting key -> status badges on screen ({node, row}); a grouped row's badge is listed
     under every posting key, so a save on any of them updates it. */
  var badges = {};
  var api = (typeof window.fetch === "function") ? T.client(window.fetch.bind(window)) : null;

  function statusOfJob(j) {
    return T.rowStatus(j, track.apps);
  }

  function statusBadge(row) {
    var s = T.rowStatus(row, track.apps);
    var b = el("span", { class: "status status-" + s, text: T.STATUS_TEXT[s] });
    T.postingsOf(row).forEach(function (p) {
      (badges[p.key] = badges[p.key] || []).push({ node: b, row: row });
    });
    return b;
  }

  function refreshBadges(key) {
    (badges[key] || []).forEach(function (entry) {
      var s = T.rowStatus(entry.row, track.apps);
      entry.node.className = "status status-" + s;
      entry.node.textContent = T.STATUS_TEXT[s];
    });
    if (R.open && R.job && T.postingsOf(R.job).some(function (p) { return p.key === key; })) refreshRecordFoot();
    updateCounts();
  }

  function trackBanner() {
    var banner = byId("track-banner");
    var msg = byId("track-banner-text");
    var retry = byId("track-retry");
    if (track.status === "ready" || track.status === "loading") { banner.hidden = true; return; }
    banner.hidden = false;
    msg.textContent = track.status === "off"
      ? "Le suivi est indisponible dans une page ouverte depuis un fichier. Les statuts et les notes demandent le tableau de bord hébergé."
      : "Le suivi n’a pas pu être chargé : les statuts s’affichent « À examiner » et rien ne peut être enregistré.";
    retry.hidden = track.status !== "error";
  }

  /* « Lancer maintenant » (Exécutions): hosted page only, one click starts one pass. */
  var RUN_NOW = {
    "ai-run-now": { call: function () { return api.runAi(); }, text: "Rerank IA lancé · le résultat s’affiche ici dans une minute" },
    "docs-run-now": { call: function () { return api.runDocuments(); }, text: "Génération des documents lancée · l’état est dans la fiche de chaque offre" }
  };
  function runNowButtons() {
    Object.keys(RUN_NOW).forEach(function (id) { var b = byId(id); if (b) b.disabled = track.status !== "ready"; });
  }
  Object.keys(RUN_NOW).forEach(function (id) {
    var b = byId(id);
    if (!b) return;
    b.addEventListener("click", function () {
      if (!api || track.status !== "ready") return;
      b.disabled = true;
      RUN_NOW[id].call().then(function () {
        showToast(RUN_NOW[id].text, [{ text: "Actualiser", run: function () { loadTracking(); } }]);
      }).catch(function (err) {
        showToast("Non lancé (" + failureText(err) + ")");
      }).then(function () { setTimeout(function () { b.disabled = track.status !== "ready"; }, 3000); });
    });
  });

  function loadTracking() {
    if (!api || !/^https?:$/.test(location.protocol)) { track.status = "off"; trackBanner(); return; }
    track.status = "loading";
    trackBanner();
    renderCurrent();  /* Tri and Candidatures say they are loading, buttons off */
    api.list().then(function (res) {
      var apps = {};
      (res.applications || []).forEach(function (a) { if (a && a.job_key) apps[a.job_key] = a; });
      var decisions = {};
      (res.decisions || []).forEach(function (d) { if (d && d.job_key) decisions[d.job_key] = d.label; });
      var overrides = {};
      (res.skill_overrides || []).forEach(function (o) { if (o && o.skill) overrides[o.skill] = true; });
      /* The AI verdicts (ADR 0016), one per key; triage.aiOf drops the ones whose hash is stale. */
      var ai = {};
      (res.ai_verdicts || []).forEach(function (v) { if (v && typeof v.job_key === "string") ai[v.job_key] = v; });
      track.ai = ai;
      track.aiRuns = Array.isArray(res.ai_runs) ? res.ai_runs.filter(function (r) { return r && typeof r === "object"; }) : [];
      /* The latest documents version per offer (ADR 0017): status and error code only. */
      var documents = {};
      (res.documents || []).forEach(function (d) { if (d && typeof d.job_key === "string") documents[d.job_key] = d; });
      track.documents = documents;
      track.budget = res.documents_budget && typeof res.documents_budget === "object" ? res.documents_budget : null;
      track.inbox = readInbox(res.inbox);
      renderAiRuns();
      track.overrides = overrides;
      track.apps = apps;
      track.confirmed = Object.assign({}, apps);
      track.decisions = decisions;
      track.status = "ready";
      overlayPending();
      trackBanner();
      JM.tri.built = false;  /* the queue depends on the statuses just loaded */
      renderPending();
      flushRetry();
      runNowButtons();
      renderJobs();
      renderCurrent();
      /* A record opened before the tracking (a #…?fiche= link) has no documents nor kit yet. */
      if (R.open && R.job) openRecord(R.job, R.opener, { quiet: true });
    }).catch(function () {
      track.status = "error";
      trackBanner();
      runNowButtons();
      renderJobs();
      renderCurrent();
    });
  }

  byId("track-retry").addEventListener("click", loadTracking);

  /* The recruiter replies (ADR 0018): the ones waiting for me and the handled ones. */
  function readInbox(raw) {
    var ok = function (it) { return it && typeof it === "object" && typeof it.message_id === "string"; };
    return {
      to_confirm: raw && Array.isArray(raw.to_confirm) ? raw.to_confirm.filter(ok) : [],
      history: raw && Array.isArray(raw.history) ? raw.history.filter(ok) : []
    };
  }

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
        ? "Chargement du suivi…" : "Suivi indisponible : rien ne peut être enregistré depuis cette page." }));
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
    var interview = el("input", { type: "date", autocomplete: "off" });
    var cv = el("input", { type: "url", inputmode: "url", autocomplete: "off", spellcheck: "false", placeholder: "https://…" });
    var cvOpen = el("a", { class: "cv-open", target: "_blank", rel: "noopener noreferrer", text: "Ouvrir" });
    var note = el("textarea", { rows: "3", maxlength: String(T.NOTE_MAX), placeholder: "Contact, salaire, prochaine étape…" });
    var counter = el("span", { class: "note-count", "aria-hidden": "true" });

    var grid = el("div", { class: "track-grid" }, [
      field("status", "Statut", status),
      field("applied_at", "Candidature envoyée le", applied),
      field("follow_up_at", "Relance le", follow),
      field("interview_at", "Entretien le", interview),
      field("cv_url", "CV envoyé", cv, cvOpen),
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
    var retry = el("button", { type: "button", class: "btn btn-retry", text: "Réessayer", hidden: true });
    box.appendChild(el("div", { class: "track-foot" }, [saveState, retry]));
    /* The verdicts live in the "Pourquoi cette offre ?" panel, next to the reasons they
       judge; detailsFor places this block there. */
    var vState = el("span", { class: "save-state", role: "status" });
    var vRetry = el("button", { type: "button", class: "btn btn-retry", text: "Réessayer", hidden: true });
    var verdictBlock = el("div", { class: "verdict-block" }, [verdicts, vState, vRetry]);
    box.verdictBlock = verdictBlock;

    function fill(r) {
      status.value = r.status;
      applied.value = r.applied_at;
      follow.value = r.follow_up_at;
      interview.value = r.interview_at;
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
        interview_at: interview.value,
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
      setState("saving", "Enregistrement…");
      track.pending += 1;
      api.save(key, next).finally(function () { track.pending -= 1; }).then(function (res) {
        if (track.seq[key] !== seq) return;          /* a later edit is in flight */
        track.apps[key] = track.confirmed[key] = res.application;
        refreshBadges(key);
        setState("saved", "Enregistré");
      }).catch(function (err) {
        if (track.seq[key] !== seq) return;
        var prev = track.confirmed[key];
        if (prev) track.apps[key] = prev; else delete track.apps[key];
        refreshBadges(key);
        fill(T.blank(prev));
        setState("error", "Non enregistré (" + failureText(err) + "). Les champs montrent les dernières valeurs enregistrées.", function () {
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
        setState("error", "Corrige le champ signalé : rien n’a été enregistré.");
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
      setVerdictState("saving", "Enregistrement de l’avis…");
      api.decide(key, label, typeof j.score === "number" ? j.score : null).then(function () {
        setVerdictState("saved", "Avis enregistré");
      }).catch(function (err) {
        if (before) track.decisions[key] = before; else delete track.decisions[key];
        syncExtras();
        setVerdictState("error", "Avis non enregistré (" + failureText(err) + ").", function () { decide(label); });
      });
    }
    verdictBlock.addEventListener("click", function (ev) { ev.stopPropagation(); });
    verdictBlock.addEventListener("keydown", function (ev) { ev.stopPropagation(); });

    var noteTimer;
    [status, applied, follow, interview, cv].forEach(function (c) { c.addEventListener("change", commit); });
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

  /* ---------- quick actions and the undo toast ---------- */

  var toast = byId("toast");
  var toastText = byId("toast-text");
  var toastActions = byId("toast-actions");
  var toastTimer = null;
  var toastHeld = false;  /* a question waits for an answer: no auto-hide */
  var toastOnEscape = null;
  var TOAST_MS = 5000;

  var toastLeave = null;
  /* Slides out (DESIGN.md "Motion"); a toast shown meanwhile cancels the exit. */
  function hideToast() {
    clearTimeout(toastTimer);
    toastHeld = false;
    toastOnEscape = null;
    if (toast.hidden) return;
    if (U.reduced()) { toast.hidden = true; return; }
    toast.classList.remove("is-in");
    toast.classList.add("leaving");
    clearTimeout(toastLeave);
    toastLeave = setTimeout(function () { toast.hidden = true; toast.classList.remove("leaving"); }, 160);
  }

  function armToast() {
    clearTimeout(toastTimer);
    if (!toastHeld) toastTimer = setTimeout(hideToast, TOAST_MS);
  }

  function toastButton(a) {
    var b = el("button", { type: a.type || "button", class: "link-btn", text: a.text });
    b.addEventListener("click", function () { if (!a.keep) hideToast(); a.run(); });
    return b;
  }

  /* `actions`: [{text, run, keep}] (keep: the toast stays, for a step inside it).
     opts.hold keeps it until answered, opts.focus moves focus to its first button,
     opts.onEscape runs on Escape. */
  function showToast(text, actions, opts) {
    opts = opts || {};
    toastText.textContent = text;
    clear(toastActions);
    (actions || []).forEach(function (a) { toastActions.appendChild(toastButton(a)); });
    toastActions.hidden = !toastActions.childNodes.length;
    clearTimeout(toastLeave);
    toast.classList.remove("leaving");
    var wasHidden = toast.hidden;
    toast.hidden = false;
    if (wasHidden) {
      toast.classList.remove("is-in");
      void toast.offsetWidth;  /* restart the slide-in */
      toast.classList.add("is-in");
    }
    toastHeld = !!opts.hold;
    toastOnEscape = opts.onEscape || null;
    armToast();
    if (opts.focus && toastActions.firstChild) toastActions.firstChild.focus({ preventScroll: true });
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape" || toast.hidden || !toastOnEscape) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    var run = toastOnEscape;
    hideToast();
    run();
  }, true);

  /* Hovering or focusing the toast holds it: the undo stays reachable. */
  toast.addEventListener("mouseenter", function () { clearTimeout(toastTimer); });
  toast.addEventListener("mouseleave", armToast);
  toast.addEventListener("focusin", function () { clearTimeout(toastTimer); });
  toast.addEventListener("focusout", armToast);

  /* A status save outside the form: the page first, then the API; a refused save brings the
     last stored record back. */
  function saveRecord(key, next) {
    var seq = (track.seq[key] || 0) + 1;
    track.seq[key] = seq;
    track.apps[key] = Object.assign({ job_key: key }, track.apps[key] || {}, next);
    refreshBadges(key);
    track.pending += 1;
    return api.save(key, next).finally(function () { track.pending -= 1; }).then(function (res) {
      if (track.seq[key] !== seq) return;
      track.apps[key] = track.confirmed[key] = res.application;
      refreshBadges(key);
    }, function (err) {
      if (track.seq[key] === seq) {
        var prev = track.confirmed[key];
        if (prev) track.apps[key] = prev; else delete track.apps[key];
        refreshBadges(key);
      }
      throw err;
    });
  }

  function rerenderLists() {
    renderJobs();
    renderCurrent();
  }

  /* changes: [{key, next}]; undo: the records to put back, or null (an undo is not undone). */
  /* `ask`: an optional question in the toast ({text, actions}), shown before "Annuler" and
     held until answered. */
  function applyChanges(changes, done, undo, ask) {
    var saving = Promise.all(changes.map(function (c) { return saveRecord(c.key, c.next); }));
    rerenderLists();
    var actions = ask ? ask.actions.slice() : [];
    if (undo) actions.push({ text: "Annuler", run: function () { applyChanges(undo, "Modification annulée", null); } });
    showToast(ask ? done + ". " + ask.text : done, actions,
      ask ? { hold: true, focus: true, onEscape: ask.onEscape } : null);
    saving.catch(function (err) {
      rerenderLists();
      showToast("Non enregistré (" + failureText(err) + ")",
        [{ text: "Réessayer", run: function () { applyChanges(changes, done, undo, ask); } }]);
    });
  }

  /* ---------- counts in the tab bar ---------- */

  var X = window.JMTriage;
  var runAt = X.latestRunAt(runs);
  var BOARD = X.BOARD;
  var BOARD_TEXT = { to_apply: "À candidater", applied: "Envoyée", interview: "Entretien", rejected: "Refus" };

  /* Every posting the page knows, listed or only tracked (closed or old offers). */
  var postingByKey = {};
  rows.forEach(function (r) { T.postingsOf(r).forEach(function (p) { postingByKey[p.key] = p; }); });
  tracked.forEach(function (p) { if (!postingByKey[p.key]) postingByKey[p.key] = p; });

  /* The AI verdict shown for a row: the Worker's, for the row's current content only. */
  function aiOf(j) { return X.aiOf(j, track.ai); }

  function boardKeys() {
    return Object.keys(track.apps).filter(function (k) { return BOARD.indexOf(T.statusOf(track.apps[k])) >= 0; });
  }

  /* Sidebar, tab bar and view headers all carry data-count="<view>". */
  function setCount(view, n) {
    document.querySelectorAll('[data-count="' + view + '"]').forEach(function (node) {
      /* The tab bar's Tri badge disappears at zero rather than showing "0". */
      node.textContent = n || !node.closest(".tab-item, .btn-n") ? String(n) : "";
    });
  }

  /* One definition per counter, shared with the tests (triage.js sidebarCounts). */
  function updateCounts() {
    var n = X.sidebarCounts(rows, track.apps, runAt, thresholds.min_score, leads, runs, track.ai);
    Object.keys(n).forEach(function (view) { setCount(view, n[view]); });
    /* « Relances à faire » (sidebar): the due follow-ups, as Candidatures lists them. */
    setCount("relances", track.status === "ready" ? dueKeys(T.localDay()).length : "");
  }

  /* ---------- record panel (Attio): split at ≥ 1280 px, overlay below ---------- */

  var record = byId("record");
  var R = JM.rec = { open: false, tab: null, job: null, opener: null };
  function wideScreen() { return !!(window.matchMedia && window.matchMedia("(min-width: 1280px)").matches); }

  /* Where the panel lives: inside the Offres split when that view is wide, else as the app
     grid's third column (the overlay rules take over below 1280 px). */
  function placeRecord() {
    var inSplit = V.tab === "offres" && wideScreen();
    var host = inSplit ? byId("offres-split") : document.querySelector(".app");
    if (record.parentNode !== host) host.appendChild(record);
    document.body.classList.toggle("record-split", inSplit);
  }

  /* Below 1280 px the record covers the page: what is under it is inert, so Tab stays inside. */
  function setInert() {
    var cover = R.open && !wideScreen();
    [byId("main"), document.querySelector(".sidebar"), byId("tabbar")].forEach(function (n) {
      if (n) { if (cover) n.setAttribute("inert", ""); else n.removeAttribute("inert"); }
    });
  }
  if (window.matchMedia) window.matchMedia("(min-width: 1280px)").addEventListener("change", function () {
    setInert();
    if (R.open) placeRecord();
    ensureSelection();
  });

  /* How old the offer is, as of the snapshot (also the Tri card's fact). */
  function ageText(days) {
    if (typeof days !== "number") return "Date inconnue";
    if (days <= 0) return "Publiée aujourd’hui";
    return days === 1 ? "Publiée hier" : "Publiée il y a " + days + "\u00a0j";
  }

  /* « Adéquation avec ton profil »: the real score, big, in its band's hue, the scale and the
     band's word; the AI's own score next to it when the Worker has one. Unknown says so. */
  function scoreBlock(j) {
    var bd = S.band(j);
    var known = typeof j.score === "number";
    var big = el("span", { class: "score-big band-" + (known ? bd.key : "low"), "aria-label": known ? j.score + " sur 100" : "Score inconnu" }, [
      el("span", { class: "num", text: known ? String(j.score) : "—" }), known ? el("small", { text: "/ 100" }) : null
    ]);
    var bar = el("span", { class: "record-score-bar band-" + bd.key, "aria-hidden": "true" }, el("i"));
    bar.firstChild.style.setProperty("--w", (known ? Math.max(0, Math.min(100, j.score)) : 0) + "%");
    var side = el("div", { class: "record-score-side" }, [bar,
      el("span", { class: "band band-" + bd.key }, [el("span", { class: "dot", "aria-hidden": "true" }), known ? bd.label : "Score inconnu"])]);
    var v = aiOf(j);
    if (v) {
      var aiBand = S.aiBand(v.level);
      side.appendChild(el("span", { class: "record-ai" }, ["Selon l’IA : ", el("b", { class: "num", text: String(v.score) }), aiBand ? " · " + aiBand.label : ""]));
    }
    return el("section", { class: "record-score", "aria-label": "Adéquation avec ton profil" }, [
      el("div", null, [el("h3", { text: "Adéquation avec ton profil" }), big]), side
    ]);
  }

  /* Order: what the offer is, the score, why (the ledger with its sentences, the AI's view),
     the announcement itself, then the tracking, the documents and the replies. */
  function recordBody(j) {
    var box = el("div", { class: "record-scroll" });
    var status = T.rowStatus(j, track.apps);
    var tags = el("div", { class: "record-tags" }, [
      status !== "to_review" ? statusBadge(j) : null,
      el("span", { class: "pill", text: j.contract && j.contract !== "UNKNOWN" ? j.contract : "Contrat inconnu" }),
      el("span", { class: "pill", text: yearsText(j.required_years) }),
      el("span", { class: "pill", title: j.posted_at ? fmtDate(j.posted_at) : null, text: ageText(j.age_days) }),
      el("span", { class: "pill", title: j.source === "ats" ? "Page carrière de " + (j.company || "l’entreprise") : null, text: sourceText(j) || "Source inconnue" })
    ]);
    box.appendChild(el("header", { class: "record-head" }, [
      el("h2", { id: "record-title", tabindex: "-1", text: j.title || "—" }),
      el("p", { class: "record-sub", text: [j.company || "Entreprise non communiquée", j.location].filter(Boolean).join(" · ") }),
      tags
    ]));
    box.appendChild(scoreBlock(j));
    var form = trackForm(j, "rec");
    var why = whyPanel(j, form.verdictBlock || null);
    why.open = true;
    var v = aiOf(j);
    box.appendChild(el("section", { class: "record-sec" }, [why, v ? U.aiBlock(v) : null]));
    /* From Tri the card already shows the whole description: not twice. */
    if (j.description_excerpt && V.tab !== "tri") {
      box.appendChild(el("details", { class: "record-desc" }, [
        el("summary", { text: "Description de l’annonce" }),
        el("div", { class: "record-desc-body" }, D.render(D.parse(j.description_excerpt), el))
      ]));
    }
    if (j.postings) box.appendChild(el("section", { class: "record-sec" }, [postingsBlock(j)]));
    box.appendChild(el("section", { class: "record-sec" }, [el("h3", { text: "Suivi" }), form]));
    if (j.key && track.status === "ready") box.appendChild(el("section", { class: "record-sec" }, [documentsBlock(j)]));
    if (j.key && track.status === "ready") {
      var replies = T.inboxHistoryFor(j.key, track.inbox.history.concat(track.inbox.to_confirm));
      if (replies.length) box.appendChild(el("section", { class: "record-sec" }, [inboxHistoryBlock(replies)]));
    }
    return box;
  }

  /* « Réponses reçues » in the record panel (ADR 0018): every reply attached to this offer. */
  function inboxHistoryBlock(replies) {
    var list = el("ul", { class: "inbox-history" });
    replies.forEach(function (it) {
      list.appendChild(el("li", null, [
        el("span", { class: "inbox-date", text: it.received_at ? fmtShortDate(it.received_at) : "—" }),
        el("span", { class: "inbox-kind kind-" + (it.kind || "none"), text: T.inboxKindText(it.kind) }),
        el("span", { class: "inbox-subject", text: it.subject || "(sans objet)" }),
        el("span", { class: "inbox-state", text: T.INBOX_STATE_TEXT[it.state] || it.state })
      ]));
    });
    return el("div", { class: "inbox-block" }, [el("h3", { text: "Réponses reçues" }), list]);
  }

  /* « Générer » / « Regénérer » (record panel and table): one new pending version. The button
     stays off while the request runs; `onDone(doc)` refreshes the caller's own view. */

  /* The footer's buttons follow the status (a save redraws them, refreshBadges). */
  function refreshRecordFoot() {
    var foot = record.querySelector(".record-foot");
    if (!foot || !R.job) return;
    clear(foot);
    foot.appendChild(recordActions(R.job));
  }

  /* opts.quiet: the panel opens without taking the focus (the split's own selection). */
  function openRecord(j, opener, opts) {
    var was = R.open;
    var quiet = !!(opts && opts.quiet);
    var keep = was && record.contains(document.activeElement) ? null : document.activeElement;
    R.opener = opener || (quiet ? R.opener : document.activeElement);
    function fill() {
      placeRecord();
      clear(record);
      var close = el("button", { type: "button", class: "icon-btn record-close", "aria-label": "Fermer la fiche", "aria-keyshortcuts": "Escape" }, U.icon("x"));
      close.addEventListener("click", function () { closeRecord(); });
      /* On a phone the bar is the way back to the list; elsewhere the overline and the close. */
      var n = V.tab === "offres" ? listedCount() : 0;
      var back = el("button", { type: "button", class: "record-back", "aria-label": "Retour à la liste" }, [U.icon("arrow-left"),
        n ? "Retour aux " + n + (n > 1 ? " offres" : " offre") : "Retour"]);
      back.addEventListener("click", function () { closeRecord(); });
      var bar = el("div", { class: "record-bar" }, [back, el("span", { class: "record-crumb", text: V.tab === "tri" ? "Offre en cours de tri" : "Offre sélectionnée" })]);
      if (j.url && HTTP.test(j.url)) {
        bar.appendChild(el("a", { class: "icon-btn", href: j.url, target: "_blank", rel: "noopener noreferrer", "aria-label": "Voir l’offre « " + (j.title || "offre") + " » sur le site source" }, U.icon("external-link")));
      }
      bar.appendChild(close);
      record.appendChild(bar);
      record.appendChild(recordBody(j));
      record.appendChild(el("div", { class: "record-foot" }, recordActions(j)));
      record.hidden = false;
      record.classList.remove("closing");
      document.body.classList.add("record-open");
      R.open = true;
      R.tab = V.tab;
      R.job = j;
      setInert();
      markSelected();
      syncHash();
    }
    /* A quiet open is synchronous: the state is set before the next render looks at it. */
    var shown = (!was && !quiet && wideScreen()) ? U.transition(fill, ["record"]) : (fill(), Promise.resolve());
    shown.then(function () {
      /* Quiet: the focus stays where it was (a row, a field), or nowhere; a focus that was
         inside the panel before it was redrawn goes to its title, as a user open does. */
      if (quiet && keep === document.body) return;
      if (quiet && keep && document.contains(keep)) { keep.focus({ preventScroll: true }); return; }
      var h = byId("record-title");
      if (h) h.focus({ preventScroll: true });
    });
  }

  function closeRecord(animate) {
    if (!R.open) return;
    var back = R.opener;
    function done() {
      record.hidden = true;
      record.classList.remove("closing");
      clear(record);
      document.body.classList.remove("record-open");
      document.body.classList.remove("record-split");
      R.open = false;
      R.job = null;
      setInert();
      markSelected();
      syncHash();
    }
    R.open = false;
    setInert();  /* the page is focusable again before the focus goes back to it */
    if (animate === false || U.reduced()) done();
    else if (wideScreen()) U.transition(done, ["record"]);
    else { record.classList.add("closing"); setTimeout(done, 160); }
    if (back && document.contains(back)) back.focus({ preventScroll: true });
  }

  var STATUS_HUE = {
    to_review: "var(--ink-3)", to_apply: "var(--slate-10)", applied: "var(--blue-9)",
    interview: "var(--green-9)", rejected: "var(--red-9)", ignored: "var(--slate-7)"
  };

  /* ---------- palette (Ctrl/Cmd+K) and shortcuts ---------- */

  var MOD = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘" : "Ctrl";
  var GO_KEYS = { tri: "T", candidatures: "C", offres: "O", leads: "L", executions: "E" };
  var VIEW_ICON = { tri: "layers", candidatures: "briefcase-business", offres: "list", leads: "radar", executions: "activity" };

  function paletteCommands(q) {
    var groups = [];
    var j = R.open ? R.job : null;
    if (j && j.key && canTriage()) {
      var cur = T.statusOf(track.apps[j.key]);
      groups.push({ title: "Changer le statut", items: T.STATUSES.filter(function (s) { return s !== cur; }).map(function (s) {
        return { label: "Statut : " + T.STATUS_TEXT[s], hint: j.title, hue: STATUS_HUE[s], run: function () {
          setRecord(j.key, { status: s }, "Statut : " + T.STATUS_TEXT[s]);
          openRecord(j, R.opener);
        } };
      }) });
    }
    groups.push({ title: "Aller à", items: TABS.map(function (t) {
      return { label: "Aller à " + VIEW_TITLE[t], icon: VIEW_ICON[t], keys: ["G", GO_KEYS[t]], run: function () { showTab(t, true, true); } };
    }) });
    var offers = q ? rows : JM.tri.items.slice(JM.tri.pos, JM.tri.pos + 4).map(function (it) { return it.row; });
    groups.push({ title: q ? "Offres" : "À trier ensuite", limit: 6, items: offers.map(function (r) {
      return { label: r.title || "—", hint: r.company || "", score: typeof r.score === "number" ? r.score : null, icon: "briefcase-business",
        text: [r.title, r.company, r.location].filter(Boolean).join(" "), run: function () { openRecord(r, null); } };
    }) });
    var actions = [{ label: "Raccourcis clavier", icon: "keyboard", keys: ["?"], run: function () { P.openHelp(); } }];
    if (V.tab === "tri" && JM.undo.size()) actions.unshift({ label: "Annuler la dernière décision", icon: "undo-2", keys: ["Z"], run: undoLast });
    groups.push({ title: "Actions", items: actions });
    return groups;
  }

  var HELP = [
    ["Général", [[[MOD, "K"], "Palette de commandes"], [["?"], "Cette aide"], [["G", "T"], "Aller au Tri"], [["G", "C"], "Aller aux Candidatures"],
      [["G", "O"], "Aller aux Offres"], [["G", "L"], "Aller aux Leads"], [["G", "E"], "Aller aux Exécutions"], [["Échap"], "Fermer la fiche ou la palette"]]],
    ["Tri", [[["→"], "Garder"], [["←"], "Écarter"], [["Z"], "Annuler la dernière décision"], [["1–4"], "Raison de l’écart"], [["↵"], "Ouvrir la fiche"], [["↑", "↓"], "Faire défiler la carte"]]],
    ["Offres", [[["J", "K"], "Offre suivante / précédente"], [["X"], "Écarter (Ignorer)"], [["S"], "Garder (À candidater)"], [["A"], "Candidature envoyée"], [["↵"], "Ouvrir l’annonce"], [["Espace"], "Déplier / replier"], [["/"], "Rechercher"]]],
    ["Fiche", [[["Échap"], "Fermer"], [["Tab"], "Champ suivant"]]]
  ];

  var gAt = 0;
  document.addEventListener("keydown", function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && !ev.altKey && (ev.key === "k" || ev.key === "K")) { ev.preventDefault(); P.toggle(); return; }
    if (P.isOpen() || ev.defaultPrevented) return;
    var t = ev.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
    if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
    if (ev.key === "?") { ev.preventDefault(); P.openHelp(); return; }
    if (ev.key === "g" || ev.key === "G") { gAt = performance.now(); return; }
    if (performance.now() - gAt < 900) {
      gAt = 0;
      var to = { t: "tri", c: "candidatures", o: "offres", l: "leads", e: "executions" }[ev.key.toLowerCase()];
      if (to) { ev.preventDefault(); showTab(to, true, true); return; }
    }
    if (V.tab === "tri" && triKeys(ev)) { ev.preventDefault(); return; }
    if (V.tab === "offres" && listKeys(ev)) { ev.preventDefault(); return; }
    if (ev.key === "Escape" && R.open) { ev.preventDefault(); closeRecord(); }
  });

  function renderCurrent() {
    try {
      if (V.tab === "tri") renderTri();
      else if (V.tab === "candidatures") renderApps();
    } catch (err) {
      console.error("affichage interrompu", V.tab, err);
      var host = byId(V.tab === "tri" ? "tri-stage" : "kb-board");
      if (host) { clear(host); host.hidden = false; host.appendChild(el("p", { class: "kb-empty", text: "Affichage interrompu : recharge la page." })); }
    }
    updateCounts();
  }

  /* Shared with the other files. */
  JM.BOARD = BOARD;
  JM.BOARD_TEXT = BOARD_TEXT;
  JM.D = D;
  JM.FILTERS_KEY = FILTERS_KEY;
  JM.HELP = HELP;
  JM.HTTP = HTTP;
  JM.MOD = MOD;
  JM.P = P;
  JM.S = S;
  JM.SECTIONS = SECTIONS;
  JM.SORT_TEXT = SORT_TEXT;
  JM.T = T;
  JM.U = U;
  JM.X = X;
  JM.ageText = ageText;
  JM.aiOf = aiOf;
  JM.api = api;
  JM.applyChanges = applyChanges;
  JM.badges = badges;
  JM.boardKeys = boardKeys;
  JM.byId = byId;
  JM.cell = cell;
  JM.clear = clear;
  JM.closeRecord = closeRecord;
  JM.data = data;
  JM.dateCell = dateCell;
  JM.dayOf = dayOf;
  JM.el = el;
  JM.failureText = failureText;
  JM.fmtAmount = fmtAmount;
  JM.fmtDate = fmtDate;
  JM.fmtDateTime = fmtDateTime;
  JM.fmtShortDate = fmtShortDate;
  JM.fmtYears = fmtYears;
  JM.jobs = jobs;
  JM.leads = leads;
  JM.link = link;
  JM.loadTracking = loadTracking;
  JM.openRecord = openRecord;
  JM.overrideViews = overrideViews;
  JM.paletteCommands = paletteCommands;
  JM.parseHash = parseHash;
  JM.postingByKey = postingByKey;
  JM.record = record;
  JM.refreshBadges = refreshBadges;
  JM.refreshRecordFoot = refreshRecordFoot;
  JM.rows = rows;
  JM.runAt = runAt;
  JM.runs = runs;
  JM.setAppsView = setAppsView;
  JM.showTab = showTab;
  JM.showToast = showToast;
  JM.statusBadge = statusBadge;
  JM.statusOfJob = statusOfJob;
  JM.syncHash = syncHash;
  JM.thresholds = thresholds;
  JM.toastActions = toastActions;
  JM.track = track;
  JM.trackForm = trackForm;
  JM.updateCounts = updateCounts;
  JM.wideScreen = wideScreen;
  JM.yearsText = yearsText;
})(window.JM);
