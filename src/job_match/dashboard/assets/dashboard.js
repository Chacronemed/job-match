/* job-match dashboard boot: wires the chrome, draws the static views and applies the hash.
   Loaded last; the core is app.js, the screens their own files. */
(function (JM) {
  "use strict";

  /* From the other files (app.js first; the screens after it): values are read once,
     functions through the namespace at call time, so the load order never matters. */
  var HELP = JM.HELP;
  var MOD = JM.MOD;
  var P = JM.P;
  var U = JM.U;
  var applyHash = function () { return JM.applyHash.apply(null, arguments); };
  var byId = function () { return JM.byId.apply(null, arguments); };
  var data = JM.data;
  var el = JM.el;
  var fillDepartments = function () { return JM.fillDepartments.apply(null, arguments); };
  var fillSources = function () { return JM.fillSources.apply(null, arguments); };
  var fillStatuses = function () { return JM.fillStatuses.apply(null, arguments); };
  var showTab = function () { return JM.showTab.apply(null, arguments); };
  var fmtShortDate = function () { return JM.fmtShortDate.apply(null, arguments); };
  var runs = JM.runs;
  var fmtDateTime = function () { return JM.fmtDateTime.apply(null, arguments); };
  var loadTracking = function () { return JM.loadTracking.apply(null, arguments); };
  var paletteCommands = function () { return JM.paletteCommands.apply(null, arguments); };
  var renderLeads = function () { return JM.renderLeads.apply(null, arguments); };
  var renderPending = function () { return JM.renderPending.apply(null, arguments); };
  var renderRuns = function () { return JM.renderRuns.apply(null, arguments); };
  var updateCounts = function () { return JM.updateCounts.apply(null, arguments); };
  /* ---------- boot ---------- */

  /* Short in the top bar; the full date and time zone in the tooltip. */
  var snap = byId("generated-at");
  var snapAt = new Date(data.generated_at);
  snap.textContent = isNaN(snapAt.getTime()) ? "Instantané" : "Instantané du " + snapAt.toLocaleString("fr-FR", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC"
  });
  snap.title = "Données générées le " + fmtDateTime(data.generated_at);

  /* The sidebar's foot: the latest collection run as the data has it (its date, whether it
     reported errors); nothing invented when there is none. */
  var lastRun = byId("last-run");
  var latest = runs.length ? runs[0] : null;
  if (latest && latest.started_at) {
    var bad = !!latest.errors;
    lastRun.appendChild(U.dot(bad ? "var(--amber-9)" : "var(--green-9)"));
    lastRun.appendChild(el("span", null, [
      (bad ? "Dernière collecte avec " + latest.errors + (latest.errors > 1 ? " erreurs" : " erreur") : "Dernière collecte réussie"),
      document.createElement("br"),
      fmtDateTime(latest.started_at)
    ]));
  } else {
    lastRun.appendChild(U.dot("var(--ink-3)"));
    lastRun.appendChild(el("span", { text: "Aucune collecte enregistrée" }));
  }

  var paletteBtn = byId("palette-btn");
  paletteBtn.insertBefore(U.icon("search"), paletteBtn.firstChild);
  paletteBtn.appendChild(U.kbd(MOD, "K"));
  paletteBtn.addEventListener("click", function () { P.open(); });
  var paletteBtnM = byId("palette-btn-m");
  paletteBtnM.appendChild(U.icon("search"));
  paletteBtnM.addEventListener("click", function () { P.open(); });
  byId("help-btn").addEventListener("click", function () { P.openHelp(); });
  /* « Trier les nouvelles » (Offres) goes to Tri; « Relances à faire » to the due list. */
  var toTri = byId("offres-to-tri");
  toTri.appendChild(U.icon("arrow-right"));
  toTri.addEventListener("click", function () { showTab("tri", true, true); });
  byId("nav-due").addEventListener("click", function (ev) {
    if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    showTab("candidatures", false, true);
    var due = byId("kb-due");
    if (!due.hidden) { due.scrollIntoView({ block: "start" }); var first = due.querySelector("button"); if (first) first.focus({ preventScroll: true }); }
    else byId("main").focus({ preventScroll: true });
  });
  P.init(paletteCommands, HELP);
  byId("tri-drop").insertBefore(U.icon("x"), byId("tri-drop").firstChild);
  byId("tri-drop").appendChild(U.kbd("←"));
  byId("tri-undo").appendChild(U.icon("undo-2"));
  byId("tri-undo").appendChild(U.kbd("Z"));
  byId("tri-keep").insertBefore(U.icon("check"), byId("tri-keep").firstChild);
  byId("tri-keep").appendChild(U.kbd("→"));
  fillDepartments();
  fillSources();
  fillStatuses();
  renderLeads();
  renderRuns();
  updateCounts();
  renderPending();  /* actions left from an earlier visit show at once */
  applyHash();
  loadTracking();
})(window.JM);
