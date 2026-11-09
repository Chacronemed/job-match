/* Candidatures: the Kanban and table views, the inbox of recruiter replies (ADR 0018), the
   documents (ADR 0017) and their rendering in the browser (ADR 0019). */
(function (JM) {
  "use strict";

  /* From the other files (app.js first; the screens after it): values are read once,
     functions through the namespace at call time, so the load order never matters. */
  var BOARD = JM.BOARD;
  var BOARD_TEXT = JM.BOARD_TEXT;
  var HTTP = JM.HTTP;
  var T = JM.T;
  var V = JM.v;
  var aiOf = function () { return JM.aiOf.apply(null, arguments); };
  var api = JM.api;
  var applyChanges = function () { return JM.applyChanges.apply(null, arguments); };
  var boardKeys = function () { return JM.boardKeys.apply(null, arguments); };
  var byId = function () { return JM.byId.apply(null, arguments); };
  var canTriage = function () { return JM.canTriage.apply(null, arguments); };
  var clear = JM.clear;
  var el = JM.el;
  var failureText = function () { return JM.failureText.apply(null, arguments); };
  var fmtShortDate = function () { return JM.fmtShortDate.apply(null, arguments); };
  var loadTracking = function () { return JM.loadTracking.apply(null, arguments); };
  var openRecord = function () { return JM.openRecord.apply(null, arguments); };
  var postingByKey = JM.postingByKey;
  var refreshBadges = function () { return JM.refreshBadges.apply(null, arguments); };
  var showToast = function () { return JM.showToast.apply(null, arguments); };
  var toastActions = JM.toastActions;
  var track = JM.track;
  var updateCounts = function () { return JM.updateCounts.apply(null, arguments); };
  function requestDocuments(key, button, onDone) {
    button.disabled = true;
    api.regenerate(key).then(function (res) {
      track.documents[key] = res.document;
      if (onDone) onDone(res.document);
      showToast("Génération lancée : les liens apparaissent ici dans une à deux minutes.");
      watchDocuments([key]);
    }).catch(function (err) {
      button.disabled = false;
      showToast(err && err.status === 409 ? "Une génération est déjà en cours." : "Demande refusée.");
    });
  }

  /* Rendering in the browser (ADR 0019). The Worker's own render.js is served as a module
     (assets/render.js); its three libraries (pdf-lib, fontkit, fflate, browser builds in
     vendor/) and the two Latin Inter TTFs (fonts/, already reduced at build time) are fetched
     once: in the background when Candidatures opens (preloadRenderer), else on the first click.
     Everything is same-origin (CSP script-src 'self'). The contact details come from
     content.json's `contact` (R2), the text from `content`, the facts from `master`.
     Each step is timed with the User Timing API (performance.getEntriesByType("measure")):
     "jm:libs", "jm:module", "jm:fonts", "jm:content", "jm:render:pdf|docx", "jm:download". */
  var VENDOR_SCRIPTS = ["vendor/pdf-lib.min.js", "vendor/fontkit.umd.min.js", "vendor/fflate.js"];
  var PDF_FONT_FILES = ["fonts/Inter-Regular-latin.ttf", "fonts/Inter-Bold-latin.ttf"];
  var renderer = { libs: null, module: null, fonts: null };
  function measure(name, start, detail) {
    try { performance.measure(name, { start: start, end: performance.now(), detail: detail || null }); } catch (e) { /* no User Timing L3 */ }
  }
  /* A promise kept in `renderer[slot]`, timed once, forgotten on failure (a later call retries). */
  function once(slot, name, make) {
    if (!renderer[slot]) {
      var t0 = performance.now();
      renderer[slot] = make().then(function (v) { measure(name, t0); return v; }, function (err) { renderer[slot] = null; throw err; });
    }
    return renderer[slot];
  }
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var tag = el("script", { src: src });
      tag.addEventListener("load", function () { resolve(); });
      tag.addEventListener("error", function () { reject(new Error("script " + src)); });
      document.head.appendChild(tag);
    });
  }
  /* The renderer module; it reads the three UMD globals when it loads (they are independent
     of each other, so they load in parallel). */
  function loadModule() {
    return once("module", "jm:module", function () {
      return once("libs", "jm:libs", function () { return Promise.all(VENDOR_SCRIPTS.map(loadScript)); })
        .then(function () { return import("./assets/render.js"); });
    });
  }
  function loadFonts() {
    return once("fonts", "jm:fonts", function () {
      return Promise.all(PDF_FONT_FILES.map(api.bytes)).then(function (b) { return { regular: b[0], bold: b[1] }; });
    });
  }
  /* When Candidatures opens: the libraries and the fonts while the browser is idle, so the
     first ⬇ waits only for its content.json and the layout. A failure here is silent: the
     click loads them again and reports it. */
  var preloadAsked = false;
  function preloadRenderer() {
    if (preloadAsked) return;
    preloadAsked = true;
    var idle = window.requestIdleCallback || function (fn) { return setTimeout(fn, 200); };
    idle(function () {
      loadModule().catch(function () {});
      loadFonts().catch(function () {});
    }, { timeout: 2000 });
  }
  /* content.json per version, kept for the session (a version never changes), fetched as soon
     as the pointer or the focus reaches a ⬇ link, so it is often there before the click. */
  var bundles = {};
  function loadBundle(key, version) {
    var k = key + "|v" + version;
    if (!bundles[k]) {
      var t0 = performance.now();
      bundles[k] = api.content(key, version).then(function (b) { measure("jm:content", t0, k); return b; }, function (err) { delete bundles[k]; throw err; });
    }
    return bundles[k];
  }
  function prefetchBundle(key, version) {
    loadBundle(key, version).catch(function () {});
  }
  /* One file of one version: the bundle -> the template's model -> bytes, named by the
     template (fileName). `kind` is cv | letter, `ext` pdf | docx: only that file is rendered. */
  function renderDocument(bundle, kind, ext, R, fonts) {
    var t0 = performance.now();
    var now = new Date();
    var model = kind === "cv" ? R.cvModel(bundle.content, bundle.master, bundle.contact) : R.letterModel(bundle.content, bundle.contact, now);
    var company = bundle.content.offer ? bundle.content.offer.company : "";
    /* the same names renderAll gives: CV_, Lettre_ or Cover_letter_ */
    var label = kind === "cv" ? "CV" : (model.language === "en" ? "Cover_letter" : "Lettre");
    var name = R.fileName(label, bundle.contact, company, ext);
    var bytes;
    if (ext === "pdf") bytes = kind === "cv" ? R.renderCvPdf(model, fonts) : R.renderLetterPdf(model, fonts);
    else bytes = kind === "cv" ? R.renderCvDocx(model) : R.renderLetterDocx(model);
    return Promise.resolve(bytes).then(function (b) {
      measure("jm:render:" + ext, t0, kind);
      return { name: name, bytes: b, type: R.MIME[ext] };
    });
  }
  /* The files rendered this session, by key + version + kind + format (+ the day for the
     letter, which is dated): a second click saves the same bytes at once. The DOCX does not
     wait for the PDF fonts. */
  var rendered = {};
  function renderedFile(key, version, kind, ext) {
    var k = [key, "v" + version, kind, ext, kind === "letter" ? new Date().toDateString() : ""].join("|");
    if (!rendered[k]) {
      var ready = [loadBundle(key, version), loadModule()];
      if (ext === "pdf") ready.push(loadFonts());
      rendered[k] = Promise.all(ready).then(function (r) {
        return renderDocument(r[0], kind, ext, r[1], r[2]);
      }).catch(function (err) { delete rendered[k]; throw err; });
    }
    return rendered[k];
  }
  function saveBlob(file) {
    var url = URL.createObjectURL(new Blob([file.bytes], { type: file.type }));
    var a = el("a", { href: url, download: file.name });
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { a.remove(); URL.revokeObjectURL(url); }, 1000);
  }
  function downloadDocument(key, version, kind, ext, link) {
    if (link.getAttribute("aria-busy") === "true") return;
    var t0 = performance.now();
    var text = link.textContent;
    link.setAttribute("aria-busy", "true");
    link.textContent = "Rendu…";
    renderedFile(key, version, kind, ext).then(function (file) {
      saveBlob(file);
      measure("jm:download", t0, kind + "." + ext);
    }).catch(function (err) {
      showToast("Document non téléchargé (" + failureText(err) + ")");
    }).then(function () {
      link.removeAttribute("aria-busy");
      link.textContent = text;
    });
  }

  /* After « Générer » the Worker runs the pass at once: the table refreshes its documents
     every WATCH_MS while one of the watched offers is pending or running, WATCH_MAX times at
     most (two minutes), quietly (no loading state, nothing else of the tracking is touched).
     `window.__jmWatchMs` shortens the interval for the browser tests only. */
  var WATCH_MS = 10000, WATCH_MAX = 12;
  var watch = { keys: {}, timer: null, ticks: 0 };
  function watchDocuments(keys) {
    (keys || []).forEach(function (k) { watch.keys[k] = true; });
    if (watch.timer || !Object.keys(watch.keys).length) return;
    watch.ticks = 0;
    var ms = typeof window.__jmWatchMs === "number" ? window.__jmWatchMs : WATCH_MS;
    watch.timer = setTimeout(watchTick, ms);
    function watchTick() {
      watch.timer = null;
      watch.ticks += 1;
      api.list().then(function (res) {
        var documents = {};
        (res.documents || []).forEach(function (d) { if (d && typeof d.job_key === "string") documents[d.job_key] = d; });
        track.documents = documents;
        track.budget = res.documents_budget && typeof res.documents_budget === "object" ? res.documents_budget : null;
        if (V.tab === "candidatures") renderApps();
        var left = T.inProgress(track.documents, Object.keys(watch.keys));
        watch.keys = {};
        left.forEach(function (k) { watch.keys[k] = true; });
        if (left.length && watch.ticks < WATCH_MAX) watch.timer = setTimeout(watchTick, ms);
        else watch.keys = {};
      }).catch(function () { watch.keys = {}; });  /* the toast's « Actualiser » remains */
    }
  }

  /* The generated CV + letter (ADR 0017): the latest version's status, and a new version on
     demand. */
  function documentsBlock(j) {
    var doc = track.documents[j.key] || null;
    var state = el("span", { class: "doc-state", role: "status", text: T.docText(doc) });
    var button = el("button", { type: "button", class: "btn", text: doc ? "Regénérer" : "Générer le CV et la lettre" });
    var busy = doc && (doc.status === "pending" || doc.status === "running");
    if (busy) button.disabled = true;
    button.addEventListener("click", function () {
      requestDocuments(j.key, button, function (d) { state.textContent = T.docText(d); });
    });
    /* an expired offer: nothing to (re)generate */
    var expired = track.apps[j.key] && T.isExpired(track.apps[j.key], postingByKey[j.key]);
    var row = el("div", { class: "doc-row" }, [state, expired ? el("span", { class: "apps-expired-note", text: "Offre expirée" }) : button]);
    var links = T.documentLinks(j.key, doc);
    if (links) {
      row.appendChild(el("span", { class: "doc-links" }, [el("span", { text: "CV :" }), fileCell(links, "cv", doc, "CV", j.key)]));
      row.appendChild(el("span", { class: "doc-links" }, [el("span", { text: "Lettre :" }), fileCell(links, "letter", doc, "Lettre", j.key)]));
    }
    var parts = [el("h3", { text: "Documents" }), row];
    if (links) parts.push(kitBlock(j, links));
    return el("div", { class: "documents" }, parts);
  }

  /* The answer kit (ADR 0023): the model's two answers from content.json, the availability
     from the master, the fixed answers and the salary rule from apply.json, built by the
     Worker's own kit.js (assets/kit.js). A salary in `manuel` has no value and no « Copier »:
     only the zone's benchmark. « Candidature envoyée » once I have sent it myself. */
  var kitModule = null;
  function loadKit() {
    if (!kitModule) kitModule = import("./assets/kit.js").catch(function (err) { kitModule = null; throw err; });
    return kitModule;
  }
  function copyText(text, button) {
    var done = function () { showToast("Copié"); button.textContent = "Copié"; setTimeout(function () { button.textContent = "Copier"; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { showToast("Copie refusée par le navigateur"); });
    } else {
      showToast("Copie impossible dans ce navigateur");
    }
  }
  function kitBlock(j, links) {
    var list = el("dl", { class: "kit-list" });
    var state = el("p", { class: "kit-state", role: "status", text: "Kit de réponses : chargement…" });
    var box = el("div", { class: "kit", "data-kit": j.key }, [el("h4", { text: "Kit de réponses" }), state, list]);
    Promise.all([loadBundle(j.key, links.version), loadKit()]).then(function (r) {
      var bundle = r[0];
      var items = r[1].answerKit(bundle.content, bundle.master, bundle.apply || null, new Date(), j.location || "");
      state.remove();
      items.forEach(function (it) {
        var dd = el("dd", { class: "kit-item", "data-kit-key": it.key });
        if (it.text) dd.appendChild(el("span", { class: "kit-text", text: it.text }));
        if (it.note) dd.appendChild(el("span", { class: "kit-note", text: it.note }));
        if (it.copy && it.text) {
          var b = el("button", { type: "button", class: "btn btn-sm kit-copy", "aria-label": "Copier : " + it.label, text: "Copier" });
          b.addEventListener("click", function () { copyText(it.text, b); });
          dd.appendChild(b);
        }
        list.appendChild(el("dt", { text: it.label + (it.key === "salary" ? (it.mode === "manuel" ? " (manuel)" : " (fourchette)") : "") }));
        list.appendChild(dd);
      });
    }).catch(function (err) {
      state.textContent = "Kit de réponses indisponible (" + failureText(err) + ")";
    });
    var app = track.apps[j.key];
    if (!app || (app.status !== "applied" && app.status !== "interview")) {
      var sent = el("button", { type: "button", class: "btn btn-primary btn-small kit-sent", text: "Candidature envoyée" });
      sent.addEventListener("click", function () {
        var today = T.localDay(new Date());
        var follow = addDays(today, 7);
        sent.disabled = true;
        setRecord(j.key, { status: "applied", applied_at: today, follow_up_at: follow },
          "Candidature envoyée le " + shortDay(today) + " · relance le " + shortDay(follow));
      });
      box.appendChild(el("p", { class: "kit-actions" }, [sent]));
    }
    return box;
  }

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

  /* Days since the record last changed (its `updated_at`, the only clock D1 keeps). */
  function daysInStatus(app, today) {
    var at = app && typeof app.updated_at === "string" ? app.updated_at.slice(0, 10) : "";
    if (!T.isDay(at)) return null;
    return Math.max(0, T.daysBetween(at, today));
  }

  /* The hue of a card's company dot: the column's own. */
  var STATUS_DOT = { to_apply: "var(--accent-ink)", applied: "var(--blue-11)", interview: "var(--green-11)", rejected: "var(--red-11)" };

  /* An application whose offer left the snapshot: its source in words, never its raw key
     (the key stays in the tooltip). IMPECCABLE_AUDIT C3. */
  var GONE_SOURCE = { france_travail: "France Travail", adzuna: "Adzuna", jooble: "Jooble", ats: "pages carrière" };
  function goneTitle(key) {
    var src = GONE_SOURCE[String(key).split(":")[0]];
    return "Offre retirée" + (src ? " (" + src + ")" : "");
  }

  function appCard(key, today) {
    var app = track.apps[key];
    var status = T.statusOf(app);
    var j = postingByKey[key];
    var card = el("article", { class: "kb-card", "data-key": key, tabindex: "-1" });
    card.appendChild(el("h3", { class: "kb-title", title: j ? (j.title || null) : key, text: j ? (j.title || "—") : goneTitle(key) }));
    var meta = el("p", { class: "kb-meta" + (j ? "" : " is-gone"), text: j ? [j.company || "Entreprise non communiquée", j.location || ""].filter(Boolean).join(" · ") : "plus dans la liste des offres" });
    meta.style.setProperty("--hue", j ? (STATUS_DOT[status] || "var(--ink-3)") : "var(--ink-3)");
    card.appendChild(meta);
    var dates = [];
    var since = daysInStatus(app, today);
    if (since !== null) dates.push(since === 0 ? "Dans cette colonne depuis aujourd’hui" : "Dans cette colonne depuis " + since + "\u00a0j");
    if (app.applied_at) dates.push("Envoyée le " + shortDay(app.applied_at));
    if (app.interview_at) dates.push("Entretien le " + shortDay(app.interview_at));
    if (dates.length) card.appendChild(el("p", { class: "kb-dates", text: dates.join(" · ") }));
    if (app.follow_up_at) {
      var due = T.isDue(app, today);
      var late = due ? T.daysBetween(app.follow_up_at, today) : 0;
      card.appendChild(el("p", { class: "kb-follow" + (due ? " is-due" : ""), icon: due ? "calendar-clock" : null,
        text: "Relance le " + shortDay(app.follow_up_at) + (late > 0 ? " · " + late + " j de retard" : due ? " · aujourd’hui" : "") }));
    }
    card.appendChild(el("p", { class: "kb-docs" }, docBadgeEl(track.documents[key] || null, true)));

    var actions = el("div", { class: "kb-actions" });
    actions.appendChild(statusMenu(key, j, status));
    if (status === "to_apply") {
      var applied = el("button", { type: "button", class: "button btn-small", text: "J’ai postulé" });
      applied.addEventListener("click", function () {
        setRecord(key, { status: "applied", applied_at: today }, "Candidature envoyée le " + shortDay(today),
          followUpAsk(key, today));
      });
      actions.appendChild(applied);
    }
    if (j && j.url && HTTP.test(j.url)) actions.appendChild(el("a", { href: j.url, target: "_blank", rel: "noopener noreferrer", "aria-label": "Voir l’annonce : " + (j.title || key), text: "Annonce" }));
    if (j) {
      var open = el("button", { type: "button", class: "link-btn kb-open", "aria-label": "Voir la fiche : " + (j.title || key) }, [JM.U.icon("external-link"), "Voir la fiche"]);
      open.addEventListener("click", function () { openRecord(j, open); });
      actions.appendChild(open);
    }
    card.appendChild(actions);
    if (window.matchMedia("(pointer: fine)").matches) attachDrag(card, key);
    return card;
  }

  /* One broken card or row never empties the view: the error is logged with the key only
     (never the record), a placeholder takes its place and the others render. */
  function safeNode(key, build, fallback) {
    try { return build(); } catch (err) {
      console.error("candidatures: carte illisible", key, err);
      try { return fallback(); } catch (e2) { return el("p", { class: "kb-empty", text: "Carte illisible" }); }
    }
  }
  function brokenTitle(key) { var j = postingByKey[key]; return j && j.title ? j.title : goneTitle(key); }
  function brokenCard(key) {
    var card = el("article", { class: "kb-card kb-card-broken", "data-key": key, tabindex: "-1" });
    card.appendChild(el("h3", { class: "kb-title", text: brokenTitle(key) }));
    card.appendChild(el("p", { class: "kb-meta", text: "Carte illisible · les autres s’affichent" }));
    try { card.appendChild(el("div", { class: "kb-actions" }, statusMenu(key, postingByKey[key], T.statusOf(track.apps[key])))); } catch (e) { /* no menu */ }
    return card;
  }
  function brokenRow(key) {
    var tr = el("tr", { "data-key": key, class: "kb-card-broken" });
    tr.appendChild(el("td", { colspan: String(APP_COLUMNS.length), text: brokenTitle(key) + " · ligne illisible, les autres s’affichent" }));
    return tr;
  }

  /* The status menu of a card or a table row: every status, the board's short labels. */
  function statusMenu(key, j, status) {
    var sel = el("select", { class: "kb-status", name: "status", "aria-label": "Statut de " + (j ? j.title : key) });
    T.STATUSES.forEach(function (s) { sel.appendChild(el("option", { value: s, text: BOARD_TEXT[s] || T.STATUS_TEXT[s] })); });
    sel.value = status;
    sel.addEventListener("change", function () {
      setRecord(key, { status: sel.value }, "Déplacée vers « " + (BOARD_TEXT[sel.value] || T.STATUS_TEXT[sel.value]) + " »");
    });
    return sel;
  }

  /* The documents badge (ADR 0017): the latest version's status. Short in the table
     (« Échec », the code in the tooltip; « — » without a row), long on the card. */
  function docBadgeEl(doc, long) {
    var b = T.docBadge(doc);
    if (long) return el("span", { class: "doc-badge kind-" + b.kind, text: doc ? T.docText(doc) : "Aucun document" });
    return el("span", { class: "doc-badge kind-" + b.kind, text: b.text, title: b.title || null });
  }

  /* A CV or letter cell: the PDF and DOCX links once the version is ready, the badge until
     then. A click renders the file here (ADR 0019) and saves it under the template's name
     (CV_Prenom_Nom_Entreprise.pdf) through a blob link: no new tab, no server rendering. */
  function fileCell(links, kind, doc, label, key) {
    if (!links) return docBadgeEl(doc);
    function link(ext, cls) {
      var a = el("a", { href: "#", class: cls, "aria-label": label + " en " + ext.toUpperCase(), text: "\u2b07 " + ext.toUpperCase() });
      a.addEventListener("click", function (ev) {
        ev.preventDefault();
        downloadDocument(key, links.version, kind, ext, a);
      });
      ["pointerenter", "focus"].forEach(function (type) {
        a.addEventListener(type, function () { prefetchBundle(key, links.version); });
      });
      return a;
    }
    return el("span", { class: "doc-links" }, [link("pdf", "doc-dl"), link("docx", "doc-dl alt")]);
  }

  /* The CV + Lettre cells of a row without files: one cell for both, with « Générer » when
     the offer has no documents row, « Regénérer » after a failure, the badge while it runs.
     No button on a rejected or ignored row, nor on an offer the page no longer lists. */
  function docsCell(k, doc, canGenerate) {
    var td = el("td", { class: "apps-docs", colspan: 2, "data-label": "CV · Lettre" });
    var busy = doc && (doc.status === "pending" || doc.status === "running");
    if (doc || !canGenerate) td.appendChild(docBadgeEl(doc));
    if (canGenerate && !busy && (!doc || doc.status === "failed")) {
      var button = el("button", { type: "button", class: "btn btn-sm", text: doc ? "Regénérer" : "Générer" });
      button.addEventListener("click", function () {
        requestDocuments(k, button, function () { renderApps(); });
      });
      td.appendChild(button);
    }
    return td;
  }

  /* « Générer les manquants » (table header): the count and the estimated cost in a held
     toast, then one request; the cron or « Lancer maintenant » does the generation. */
  function generateMissing(button) {
    var missing = T.missingDocuments(track.apps, track.documents, postingByKey, decisionsIndex(), T.localDay());
    var summary = T.budgetSummary(track.budget, missing.length);
    if (!summary.affordable) { showToast(summary.text); return; }
    showToast("Générer " + summary.text + " ?", [
      { text: "Confirmer", run: function () {
        button.disabled = true;
        api.requestMissing().then(function (res) {
          (res.documents || []).forEach(function (d) { if (d && d.job_key) track.documents[d.job_key] = d; });
          var n = res.requested | 0;
          var text = n + (n > 1 ? " générations demandées" : " génération demandée") + " · prêtes dans une dizaine de minutes";
          if (res.skipped_budget > 0) text += " · " + res.skipped_budget + " au-delà du budget";
          showToast(text, [{ text: "Actualiser", run: function () { loadTracking(); } }]);
          renderApps();
          watchDocuments((res.documents || []).map(function (d) { return d && d.job_key; }).filter(Boolean));
        }).catch(function (err) {
          button.disabled = false;
          showToast("Non demandé (" + failureText(err) + ")");
        });
      } },
      { text: "Annuler", run: function () {} }
    ], { hold: true, focus: true, onEscape: function () {} });
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

  /* Auto-archive (ADR 0028): the latest decision as the rule reads it, the state of one
     application (null when live, expired or not « À candidater »), the archived keys. */
  function decisionOf(k) {
    return track.decisions[k] ? { label: track.decisions[k], created_at: track.decisionAt[k] || null } : null;
  }
  function decisionsIndex() {
    var idx = {};
    Object.keys(track.decisions).forEach(function (k) { idx[k] = decisionOf(k); });
    return idx;
  }
  function archiveStateOf(k, today) {
    var app = track.apps[k];
    if (!app) return null;
    return T.archiveState(app, postingByKey[k], decisionOf(k), today || T.localDay());
  }
  /* What leaves the lists: the archived and the « Expirée » applications (T.hiddenState). */
  function hiddenStateOf(k, today) {
    var app = track.apps[k];
    if (!app) return null;
    return T.hiddenState(app, postingByKey[k], decisionOf(k), today || T.localDay());
  }
  function archivedKeys(today) {
    return boardKeys().filter(function (k) { return hiddenStateOf(k, today) !== null; });
  }
  function archivedSet() {
    var set = {};
    archivedKeys(T.localDay()).forEach(function (k) { set[k] = true; });
    return set;
  }

  /* « Réactiver »: the Worker writes reactivated_at, the application is back in the lists
     for another kept_days from today. `onDone` redraws the caller's own view. */
  function reactivate(k, button, onDone) {
    if (button) button.disabled = true;
    api.reactivate(k).then(function (res) {
      if (res && res.application && res.application.job_key) {
        track.apps[k] = track.confirmed[k] = res.application;
      }
      showToast("Réactivée : elle reste « À candidater » " + T.ARCHIVE.kept_days + " jours de plus");
      renderApps();
      refreshBadges(k);
      /* the record open on it loses its « Archivée » badge and gets its usual buttons back */
      if (JM.rec && JM.rec.open && JM.rec.job && JM.rec.job.key === k) openRecord(JM.rec.job, null, { quiet: true });
      if (onDone) onDone(res);
    }).catch(function (err) {
      if (button) button.disabled = false;
      showToast("Non réactivée (" + failureText(err) + ")", [{ text: "Réessayer", run: function () { reactivate(k, button, onDone); } }]);
    });
  }

  /* The follow-ups due today or before, soonest first (expired and archived offers excluded). */
  function dueKeys(today) {
    return Object.keys(track.apps).filter(function (k) {
      return T.isDue(track.apps[k], today) && !T.isExpired(track.apps[k], postingByKey[k]) && archiveStateOf(k, today) === null;
    }).sort(function (a, b) { return track.apps[a].follow_up_at < track.apps[b].follow_up_at ? -1 : 1; });
  }

  /* Under the title: « N à postuler · N relances dues · N entretiens ». */
  function renderStats(keys, dueCount) {
    var stats = byId("apps-stats");
    clear(stats);
    var chip = byId("apps-due-chip");
    /* Without the tracking the counts are unknown, not zero (IMPECCABLE_AUDIT C1). */
    if (track.status !== "ready") {
      chip.hidden = true;
      stats.appendChild(el("span", null, [el("b", { text: "—" }), " " + (track.status === "loading" ? "chargement du suivi…" : "suivi indisponible")]));
      return;
    }
    var n = T.appsFilterCounts(track.apps, keys);
    [[n.postuler, "à postuler"],
      [dueCount, dueCount > 1 ? "relances dues" : "relance due"],
      [n.entretiens, n.entretiens > 1 ? "entretiens" : "entretien"]].forEach(function (pair) {
      stats.appendChild(el("span", null, [el("b", { class: "num", text: String(pair[0]) }), " " + pair[1]]));
    });
    /* The due follow-ups are said by the banner above the board (C2): no second chip. */
    chip.hidden = true;
    clear(chip);
    chip.appendChild(JM.U.icon("calendar-clock"));
    chip.appendChild(document.createTextNode(dueCount + (dueCount > 1 ? " relances en retard" : " relance en retard")));
  }
  byId("apps-due-chip").addEventListener("click", function () {
    var due = byId("kb-due");
    if (due.hidden) return;
    due.scrollIntoView({ block: "start" });
    var first = due.querySelector("button");
    if (first) first.focus({ preventScroll: true });
  });

  /* The segments above the views: « À postuler (N) » … « Tout (N) », the real counts. */
  function renderFilter(keys) {
    var bar = byId("apps-filter");
    clear(bar);
    bar.hidden = track.status !== "ready";
    if (bar.hidden) return;
    var n = T.appsFilterCounts(track.apps, keys);
    T.APPS_FILTERS.forEach(function (f) {
      var b = el("button", { type: "button", class: "chip chip-plain", "data-filter": f, "aria-pressed": String(V.appsFilter === f) }, [
        T.APPS_FILTER_TEXT[f] + " ", el("span", { class: "tab-count num", text: String(n[f]) })]);
      b.addEventListener("click", function () {
        if (V.appsFilter === f) return;
        V.appsFilter = f;
        renderApps();
        JM.syncHash();
      });
      bar.appendChild(b);
    });
  }
  function scoreOf(k) { var j = postingByKey[k]; var v = j ? aiOf(j) : null; return v ? v.score : null; }

  function renderApps() {
    var today = T.localDay();
    var board = byId("kb-board");
    var due = byId("kb-due");
    clear(board);
    clear(due);
    board.hidden = V.appsView === "table";
    byId("kb-table").hidden = V.appsView !== "table";
    var off = byId("kb-off");
    off.hidden = track.status === "ready" || track.status === "loading";
    off.textContent = track.status === "off"
      ? "Les candidatures viennent du suivi : il demande le tableau de bord hébergé."
      : "Suivi indisponible : tes candidatures ne sont pas chargées, rien n’est effacé. Réessaie depuis le bandeau en haut de la page.";
    renderInbox();
    /* No board on an unknown state: empty columns would read as « nothing tracked ». */
    if (track.status !== "ready" && track.status !== "loading") {
      board.hidden = true;
      byId("kb-table").hidden = true;
      due.hidden = true;
      byId("apps-show-archived").hidden = true;
      byId("kb-archived").hidden = true;
      renderFilter([]);
      renderStats([], 0);
      updateCounts();
      return;
    }
    /* The archived and the expired applications (ADR 0028) leave the board, the table and
       the counts; the toggle shows them in a folded section under either view. */
    var archived = archivedKeys(today);
    var archivedMap = {};
    archived.forEach(function (k) { archivedMap[k] = true; });
    var keys = boardKeys().filter(function (k) { return !archivedMap[k]; });
    var toggle = byId("apps-show-archived");
    toggle.hidden = track.status !== "ready" || (!archived.length && !V.showArchived);
    toggle.textContent = (V.showArchived ? "Masquer les archivées" : "Afficher les archivées") + " (" + archived.length + ")";
    toggle.setAttribute("aria-pressed", String(V.showArchived));
    var archBox = byId("kb-archived");
    clear(archBox);
    archBox.hidden = !(V.showArchived && track.status === "ready");
    if (!archBox.hidden) archBox.appendChild(archivedSection(archived, today));
    var dueKeys = JM.dueKeys(today);
    renderStats(keys, dueKeys.length);
    V.appsFilter = T.appsFilterOf(V.appsFilter);
    renderFilter(keys);
    var shown = T.appsFilterKeys(track.apps, keys, V.appsFilter, scoreOf, decisionsIndex());
    due.hidden = dueKeys.length === 0;
    if (dueKeys.length) {
      due.appendChild(el("h2", { class: "kb-due-title", icon: "calendar-clock", text: dueKeys.length + (dueKeys.length > 1 ? " relances en retard" : " relance en retard") }));
      var list = el("ul", { class: "kb-due-list" });
      dueKeys.forEach(function (k) {
        var app = track.apps[k];
        var j = postingByKey[k];
        var late = T.daysBetween(app.follow_up_at, today);
        var go = el("button", { type: "button", class: "link-btn", title: j ? (j.title || null) : k, text: j ? (j.title || k) : goneTitle(k) });
        go.addEventListener("click", function () {
          var target = board.querySelector('.kb-card[data-key="' + (window.CSS && CSS.escape ? CSS.escape(k) : k) + '"]');
          if (target) { target.scrollIntoView({ block: "center" }); target.focus({ preventScroll: true }); }
        });
        list.appendChild(el("li", null, [go, el("span", { class: "kb-due-late", text: late > 0 ? late + " j de retard" : "aujourd’hui" })]));
      });
      due.appendChild(list);
    }
    if (V.appsView === "table") {
      renderAppsTable(today, shown);
      updateCounts();
      return;
    }
    /* the filter keeps its columns only; « À candidater » in the filter's order */
    var cols = BOARD.filter(function (status) { return T.APPS_FILTER_STATUSES[V.appsFilter].indexOf(status) >= 0; });
    board.classList.toggle("is-single", cols.length === 1);
    cols.forEach(function (status) {
      var inCol = shown.filter(function (k) { return T.statusOf(track.apps[k]) === status; });
      if (status !== "to_apply") inCol.sort(function (a, b) {
        var da = T.isDue(track.apps[a], today) ? 0 : 1, db = T.isDue(track.apps[b], today) ? 0 : 1;
        if (da !== db) return da - db;
        return String(track.apps[b].updated_at || "").localeCompare(String(track.apps[a].updated_at || ""));
      });
      var col = el("section", { class: "kb-col kb-" + status, "data-status": status, "aria-label": BOARD_TEXT[status] });
      col.appendChild(el("h2", { class: "kb-col-title" }, [BOARD_TEXT[status] + " ", el("span", { class: "tab-count", text: String(inCol.length) })]));
      var body = el("div", { class: "kb-col-body" });
      inCol.forEach(function (k) { body.appendChild(safeNode(k, function () { return appCard(k, today); }, function () { return brokenCard(k); })); });
      if (!inCol.length) body.appendChild(el("p", { class: "kb-empty", text: status === "to_apply" ? "Garde des offres dans Tri pour les voir ici." : "Aucune." }));
      col.appendChild(body);
      board.appendChild(col);
    });
    updateCounts();
  }

  /* « Réponses à confirmer » (ADR 0018): the recruiter replies the Worker did not apply by
     itself (unsure, or neither an interview nor a refusal). Valider applies the proposed
     verdict, Corriger lets me pick the application, the kind and the date, Ignorer archives.
     The item leaves the block as soon as the Worker answers; the application it returns
     replaces the one on screen. */
  function renderInbox() {
    var box = byId("kb-inbox");
    if (!box) return;
    clear(box);
    var items = track.status === "ready" ? track.inbox.to_confirm : [];
    box.hidden = items.length === 0;
    if (!items.length) return;
    box.appendChild(el("h3", { class: "kb-inbox-title", text: "Réponses à confirmer (" + items.length + ")" }));
    var list = el("div", { class: "inbox-list" });
    items.forEach(function (it) { list.appendChild(safeNode(it.message_id, function () { return inboxItem(it); }, function () { return el("p", { class: "kb-empty", text: "Réponse illisible" }); })); });
    box.appendChild(list);
  }

  function inboxDone(it, res) {
    track.inbox.to_confirm = track.inbox.to_confirm.filter(function (x) { return x.message_id !== it.message_id; });
    if (res && res.item) track.inbox.history.unshift(res.item);
    if (res && res.application && res.application.job_key) {
      track.apps[res.application.job_key] = track.confirmed[res.application.job_key] = res.application;
      refreshBadges(res.application.job_key);
    }
    renderApps();
  }

  function inboxItem(it) {
    var summary = T.inboxSummary(it, postingByKey);
    var art = el("article", { class: "inbox-item", "data-id": it.message_id });
    var head = el("p", { class: "inbox-head" }, [
      el("span", { class: "inbox-kind kind-" + (it.kind || "none"), text: T.inboxKindText(it.kind) }),
      it.confidence !== null && it.confidence !== undefined ? el("span", { class: "inbox-conf", text: T.confidenceText(it.confidence) }) : null,
      el("span", { class: "inbox-date", text: it.received_at ? fmtShortDate(it.received_at) : "" })
    ]);
    art.appendChild(head);
    art.appendChild(el("p", { class: "inbox-subject", text: it.subject || "(sans objet)" }));
    art.appendChild(el("p", { class: "inbox-meta", text: [it.sender_domain || "expéditeur inconnu", summary.text].join(" → ") }));
    if (it.interview_at) art.appendChild(el("p", { class: "inbox-meta", text: "Entretien le " + shortDay(it.interview_at) }));

    var actions = el("div", { class: "inbox-actions" });
    var validate = el("button", { type: "button", class: "btn btn-primary btn-small", text: "Valider" });
    var correct = el("button", { type: "button", class: "btn btn-small", text: "Corriger" });
    var ignore = el("button", { type: "button", class: "btn btn-small", text: "Ignorer" });
    var needsKey = (it.kind === "entretien" || it.kind === "refus") && !summary.key;
    if (!it.kind || needsKey) validate.disabled = true;
    actions.appendChild(validate); actions.appendChild(correct); actions.appendChild(ignore);
    art.appendChild(actions);
    var form = null;

    function send(body, text) {
      [validate, correct, ignore].forEach(function (b) { b.disabled = true; });
      api.inboxAct(it.message_id, body).then(function (res) {
        showToast(text);
        inboxDone(it, res);
      }).catch(function (err) {
        [validate, correct, ignore].forEach(function (b) { b.disabled = false; });
        if (!it.kind || needsKey) validate.disabled = true;
        showToast("Non enregistré (" + failureText(err) + ")", [{ text: "Réessayer", run: function () { send(body, text); } }]);
      });
    }
    validate.addEventListener("click", function () { send({ action: "confirm" }, "Réponse validée"); });
    ignore.addEventListener("click", function () { send({ action: "ignore" }, "Réponse ignorée"); });
    correct.addEventListener("click", function () {
      if (form) { form.hidden = !form.hidden; return; }
      var target = el("select", { name: "application_key", "aria-label": "Candidature concernée" });
      T.inboxTargets(track.apps, postingByKey).forEach(function (k) {
        var j = postingByKey[k];
        target.appendChild(el("option", { value: k, text: j ? [j.title || k, j.company || null].filter(Boolean).join(" · ") : k }));
      });
      if (summary.key) target.value = summary.key;
      var kind = el("select", { name: "kind", "aria-label": "Type de réponse" });
      T.INBOX_KINDS.forEach(function (k) { kind.appendChild(el("option", { value: k, text: T.INBOX_KIND_TEXT[k] })); });
      kind.value = it.kind && T.INBOX_KINDS.indexOf(it.kind) >= 0 ? it.kind : "autre";
      var date = el("input", { type: "date", name: "interview_at", "aria-label": "Date d’entretien", value: it.interview_at || "", autocomplete: "off" });
      var save = el("button", { type: "button", class: "btn btn-primary btn-small", text: "Enregistrer" });
      save.addEventListener("click", function () {
        if (!target.value) { target.focus(); return; }
        if (date.value && !T.isDay(date.value)) { date.focus(); return; }
        send({ action: "correct", application_key: target.value, kind: kind.value, interview_at: date.value || null }, "Réponse corrigée");
      });
      form = el("div", { class: "inbox-correct" }, [target, kind, date, save]);
      art.appendChild(form);
      target.focus();
    });
    return art;
  }

  /* The table view: one row per application on the board, due ones first, then the most
     recently touched. Same statuses, same menu, plus the downloads. */
  var APP_COLUMNS = ["Offre", "Entreprise", "Score IA", "Statut", "CV", "Lettre", "Lien", "Relance"];
  var APP_COL_CLASS = { Offre: "title", Entreprise: "company", "Score IA": "ai", Statut: "status", CV: "doc", Lettre: "doc", Lien: "link", Relance: "due" };
  function renderAppsTable(today, keys) {
    var wrap = byId("kb-table");
    clear(wrap);
    var rows = V.appsFilter === "postuler" ? keys.slice() : keys.slice().sort(function (a, b) {
      var da = T.isDue(track.apps[a], today) ? 0 : 1, db = T.isDue(track.apps[b], today) ? 0 : 1;
      if (da !== db) return da - db;
      var ra = T.STATUS_RANK[T.statusOf(track.apps[a])], rb = T.STATUS_RANK[T.statusOf(track.apps[b])];
      if (ra !== rb) return ra - rb;
      return String(track.apps[b].updated_at || "").localeCompare(String(track.apps[a].updated_at || ""));
    });
    if (!rows.length) {
      wrap.appendChild(el("p", { class: "kb-empty", text: V.appsFilter === "postuler" || V.appsFilter === "tout"
        ? "Garde des offres dans Tri pour les voir ici." : "Aucune candidature dans ce filtre." }));
      return;
    }
    var missing = T.missingDocuments(track.apps, track.documents, postingByKey, decisionsIndex(), today);
    var gen = el("button", { type: "button", class: "btn", id: "apps-generate-missing", text: "Générer les manquants (" + missing.length + ")" });
    gen.disabled = !missing.length || track.status !== "ready";
    gen.addEventListener("click", function () { generateMissing(gen); });
    wrap.appendChild(el("div", { class: "kb-table-bar" }, [
      el("span", { class: "kb-table-hint", text: missing.length ? "Sans CV ni lettre : " + missing.length : "Chaque candidature a ses documents." }), gen]));
    var cols = el("colgroup", null, APP_COLUMNS.map(function (h) { return el("col", { class: "w-" + APP_COL_CLASS[h] }); }));
    var head = el("tr");
    APP_COLUMNS.forEach(function (h) { head.appendChild(el("th", { scope: "col", class: h === "Score IA" ? "num" : null, text: h })); });
    var body = el("tbody");
    rows.forEach(function (k) { body.appendChild(safeNode(k, function () { return appRow(k, today); }, function () { return brokenRow(k); })); });
    wrap.appendChild(el("table", { class: "data apps fixed", "aria-label": "Candidatures" }, [cols, el("thead", null, head), body]));
  }

  /* « Postuler » (ADR 0024): a supported form copies the one command and says which number
     to type in its list (T.applyList, the CLI's own order); any other form opens the offer. */
  var APPLY_COMMAND = ".venv\\Scripts\\job-match apply";
  function applyButton(k, j) {
    var b = el("button", { type: "button", class: "btn btn-primary btn-small apps-apply", text: "Postuler",
      "aria-label": "Postuler : " + (j.title || k) });
    b.addEventListener("click", function () {
      if (!T.canPrefill(j)) {
        window.open(j.url, "_blank", "noopener,noreferrer");
        return;
      }
      var n = T.applyList(track.apps, postingByKey, decisionsIndex(), T.localDay()).indexOf(k) + 1;
      var say = function () { showToast("Commande copiée · Colle dans PowerShell et choisis le n° " + n); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(APPLY_COMMAND).then(say, function () {
          showToast("Copie refusée : tape " + APPLY_COMMAND + " puis le n° " + n);
        });
      } else {
        showToast("Tape " + APPLY_COMMAND + " dans PowerShell puis le n° " + n);
      }
    });
    return b;
  }

  function appRow(k, today) {
    {
      var app = track.apps[k];
      var j = postingByKey[k];
      var doc = track.documents[k] || null;
      var links = T.documentLinks(k, doc);
      var expired = T.isExpired(app, j);
      var tr = el("tr", { "data-key": k, class: expired ? "is-expired" : null });
      var titleText = j ? (j.title || k) : goneTitle(k);
      /* the title opens the record; an offer the page no longer has has no record to open */
      var title = j
        ? el("button", { type: "button", class: "link-btn", title: titleText, text: titleText })
        : el("span", { class: "apps-gone", title: titleText, text: titleText });
      if (j) title.addEventListener("click", function () { openRecord(j, title); });
      var prefill = j ? el("span", { class: "apps-form" + (T.canPrefill(j) ? " can-prefill" : ""), text: T.canPrefill(j) ? "Pré-remplissage" : "Manuel",
        title: T.canPrefill(j) ? "job-match apply remplit le formulaire" : "Formulaire à remplir à la main" }) : null;
      tr.appendChild(el("td", { class: "apps-title", "data-label": "Offre" }, [title, prefill]));
      var company = j ? (j.company || null) : "plus dans la liste des offres";
      tr.appendChild(el("td", { class: "apps-company", "data-label": "Entreprise", title: company },
        company ? company : el("span", { class: "apps-unknown", text: "Non communiquée" })));
      var ai = j ? aiOf(j) : null;
      tr.appendChild(el("td", { class: "num", "data-label": "Score IA", text: ai ? String(ai.score) : "—" }));
      tr.appendChild(el("td", { class: "apps-status", "data-label": "Statut" }, el("div", { class: "apps-status-stack" }, expired
        ? [el("span", { class: "status-badge is-expired", text: "Expirée", title: "La source a retiré l’offre" }), statusMenu(k, j, T.statusOf(app))]
        : [statusMenu(k, j, T.statusOf(app))])));
      if (links) {
        tr.appendChild(el("td", { class: "doc-cell", "data-label": "CV" }, fileCell(links, "cv", doc, "CV", k)));
        tr.appendChild(el("td", { class: "doc-cell", "data-label": "Lettre" }, fileCell(links, "letter", doc, "Lettre", k)));
      } else {
        /* the Worker only generates for a kept status and a listed offer (KEEP_STATUSES) */
        tr.appendChild(docsCell(k, doc, Boolean(j) && T.missingDocuments({ k: app }, {}, { k: j }).length === 1));
      }
      var offerLink = j && j.url && HTTP.test(j.url)
        ? el("a", { href: j.url, target: "_blank", rel: "noopener noreferrer", "aria-label": "Voir l’offre : " + (j.title || k), text: "Offre ↗" })
        : null;
      var canApply = j && !expired && T.statusOf(app) === "to_apply" && (T.canPrefill(j) || offerLink);
      tr.appendChild(el("td", { class: "link-col", "data-label": "Lien" },
        offerLink || canApply ? [canApply ? applyButton(k, j) : null, offerLink] : "—"));
      var due = !expired && T.isDue(app, today);
      var late = due ? T.daysBetween(app.follow_up_at, today) : 0;
      tr.appendChild(el("td", { class: (due ? "is-due " : "") + "apps-due", "data-label": "Relance", text: app.follow_up_at
        ? shortDay(app.follow_up_at) + (late > 0 ? " (" + late + " j de retard)" : due ? " (aujourd’hui)" : "")
        : "—" }));
      return tr;
    }
  }

  /* « Archivées » (ADR 0028): a folded section, oldest first. Grey badge with the reason, the
     documents still downloadable, « Réactiver »; no « Postuler », no « Générer ». */
  var ARCHIVED_COLUMNS = ["Offre", "Entreprise", "Statut", "CV", "Lettre", "Action"];
  function archivedSection(keys, today) {
    /* shown only when asked for (button or #…&archived=1): open from the start */
    var box = el("details", { class: "kb-archived-box", id: "kb-archived-box", open: "" });
    box.appendChild(el("summary", null, [
      "Archivées ", el("span", { class: "tab-count", text: String(keys.length) }),
      el("span", { class: "kb-archived-hint", text: "À candidater jamais traitées : offre expirée, gardées il y a plus de " + T.ARCHIVE.kept_days +
        " jours ou publiées il y a plus de " + T.ARCHIVE.published_days + " jours. Rien n’est supprimé ; les documents restent téléchargeables. Une offre qui réapparaît revient seule." })
    ]));
    if (!keys.length) {
      box.appendChild(el("p", { class: "kb-empty", text: "Aucune candidature archivée." }));
      return box;
    }
    var rows = keys.slice().sort(function (a, b) {
      return (hiddenStateOf(b, today) || { days: 0 }).days - (hiddenStateOf(a, today) || { days: 0 }).days || (a < b ? -1 : 1);
    });
    var head = el("tr");
    ARCHIVED_COLUMNS.forEach(function (h) { head.appendChild(el("th", { scope: "col", text: h })); });
    var body = el("tbody");
    rows.forEach(function (k) { body.appendChild(safeNode(k, function () { return archivedRow(k, today); }, function () { return brokenRow(k); })); });
    box.appendChild(el("table", { class: "data apps archived", "aria-label": "Candidatures archivées" }, [el("thead", null, head), body]));
    return box;
  }

  function archivedRow(k, today) {
    var app = track.apps[k];
    var j = postingByKey[k];
    var doc = track.documents[k] || null;
    var links = T.documentLinks(k, doc);
    var state = hiddenStateOf(k, today);
    var expired = !!state && state.reason === "expired";
    var tr = el("tr", { "data-key": k, class: "is-archived" + (expired ? " is-expired" : "") });
    var titleText = j ? (j.title || k) : goneTitle(k);
    var title = j
      ? el("button", { type: "button", class: "link-btn", title: titleText, text: titleText })
      : el("span", { class: "apps-gone", title: titleText, text: titleText });
    if (j) title.addEventListener("click", function () { openRecord(j, title); });
    tr.appendChild(el("td", { class: "apps-title", "data-label": "Offre" }, title));
    var company = j ? (j.company || null) : "plus dans la liste des offres";
    tr.appendChild(el("td", { class: "apps-company", "data-label": "Entreprise", title: company },
      company ? company : el("span", { class: "apps-unknown", text: "Non communiquée" })));
    /* badge, reason (and the menu of an expired one) stacked in the cell, never overlapping */
    tr.appendChild(el("td", { class: "apps-status", "data-label": "Statut" }, el("div", { class: "apps-status-stack" }, [
      expired
        ? el("span", { class: "status-badge is-expired", text: "Expirée", title: "La source a retiré l’offre" })
        : el("span", { class: "status-badge is-archived", text: "Archivée", title: "Archivée automatiquement, rien n’est supprimé" }),
      el("span", { class: "kb-archived-reason", text: T.archiveReason(state) }),
      expired ? statusMenu(k, j, T.statusOf(app)) : null
    ])));
    if (links) {
      tr.appendChild(el("td", { class: "doc-cell", "data-label": "CV" }, fileCell(links, "cv", doc, "CV", k)));
      tr.appendChild(el("td", { class: "doc-cell", "data-label": "Lettre" }, fileCell(links, "letter", doc, "Lettre", k)));
    } else if (expired && doc) {
      /* a failed or pending version on a closed offer: nothing to regenerate */
      tr.appendChild(el("td", { class: "apps-docs", colspan: 2, "data-label": "CV · Lettre" }, [
        docBadgeEl(doc), el("span", { class: "apps-expired-note", text: "Offre expirée" })]));
    } else {
      tr.appendChild(el("td", { class: "doc-cell", "data-label": "CV", text: "—" }));
      tr.appendChild(el("td", { class: "doc-cell", "data-label": "Lettre", text: "—" }));
    }
    if (expired) {
      tr.appendChild(el("td", { class: "link-col", "data-label": "Action", text: "—" }));
      return tr;
    }
    var react = el("button", { type: "button", class: "btn btn-small apps-reactivate", text: "Réactiver",
      "aria-label": "Réactiver : " + titleText, title: "Remet la candidature dans la liste pour " + T.ARCHIVE.kept_days + " jours" });
    react.disabled = track.status !== "ready";
    react.addEventListener("click", function () { reactivate(k, react); });
    tr.appendChild(el("td", { class: "link-col", "data-label": "Action" }, react));
    return tr;
  }

  byId("apps-show-archived").addEventListener("click", function () {
    V.showArchived = !V.showArchived;
    renderApps();
    JM.syncHash();
    if (V.showArchived) {
      var box = byId("kb-archived-box");
      if (box) { box.open = true; box.scrollIntoView({ block: "nearest" }); }
    }
  });

  /* A view that fails to render says so instead of leaving the panel blank. */

  /* Shared with the other files. */
  JM.documentsBlock = documentsBlock;
  JM.dueKeys = dueKeys;
  JM.archiveStateOf = archiveStateOf;
  JM.archivedKeys = archivedKeys;
  JM.archivedSet = archivedSet;
  JM.decisionsIndex = decisionsIndex;
  JM.reactivate = reactivate;
  JM.preloadRenderer = preloadRenderer;
  JM.renderApps = renderApps;
  JM.setRecord = setRecord;
  JM.followUpAsk = followUpAsk;
})(window.JM);
