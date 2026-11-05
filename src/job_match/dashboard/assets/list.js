/* Offres: one scannable row per offer (score, title, company, city, contract, age, the single
   strongest reason), everything else behind one expand; dense by default; the filters and the
   sort live in the hash and outlive a reload; keyboard-first triage (j/k/x/s/a/Enter/Space, see
   listKeys). Every string from the data lands in the DOM through textContent. */
(function (JM) {
  "use strict";

  /* From app.js (values) and the other screens (functions, read at call time). */
  var el = JM.el, clear = JM.clear, byId = JM.byId, cell = JM.cell, link = JM.link, dateCell = JM.dateCell;
  var fmtDate = JM.fmtDate, fmtShortDate = JM.fmtShortDate, fmtYears = JM.fmtYears, dayOf = JM.dayOf;
  var T = JM.T, S = JM.S, U = JM.U, V = JM.v, R = JM.rec, X = JM.X;
  var jobs = JM.jobs, rows = JM.rows, thresholds = JM.thresholds, track = JM.track, api = JM.api, badges = JM.badges;
  var SECTIONS = JM.SECTIONS, SORT_TEXT = JM.SORT_TEXT, HTTP = JM.HTTP;
  var aiOf = JM.aiOf, statusOfJob = JM.statusOfJob, statusBadge = JM.statusBadge, applyChanges = JM.applyChanges;
  var syncHash = JM.syncHash, parseHash = JM.parseHash, showTab = JM.showTab, setAppsView = JM.setAppsView;
  var openRecord = JM.openRecord, closeRecord = JM.closeRecord, trackForm = JM.trackForm;
  var whyPanel = function () { return JM.whyPanel.apply(null, arguments); };
  var frExplanation = function () { return JM.frExplanation.apply(null, arguments); };
  var setRecord = function () { return JM.setRecord.apply(null, arguments); };
  var followUpAsk = function () { return JM.followUpAsk.apply(null, arguments); };

  /* ---------- state: filters and sort (the hash is the source of truth, localStorage its memory) ---------- */

  var state = {
    q: "",
    sections: { strong: true, eligible: true, stretch: true },
    department: "",
    source: "",
    status: "",
    ai: "",
    minScore: 0,
    from: "",
    to: "",
    sortKey: "score",
    sortDir: "desc",
    expanded: {}
  };

  var searchInput = byId("f-search");
  var deptSelect = byId("f-department");
  var sourceSelect = byId("f-source");
  var statusSelect = byId("f-status");
  var aiSelect = byId("f-ai");
  /* The IA filter's values (hash `ia=`): the Worker's levels, as score.js names them. */
  var AI_LEVELS = ["fort", "tenter", "hors_sujet"];
  var minScoreInput = byId("f-min-score");
  var minScoreOut = byId("f-min-score-out");
  var fromInput = byId("f-from");
  var toInput = byId("f-to");
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip[data-section]"));
  var jobsBody = byId("jobs-body");
  var controls = byId("jobs-controls");

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

  /* Where an offer comes from: a national board by name, a company board by its ATS. */
  var SOURCE_TEXT = { france_travail: "France Travail", adzuna: "Adzuna", jooble: "Jooble", ats: "Pages carrière (ATS)" };
  var ATS_TEXT = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", workday: "Workday", smartrecruiters: "SmartRecruiters" };
  function sourceText(j) {
    if (j.source === "ats") return ATS_TEXT[j.ats] || j.ats || "ATS";
    return SOURCE_TEXT[j.source] || j.source || "";
  }
  /* The Source filter's values a posting answers to: its source ("ats"), and for a company
     board also that company ("ats:Dataiku"). */
  function sourceKeys(p) {
    var keys = [p.source || ""];
    if (p.source === "ats" && p.company) keys.push("ats:" + p.company);
    return keys;
  }

  /* Each source with its count; the companies read through their ATS listed under it. */
  function fillSources() {
    var counts = {};
    var companies = {};
    jobs.forEach(function (j) {
      counts[j.source] = (counts[j.source] || 0) + 1;
      if (j.source === "ats" && j.company) companies[j.company] = (companies[j.company] || 0) + 1;
    });
    Object.keys(counts).sort(function (a, b) {
      if (a === "ats" || b === "ats") return a === "ats" ? 1 : -1;
      return a < b ? -1 : 1;
    }).forEach(function (s) {
      sourceSelect.appendChild(el("option", { value: s, text: (SOURCE_TEXT[s] || s) + " (" + counts[s] + ")" }));
      if (s !== "ats") return;
      Object.keys(companies).sort(function (a, b) { return a.localeCompare(b, "fr"); }).forEach(function (c) {
        sourceSelect.appendChild(el("option", { value: "ats:" + c, text: "\u00a0\u00a0· " + c + " (" + companies[c] + ")" }));
      });
    });
  }

  function fillStatuses() {
    T.STATUSES.forEach(function (s) {
      statusSelect.appendChild(el("option", { value: s, text: T.STATUS_TEXT[s] }));
    });
    AI_LEVELS.forEach(function (l) {
      aiSelect.appendChild(el("option", { value: l, text: S.aiBand(l).label }));
    });
  }

  /* How many Offres filters differ from their default: shown on the "Filtres" summary. */
  function activeFilters() {
    var n = 0;
    if (state.q) n += 1;
    if (SECTIONS.some(function (s) { return !state.sections[s]; })) n += 1;
    if (state.department) n += 1;
    if (state.source) n += 1;
    if (state.status) n += 1;
    if (state.ai) n += 1;
    if (state.minScore) n += 1;
    if (state.from) n += 1;
    if (state.to) n += 1;
    return n;
  }

  function matches(j) {
    if (!state.sections[j.section]) return false;
    if (state.status && statusOfJob(j) !== state.status) return false;
    if (state.ai) {
      var verdict = aiOf(j);
      if (!verdict || verdict.level !== state.ai) return false;
    }
    if (state.minScore > 0 && (j.score === null || j.score < state.minScore)) return false;
    if (state.source && !T.postingsOf(j).some(function (p) { return sourceKeys(p).indexOf(state.source) >= 0; })) return false;
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
    if (k === "status") return T.STATUSES.indexOf(statusOfJob(j));
    if (k === "department") return cityOf(j);
    if (k === "source") return sourceText(j);
    return j[k];
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

  /* ---------- row cells ---------- */

  /* "Paris" from "75 - Paris"; the bare department code when the place is not named. */
  function cityOf(j) {
    if (j.postings) return j.departments.length + " dép.";
    var loc = String(j.location || "");
    var m = /^\s*\d{2,3}\s*-\s*(.+)$/.exec(loc);
    if (m) return m[1].trim();
    return loc || (j.department ? j.department : "");
  }

  function scoreCell(j) {
    var wrap = el("span", { class: "score score-" + j.section });
    var bar = el("span", { class: "score-bar", "aria-hidden": "true" });
    var fill = el("i");
    fill.style.width = (j.score === null ? 0 : Math.max(0, Math.min(100, j.score))) + "%";
    bar.appendChild(fill);
    wrap.appendChild(bar);
    wrap.appendChild(el("span", { class: "score-n num", text: j.score === null ? "—" : String(j.score) }));
    var v = aiOf(j);
    if (v) {
      var band = S.aiBand(v.level);
      wrap.appendChild(el("span", { class: "score-ai" + (band ? " ai-" + band.key : ""), title: band ? "Selon l’IA : " + band.label : "Selon l’IA", text: "IA " + v.score }));
    }
    return wrap;
  }

  /* The single strongest reason, from the scorer's own lines (score.js): the biggest positive
     weight, else the biggest penalty; the sentence it came from in the tooltip. */
  function topReason(j) {
    var b = S.breakdown(j);
    if (!b || !b.lines.length) return null;
    var w = j.why || { skills: [], lowered: [] };
    var bySkill = {};
    (w.skills || []).concat(w.lowered || []).forEach(function (s) { bySkill[s.name] = s; });
    function nameOf(l) { return l.label.replace(/ \(demandée au profil\)$/, ""); }
    /* A skill the offer names beats the title family line: it has a sentence to show. */
    var ranked = b.lines.slice().sort(function (x, y) {
      var ex = bySkill[nameOf(x)] ? 1 : 0, ey = bySkill[nameOf(y)] ? 1 : 0;
      return (ey - ex) || Math.abs(y.value) - Math.abs(x.value) || (y.value - x.value);
    });
    var best = ranked[0];
    var name = nameOf(best);
    var found = bySkill[name];
    var span = el("span", { class: "why-top " + (best.value < 0 ? "down" : "up"), title: found && found.snippet ? found.snippet : null }, [
      el("b", { class: "num", text: S.signed(best.value) }), " " + name
    ]);
    return span;
  }

  var COLUMNS = {
    score: function (j) { return cell("num col-score", "Score", scoreCell(j)); },
    title: function (j, prefix, expanded) {
      var td = cell("col-title", "Titre", el("span", { class: "title-text", text: j.title || "—", title: j.title || null }));
      if (statusOfJob(j) !== "to_review") td.appendChild(statusBadge(j));
      /* On a phone the quiet columns fold into one line under the title (CSS shows one or the other). */
      var age = typeof j.age_days === "number" ? j.age_days + " j" : "";
      td.appendChild(el("span", { class: "row-meta", "aria-hidden": "true", text: [j.company, cityOf(j), j.contract !== "UNKNOWN" ? j.contract : "", age].filter(Boolean).join(" · ") }));
      return td;
    },
    company: function (j) {
      var td = cell("col-company", "Entreprise", j.company || "—");
      if (j.company) td.title = j.company;
      return td;
    },
    department: function (j) {
      var td = cell("col-city", "Ville", cityOf(j) || "?");
      if (j.postings) td.title = j.departments.length + " départements : " + j.departments.join(", ");
      else if (j.location) td.title = j.location;
      return td;
    },
    contract: function (j) { return cell("col-contract", "Contrat", j.contract && j.contract !== "UNKNOWN" ? j.contract : "—"); },
    source: function (j) {
      var td = cell("col-source", "Source", sourceText(j) || "—");
      td.title = j.source === "ats" ? "Page carrière de " + (j.company || "l’entreprise") + " (" + sourceText(j) + ")" : sourceText(j);
      return td;
    },
    age_days: function (j) {
      var age = typeof j.age_days === "number" ? j.age_days : null;
      var td = cell("num col-age", "Âge", el("span", { class: age === null ? "unknown" : "", text: age === null ? "—" : age + " j" }));
      if (j.posted_at) td.title = "Publiée le " + fmtDate(j.posted_at);
      return td;
    },
    why: function (j) { return cell("col-why", "Pourquoi", topReason(j) || el("span", { class: "unknown", text: "—" })); },
    more: function (j, prefix, expanded) {
      return cell("col-more", "Détails", el("button", {
        type: "button", class: "expand icon-btn", "aria-expanded": expanded ? "true" : "false",
        "aria-controls": prefix + "-details-" + j.id, "aria-label": "Détails de l’offre : " + (j.title || "offre"), icon: "chevron-right"
      }));
    }
  };
  var JOB_COLUMNS = ["score", "title", "company", "department", "contract", "source", "age_days", "why", "more"];

  /* ---------- the row's details ---------- */

  /* The status writes, from a row or a key: the page first, the API after (applyChanges). */
  function quickSet(row, status) {
    var targets = status === "ignored" ? T.postingsOf(row) : [row];
    var before = targets.map(function (p) { return { key: p.key, next: T.blank(track.apps[p.key]) }; });
    var changes = before.map(function (b) { return { key: b.key, next: Object.assign({}, b.next, { status: status }) }; });
    var done = status === "ignored"
      ? (targets.length > 1 ? targets.length + " offres ignorées" : "Offre ignorée")
      : "Offre passée à « À candidater »";
    applyChanges(changes, done, before);
  }

  /* « Candidature envoyée » today, then the follow-up question in the toast (board.js). */
  function markApplied(row) {
    var today = T.localDay();
    setRecord(row.key, { status: "applied", applied_at: today }, "Candidature envoyée le " + fmtShortDate(today + "T00:00:00Z"), followUpAsk(row.key, today));
  }

  function canWrite() { return track.status === "ready" && !!api; }

  /* The actions of one offer, under its details: reachable with a thumb on a phone. */
  function actionsBar(row) {
    var bar = el("div", { class: "row-actions", role: "group", "aria-label": "Actions" });
    var s = T.rowStatus(row, track.apps);
    function button(text, run, cls) {
      var b = el("button", { type: "button", class: "button " + (cls || ""), text: text });
      b.addEventListener("click", function (ev) { ev.stopPropagation(); run(); });
      bar.appendChild(b);
    }
    if (canWrite()) {
      if (s !== "to_apply" && s !== "applied" && s !== "interview") button("Garder", function () { quickSet(row, "to_apply"); }, "primary");
      if (s !== "applied" && s !== "interview") button("Candidature envoyée", function () { markApplied(row); });
      if (s !== "ignored") button("Écarter", function () { quickSet(row, "ignored"); });
    }
    if (row.url && HTTP.test(row.url)) bar.appendChild(el("a", { class: "button", href: row.url, target: "_blank", rel: "noopener noreferrer", icon: "external-link" }, "Ouvrir l’annonce"));
    var fiche = el("button", { type: "button", class: "button", text: "Fiche" });
    fiche.addEventListener("click", function (ev) { ev.stopPropagation(); openRecord(row, fiche); });
    bar.appendChild(fiche);
    return bar;
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
      if (canWrite()) {
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

  function detailsFor(j, prefix, colspan) {
    var td = el("td", { colspan: String(colspan) });
    var box = el("div", { class: "details" });
    box.appendChild(actionsBar(j));
    var meta = [];
    if (j.location) meta.push(j.location);
    var years = fmtYears(j.required_years);
    if (years !== null) meta.push(years + " an" + (years === "0" || years === "1" ? "" : "s") + " requis");
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

    var form = trackForm(j, prefix);
    var panel = whyPanel(j, form.verdictBlock || null);
    panel.open = true;
    if (others.length) {
      panel.appendChild(el("details", { class: "explain-all" }, [
        el("summary", { text: "Toutes les explications (" + others.length + ")" }),
        el("ul", null, others.map(function (t) { return el("li", { text: frExplanation(t) }); }))
      ]));
    }
    box.appendChild(panel);
    box.appendChild(el("div", { class: "details-track" }, [el("h4", { text: "Suivi" }), form]));
    td.appendChild(box);
    return el("tr", { class: "details", id: prefix + "-details-" + j.id }, td);
  }

  function jobRows(list, prefix, columns, expandedMap) {
    var frag = document.createDocumentFragment();
    list.forEach(function (j) {
      var open = !!expandedMap[j.id];
      var s = statusOfJob(j);
      var row = el("tr", {
        class: "row row-" + j.section + (s !== "to_review" ? " is-handled st-" + s : ""),
        tabindex: "0", "aria-expanded": open ? "true" : "false", "data-key": j.key || null
      });
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
      row.toggleDetails = toggle;
      row.jmRow = j;
      row.addEventListener("click", function (ev) {
        if (ev.target.closest("a, .qa, .status")) return;
        toggle();
      });
      row.addEventListener("keydown", function (ev) {
        if (ev.target !== row) return;
        if (ev.key === " ") { ev.preventDefault(); toggle(); }
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

  function setEmpty(shown) {
    var empty = byId("jobs-empty");
    empty.hidden = shown > 0;
    if (shown > 0) return;
    var n = activeFilters();
    byId("jobs-empty-text").textContent = rows.length === 0
      ? "Le run de ce matin n’a rien collecté : la prochaine exécution tourne demain matin (voir Exécutions)."
      : "Le run de ce matin n’a rien trouvé pour ces filtres.";
    byId("jobs-empty-reset").hidden = n === 0;
  }

  /* Re-rendered whole on every change (about 50 rows: a few milliseconds); the focused row
     keeps the focus, by key, so j/k continue where they were. */
  function renderJobs() {
    var focusedKey = document.activeElement && document.activeElement.classList && document.activeElement.classList.contains("row")
      ? document.activeElement.getAttribute("data-key") : null;
    var shown = rows.filter(matches).sort(compare);
    var counts = { strong: 0, eligible: 0, stretch: 0 };
    rows.forEach(function (j) { counts[j.section] += 1; });
    byId("kpi-strong").textContent = counts.strong;
    byId("kpi-eligible").textContent = counts.eligible;
    byId("kpi-stretch").textContent = counts.stretch;
    byId("jobs-rowcount").textContent = shown.length + " sur " + rows.length + " · tri par " +
      SORT_TEXT[state.sortKey] + (state.sortDir === "asc" ? " ↑" : " ↓");
    dropBadges(jobsBody);
    clear(jobsBody);
    setEmpty(shown.length);
    byId("filters-count").textContent = activeFilters() ? " (" + activeFilters() + ")" : "";
    jobsBody.appendChild(jobRows(shown, "jobs", JOB_COLUMNS, state.expanded));
    if (focusedKey) {
      var again = rowByKeyNode(focusedKey);
      if (again) again.focus({ preventScroll: true });
    }
  }

  function rowByKeyNode(key) {
    return jobsBody.querySelector('tr.row[data-key="' + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]');
  }

  /* ---------- keys: the cursor is the focused row ---------- */

  function focusedRow() {
    var a = document.activeElement;
    return a && a.classList && a.classList.contains("row") && jobsBody.contains(a) ? a : null;
  }

  function moveFocus(dir) {
    var list = Array.prototype.slice.call(jobsBody.querySelectorAll("tr.row"));
    if (!list.length) return;
    var cur = focusedRow();
    var i = cur ? list.indexOf(cur) + dir : (dir > 0 ? 0 : list.length - 1);
    i = Math.max(0, Math.min(list.length - 1, i));
    list[i].focus({ preventScroll: true });
    list[i].scrollIntoView({ block: "nearest", behavior: U.reduced() ? "auto" : "smooth" });
  }

  /* True when the key was handled. Inside the row's details (a form, a chip) the keys are the
     controls' own. */
  function listKeys(ev) {
    if (R.open && !JM.wideScreen()) return false;
    if (ev.key === "/") { controls.open = true; searchInput.focus(); searchInput.select(); return true; }
    if (ev.key === "j" || ev.key === "ArrowDown") { moveFocus(1); return true; }
    if (ev.key === "k" || ev.key === "ArrowUp") { moveFocus(-1); return true; }
    var row = focusedRow();
    if (!row) return false;
    var j = row.jmRow;
    if (ev.key === "x" && canWrite()) { quickSet(j, "ignored"); return true; }
    if (ev.key === "s" && canWrite()) { quickSet(j, "to_apply"); return true; }
    if (ev.key === "a" && canWrite()) { markApplied(j); return true; }
    if (ev.key === "Enter") {
      if (j.url && HTTP.test(j.url)) window.open(j.url, "_blank", "noopener");
      else row.toggleDetails();
      return true;
    }
    if (ev.key === "o") { openRecord(j, row); return true; }
    return false;
  }

  /* ---------- density ---------- */

  var DENSITY_KEY = "jm.density.v1";
  function setDensity(d, persist) {
    d = d === "comfortable" ? "comfortable" : "dense";
    document.body.setAttribute("data-density", d);
    ["dense", "comfortable"].forEach(function (x) {
      var b = byId("density-" + x);
      if (b) b.setAttribute("aria-pressed", String(x === d));
    });
    if (persist) { try { localStorage.setItem(DENSITY_KEY, d); } catch (e) { /* private window */ } }
  }
  (function () {
    var d = "dense";
    try { d = localStorage.getItem(DENSITY_KEY) || d; } catch (e) { /* private window */ }
    setDensity(d, false);
  })();
  ["dense", "comfortable"].forEach(function (x) {
    var b = byId("density-" + x);
    if (b) b.addEventListener("click", function () { setDensity(x, true); });
  });

  /* The filters panel: closed by default (rows first), its state remembered. */
  var CONTROLS_KEY = "jm.offres.filters.open";
  try { controls.open = localStorage.getItem(CONTROLS_KEY) === "1"; } catch (e) { /* private window */ }
  controls.addEventListener("toggle", function () {
    try { localStorage.setItem(CONTROLS_KEY, controls.open ? "1" : "0"); } catch (e) { /* private window */ }
  });

  /* ---------- controls ---------- */

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

  sourceSelect.addEventListener("change", function () {
    state.source = sourceSelect.value;
    renderJobs();
    syncHash();
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
  aiSelect.addEventListener("change", function () {
    state.ai = AI_LEVELS.indexOf(aiSelect.value) >= 0 ? aiSelect.value : "";
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

  function resetFilters(focus) {
    state.q = ""; searchInput.value = "";
    SECTIONS.forEach(function (s) { state.sections[s] = true; });
    chips.forEach(function (c) { c.setAttribute("aria-pressed", "true"); });
    state.department = ""; deptSelect.value = "";
    state.source = ""; sourceSelect.value = "";
    state.status = ""; statusSelect.value = "";
    state.ai = ""; aiSelect.value = "";
    state.minScore = 0; minScoreInput.value = "0"; minScoreOut.textContent = "0";
    state.from = ""; fromInput.value = "";
    state.to = ""; toInput.value = "";
    renderJobs();
    syncHash();
    if (focus) searchInput.focus();
  }
  byId("f-reset").addEventListener("click", function () { resetFilters(true); });
  byId("jobs-empty-reset").addEventListener("click", function () { resetFilters(false); });

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

  var SORT_KEYS = ["title", "company", "department", "contract", "source", "score", "required_years", "status", "posted_at", "age_days"];
  var DAY = /^\d{4}-\d{2}-\d{2}$/;

  /* The remembered filters (app.js writes them with the hash), for a hash that carries none. */
  function storedParams() {
    var raw = null;
    try { raw = localStorage.getItem(JM.FILTERS_KEY); } catch (e) { return {}; }
    var params = {};
    (raw || "").split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i < 0) return;
      try { params[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* bad escape */ }
    });
    delete params.view;
    delete params.fiche;
    return params;
  }

  function applyHash() {
    var parsed = parseHash();
    var p = location.hash.indexOf("?") < 0 ? storedParams() : parsed.params;
    V.applyingHash = true;
    state.q = (p.q || "").trim().toLowerCase();
    searchInput.value = p.q || "";
    SECTIONS.forEach(function (s) { state.sections[s] = true; });
    (p.hide || "").split(",").forEach(function (s) { if (SECTIONS.indexOf(s) >= 0) state.sections[s] = false; });
    chips.forEach(function (c) { c.setAttribute("aria-pressed", state.sections[c.getAttribute("data-section")] ? "true" : "false"); });
    var deptOk = p.dept && Array.prototype.some.call(deptSelect.options, function (o) { return o.value === p.dept; });
    state.department = deptOk ? p.dept : "";
    deptSelect.value = state.department;
    var srcOk = p.src && Array.prototype.some.call(sourceSelect.options, function (o) { return o.value === p.src; });
    state.source = srcOk ? p.src : "";
    sourceSelect.value = state.source;
    state.status = T.STATUSES.indexOf(p.st) >= 0 ? p.st : "";
    statusSelect.value = state.status;
    state.ai = AI_LEVELS.indexOf(p.ia) >= 0 ? p.ia : "";
    aiSelect.value = state.ai;
    if (parsed.params.view === "table" || parsed.params.view === "kanban") setAppsView(parsed.params.view, true);
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
    var fiche = parsed.tab !== "tri" && parsed.params.fiche && rowByKey(parsed.params.fiche);
    if (fiche && (!R.open || R.job !== fiche)) openRecord(fiche, null);
    else if (!parsed.params.fiche && R.open) closeRecord(false);
    V.applyingHash = false;
    syncHash();
  }

  /* The listed row (a group's best posting stands for the group) that holds this key. */
  function rowByKey(key) {
    for (var i = 0; i < rows.length; i++) {
      if (T.postingsOf(rows[i]).some(function (p) { return p.key === key; })) return rows[i];
    }
    return null;
  }

  /* Shared with the other files. */
  JM.applyHash = applyHash;
  JM.fillDepartments = fillDepartments;
  JM.fillSources = fillSources;
  JM.fillStatuses = fillStatuses;
  JM.postingsBlock = postingsBlock;
  JM.renderJobs = renderJobs;
  JM.listKeys = listKeys;
  JM.quickSet = quickSet;
  JM.state = state;
})(window.JM);
