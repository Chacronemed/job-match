/* job-match dashboard. Vanilla JS, no dependencies. Every string from the data lands in
   the DOM through textContent or an attribute set on an element we created: nothing from
   the database is ever parsed as HTML. */
(function () {
  "use strict";

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
    age_days: "âge"
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

  /* Dark only for now (DESIGN.md "Light mode": planned). The toggle stays wired, hidden, so
     light mode can come back without new plumbing; theme-color follows the applied theme. */
  var DARK_ONLY = true;
  var THEME_COLOR = { dark: "#111113", light: "#ffffff" };

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
    var entering = name !== currentTab;
    function swap() {
      navLinks.forEach(function (a) {
        if (a.getAttribute("data-tab") === name) a.setAttribute("aria-current", "page");
        else a.removeAttribute("aria-current");
      });
      TABS.forEach(function (t) { byId("panel-" + t).hidden = t !== name; });
      currentTab = name;
      if (entering) {
        if (recordOpen && recordFor !== name) closeRecord(false);
        renderCurrent();
        byId("main").scrollTop = 0;
      }
      syncHash();
      document.title = VIEW_TITLE[name] + " · job-match";
    }
    if (animate && entering && currentTab) U.transition(swap, ["view"]).then(afterEnter); else { swap(); if (entering) afterEnter(); }
    function afterEnter() {
      /* Tri opened with the pointer: the card takes focus so ← → decide at once (AUDIT P2-9). */
      if (name === "tri") focusTriCard();
      else if (focus) byId("main").focus({ preventScroll: true });
    }
  }
  var VIEW_TITLE = { tri: "Tri", candidatures: "Candidatures", offres: "Offres", leads: "Leads", executions: "Exécutions" };

  var currentTab = "";
  var applyingHash = false;

  /* The hash carries the tab and the Offres filters (#offres?q=...&hide=...), whatever the
     tab: switching to Tri and back, or reloading, keeps them. Every value is validated before
     it touches the state. */
  function syncHash() {
    if (applyingHash) return;
    var parts = [];
    {
      if (state.q) parts.push("q=" + encodeURIComponent(state.q));
      var off = SECTIONS.filter(function (s) { return !state.sections[s]; });
      if (off.length) parts.push("hide=" + off.join(","));
      if (state.department) parts.push("dept=" + encodeURIComponent(state.department));
      if (state.status) parts.push("st=" + state.status);
      if (state.minScore) parts.push("min=" + state.minScore);
      if (state.from) parts.push("from=" + state.from);
      if (state.to) parts.push("to=" + state.to);
      if (state.sortKey !== "score" || state.sortDir !== "desc") parts.push("sort=" + state.sortKey + ":" + state.sortDir);
      /* The open record, so a link or a reload shows the same offer. */
      if (typeof recordOpen !== "undefined" && recordOpen && recordJob && recordJob.key) parts.push("fiche=" + encodeURIComponent(recordJob.key));
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
    tab = TAB_ALIASES[tab] || tab;
    return { tab: TABS.indexOf(tab) >= 0 ? tab : "tri", params: params };
  }

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

  var searchInput = byId("f-search");
  var deptSelect = byId("f-department");
  var statusSelect = byId("f-status");
  var minScoreInput = byId("f-min-score");
  var minScoreOut = byId("f-min-score-out");
  var fromInput = byId("f-from");
  var toInput = byId("f-to");
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip[data-section]"));
  var jobsBody = byId("jobs-body");

  byId("min-score-hint").textContent = "(digest ≥ " + thresholds.min_score + ", fort ≥ " + thresholds.strong + ")";

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
    if (unknown) deptSelect.appendChild(el("option", { value: "?", text: "? inconnu (" + unknown + ")" }));
  }

  function fillStatuses() {
    T.STATUSES.forEach(function (s) {
      statusSelect.appendChild(el("option", { value: s, text: T.STATUS_TEXT[s] }));
    });
  }

  /* How many Offres filters differ from their default: shown on the phone's "Filtres" bar. */
  function activeFilters() {
    var n = 0;
    if (state.q) n += 1;
    if (SECTIONS.some(function (s) { return !state.sections[s]; })) n += 1;
    if (state.department) n += 1;
    if (state.status) n += 1;
    if (state.minScore) n += 1;
    if (state.from) n += 1;
    if (state.to) n += 1;
    return n;
  }

  function matches(j) {
    if (!state.sections[j.section]) return false;
    if (state.status && statusOfJob(j) !== state.status) return false;
    if (state.minScore > 0 && (j.score === null || j.score < state.minScore)) return false;
    if (state.department) {
      var depts = T.postingsOf(j).map(function (p) { return p.department || ""; });
      if (state.department === "?" ? depts.indexOf("") < 0 : depts.indexOf(state.department) < 0) return false;
    }
    var day = dayOf(j.posted_at);
    if (state.from && day < state.from) return false;
    if (state.to && day > state.to) return false;
    return T.matchesWords(j, searchWords());
  }

  /* The query's words, split once per query rather than once per row. */
  var wordsFor = { q: null, words: [] };
  function searchWords() {
    if (wordsFor.q !== state.q) wordsFor = { q: state.q, words: T.queryWords(state.q) };
    return wordsFor.words;
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
    if (err && err.status === 401) return "ta session Access a expiré, recharge la page";
    if (err && err.status >= 500) return "le serveur a échoué";
    return (err && err.message) || "erreur réseau";
  }

  /* A note typed in the last moment, or a save still in flight, is not stored yet. */
  window.addEventListener("beforeunload", function (ev) {
    if (track.pending > 0 || (typeof retry !== "undefined" && retry.size() > 0)) { ev.preventDefault(); ev.returnValue = ""; }
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
      track.overrides = overrides;
      track.apps = apps;
      track.confirmed = Object.assign({}, apps);
      track.decisions = decisions;
      track.status = "ready";
      overlayPending();
      trackBanner();
      tri.built = false;  /* the queue depends on the statuses just loaded */
      renderPending();
      flushRetry();
      renderJobs();
      renderCurrent();
    }).catch(function () {
      track.status = "error";
      trackBanner();
      renderJobs();
      renderCurrent();
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
    var cv = el("input", { type: "url", inputmode: "url", autocomplete: "off", spellcheck: "false", placeholder: "https://…" });
    var cvOpen = el("a", { class: "cv-open", target: "_blank", rel: "noopener noreferrer", text: "Ouvrir" });
    var note = el("textarea", { rows: "3", maxlength: String(T.NOTE_MAX), placeholder: "Contact, salaire, prochaine étape…" });
    var counter = el("span", { class: "note-count", "aria-hidden": "true" });

    var grid = el("div", { class: "track-grid" }, [
      field("status", "Statut", status),
      field("applied_at", "Candidature envoyée le", applied),
      field("follow_up_at", "Relance le", follow),
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

  /* "poids +3": what the skill adds to (or takes from) this offer's score, said in full on
     hover and to screen readers. */
  function weightTag(w) {
    var n = Math.abs(w);
    var points = n + " point" + (n > 1 ? "s" : "");
    var says = w > 0 ? "Ajoute " + points + " au score de cette offre" : "Retire " + points + " au score de cette offre";
    return el("span", { class: "why-weight", title: says + ". Le poids se règle dans ton profil.", "aria-label": "poids " + weightText(w) + " : " + says }, "poids " + weightText(w));
  }

  var chipSeq = 0;

  /* Chips only; a chip with a sentence is a button that shows it under the list. One
     sentence open at a time per list. */
  function chipList(entries) {
    var wrap = el("div", { class: "why-chips" });
    var ul = el("ul", { class: "why-list" });
    var out = el("q", { class: "evidence", id: "ev-" + (++chipSeq), hidden: true });
    var open = null;
    function close() {
      if (open) open.setAttribute("aria-expanded", "false");
      open = null;
      out.hidden = true;
      out.textContent = "";
    }
    entries.forEach(function (e) {
      var chip;
      if (e.snippet) {
        chip = el("button", { type: "button", class: "tag chip-ev " + e.cls, "aria-expanded": "false", "aria-controls": out.id, title: "Voir la phrase de l’offre", text: e.name });
        chip.addEventListener("click", function () {
          if (open === chip) { close(); return; }
          if (open) open.setAttribute("aria-expanded", "false");
          open = chip;
          chip.setAttribute("aria-expanded", "true");
          out.textContent = e.snippet;
          out.hidden = false;
        });
      } else {
        chip = el("span", { class: "tag " + e.cls, text: e.name });
      }
      ul.appendChild(el("li", { class: "why-item" }, [
        chip,
        typeof e.weight === "number" ? weightTag(e.weight) : null,
        e.control || null
      ]));
    });
    wrap.appendChild(ul);
    wrap.appendChild(out);
    return wrap;
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
    var retry = el("button", { type: "button", class: "btn btn-retry", text: "Réessayer", hidden: true });
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
      state.textContent = "Enregistrement…";
      retry.hidden = true;
      track.pending += 1;
      api.overrideSkill(skill, on).finally(function () { track.pending -= 1; }).then(function () {
        wrap.setAttribute("data-state", "saved");
        state.textContent = "";
      }).catch(function (err) {
        if (before) track.overrides[skill] = true; else delete track.overrides[skill];
        syncAll();
        wrap.setAttribute("data-state", "error");
        state.textContent = "Non enregistré (" + failureText(err) + ").";
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
    var head = el("div", { class: "why-head" }, [
      el("span", { class: "why-years", text: text }),
      el("span", { class: "confidence confidence-" + basis, text: basis === "none" ? "non recalculé" : BASIS_TEXT[basis] })
    ]);
    var out = [head];
    if (e.sentence) {
      var q = el("q", { class: "evidence", id: "ev-" + (++chipSeq), hidden: true, text: e.sentence });
      var more = el("button", { type: "button", class: "link-btn", "aria-expanded": "false", "aria-controls": q.id, text: "voir la phrase" });
      more.addEventListener("click", function () {
        var show = q.hidden;
        q.hidden = !show;
        more.setAttribute("aria-expanded", show ? "true" : "false");
        more.textContent = show ? "masquer la phrase" : "voir la phrase";
      });
      head.appendChild(more);
      out.push(q);
    }
    if (e.excludes_apprenticeship) out.push(el("span", { class: "tag tag-flag", text: "hors stage et alternance" }));
    return out;
  }

  function plural(n, one, many) { return n + " " + (n > 1 ? many : one); }

  /* Closed by default: the tracking form is what a row is opened for; the reasons are one
     click away. */
  function whyPanel(j, verdictBlock) {
    var w = j.why || { skills: [], unlisted: [], lowered: [], experience: null };
    var parts = [plural(w.skills.length, "compétence", "compétences")];
    if (w.unlisted.length) parts.push(plural(w.unlisted.length, "non trouvée", "non trouvées"));
    if (w.lowered.length) parts.push(plural(w.lowered.length, "malus", "malus"));
    var panel = el("details", { class: "why" });
    panel.appendChild(el("summary", { class: "why-title" }, [
      el("span", { text: "Pourquoi cette offre ?" }),
      el("span", { class: "why-summary", text: parts.join(" · ") })
    ]));
    var grid = el("div", { class: "why-grid" });
    /* Skills on the left; the shorter blocks stack on the right; the verdict spans both. */
    var left = el("div", { class: "why-col" });
    var right = el("div", { class: "why-col" });
    var target = left;
    function block(name, title, body) {
      target.appendChild(el("div", { class: "why-block why-" + name }, [el("h4", { text: title })].concat(body)));
    }

    var skills = [w.skills.length
      ? chipList(w.skills.map(function (s) { return { cls: "tag-pos", name: s.name, weight: s.weight, snippet: s.snippet }; }))
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
      ? chipList(w.unlisted.map(function (u) { return { cls: "tag-miss", name: u.name, snippet: u.snippet, control: overrideControl(u.name) }; }))
      : el("p", { class: "note", text: "L’offre ne cite pas d’autre compétence connue." })]);

    block("experience", "Expérience", experienceBody(w.experience));

    block("lowered", "Ce qui a baissé le score", [w.lowered.length
      ? chipList(w.lowered.map(function (s) { return { cls: "tag-neg", name: s.name, weight: s.weight, snippet: s.snippet }; }))
      : el("p", { class: "note", text: "Rien n’a baissé le score." })]);

    grid.appendChild(left);
    grid.appendChild(right);
    target = grid;
    block("verdict", "Ton avis", [verdictBlock ||
      el("p", { class: "note", text: "Les avis s’enregistrent depuis le tableau de bord hébergé." })]);

    panel.appendChild(grid);
    /* Clicks inside the panel (chips, buttons, the summary) must not toggle the row. */
    panel.addEventListener("click", function (ev) { ev.stopPropagation(); });
    panel.addEventListener("keydown", function (ev) { ev.stopPropagation(); });
    return panel;
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

  /* "Ignorer" sets every posting of a group; "À candidater" only the best-scored one (the
     others stay one click away in the details). */
  function quickSet(row, status) {
    var targets = status === "ignored" ? T.postingsOf(row) : [row];
    var before = targets.map(function (p) { return { key: p.key, next: T.blank(track.apps[p.key]) }; });
    var changes = before.map(function (b) { return { key: b.key, next: Object.assign({}, b.next, { status: status }) }; });
    var done = status === "ignored"
      ? (targets.length > 1 ? targets.length + " offres ignorées" : "Offre ignorée")
      : "Offre passée à « À candidater »";
    applyChanges(changes, done, before);
  }

  function quickActions(row) {
    if (track.status !== "ready" || !api) return null;
    var s = T.rowStatus(row, track.apps);
    var wrap = el("span", { class: "qa-wrap" });
    function button(text, status) {
      var b = el("button", { type: "button", class: "qa", "aria-label": text + " : " + (row.title || "offre"), text: text });
      b.addEventListener("click", function (ev) { ev.stopPropagation(); quickSet(row, status); });
      b.addEventListener("keydown", function (ev) { ev.stopPropagation(); });
      wrap.appendChild(b);
    }
    if (s === "to_review" || s === "ignored") button("À candidater", "to_apply");
    if (s === "to_review" || s === "to_apply") button("Ignorer", "ignored");
    return wrap.childNodes.length ? wrap : null;
  }

  /* A grouped row's postings: each keeps its own status. */
  function postingsBlock(j) {
    var box = el("div", { class: "postings" });
    box.appendChild(el("h4", { text: "Publiée dans " + j.departments.length + " départements" }));
    var ul = el("ul", { class: "postings-list" });
    j.postings.forEach(function (p) {
      var li = el("li", { class: "posting" }, [
        el("span", { class: "posting-place", text: p.location || p.department || "—" }),
        el("span", { class: "posting-date", title: p.posted_at ? fmtDate(p.posted_at) : null, text: fmtShortDate(p.posted_at) })
      ]);
      if (track.status === "ready" && api) {
        var sel = el("select", { class: "posting-status", "aria-label": "Statut de l’offre à " + (p.location || p.department || "?") });
        T.STATUSES.forEach(function (s) { sel.appendChild(el("option", { value: s, text: T.STATUS_TEXT[s] })); });
        sel.value = T.statusOf(track.apps[p.key]);
        sel.addEventListener("change", function () {
          var before = [{ key: p.key, next: T.blank(track.apps[p.key]) }];
          applyChanges([{ key: p.key, next: Object.assign({}, before[0].next, { status: sel.value }) }],
            "Statut enregistré pour " + (p.department || "?"), before);
        });
        li.appendChild(sel);
      } else {
        li.appendChild(statusBadge(p));
      }
      li.appendChild(link(p.url, "Ouvrir"));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    box.addEventListener("click", function (ev) { ev.stopPropagation(); });
    box.addEventListener("keydown", function (ev) { ev.stopPropagation(); });
    return box;
  }

  /* The scorer writes its explanations in English (they are stored and logged that way);
     the page shows them in French. Unknown lines pass through as they are. */
  var EXPLAIN_FR = [
    [/^stretch: requires (\S+)y, you have (\S+)$/, function (m) { return "À tenter : " + m[1] + " an(s) requis, tu en as " + m[2]; }],
    [/^Matched preferred: (.+) \((\+?-?\d+)\)$/, function (m) { return "Compétence trouvée : " + m[1] + " (" + m[2] + ")"; }],
    [/^Missed preferred: (.+)$/, function (m) { return "Compétence absente de l’offre : " + m[1]; }],
    [/^Matched negative: (.+) \((-?\d+)\)$/, function (m) { return "Malus : " + m[1] + " (" + m[2] + ")"; }],
    [/^Title keyword match: (.+) \((\+?\d+)\)$/, function (m) { return "Mot-clé dans le titre : " + m[1] + " (" + m[2] + ")"; }],
    [/^experience: internships\/work-study excluded from required years$/, function () { return "Expérience : stages et alternance exclus des années requises"; }]
  ];

  function frExplanation(line) {
    for (var i = 0; i < EXPLAIN_FR.length; i++) {
      var m = EXPLAIN_FR[i][0].exec(line);
      if (m) return EXPLAIN_FR[i][1](m);
    }
    return line;
  }

  function detailsFor(j, prefix, colspan) {
    var td = el("td", { colspan: String(colspan) });
    var box = el("div", { class: "details" });
    var form = trackForm(j, prefix);
    box.appendChild(form);
    var meta = [];
    if (j.location) meta.push(j.location);
    if (j.source) meta.push("source : " + j.source);
    if (!j.published_at) meta.push("pas de date de publication à la source");
    if (j.posted_at) meta.push("publiée le " + fmtDate(j.posted_at));
    if (j.collected_at) meta.push("collectée le " + fmtDate(j.collected_at));
    var stretchLine = null;
    var others = [];
    (j.explanations || []).forEach(function (line) {
      if (line.indexOf("stretch:") === 0 && !stretchLine) stretchLine = line;
      else others.push(line);
    });
    box.appendChild(el("p", { class: "meta", text: meta.join(" · ") }));
    if (stretchLine) box.appendChild(el("p", { class: "stretch-note", text: frExplanation(stretchLine) }));
    if (j.postings) box.appendChild(postingsBlock(j));

    var panel = whyPanel(j, form.verdictBlock || null);
    if (others.length) {
      panel.appendChild(el("details", { class: "explain-all" }, [
        el("summary", { text: "Toutes les explications (" + others.length + ")" }),
        el("ul", null, others.map(function (t) { return el("li", { text: frExplanation(t) }); }))
      ]));
    }
    box.appendChild(panel);
    td.appendChild(box);
    return el("tr", { class: "details", id: prefix + "-details-" + j.id }, td);
  }

  /* Cell builders shared by the Jobs table and the Aujourd'hui queue. */
  var COLUMNS = {
    title: function (j, prefix, expanded) {
      return cell("col-title", "Titre", el("button", {
        type: "button", class: "expand", "aria-expanded": expanded ? "true" : "false",
        "aria-controls": prefix + "-details-" + j.id
      }, [el("span", { class: "dot dot-" + j.section, "aria-hidden": "true" }), el("span", { class: "title-text", text: j.title || "—", title: j.title || null })]));
    },
    company: function (j) {
      var td = cell("col-company", "Entreprise", j.company || "—");
      if (j.company) td.title = j.company;
      return td;
    },
    department: function (j) {
      if (!j.postings) return cell("col-dept", "Dép.", j.department || "?");
      var td = cell("col-dept", "Dép.", el("span", { class: "dept-multi", text: j.departments.length + " dép." }));
      td.title = j.departments.length + " départements : " + j.departments.join(", ");
      return td;
    },
    actions: function (j) { return cell("col-actions", "Actions", quickActions(j)); },
    contract: function (j) { return cell("col-contract", "Contrat", j.contract || "INCONNU"); },
    score: function (j) { return cell("num col-score", "Score", scoreCell(j)); },
    required_years: function (j) {
      var years = fmtYears(j.required_years);
      return cell("num col-years", "Années", el("span", { class: years === null ? "unknown years" : "years", text: years === null ? "—" : years + " an" + (years === "0" || years === "1" ? "" : "s") }));
    },
    status: function (j) { return cell("col-status", "Statut", statusBadge(j)); },
    posted_at: function (j) { return dateCell("col-date", "Publiée", j.posted_at); },
    age_days: function (j) {
      var age = typeof j.age_days === "number" ? j.age_days : null;
      return cell("num col-age", "Âge", el("span", { class: age === null ? "unknown" : "", text: age === null ? "—" : age + " j" }));
    },
    link: function (j) { return cell("link-col", "Lien", link(j.url, "Ouvrir")); }
  };
  var JOB_COLUMNS = ["title", "company", "department", "contract", "score", "required_years", "status", "posted_at", "age_days", "actions", "link"];

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
        if (ev.target.closest("a, .qa")) return;
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
      badges[k] = badges[k].filter(function (b) { return !root.contains(b.node); });
    });
  }

  function renderJobs() {
    var shown = rows.filter(matches).sort(compare);
    var counts = { strong: 0, eligible: 0, stretch: 0 };
    shown.forEach(function (j) { counts[j.section] += 1; });
    byId("kpi-strong").textContent = counts.strong;
    byId("kpi-eligible").textContent = counts.eligible;
    byId("kpi-stretch").textContent = counts.stretch;
    byId("kpi-shown").textContent = shown.length;
    byId("kpi-total").textContent = rows.length;
    byId("jobs-rowcount").textContent = shown.length + " sur " + rows.length + " offres · tri par " +
      SORT_TEXT[state.sortKey] + (state.sortDir === "asc" ? " ↑" : " ↓");

    dropBadges(jobsBody);
    clear(jobsBody);
    byId("jobs-empty").hidden = shown.length > 0;
    byId("filters-count").textContent = activeFilters() ? " (" + activeFilters() + ")" : "";
    jobsBody.appendChild(jobRows(shown, "jobs", JOB_COLUMNS, state.expanded));
  }

  /* ---------- counts in the tab bar ---------- */

  var X = window.JMTriage;
  var runAt = X.latestRunAt(runs);
  var BOARD = ["to_apply", "applied", "interview", "rejected"];
  var BOARD_TEXT = { to_apply: "À candidater", applied: "Envoyée", interview: "Entretien", rejected: "Refus" };

  /* Every posting the page knows, listed or only tracked (closed or old offers). */
  var postingByKey = {};
  rows.forEach(function (r) { T.postingsOf(r).forEach(function (p) { postingByKey[p.key] = p; }); });
  tracked.forEach(function (p) { if (!postingByKey[p.key]) postingByKey[p.key] = p; });

  function boardKeys() {
    return Object.keys(track.apps).filter(function (k) { return BOARD.indexOf(T.statusOf(track.apps[k])) >= 0; });
  }

  /* Sidebar, tab bar and view headers all carry data-count="<view>". */
  function setCount(view, n) {
    document.querySelectorAll('[data-count="' + view + '"]').forEach(function (node) {
      /* The tab bar's Tri badge disappears at zero rather than showing "0". */
      node.textContent = n || !node.closest(".tab-item") ? String(n) : "";
    });
  }

  function updateCounts() {
    setCount("tri", X.triageQueue(rows, track.apps, runAt).length);
    setCount("candidatures", boardKeys().length);
  }

  /* ---------- Tri ---------- */

  var tri = {
    items: [],      /* the session's queue, fixed when it starts so positions stay put */
    pos: 0,
    kept: 0,
    dropped: 0,
    built: false,
    pausedAt: -1    /* batch boundary already acknowledged */
  };
  var undo = X.undoStack();
  /* Read at each move: the setting can change while the page is open. */
  function reduceMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  var triLive = byId("tri-live");
  var reasonTimer = null;

  var retry = X.retryQueue(function (op) {
    var p = op.payload;
    if (op.kind === "save") return api.save(p.key, p.rec).then(function (res) { track.confirmed[p.key] = res.application; });
    if (op.kind === "decide") {
      return api.decide(p.key, p.label, p.score).then(function (res) {
        if (res && res.decision) undo.attach(p.key, res.decision.id);
      });
    }
    return api.undecide(p.id);
  }, function (op, err) {
    announce("Action refusée par le serveur (" + failureText(err) + ") : rien n’a été enregistré, refais-la depuis l’onglet Offres.");
    renderPending();
  }, X.localStore("jm.pending.v1"));

  /* Saves still waiting from an earlier visit win over what the API says until they are
     sent: the page shows the decision I made, not the one it replaces. */
  function overlayPending() {
    retry.list().forEach(function (op) {
      if (op.kind === "save") track.apps[op.payload.key] = Object.assign({ job_key: op.payload.key }, track.apps[op.payload.key] || {}, op.payload.rec);
    });
  }

  function announce(text) {
    triLive.textContent = "";
    /* A new node each time so the same words are read twice in a row. */
    setTimeout(function () { triLive.textContent = text; }, 30);
  }

  function renderPending() {
    var bar = byId("tri-pending");
    bar.hidden = retry.size() === 0;
    var n = X.pendingOffers(retry.list());
    byId("tri-pending-text").textContent = n + (n > 1 ? " offres en attente" : " offre en attente") + " de connexion";
  }

  function flushRetry() {
    if (!api || !retry.size()) return;
    retry.flush().then(renderPending, renderPending);
  }
  window.addEventListener("online", flushRetry);
  setInterval(flushRetry, 15000);
  byId("tri-pending-retry").addEventListener("click", flushRetry);

  /* Send now; a network or server failure waits in the retry queue, the page keeps the new
     state (it is what I decided). A refusal (4xx) puts the old record back. */
  function triSave(key, rec, prev) {
    track.apps[key] = Object.assign({ job_key: key }, track.apps[key] || {}, rec);
    refreshBadges(key);
    return api.save(key, rec).then(function (res) {
      track.apps[key] = track.confirmed[key] = res.application;
    }, function (err) {
      if (X.retryable(err)) { retry.add({ kind: "save", payload: { key: key, rec: rec } }); renderPending(); return; }
      if (prev) track.apps[key] = prev; else delete track.apps[key];
      refreshBadges(key);
      announce("Non enregistré (" + failureText(err) + ") : recharge la page puis refais ce choix.");
    });
  }

  function triDecide(key, label, score) {
    track.decisions[key] = label;
    return api.decide(key, label, score).then(function (res) {
      if (res && res.decision) undo.attach(key, res.decision.id);
    }, function (err) {
      if (X.retryable(err)) { retry.add({ kind: "decide", payload: { key: key, label: label, score: score } }); renderPending(); }
    });
  }

  function buildTri() {
    tri.items = X.triageQueue(rows, track.apps, runAt);
    tri.pos = 0;
    tri.built = true;
    tri.pausedAt = -1;
  }

  function canTriage() { return track.status === "ready" && !!api; }

  function focusTriCard() {
    var card = byId("tri-stage").querySelector(".tcard:not(.is-next)");
    if (card) card.focus({ preventScroll: true });
  }

  /* The "Publiée" fact: how long ago, as of the snapshot. */
  function ageText(days) {
    if (typeof days !== "number") return "Date inconnue";
    if (days <= 0) return "Aujourd’hui";
    return days === 1 ? "Hier" : "Il y a " + days + "\u00a0j";
  }

  /* The ledger animates only when a card arrives (first view, or the one after a decision),
     not when the same card is drawn again. */
  var triArrive = true;

  /* One card (DESIGN.md "Tri card"): the facts, the collapsible ledger, then the whole
     description laid out by description.js; the card's own content scrolls, the buttons stay.
     Everything from the data goes through textContent. The ledger carries the weights, so the
     skills are not listed a second time (AUDIT P2-7); the title opens this exact offer's
     record (P1-9). */
  function triCard(item, isNext) {
    var j = item.row;
    var w = j.why || { skills: [], unlisted: [], lowered: [] };
    var desc = D.parse(j.description_excerpt || "");
    var card = el("article", {
      class: "tcard" + (isNext ? " is-next" : ""),
      tabindex: isNext ? null : "-1",
      "aria-hidden": isNext ? "true" : null,
      "aria-label": isNext ? null : (j.title || "Offre") + (j.company ? ", " + j.company : "")
    });
    if (!isNext) {
      card.appendChild(el("span", { class: "stamp stamp-keep", "aria-hidden": "true", icon: "check" }, "Garder"));
      card.appendChild(el("span", { class: "stamp stamp-drop", "aria-hidden": "true", icon: "x" }, "Écarter"));
    }
    var body = el("div", { class: "tcard-scroll" });
    card.appendChild(body);

    var badges = [];
    if (item.isNew) badges.push(el("span", { class: "badge badge-new", text: "Nouveau" }));
    if (j.section === "stretch") badges.push(el("span", { class: "badge badge-stretch", text: "À tenter" }));
    if (j.postings) badges.push(el("span", { class: "badge", text: j.departments.length + " départements" }));
    if (badges.length) body.appendChild(el("div", { class: "tcard-badges" }, badges));

    /* The facts first, in a fixed order, scannable at a glance. Salary only when the text
       states it on its own line (description.js), word for word. */
    var open = el("button", { type: "button", class: "tcard-open", title: "Ouvrir la fiche", text: j.title || "—", tabindex: isNext ? "-1" : null });
    open.addEventListener("click", function () { openRecord(j, open); });
    function fact(label, value, cls) {
      return el("div", { class: "fact" + (cls ? " " + cls : "") }, [el("dt", { text: label }), el("dd", null, value)]);
    }
    var facts = [
      fact("Poste", el("h2", { class: "tcard-title" }, open), "fact-title"),
      fact("Entreprise", j.company || "Non communiquée"),
      fact("Expérience demandée", yearsText(j.required_years)),
      fact("Lieu", j.location || (j.department ? "Département " + j.department : "Non précisé")),
      fact("Contrat", j.contract || "Inconnu")
    ];
    if (desc.salary) facts.push(fact("Salaire", desc.salary));
    var posted = fact("Publiée", ageText(j.age_days));
    if (j.posted_at) posted.title = fmtDate(j.posted_at);
    facts.push(posted);
    body.appendChild(el("dl", { class: "tcard-facts" }, facts));

    body.appendChild(U.ledger(j, thresholds, {
      collapsible: true, animate: !isNext && triArrive,
      missing: j.missing || [], unlisted: (w.unlisted || []).map(function (u) { return u.name; })
    }));

    if (desc.sections.length) {
      body.appendChild(el("div", { class: "tcard-desc", "aria-label": "Description de l’offre", role: "group" }, D.render(desc, el)));
    } else {
      body.appendChild(el("p", { class: "tcard-empty", text: "La source n’a pas fourni de description." }));
    }
    if (!isNext && j.url && HTTP.test(j.url)) {
      body.appendChild(el("p", { class: "tcard-foot" }, el("a", { class: "link-btn tri-link", href: j.url, target: "_blank", rel: "noopener noreferrer",
        "aria-label": "Voir l’offre « " + (j.title || "offre") + " » sur le site source", icon: "external-link" }, "Voir l’offre")));
    }
    if (!isNext && canTriage()) {
      var keepS = card.querySelector(".stamp-keep"), dropS = card.querySelector(".stamp-drop");
      U.draggable(card, {
        canStart: function () { return !flying; },
        onMove: function (dx) {
          keepS.style.opacity = String(Math.max(0, Math.min(1, dx / 90)));
          dropS.style.opacity = String(Math.max(0, Math.min(1, -dx / 90)));
        },
        onDecide: function (dir, release) { commit(dir > 0 ? "right" : "left", release); }
      });
    }
    return card;
  }

  /* The reason step sits above the buttons; the buttons stay (AUDIT P2-22), and the next
     decision closes it without a reason. */
  function hideReasons() {
    clearTimeout(reasonTimer);
    byId("tri-reasons-bar").hidden = true;
    reasonFor = null;
  }

  var reasonFor = null;
  function giveReason(label) {
    var item = reasonFor;
    hideReasons();
    if (!item || !label) return;
    T.postingsOf(item.row).slice(0, 1).forEach(function (p) {
      triDecide(p.key, label, typeof item.row.score === "number" ? item.row.score : null);
    });
    announce("Raison enregistrée : " + T.LABEL_TEXT[label]);
  }

  /* After a drop: why, in one tap or one key (1–4), for 8 seconds, named after the offer. */
  function showReasons(item) {
    var bar = byId("tri-reasons-bar");
    var list = byId("tri-reason-chips");
    var question = "Dernière offre écartée : " + (item.row.title || "offre sans titre");
    byId("tri-reasons-title").textContent = question;
    clear(list);
    X.REASONS.forEach(function (label, i) {
      var b = el("button", { type: "button", class: "chip-btn", "aria-keyshortcuts": String(i + 1) }, [T.LABEL_TEXT[label], U.kbd(String(i + 1))]);
      b.addEventListener("click", function () { giveReason(label); });
      list.appendChild(b);
    });
    var skip = el("button", { type: "button", class: "chip-btn ghost", text: "Passer" });
    skip.addEventListener("click", function () { hideReasons(); focusTriCard(); });
    list.appendChild(skip);
    reasonFor = item;
    bar.hidden = false;
    announce(question + ". Pourquoi\u00a0? Touches 1 à 4, ou la décision suivante pour passer.");
    clearTimeout(reasonTimer);
    reasonTimer = setTimeout(hideReasons, 8000);
  }

  /* right = keep (to_apply + good_fit), left = drop (ignored; the reason is optional).
     A group: keep its best posting, drop all of them (as the row's quick actions do).
     `release`: the drag's last position and speed, so the card leaves with its inertia. */
  var flying = null;  /* {anim, advance}: a new action lands the card in flight first */

  function commit(direction, release) {
    if (flying) { var f = flying; flying = null; f.anim.onfinish = null; f.advance(); }
    if (!canTriage() || tri.pos >= tri.items.length) return;
    hideReasons();
    var item = tri.items[tri.pos];
    var targets = direction === "right" ? [item.row] : T.postingsOf(item.row);
    var entry = { key: item.row.key, pos: tri.pos, direction: direction, prev: [], decisionIds: [] };
    targets.forEach(function (p) {
      var prev = track.apps[p.key];
      entry.prev.push({ key: p.key, rec: prev ? Object.assign({}, prev) : null });
      triSave(p.key, X.swipeRecord(prev, direction), prev);
    });
    undo.push(entry);
    var rule = X.SWIPE[direction];
    if (rule.label) triDecide(item.row.key, rule.label, typeof item.row.score === "number" ? item.row.score : null);
    if (direction === "right") tri.kept += 1; else tri.dropped += 1;
    announce((direction === "right" ? "Gardée : " : "Écartée : ") + (item.row.title || "offre"));
    var stage = byId("tri-stage");
    var card = stage.querySelector(".tcard:not(.is-next)");
    var hadFocus = !!(card && card.contains(document.activeElement));
    function advance() {
      flying = null;
      tri.pos += 1;
      triArrive = true;
      renderTri({ rise: true });
      /* No reason step on the end screen: it would ask about an offer no longer in view. */
      if (direction === "left" && byId("tri-end").hidden) showReasons(item);
      updateCounts();
      /* Focus was on the card that just left: give it to the new card, not to the page. */
      if (hadFocus) {
        if (stage.querySelector(".tcard:not(.is-next)")) focusTriCard();
        else byId("tri-end").focus({ preventScroll: true });
      }
    }
    if (card) {
      var stamp = card.querySelector(direction === "right" ? ".stamp-keep" : ".stamp-drop");
      if (stamp) stamp.style.opacity = "1";
    }
    var anim = card ? U.flyOut(card, direction === "right" ? 1 : -1, release) : null;
    if (anim) { flying = { anim: anim, advance: advance }; anim.onfinish = function () { if (flying && flying.anim === anim) advance(); }; }
    else advance();
  }

  function undoLast() {
    if (flying) { var f = flying; flying = null; f.anim.onfinish = null; f.advance(); }
    var entry = undo.pop();
    if (!entry) { announce("Rien à annuler."); return; }
    hideReasons();
    if (entry.direction === "right") tri.kept -= 1; else tri.dropped -= 1;
    entry.prev.forEach(function (p) {
      triSave(p.key, T.blank(p.rec), track.apps[p.key]);
      if (!p.rec) delete track.decisions[p.key];
    });
    entry.decisionIds.forEach(function (id) {
      api.undecide(id).catch(function (err) {
        if (X.retryable(err)) { retry.add({ kind: "undecide", payload: { id: id } }); renderPending(); }
      });
    });
    var item = tri.items[entry.pos];
    var back = false;
    if (item && T.rowStatus(item.row, track.apps) === "to_review") {
      tri.pos = entry.pos;
      tri.pausedAt = -1;
      back = true;
    }
    announce("Annulé.");
    triArrive = false;
    renderTri();
    updateCounts();
    if (back) {
      U.flyIn(byId("tri-stage").querySelector(".tcard:not(.is-next)"), entry.direction === "right" ? 1 : -1);
      focusTriCard();
    }
  }

  /* opts.rise: the card that was underneath comes up into place. */
  function renderTri(opts) {
    if (!tri.built) buildTri();
    var stage = byId("tri-stage");
    var end = byId("tri-end");
    var total = tri.items.length;
    clear(stage);
    var loading = track.status === "loading";
    var off = byId("tri-off");
    off.hidden = canTriage() || loading;
    ["tri-keep", "tri-drop"].forEach(function (id) { byId(id).disabled = !canTriage(); });
    if (loading) {
      byId("tri-count").textContent = "";
      byId("tri-left").textContent = "Chargement du suivi…";
      byId("tri-progress-bar").hidden = true;
      byId("tri-controls").hidden = false;
      stage.appendChild(el("div", { class: "tcard sk-card", "aria-hidden": "true" }, [
        el("span", { class: "sk", style: "width:30%;height:10px" }), el("span", { class: "sk", style: "width:75%;height:18px" }),
        el("span", { class: "sk", style: "width:90%;height:10px" }), el("span", { class: "sk sk-block" })
      ]));
      return;
    }
    var b = X.batchOf(Math.min(tri.pos, Math.max(total - 1, 0)), total, X.BATCH);
    var atBoundary = tri.pos > 0 && tri.pos < total && tri.pos % X.BATCH === 0 && tri.pausedAt !== tri.pos;
    var done = tri.pos >= total;
    byId("tri-progress-bar").hidden = total === 0;
    /* One prominent counter (this batch), the rest of the queue secondary (AUDIT P2-8). */
    var inBatch = done ? b.size : (atBoundary ? X.BATCH : tri.pos - b.start);
    var size = done ? b.size : (atBoundary ? X.BATCH : b.size);
    byId("tri-count").textContent = total ? (done ? "" : Math.min(inBatch + 1, size) + " / " + size) : "";
    byId("tri-left").textContent = total ? (b.count > 1 ? "lot " + (atBoundary ? b.index : b.index + 1) + " sur " + b.count + ", " : "") +
      Math.max(total - tri.pos, 0) + (total - tri.pos > 1 ? " restantes" : " restante") : "";
    if (total) {
      byId("tri-progress-fill").style.transform = "scaleX(" + (inBatch / Math.max(size, 1)) + ")";
      var bar = byId("tri-progress-bar");
      bar.setAttribute("aria-valuenow", String(inBatch));
      bar.setAttribute("aria-valuemax", String(size));
      bar.setAttribute("aria-valuetext", inBatch + " sur " + size + " dans ce lot");
    }
    end.hidden = !(done || atBoundary);
    if (!end.hidden) hideReasons();
    byId("tri-controls").hidden = done || atBoundary || total === 0;
    byId("tri-undo").disabled = undo.size() === 0;
    if (done || atBoundary) {
      clear(end);
      var session = tri.kept + (tri.kept > 1 ? " gardées, " : " gardée, ") + tri.dropped + (tri.dropped > 1 ? " écartées" : " écartée");
      var toApps = el("button", { type: "button", class: "button", text: "Voir mes candidatures" });
      toApps.addEventListener("click", function () { showTab("candidatures", true, true); });
      end.appendChild(U.icon("circle-check"));
      if (atBoundary) {
        end.appendChild(el("h2", { text: "Lot " + b.index + " terminé" }));
        end.appendChild(el("p", { text: session + " pendant cette session. " + (total - tri.pos) + " offres attendent encore." }));
        var next = el("button", { type: "button", class: "button primary", text: "Lot suivant" });
        next.addEventListener("click", function () { tri.pausedAt = tri.pos; triArrive = true; renderTri(); focusTriCard(); });
        end.appendChild(el("div", { class: "tri-end-actions" }, [next, toApps]));
        announce("Lot " + b.index + " sur " + b.count + " terminé.");
      } else {
        end.appendChild(el("h2", { text: "Tri terminé" }));
        end.appendChild(el("p", { text: total === 0
          ? "Aucune offre à examiner : tout est trié. Les nouvelles offres arrivent avec la prochaine exécution."
          : session + ". Les offres gardées attendent dans Candidatures." }));
        end.appendChild(el("div", { class: "tri-end-actions" }, [toApps]));
      }
      return;
    }
    /* The front card sizes the pile (up to the stage's height); the back card fills the same
       box from behind, so it peeks out below whatever the two descriptions' lengths. */
    var pile = el("div", { class: "tri-pile" });
    if (tri.items[tri.pos + 1]) pile.appendChild(triCard(tri.items[tri.pos + 1], true));
    var top = triCard(tri.items[tri.pos], false);
    pile.appendChild(top);
    stage.appendChild(pile);
    triArrive = false;
    if (opts && opts.rise) {
      U.rise(top);
      var under = stage.querySelector(".tcard.is-next");
      if (under && !U.reduced()) under.animate([{ opacity: 0 }, { opacity: 0.6 }], { duration: 200, easing: "ease-out" });
    }
  }

  byId("tri-keep").addEventListener("click", function () { commit("right"); });
  byId("tri-drop").addEventListener("click", function () { commit("left"); });
  byId("tri-undo").addEventListener("click", undoLast);

  /* Tri keys; the record panel's own controls keep their keys when focus is inside it. */
  function triKeys(ev) {
    if (record.contains(document.activeElement) || (recordOpen && !wideScreen())) return false;
    if (reasonFor && /^[1-4]$/.test(ev.key)) { giveReason(X.REASONS[Number(ev.key) - 1]); return true; }
    if (ev.key === "Escape" && reasonFor) { hideReasons(); return true; }
    /* The card scrolls inside itself: ↑ ↓, Page ↑ ↓ and Space move its text (← → decide). */
    var sc = byId("tri-stage").querySelector(".tcard:not(.is-next) .tcard-scroll");
    var step = { ArrowDown: 64, ArrowUp: -64, PageDown: 0.9, PageUp: -0.9, " ": 0.9 }[ev.key];
    if (sc && step !== undefined && !(ev.key === " " && ev.target && ev.target.closest && ev.target.closest("button, a"))) {
      var by = Math.abs(step) < 1 ? step * sc.clientHeight : step;
      sc.scrollBy({ top: ev.shiftKey && ev.key === " " ? -by : by, behavior: U.reduced() ? "auto" : "smooth" });
      return true;
    }
    if (ev.key === "ArrowRight") { commit("right"); return true; }
    if (ev.key === "ArrowLeft") { commit("left"); return true; }
    if (ev.key === "z" || ev.key === "Z") { undoLast(); return true; }
    if (ev.key === "Enter" && !(ev.target && ev.target.closest && ev.target.closest("a, button"))) {
      var item = tri.items[tri.pos];
      if (item && byId("tri-end").hidden) { openRecord(item.row, byId("tri-stage").querySelector(".tcard-title button")); return true; }
    }
    return false;
  }

  /* ---------- record panel (Attio): split at ≥ 1280 px, overlay below ---------- */

  var record = byId("record");
  var recordOpen = false, recordFor = null, recordJob = null, recordOpener = null;
  function wideScreen() { return !!(window.matchMedia && window.matchMedia("(min-width: 1280px)").matches); }

  /* Below 1280 px the record covers the page: what is under it is inert, so Tab stays inside. */
  function setInert() {
    var cover = recordOpen && !wideScreen();
    [byId("main"), document.querySelector(".sidebar"), byId("tabbar")].forEach(function (n) {
      if (n) { if (cover) n.setAttribute("inert", ""); else n.removeAttribute("inert"); }
    });
  }
  if (window.matchMedia) window.matchMedia("(min-width: 1280px)").addEventListener("change", setInert);

  function prop(iconName, label, value) {
    return el("div", { class: "prop" }, [el("dt", { icon: iconName }, label), el("dd", null, value)]);
  }

  /* Order (AUDIT P2-13): what the offer says, why it scored so, then the tracking. */
  function recordBody(j) {
    var box = el("div", { class: "record-scroll" });
    box.appendChild(el("header", { class: "record-head" }, [
      el("h2", { id: "record-title", tabindex: "-1", text: j.title || "—" }),
      el("p", { class: "record-sub", text: [j.company || "Entreprise non communiquée", j.location].filter(Boolean).join(", ") })
    ]));
    box.appendChild(el("dl", { class: "props" }, [
      prop("circle-dot", "Statut", el("span", { class: "band" }, [U.dot(STATUS_HUE[T.rowStatus(j, track.apps)]), T.STATUS_TEXT[T.rowStatus(j, track.apps)]])),
      prop("briefcase-business", "Contrat", j.contract || "Inconnu"),
      prop("timer", "Expérience", yearsText(j.required_years)),
      prop("calendar", "Publiée", j.posted_at ? fmtDate(j.posted_at) : "Date inconnue"),
      prop("git-branch", "Source", j.source || "—")
    ]));
    if (j.description_excerpt) {
      box.appendChild(el("section", { class: "record-sec record-desc" }, [el("h3", { text: "Description de l’offre" })].concat(D.render(D.parse(j.description_excerpt), el))));
    }
    box.appendChild(el("section", { class: "record-sec" }, [U.ledger(j, thresholds, { compact: true })]));
    var form = trackForm(j, "rec");
    var why = whyPanel(j, form.verdictBlock || null);
    why.open = true;
    box.appendChild(el("section", { class: "record-sec" }, [why]));
    if (j.postings) box.appendChild(el("section", { class: "record-sec" }, [postingsBlock(j)]));
    box.appendChild(el("section", { class: "record-sec" }, [el("h3", { text: "Suivi" }), form]));
    return box;
  }

  function openRecord(j, opener) {
    var was = recordOpen;
    recordOpener = opener || document.activeElement;
    function fill() {
      clear(record);
      var close = el("button", { type: "button", class: "icon-btn", "aria-label": "Fermer la fiche", "aria-keyshortcuts": "Escape" }, U.icon("x"));
      close.addEventListener("click", function () { closeRecord(); });
      var bar = el("div", { class: "record-bar" }, [el("span", { class: "record-crumb", text: VIEW_TITLE[currentTab] }), el("span", { class: "fill" })]);
      if (j.url && HTTP.test(j.url)) {
        bar.appendChild(el("a", { class: "icon-btn", href: j.url, target: "_blank", rel: "noopener noreferrer", "aria-label": "Voir l’offre « " + (j.title || "offre") + " » sur le site source" }, U.icon("external-link")));
      }
      bar.appendChild(close);
      record.appendChild(bar);
      record.appendChild(recordBody(j));
      record.hidden = false;
      record.classList.remove("closing");
      document.body.classList.add("record-open");
      recordOpen = true;
      recordFor = currentTab;
      recordJob = j;
      setInert();
      syncHash();
    }
    var shown = (!was && wideScreen()) ? U.transition(fill, ["record"]) : (fill(), Promise.resolve());
    shown.then(function () { var h = byId("record-title"); if (h) h.focus({ preventScroll: true }); });
  }

  function closeRecord(animate) {
    if (!recordOpen) return;
    var back = recordOpener;
    function done() {
      record.hidden = true;
      record.classList.remove("closing");
      clear(record);
      document.body.classList.remove("record-open");
      recordOpen = false;
      recordJob = null;
      setInert();
      syncHash();
    }
    recordOpen = false;
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
    var j = recordOpen ? recordJob : null;
    if (j && j.key && canTriage()) {
      var cur = T.statusOf(track.apps[j.key]);
      groups.push({ title: "Changer le statut", items: T.STATUSES.filter(function (s) { return s !== cur; }).map(function (s) {
        return { label: "Statut : " + T.STATUS_TEXT[s], hint: j.title, hue: STATUS_HUE[s], run: function () {
          setRecord(j.key, { status: s }, "Statut : " + T.STATUS_TEXT[s]);
          openRecord(j, recordOpener);
        } };
      }) });
    }
    groups.push({ title: "Aller à", items: TABS.map(function (t) {
      return { label: "Aller à " + VIEW_TITLE[t], icon: VIEW_ICON[t], keys: ["G", GO_KEYS[t]], run: function () { showTab(t, true, true); } };
    }) });
    var offers = q ? rows : tri.items.slice(tri.pos, tri.pos + 4).map(function (it) { return it.row; });
    groups.push({ title: q ? "Offres" : "À trier ensuite", limit: 6, items: offers.map(function (r) {
      return { label: r.title || "—", hint: r.company || "", score: typeof r.score === "number" ? r.score : null, icon: "briefcase-business",
        text: [r.title, r.company, r.location].filter(Boolean).join(" "), run: function () { openRecord(r, null); } };
    }) });
    var actions = [{ label: "Raccourcis clavier", icon: "keyboard", keys: ["?"], run: function () { P.openHelp(); } }];
    if (currentTab === "tri" && undo.size()) actions.unshift({ label: "Annuler la dernière décision", icon: "undo-2", keys: ["Z"], run: undoLast });
    groups.push({ title: "Actions", items: actions });
    return groups;
  }

  var HELP = [
    ["Général", [[[MOD, "K"], "Palette de commandes"], [["?"], "Cette aide"], [["G", "T"], "Aller au Tri"], [["G", "C"], "Aller aux Candidatures"],
      [["G", "O"], "Aller aux Offres"], [["G", "L"], "Aller aux Leads"], [["G", "E"], "Aller aux Exécutions"], [["Échap"], "Fermer la fiche ou la palette"]]],
    ["Tri", [[["→"], "Garder"], [["←"], "Écarter"], [["Z"], "Annuler la dernière décision"], [["1–4"], "Raison de l’écart"], [["↵"], "Ouvrir la fiche"], [["↑", "↓"], "Faire défiler la carte"]]],
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
    if (currentTab === "tri" && triKeys(ev)) { ev.preventDefault(); return; }
    if (ev.key === "Escape" && recordOpen) { ev.preventDefault(); closeRecord(); }
  });

  /* ---------- Candidatures ---------- */

  var drag = null;

  function addDays(day, n) {
    var d = new Date(day + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  var DAY_SHORT = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", timeZone: "UTC" });
  /* A calendar day (YYYY-MM-DD) as "28/10": read as UTC so no time zone moves it a day. */
  function shortDay(day) { return T.isDay(day) ? DAY_SHORT.format(new Date(day + "T00:00:00Z")) : ""; }

  function setRecord(key, patch, done, ask) {
    var prev = T.blank(track.apps[key]);
    applyChanges([{ key: key, next: Object.assign({}, prev, patch) }], done, [{ key: key, next: prev }], ask);
  }

  /* The follow-up question after "J'ai postulé". It lives in the toast: the card has already
     moved to another column, often off-screen. */
  function followUpAsk(key, appliedOn) {
    var suggested = addDays(appliedOn, 7);
    function plan(day) {
      setRecord(key, { follow_up_at: day }, "Relance prévue le " + shortDay(day));
    }
    function otherDate() {
      var input = el("input", { type: "date", name: "follow_up_at", value: suggested, min: appliedOn, "aria-label": "Date de relance", autocomplete: "off" });
      function save() {
        if (!T.isDay(input.value)) { input.focus(); return; }
        plan(input.value);
      }
      input.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") { ev.preventDefault(); save(); }
      });
      showToast("Relance le", [
        { text: "Enregistrer", run: save, keep: true },
        { text: "Non", run: function () {} }
      ], { hold: true, onEscape: function () {} });
      toastActions.insertBefore(input, toastActions.firstChild);
      input.focus();
    }
    return {
      text: "Relance ?",
      actions: [
        { text: "Relancer le " + shortDay(suggested), run: function () { plan(suggested); } },
        { text: "Autre date", run: otherDate, keep: true },
        { text: "Non", run: function () {} }
      ],
      onEscape: function () {}
    };
  }

  function appCard(key, today) {
    var app = track.apps[key];
    var status = T.statusOf(app);
    var j = postingByKey[key];
    var card = el("article", { class: "kb-card", "data-key": key, tabindex: "-1" });
    card.appendChild(el("h4", { class: "kb-title", text: j ? (j.title || "—") : key }));
    card.appendChild(el("p", { class: "kb-meta", text: j ? [j.company || "—", j.location || ""].filter(Boolean).join(" · ") : "offre plus affichée" }));
    var dates = [];
    if (app.applied_at) dates.push("Envoyée le " + shortDay(app.applied_at));
    if (app.follow_up_at) {
      var late = T.isDue(app, today) ? T.daysBetween(app.follow_up_at, today) : 0;
      dates.push("Relance le " + shortDay(app.follow_up_at) + (late > 0 ? " (" + late + " j de retard)" : T.isDue(app, today) ? " (aujourd’hui)" : ""));
    }
    if (dates.length) card.appendChild(el("p", { class: "kb-dates" + (T.isDue(app, today) ? " is-due" : ""), text: dates.join(" · ") }));

    var actions = el("div", { class: "kb-actions" });
    var sel = el("select", { class: "kb-status", name: "status", "aria-label": "Statut de " + (j ? j.title : key) });
    T.STATUSES.forEach(function (s) { sel.appendChild(el("option", { value: s, text: BOARD_TEXT[s] || T.STATUS_TEXT[s] })); });
    sel.value = status;
    sel.addEventListener("change", function () {
      setRecord(key, { status: sel.value }, "Déplacée vers « " + (BOARD_TEXT[sel.value] || T.STATUS_TEXT[sel.value]) + " »");
    });
    actions.appendChild(sel);
    if (status === "to_apply") {
      var applied = el("button", { type: "button", class: "btn btn-primary btn-small", text: "J’ai postulé" });
      applied.addEventListener("click", function () {
        setRecord(key, { status: "applied", applied_at: today }, "Candidature envoyée le " + shortDay(today),
          followUpAsk(key, today));
      });
      actions.appendChild(applied);
    }
    if (j && j.url && HTTP.test(j.url)) actions.appendChild(el("a", { href: j.url, target: "_blank", rel: "noopener noreferrer", "aria-label": "Voir l’offre : " + (j.title || key), text: "Offre" }));
    card.appendChild(actions);
    if (window.matchMedia("(pointer: fine)").matches) attachDrag(card, key);
    return card;
  }

  /* Desktop drag between columns, Pointer Events (no HTML5 drag and drop). The status menu
     on each card does the same with the keyboard or a finger. */
  function attachDrag(card, key) {
    card.addEventListener("pointerdown", function (ev) {
      if (ev.button !== 0 || ev.target.closest("a, button, select, input")) return;
      drag = { key: key, card: card, x: ev.clientX, y: ev.clientY, id: ev.pointerId, moved: false };
      card.setPointerCapture(ev.pointerId);
    });
    card.addEventListener("pointermove", function (ev) {
      if (!drag || drag.card !== card) return;
      var dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 6) return;
      drag.moved = true;
      document.body.classList.add("is-dragging-card");
      card.classList.add("is-dragging");
      card.style.transform = "translate(" + dx + "px," + dy + "px)";
      card.style.pointerEvents = "none";
      var under = document.elementFromPoint(ev.clientX, ev.clientY);
      var col = under && under.closest ? under.closest(".kb-col") : null;
      document.querySelectorAll(".kb-col.is-over").forEach(function (c) { if (c !== col) c.classList.remove("is-over"); });
      if (col) col.classList.add("is-over");
      card.style.pointerEvents = "";
    });
    function end(ev) {
      if (!drag || drag.card !== card) return;
      var was = drag;
      drag = null;
      document.body.classList.remove("is-dragging-card");
      card.classList.remove("is-dragging");
      card.style.transform = "";
      var col = document.querySelector(".kb-col.is-over");
      document.querySelectorAll(".kb-col.is-over").forEach(function (c) { c.classList.remove("is-over"); });
      if (!was.moved || !col || ev.type === "pointercancel") return;
      var status = col.getAttribute("data-status");
      if (status && status !== T.statusOf(track.apps[key])) {
        setRecord(key, { status: status }, "Déplacée vers « " + BOARD_TEXT[status] + " »");
      }
    }
    card.addEventListener("pointerup", end);
    card.addEventListener("pointercancel", end);
  }

  function renderApps() {
    var today = T.localDay();
    var board = byId("kb-board");
    var due = byId("kb-due");
    clear(board);
    clear(due);
    byId("kb-off").hidden = canTriage() || track.status === "loading";
    var keys = boardKeys();
    var dueKeys = Object.keys(track.apps).filter(function (k) { return T.isDue(track.apps[k], today); })
      .sort(function (a, b) { return track.apps[a].follow_up_at < track.apps[b].follow_up_at ? -1 : 1; });
    due.hidden = dueKeys.length === 0;
    if (dueKeys.length) {
      due.appendChild(el("h3", { class: "kb-due-title", text: "Relances dues (" + dueKeys.length + ")" }));
      var list = el("ul", { class: "kb-due-list" });
      dueKeys.forEach(function (k) {
        var app = track.apps[k];
        var j = postingByKey[k];
        var late = T.daysBetween(app.follow_up_at, today);
        var go = el("button", { type: "button", class: "link-btn", text: j ? (j.title || k) : k });
        go.addEventListener("click", function () {
          var target = board.querySelector('.kb-card[data-key="' + (window.CSS && CSS.escape ? CSS.escape(k) : k) + '"]');
          if (target) { target.scrollIntoView({ block: "center" }); target.focus({ preventScroll: true }); }
        });
        list.appendChild(el("li", null, [go, el("span", { class: "kb-due-late", text: late > 0 ? late + " j de retard" : "aujourd’hui" })]));
      });
      due.appendChild(list);
    }
    BOARD.forEach(function (status) {
      var inCol = keys.filter(function (k) { return T.statusOf(track.apps[k]) === status; })
        .sort(function (a, b) {
          var da = T.isDue(track.apps[a], today) ? 0 : 1, db = T.isDue(track.apps[b], today) ? 0 : 1;
          if (da !== db) return da - db;
          return String(track.apps[b].updated_at || "").localeCompare(String(track.apps[a].updated_at || ""));
        });
      var col = el("section", { class: "kb-col kb-" + status, "data-status": status, "aria-label": BOARD_TEXT[status] });
      col.appendChild(el("h3", { class: "kb-col-title" }, [BOARD_TEXT[status] + " ", el("span", { class: "tab-count", text: String(inCol.length) })]));
      var body = el("div", { class: "kb-col-body" });
      inCol.forEach(function (k) { body.appendChild(appCard(k, today)); });
      if (!inCol.length) body.appendChild(el("p", { class: "kb-empty", text: status === "to_apply" ? "Garde des offres dans Tri pour les voir ici." : "Aucune." }));
      col.appendChild(body);
      board.appendChild(col);
    });
    updateCounts();
  }

  function renderCurrent() {
    if (currentTab === "tri") renderTri();
    else if (currentTab === "candidatures") renderApps();
    updateCounts();
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
    var fiche = p.fiche && rowByKey(p.fiche);
    if (fiche && (!recordOpen || recordJob !== fiche)) openRecord(fiche, null);
    else if (!p.fiche && recordOpen) closeRecord(false);
    applyingHash = false;
    syncHash();
  }

  /* The listed row (a group's best posting stands for the group) that holds this key. */
  function rowByKey(key) {
    for (var i = 0; i < rows.length; i++) {
      if (T.postingsOf(rows[i]).some(function (p) { return p.key === key; })) return rows[i];
    }
    return null;
  }

  /* ---------- leads ---------- */

  function leadDetails(l) {
    var td = el("td", { colspan: "7" });
    var box = el("div", { class: "details" });
    var meta = [];
    if (l.reason) meta.push(l.reason);
    if (l.country) meta.push(l.country);
    if (l.source) meta.push("source : " + l.source);
    if (l.article_title) meta.push(l.article_title);
    box.appendChild(el("p", { class: "meta", text: meta.join(" · ") }));
    var grid = el("div", { class: "details-grid" });
    var left = el("div");
    left.appendChild(el("h3", { text: "Preuves" }));
    var keys = Object.keys(l.evidence || {});
    if (keys.length) {
      left.appendChild(el("ul", null, keys.map(function (k) {
        return el("li", null, [el("b", { text: k + ": " }), l.evidence[k]]);
      })));
    } else {
      left.appendChild(el("p", { class: "note", text: "Aucune phrase de preuve enregistrée." }));
    }
    grid.appendChild(left);
    var right = el("div");
    if (l.investors && l.investors.length) {
      right.appendChild(el("h3", { text: "Investisseurs" }));
      right.appendChild(el("div", { class: "tags" }, l.investors.map(function (t) { return el("span", { class: "tag", text: t }); })));
    }
    right.appendChild(el("h3", { text: "Offres éligibles ouvertes" }));
    right.appendChild(el("p", { class: "note", text: String(l.open_jobs || 0) + " offre(s) éligible(s) de cette entreprise dans la fenêtre de déduplication" }));
    grid.appendChild(right);
    box.appendChild(grid);
    td.appendChild(box);
    return el("tr", { class: "details", id: "lead-details-" + l.id }, td);
  }

  function renderLeads() {
    var body = byId("leads-body");
    clear(body);
    byId("leads-rowcount").textContent = leads.length + " leads de financement · priorité haute d’abord";
    byId("leads-empty").hidden = leads.length > 0;
    var frag = document.createDocumentFragment();
    leads.forEach(function (l) {
      var row = el("tr", { class: "row", tabindex: "0", "aria-expanded": "false" });
      var btn = el("button", { type: "button", class: "expand", "aria-expanded": "false", "aria-controls": "lead-details-" + l.id },
        [el("span", { class: "dot " + (l.priority === "high" ? "dot-strong" : ""), "aria-hidden": "true" }), el("span", { class: "title-text", text: l.company || "—" })]);
      row.appendChild(cell("col-title", "Entreprise", btn));
      row.appendChild(cell("col-priority", "Priorité", el("span", { class: "badge" + (l.priority === "high" ? " badge-high" : ""), text: l.priority === "high" ? "haute" : "normale" })));
      var raise = [fmtAmount(l.amount, l.currency), l.round].filter(Boolean).join(" · ");
      row.appendChild(cell("col-raise", "Levée", raise ? el("span", { class: "mono", text: raise }) : el("span", { class: "unknown", text: "—" })));
      row.appendChild(cell("col-hiring", "Recrutement", l.hiring ? l.hiring : el("span", { class: "unknown", text: "—" })));
      row.appendChild(cell("num col-open", "Offres", el("span", { class: "mono", text: String(l.open_jobs || 0) })));
      row.appendChild(dateCell("col-date", "Publiée", l.published_at || l.created_at));
      row.appendChild(cell("link-col", "Article", link(l.article_url, "Lire")));
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
    byId("runs-rowcount").textContent = runs.length + " dernières exécutions · la plus récente d’abord";
    byId("runs-empty").hidden = runs.length > 0;
    runs.forEach(function (r) {
      var card = el("article", { class: "run" });
      var head = el("div", { class: "run-head" });
      head.appendChild(el("span", { class: "run-date", text: fmtDateTime(r.started_at) }));
      if (r.pipeline === "jobs_reprocess") head.appendChild(el("span", { class: "badge badge-reprocess", text: "retraitement" }));
      if (r.errors) head.appendChild(el("span", { class: "badge", text: r.errors + " erreur(s)" }));
      head.appendChild(el("span", { class: "run-fetched" }, [r.pipeline === "jobs_reprocess" ? "lues " : "récupérées ", el("b", { text: String(r.fetched) })]));
      card.appendChild(head);

      var total = r.fetched || 0;
      var funnel = el("div", { class: "funnel" });
      funnel.appendChild(seg("seg-rejected", r.rejected, total, "Rejetées"));
      funnel.appendChild(seg("seg-duplicates", r.duplicates, total, r.pipeline === "jobs_reprocess" ? "Nouveaux doublons" : "Doublons"));
      var strongInner = el("i", { title: "Fortes : " + r.strong });
      strongInner.style.width = r.eligible > 0 ? (100 * r.strong / r.eligible) + "%" : "0%";
      funnel.appendChild(seg("seg-eligible", r.eligible, total, "Éligibles (" + r.strong + " fortes)", strongInner));
      funnel.appendChild(seg("seg-stretch", r.stretch, total, "À tenter"));
      card.appendChild(funnel);

      var stats = el("p", { class: "run-stats" });
      stats.appendChild(stat("rejetées", r.rejected));
      stats.appendChild(stat(r.pipeline === "jobs_reprocess" ? "nouveaux liens" : "doublons", r.duplicates));
      stats.appendChild(stat("éligibles", r.eligible));
      stats.appendChild(stat("fortes", r.strong));
      stats.appendChild(stat("à tenter", r.stretch));
      if (r.api_calls) stats.appendChild(stat("appels API", r.api_calls));
      if (r.checked) stats.appendChild(stat("vérifiées à la source", r.checked));
      if (r.closed) stats.appendChild(stat("fermées", r.closed));
      if (r.self_links_dropped) stats.appendChild(stat("auto-liens supprimés", r.self_links_dropped));
      if (r.stale_links_dropped) stats.appendChild(stat("liens obsolètes supprimés", r.stale_links_dropped));
      card.appendChild(stats);

      var reasons = Object.keys(r.rejected_by_reason || {}).sort(function (a, b) {
        return r.rejected_by_reason[b] - r.rejected_by_reason[a];
      });
      if (reasons.length) {
        var p = el("p", { class: "run-reasons" }, ["Rejets par motif (une offre peut échouer à plusieurs filtres) : "]);
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
            el("b", { text: String(s.fetched || 0) }), " récupérées, ",
            el("b", { text: String(s.eligible || 0) }), " éligibles, ",
            el("b", { text: String(s.calls || 0) }), " appels"
          ]));
        });
        card.appendChild(sp);
      }
      list.appendChild(card);
    });
  }

  /* ---------- boot ---------- */

  /* Short in the sidebar; the full date and time zone in the tooltip. */
  var snap = byId("generated-at");
  var snapAt = new Date(data.generated_at);
  snap.textContent = isNaN(snapAt.getTime()) ? "Instantané" : "Instantané du " + snapAt.toLocaleString("fr-FR", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC"
  });
  snap.title = "Données générées le " + fmtDateTime(data.generated_at);
  setCount("offres", rows.length);
  setCount("leads", leads.length);
  setCount("executions", runs.length);

  var paletteBtn = byId("palette-btn");
  paletteBtn.insertBefore(U.icon("search"), paletteBtn.firstChild);
  paletteBtn.appendChild(U.kbd(MOD, "K"));
  paletteBtn.addEventListener("click", function () { P.open(); });
  byId("help-btn").addEventListener("click", function () { P.openHelp(); });
  P.init(paletteCommands, HELP);
  byId("tri-drop").insertBefore(U.icon("x"), byId("tri-drop").firstChild);
  byId("tri-drop").appendChild(U.kbd("←"));
  byId("tri-undo").appendChild(U.icon("undo-2"));
  byId("tri-undo").appendChild(U.kbd("Z"));
  byId("tri-keep").insertBefore(U.icon("check"), byId("tri-keep").firstChild);
  byId("tri-keep").appendChild(U.kbd("→"));
  fillDepartments();
  fillStatuses();
  renderLeads();
  renderRuns();
  if (window.innerWidth <= 768) byId("jobs-controls").removeAttribute("open");
  updateCounts();
  renderPending();  /* actions left from an earlier visit show at once */
  applyHash();
  loadTracking();
})();
