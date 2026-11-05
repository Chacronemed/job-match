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
  var fillDepartments = function () { return JM.fillDepartments.apply(null, arguments); };
  var fillStatuses = function () { return JM.fillStatuses.apply(null, arguments); };
  var fmtDateTime = function () { return JM.fmtDateTime.apply(null, arguments); };
  var loadTracking = function () { return JM.loadTracking.apply(null, arguments); };
  var paletteCommands = function () { return JM.paletteCommands.apply(null, arguments); };
  var renderLeads = function () { return JM.renderLeads.apply(null, arguments); };
  var renderPending = function () { return JM.renderPending.apply(null, arguments); };
  var renderRuns = function () { return JM.renderRuns.apply(null, arguments); };
  var updateCounts = function () { return JM.updateCounts.apply(null, arguments); };
  /* ---------- boot ---------- */

  /* Short in the sidebar; the full date and time zone in the tooltip. */
  var snap = byId("generated-at");
  var snapAt = new Date(data.generated_at);
  snap.textContent = isNaN(snapAt.getTime()) ? "Instantané" : "Instantané du " + snapAt.toLocaleString("fr-FR", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC"
  });
  snap.title = "Données générées le " + fmtDateTime(data.generated_at);

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
  updateCounts();
  renderPending();  /* actions left from an earlier visit show at once */
  applyHash();
  loadTracking();
})(window.JM);
