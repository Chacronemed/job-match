/* The score « Relevé »: how an offer's score adds up, read from the scorer's own explanation
   lines (scoring/native.py writes every weight into them). Pure functions, no DOM: shared by
   the page and the Node tests. Nothing is guessed: a capped score (0 or 100) has no start line,
   because the sum before the cap is not in the data. */
(function (root) {
  "use strict";

  var LINE = [
    [/^Matched preferred: (.+) \((\+?-?\d+)\)$/, "up"],
    [/^Matched negative: (.+) \((-?\d+)\)$/, "down"],
    [/^Title keyword match: (.+) \((\+?\d+)\)$/, "title"],
    [/^Title relevance: (core|near|other) \(([+-]?\d+)\)$/, "family"]
  ];
  /* M24: what the title says the job is (scoring/title.py). */
  var FAMILY = { core: "titre : métier visé", near: "titre : métier proche", other: "titre : hors des métiers visés" };
  var PROFILE = /^Profile section: (.+) \(x[\d.]+\)$/;
  var STRETCH = /^stretch: requires (\S+)y, you have (\S+)$/;

  /* {start, lines:[{kind, label, value}], total, capped} or null without a numeric score. */
  function breakdown(job) {
    if (!job || typeof job.score !== "number") return null;
    var lines = [];
    var inProfile = {};
    (job.explanations || []).forEach(function (text) {
      var p = PROFILE.exec(text);
      if (p) inProfile[p[1]] = true;
    });
    (job.explanations || []).forEach(function (text) {
      for (var i = 0; i < LINE.length; i++) {
        var m = LINE[i][0].exec(text);
        if (!m) continue;
        var kind = LINE[i][1], value = Number(m[2]);
        if (kind === "family") {
          if (value) lines.push({ kind: value > 0 ? "up" : "down", label: FAMILY[m[1]], value: value });
          return;
        }
        lines.push({
          kind: kind === "title" ? "up" : kind,
          label: kind === "title" ? "titre « " + m[1] + " »"
            : m[1] + (kind === "up" && inProfile[m[1]] ? " (demandée au profil)" : ""),
          value: value
        });
        return;
      }
    });
    var delta = lines.reduce(function (a, l) { return a + l.value; }, 0);
    var capped = job.score === 0 || job.score === 100;
    return { start: capped ? null : job.score - delta, lines: lines, total: job.score, capped: capped };
  }

  /* The band the pipeline put the offer in (data.py `section`), in words. */
  var BAND = {
    strong: { key: "strong", label: "Forte" },
    eligible: { key: "eligible", label: "Éligible" },
    stretch: { key: "stretch", label: "À tenter" }
  };
  function band(job) {
    return BAND[job && job.section] || { key: "low", label: "Faible" };
  }

  function points(n) { return n + (n > 1 ? " points" : " point"); }
  var YEARS = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

  /* The one sentence under the ledger: what separates this offer from « forte ». */
  function gapSentence(job, thresholds) {
    if (!job || typeof job.score !== "number") return "Score inconnu.";
    if (job.section === "stretch") {
      for (var i = 0; i < (job.explanations || []).length; i++) {
        var m = STRETCH.exec(job.explanations[i]);
        if (m) {
          var need = Number(m[1]), have = Number(m[2]);
          return "À tenter : " + YEARS.format(need) + (need < 2 ? " an requis" : " ans requis") +
            ", tu en as " + YEARS.format(have) + ".";
        }
      }
      return "À tenter : un peu plus d’expérience que ton profil.";
    }
    var strong = thresholds && typeof thresholds.strong === "number" ? thresholds.strong : 75;
    var gap = strong - job.score;
    if (gap > 0) return "Il manque " + points(gap) + " pour forte.";
    return gap === 0 ? "Forte, pile au seuil (" + strong + ")." : "Forte : " + points(-gap) + " au-dessus du seuil.";
  }

  function signed(v) { return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v); }

  var api = { breakdown: breakdown, band: band, gapSentence: gapSentence, signed: signed };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JMScore = api;
})(this);
