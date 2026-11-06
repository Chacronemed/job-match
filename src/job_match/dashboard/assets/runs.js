/* Exécutions: the AI passes and the collection runs, as funnels. */
(function (JM) {
  "use strict";

  /* From the other files (app.js first; the screens after it): values are read once,
     functions through the namespace at call time, so the load order never matters. */
  var S = JM.S;
  var byId = function () { return JM.byId.apply(null, arguments); };
  var clear = JM.clear;
  var el = JM.el;
  var fmtDateTime = function () { return JM.fmtDateTime.apply(null, arguments); };
  var runs = JM.runs;
  var track = JM.track;
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

  /* « Rerank IA » (ADR 0016): the cron passes the Worker recorded, newest first, from
     /api/applications. A stopped pass shows its HTTP status in red; nothing else is known. */
  function renderAiRuns() {
    var list = byId("ai-runs-list");
    clear(list);
    var runs = track.aiRuns || [];
    byId("ai-runs-empty").hidden = runs.length > 0;
    runs.forEach(function (r) {
      var line = S.aiRunLine(r);
      var head = el("div", { class: "run-head" }, [
        el("span", { class: "run-date", text: r.started_at ? fmtDateTime(r.started_at) : "—" }),
        el("span", { class: "badge" + (line.bad ? " badge-bad" : " badge-ok"), text: line.label }),
        r.provider ? el("span", { class: "run-fetched", text: r.provider === "workers_ai" ? "Workers AI" : "Claude" }) : null
      ]);
      var stats = el("p", { class: "run-stats" }, line.stats.map(function (s) { return stat(s.label, s.value); }));
      list.appendChild(el("article", { class: "run run-ai" }, [head, stats]));
    });
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

      /* Source outage guard (ADR 0027): the sources (or ATS boards) the run read as down, so
         none of their offers was closed that day. One line each, the reason in full. */
      (r.outages || []).forEach(function (o) {
        var scope = (o.boards && o.boards.length) ? " (" + o.boards.length + " board(s))" : "";
        card.appendChild(el("p", { class: "run-outage", role: "status", "data-source": o.source }, [
          el("b", { text: (o.label || o.source) + scope + " indisponible — clôtures suspendues" }),
          " : " + (o.reason || "")
        ]));
      });

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
      if (r.suspended) stats.appendChild(stat("clôtures suspendues", r.suspended));
      /* Auto-archived applications (ADR 0028): the day's new ones, the total in the title. */
      if (r.archived_today || r.archived) {
        var arch = stat("candidatures archivées aujourd’hui", r.archived_today || 0);
        arch.title = (r.archived || 0) + " archivée(s) au total";
        arch.className = "run-archived";
        stats.appendChild(arch);
      }
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
          var parts = [
            name + ": ",
            el("b", { text: String(s.fetched || 0) }), " récupérées, ",
            el("b", { text: String(s.eligible || 0) }), " éligibles, ",
            el("b", { text: String(s.calls || 0) }), " appels"
          ];
          /* The closure counters per source (ADR 0027), on runs that stored them. */
          if ("checked" in s) {
            parts.push(", ", el("b", { text: String(s.checked || 0) }), " vérifiées, ",
              el("b", { text: String(s.closed || 0) }), " fermées");
            if (s.suspended) parts.push(", ", el("b", { text: String(s.suspended) }), " clôtures suspendues");
          }
          sp.appendChild(el("span", { class: "run-source", "data-source": name }, parts));
        });
        card.appendChild(sp);
      }

      /* The company boards (source ats, ADR 0020): fetched / eligible per company, the
         busiest first; a board that answered nothing is not listed. Folded: 30+ lines. */
      Object.keys(r.by_company || {}).sort().forEach(function (name) {
        var per = r.by_company[name] || {};
        var names = Object.keys(per).sort(function (a, b) {
          return (per[b].fetched || 0) - (per[a].fetched || 0) || a.localeCompare(b, "fr");
        });
        if (!names.length) return;
        var box = el("details", { class: "run-companies" }, [
          el("summary", { text: (name === "ats" ? "Pages carrière" : name) + " par entreprise (" + names.length + ")" })
        ]);
        var ul = el("ul");
        names.forEach(function (c) {
          ul.appendChild(el("li", null, [
            c + " : ",
            el("b", { text: String(per[c].fetched || 0) }), " récupérées, ",
            el("b", { text: String(per[c].eligible || 0) }), " éligibles"
          ]));
        });
        box.appendChild(ul);
        card.appendChild(box);
      });
      list.appendChild(card);
    });
  }

  /* Shared with the other files. */
  JM.renderAiRuns = renderAiRuns;
  JM.renderRuns = renderRuns;
})(window.JM);
