/* « Pourquoi cette offre ? » (ADR 0013): the evidence behind a score, read top-down as a ledger.
   Every line is something the engine actually used: the skills it matched (weight and the
   sentence of the offer), the penalties, the title, the experience gate. The skills the offer
   cites that the profile lacks come after, marked as not counted, because « je maîtrise » saves
   them for the next run. Weights sit in one right-aligned column with tabular digits. */
(function (JM) {
  "use strict";

  var el = JM.el, fmtYears = JM.fmtYears, failureText = JM.failureText;
  var S = JM.S, track = JM.track, api = JM.api, overrideViews = JM.overrideViews;

  var BASIS_TEXT = {
    explicit: "chiffre explicite",
    seniority: "mot-clé de séniorité",
    unknown: "inconnu",
    not_mentioned: "non mentionné"
  };

  function weightText(w) {
    return typeof w === "number" ? S.signed(w) : "";
  }

  /* One ledger line: what, how much, and the sentence it came from. */
  function line(kind, name, weight, sentence, control) {
    var n = Math.abs(weight || 0);
    var says = typeof weight !== "number" ? null
      : (weight > 0 ? "Ajoute " : "Retire ") + n + " point" + (n > 1 ? "s" : "") + " au score de cette offre";
    var row = el("div", { class: "why-line " + kind }, [
      el("dt", null, [el("span", { class: "why-name", text: name }), control || null]),
      el("dd", { class: "num why-w", title: says, "aria-label": says ? says : null, text: weightText(weight) })
    ]);
    if (sentence) row.appendChild(el("q", { class: "why-ev", text: sentence }));
    return row;
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

  /* The experience gate as one line: the years, how they were found, the sentence. */
  function experienceLine(e, job) {
    if (!e) return line("gate", "Expérience : aucune analyse stockée", null, null);
    var years = fmtYears(e.required_years);
    var text = years === null
      ? (e.basis === "explicit" ? "Pas de minimum chiffré" : "Années requises inconnues")
      : years === "0" ? "Aucune année exigée"
        : years + (years === "1" ? " an requis" : " ans requis");
    var basis = e.basis && BASIS_TEXT[e.basis] ? BASIS_TEXT[e.basis] : "non recalculé";
    var verdict = job.section === "stretch" ? "à tenter" : "passe";
    var row = el("div", { class: "why-line gate" + (job.section === "stretch" ? " down" : "") }, [
      el("dt", null, [el("span", { class: "why-name", text: "Expérience : " + text }), el("span", { class: "why-basis", text: basis })]),
      el("dd", { class: "why-w", text: verdict })
    ]);
    if (e.sentence) row.appendChild(el("q", { class: "why-ev", text: e.sentence }));
    if (e.excludes_apprenticeship) row.appendChild(el("span", { class: "tag tag-flag", text: "hors stage et alternance" }));
    return row;
  }

  function plural(n, one, many) { return n + " " + (n > 1 ? many : one); }

  /* Closed in the record panel's host by default; the list opens it with the row. */
  function whyPanel(j, verdictBlock) {
    var w = j.why || { skills: [], unlisted: [], lowered: [], experience: null };
    var parts = [plural(w.skills.length, "compétence", "compétences")];
    if (w.lowered.length) parts.push(plural(w.lowered.length, "malus", "malus"));
    if (w.unlisted.length) parts.push(plural(w.unlisted.length, "non trouvée", "non trouvées"));
    var panel = el("details", { class: "why" });
    panel.appendChild(el("summary", { class: "why-title" }, [
      el("span", { text: "Pourquoi cette offre te correspond" }),
      el("span", { class: "why-summary", text: parts.join(" · ") })
    ]));
    var ledger = el("dl", { class: "why-ledger" });
    var b = S.breakdown(j);
    var bySkill = {};
    w.skills.forEach(function (s) { bySkill[s.name] = s; });
    w.lowered.forEach(function (s) { bySkill[s.name] = s; });
    /* The scorer's own lines, in its order: skills, penalties, title; each with its sentence. */
    var seen = {};
    if (b && b.lines.length) {
      b.lines.forEach(function (l) {
        var name = l.label.replace(/ \(demandée au profil\)$/, "");
        var ev = bySkill[name];
        if (ev) seen[name] = true;
        ledger.appendChild(line(l.kind, l.label, l.value, ev ? ev.snippet : null));
      });
    }
    /* Skills with a stored weight but no explanation line (rows scored before the ledger). */
    /* A lowered skill is a malus even when its weight was not stored (AUDIT O11). */
    w.skills.forEach(function (s) {
      if (!seen[s.name]) ledger.appendChild(line(typeof s.weight === "number" && s.weight < 0 ? "down" : "up", s.name, s.weight, s.snippet));
    });
    w.lowered.forEach(function (s) {
      if (seen[s.name]) return;
      var l = line("down", s.name, s.weight, s.snippet);
      if (typeof s.weight !== "number") l.querySelector(".why-w").textContent = "malus";
      ledger.appendChild(l);
    });
    if (!ledger.childNodes.length) ledger.appendChild(el("p", { class: "note", text: "Aucune compétence de ton profil trouvée dans l’offre." }));
    ledger.appendChild(experienceLine(w.experience, j));
    if (b) ledger.appendChild(el("div", { class: "why-line total" }, [el("dt", { text: b.capped ? "Score (plafonné)" : "Score" }), el("dd", { class: "num why-w", text: String(b.total) })]));
    panel.appendChild(ledger);

    if (w.unlisted.length) {
      var extra = el("dl", { class: "why-ledger why-unlisted", "aria-label": "Dans l’offre, pas dans ton profil" });
      extra.appendChild(el("div", { class: "why-line head" }, [el("dt", { text: "Dans l’offre, pas dans ton profil" }), el("dd", { class: "why-w", text: "non compté" })]));
      w.unlisted.forEach(function (u) { extra.appendChild(line("miss", u.name, null, u.snippet, overrideControl(u.name))); });
      panel.appendChild(extra);
    }
    panel.appendChild(el("div", { class: "why-block why-verdict" }, [el("h4", { text: "Ton avis" }), verdictBlock ||
      el("p", { class: "note", text: "Les avis s’enregistrent depuis le tableau de bord hébergé." })]));
    /* Clicks inside the panel (chips, buttons, the summary) must not toggle the row. */
    panel.addEventListener("click", function (ev) { ev.stopPropagation(); });
    panel.addEventListener("keydown", function (ev) { ev.stopPropagation(); });
    return panel;
  }

  /* The scorer writes its explanations in English (they are stored and logged that way);
     the page shows them in French. Unknown lines pass through as they are. */
  var EXPLAIN_FR = [
    [/^stretch: requires (\S+)y, you have (\S+)$/, function (m) { return "À tenter : " + m[1] + " an(s) requis, tu en as " + m[2]; }],
    [/^Matched preferred: (.+) \((\+?-?\d+)\)$/, function (m) { return "Compétence trouvée : " + m[1] + " (" + m[2] + ")"; }],
    [/^Missed preferred: (.+)$/, function (m) { return "Compétence absente de l’offre : " + m[1]; }],
    [/^Matched negative: (.+) \((-?\d+)\)$/, function (m) { return "Malus : " + m[1] + " (" + m[2] + ")"; }],
    [/^Title keyword match: (.+) \((\+?\d+)\)$/, function (m) { return "Mot-clé dans le titre : " + m[1] + " (" + m[2] + ")"; }],
    [/^Title relevance: (core|near|other) \(([+-]?\d+)\)$/, function (m) {
      return "Titre : " + { core: "métier visé", near: "métier proche", other: "hors des métiers visés" }[m[1]] + " (" + m[2] + ")";
    }],
    [/^Profile section: (.+) \(x([\d.]+)\)$/, function (m) { return "Demandée dans le profil : " + m[1] + " (poids ×" + m[2].replace(".", ",") + ")"; }],
    [/^experience: internships\/work-study excluded from required years$/, function () { return "Expérience : stages et alternance exclus des années requises"; }]
  ];

  function frExplanation(line) {
    for (var i = 0; i < EXPLAIN_FR.length; i++) {
      var m = EXPLAIN_FR[i][0].exec(line);
      if (m) return EXPLAIN_FR[i][1](m);
    }
    return line;
  }

  /* Shared with the other files. */
  JM.frExplanation = frExplanation;
  JM.whyPanel = whyPanel;
})(window.JM);
