/* Statistiques: the funnel of my search, from the snapshot and the tracking only. Nothing is
   estimated: a stage without a date stays out of the weekly chart and is counted as such, a
   delay is a mean over the pairs that have both dates, and "—" means there is none.

   The period is a cohort: the offers collected since (generated_at − 30 / 90 days), followed
   to their current status. « Tout » adds the applications whose offer the snapshot no longer
   has. The weekly chart is the exception: it places each event on its own date.

   Dates: « gardée » = the latest verdict when it is « Bon match » (Tri, or the record);
   « envoyée » = applied_at; « réponse » = the first recruiter reply linked to the application
   (an acknowledgment is not one), or the status entretien / refusée when no reply is linked. */
(function (root) {
  "use strict";

  var KEPT = ["to_apply", "applied", "interview", "rejected"];
  var SENT = ["applied", "interview", "rejected"];
  var DROP_LABELS = ["off_topic", "too_senior", "missing_skill", "location"];
  var PERIOD_DAYS = { "30": 30, "90": 90, tout: null };
  var DAY_MS = 86400000;
  var MAX_WEEKS = 26;

  function ms(value) {
    if (typeof value !== "string" || !value) return null;
    var t = Date.parse(value.length === 10 ? value + "T00:00:00Z" : value);
    return isNaN(t) ? null : t;
  }

  /* Whole days between two dates, by their UTC calendar day. */
  function dayGap(from, to) {
    var a = ms(from), b = ms(to);
    if (a === null || b === null) return null;
    return Math.round((Math.floor(b / DAY_MS) - Math.floor(a / DAY_MS)));
  }

  /* Monday 00:00 UTC of the week holding `t`. */
  function weekStart(t) {
    var day = Math.floor(t / DAY_MS);
    var dow = (new Date(day * DAY_MS).getUTCDay() + 6) % 7;
    return (day - dow) * DAY_MS;
  }

  function mean(list) {
    if (!list.length) return null;
    return list.reduce(function (s, x) { return s + x; }, 0) / list.length;
  }

  function rate(n, of) {
    return of > 0 ? n / of : null;
  }

  function bump(map, key, field) {
    var row = map[key] = map[key] || { name: key, eligible: 0, kept: 0, sent: 0 };
    if (field) row[field] += 1;
    return row;
  }

  /* input: {postings: [{key, collected_at, source, company, closed, listed, why}],
     apps: {key: application}, decisions: {key: label}, decisionAt: {key: iso},
     replies: [{key, received_at, kind}], overrides: {skill: true}, period, now: iso}. */
  function compute(input) {
    var apps = input.apps || {};
    var decisions = input.decisions || {};
    var decisionAt = input.decisionAt || {};
    var overrides = input.overrides || {};
    var days = PERIOD_DAYS.hasOwnProperty(input.period) ? PERIOD_DAYS[input.period] : 30;
    var now = ms(input.now) || Date.now();
    var since = days === null ? null : now - days * DAY_MS;
    function inWindow(t) { return since === null || (t !== null && t >= since); }
    function status(k) { var a = apps[k]; return a && KEPT.concat(["to_review", "ignored"]).indexOf(a.status) >= 0 ? a.status : "to_review"; }

    var byKey = {};
    (input.postings || []).forEach(function (p) { if (p && p.key && !byKey[p.key]) byKey[p.key] = p; });

    /* The first real reply per application. */
    var firstReply = {};
    (input.replies || []).forEach(function (r) {
      if (!r || !r.key || r.kind === "accuse_reception" || !r.kind) return;
      var t = ms(r.received_at);
      if (t === null) return;
      if (!firstReply[r.key] || t < ms(firstReply[r.key])) firstReply[r.key] = r.received_at;
    });

    function keptAt(k) { return decisions[k] === "good_fit" && decisionAt[k] ? decisionAt[k] : null; }
    function isKept(k) { return KEPT.indexOf(status(k)) >= 0; }
    function isSent(k) { return SENT.indexOf(status(k)) >= 0; }
    function isInterview(k) { return status(k) === "interview" || !!(apps[k] && apps[k].interview_at && isSent(k)); }
    function hasReply(k) { return isSent(k) && (status(k) === "interview" || status(k) === "rejected" || !!firstReply[k] || isInterview(k)); }
    function isExpired(k) { return status(k) === "to_apply" && !!byKey[k] && byKey[k].closed === true; }

    var keys = [];
    Object.keys(byKey).forEach(function (k) { if (inWindow(ms(byKey[k].collected_at))) keys.push(k); });
    var orphans = 0;
    if (since === null) {
      Object.keys(apps).forEach(function (k) {
        if (!byKey[k] && status(k) !== "to_review") { keys.push(k); orphans += 1; }
      });
    }

    var f = { seen: keys.length, kept: 0, sent: 0, replies: 0, interviews: 0, refusals: 0 };
    var reasons = { off_topic: 0, too_senior: 0, missing_skill: 0, location: 0, none: 0 };
    var dropped = 0;
    var skills = {};
    var keptWithPosting = 0;
    var sources = {}, companies = {};
    var expired = 0, archived = 0;
    var keepToSend = [], sendToReply = [];
    var undated = { kept: 0, sent: 0, replies: 0 };

    keys.forEach(function (k) {
      var p = byKey[k];
      var s = status(k);
      var kept = isKept(k), sent = isSent(k);
      if (kept) f.kept += 1;
      if (sent) f.sent += 1;
      if (hasReply(k)) f.replies += 1;
      if (isInterview(k)) f.interviews += 1;
      if (s === "rejected") f.refusals += 1;
      if (s === "ignored") {
        dropped += 1;
        reasons[DROP_LABELS.indexOf(decisions[k]) >= 0 ? decisions[k] : "none"] += 1;
      }
      if (kept && !keptAt(k)) undated.kept += 1;
      if (sent && !ms(apps[k].applied_at)) undated.sent += 1;
      if (hasReply(k) && !firstReply[k]) undated.replies += 1;
      if (isExpired(k)) expired += 1;
      else if (p && p.listed === false) archived += 1;
      if (p) {
        var src = p.source || "?";
        bump(sources, src, "eligible");
        if (kept) bump(sources, src, "kept");
        if (sent) bump(sources, src, "sent");
        if (p.company) {
          bump(companies, p.company, "eligible");
          if (kept) bump(companies, p.company, "kept");
          if (sent) bump(companies, p.company, "sent");
        }
        if (kept) {
          keptWithPosting += 1;
          var seen = {};
          ((p.why && p.why.unlisted) || []).forEach(function (u) {
            var name = u && u.name;
            if (!name || overrides[name] || seen[name]) return;
            seen[name] = true;
            skills[name] = (skills[name] || 0) + 1;
          });
        }
      }
      if (sent && keptAt(k) && apps[k].applied_at) {
        var g = dayGap(keptAt(k), apps[k].applied_at);
        if (g !== null && g >= 0) keepToSend.push(g);
      }
      if (sent && firstReply[k] && apps[k].applied_at) {
        var r = dayGap(apps[k].applied_at, firstReply[k]);
        if (r !== null && r >= 0) sendToReply.push(r);
      }
    });

    function sorted(map) {
      return Object.keys(map).map(function (k) { return map[k]; }).sort(function (a, b) {
        return b.eligible - a.eligible || b.kept - a.kept || b.sent - a.sent || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
      });
    }

    return {
      period: days === null ? "tout" : String(days),
      since: since === null ? null : new Date(since).toISOString(),
      orphans: orphans,
      funnel: [
        { key: "seen", label: "Offres vues", n: f.seen, rate: null, of: null },
        { key: "kept", label: "Gardées", n: f.kept, rate: rate(f.kept, f.seen), of: "des vues" },
        { key: "sent", label: "Envoyées", n: f.sent, rate: rate(f.sent, f.kept), of: "des gardées" },
        { key: "replies", label: "Réponses", n: f.replies, rate: rate(f.replies, f.sent), of: "des envoyées" },
        { key: "interviews", label: "Entretiens", n: f.interviews, rate: rate(f.interviews, f.sent), of: "des envoyées" },
        { key: "refusals", label: "Refus", n: f.refusals, rate: rate(f.refusals, f.sent), of: "des envoyées" }
      ],
      dropped: dropped,
      reasons: DROP_LABELS.concat(["none"]).map(function (l) { return { label: l, n: reasons[l] }; }),
      skills: Object.keys(skills).map(function (n) { return { name: n, n: skills[n] }; })
        .sort(function (a, b) { return b.n - a.n || (a.name < b.name ? -1 : 1); }).slice(0, 8),
      keptWithPosting: keptWithPosting,
      sources: sorted(sources),
      companies: sorted(companies).slice(0, 10),
      companyCount: Object.keys(companies).length,
      expired: expired,
      archived: archived,
      delays: {
        keepToSend: { days: mean(keepToSend), n: keepToSend.length },
        sendToReply: { days: mean(sendToReply), n: sendToReply.length }
      },
      undated: undated,
      weeks: weekly(apps, decisions, decisionAt, firstReply, isKept, isSent, since, now)
    };
  }

  /* Gardées, envoyées, réponses per week (Monday, UTC), each event on its own date. */
  function weekly(apps, decisions, decisionAt, firstReply, isKept, isSent, since, now) {
    var events = [];
    Object.keys(apps).forEach(function (k) {
      if (isKept(k) && decisions[k] === "good_fit" && ms(decisionAt[k]) !== null) events.push(["kept", ms(decisionAt[k])]);
      if (isSent(k) && ms(apps[k].applied_at) !== null) events.push(["sent", ms(apps[k].applied_at)]);
      if (isSent(k) && firstReply[k]) events.push(["replies", ms(firstReply[k])]);
    });
    events = events.filter(function (e) { return since === null || e[1] >= since; });
    if (!events.length) return { list: [], capped: false };
    var first = since === null ? Math.min.apply(null, events.map(function (e) { return e[1]; })) : since;
    var last = Math.max(now, Math.max.apply(null, events.map(function (e) { return e[1]; })));
    var start = weekStart(first), end = weekStart(last);
    var list = [];
    for (var w = start; w <= end; w += 7 * DAY_MS) list.push({ start: new Date(w).toISOString().slice(0, 10), kept: 0, sent: 0, replies: 0 });
    events.forEach(function (e) {
      var i = Math.round((weekStart(e[1]) - start) / (7 * DAY_MS));
      if (list[i]) list[i][e[0]] += 1;
    });
    var capped = list.length > MAX_WEEKS;
    return { list: capped ? list.slice(-MAX_WEEKS) : list, capped: capped };
  }

  root.JMStats = { compute: compute, PERIOD_DAYS: PERIOD_DAYS, weekStart: weekStart };
})(window);

/* The view. */
(function (JM) {
  "use strict";

  var el = JM.el, clear = JM.clear, byId = JM.byId, T = JM.T;
  var S = window.JMStats;
  var NS = "http://www.w3.org/2000/svg";
  var V = function () { return JM.v; };
  var SERIES = [
    { key: "kept", label: "Gardées" },
    { key: "sent", label: "Envoyées" },
    { key: "replies", label: "Réponses" }
  ];
  var REASON_TEXT = { none: "Sans raison donnée" };

  /* A rate between 0 and 1 % is « < 1 % », never « 0 % » (IMPECCABLE_AUDIT S3). */
  function pct(r) { return r === null ? "—" : r > 0 && r < 0.005 ? "< 1 %" : Math.round(r * 100) + " %"; }
  function plural(n, one, many) { return n + " " + (n > 1 ? many : one); }
  function fmtDay(iso) {
    var d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", timeZone: "UTC" });
  }
  function fmtDays(d) {
    if (d === null) return "—";
    var v = Math.round(d * 10) / 10;
    return String(v).replace(".", ",") + (v >= 2 ? " jours" : " jour");
  }

  function input() {
    var postings = [];
    var listed = {};
    JM.rows.forEach(function (r) { T.postingsOf(r).forEach(function (p) { listed[p.key] = true; }); });
    Object.keys(JM.postingByKey).forEach(function (k) {
      var p = JM.postingByKey[k];
      postings.push({ key: k, collected_at: p.collected_at || p.posted_at, source: p.source, company: p.company,
        closed: p.closed === true, listed: !!listed[k], why: p.why });
    });
    var track = JM.track;
    var replies = [];
    track.inbox.history.forEach(function (it) {
      if ((it.state === "applied" || it.state === "corrected") && it.applied_key) replies.push({ key: it.applied_key, received_at: it.received_at, kind: it.kind });
    });
    return { postings: postings, apps: track.apps, decisions: track.decisions, decisionAt: track.decisionAt,
      replies: replies, overrides: track.overrides, period: V().statsPeriod, now: JM.data.generated_at };
  }

  function card(title, id, children, cls) {
    return el("section", { class: "card stats-card" + (cls ? " " + cls : ""), "aria-labelledby": id },
      [el("h2", { class: "section-title", id: id, text: title })].concat(children));
  }

  function bar(fraction) {
    var fill = el("i");
    fill.style.width = Math.max(0, Math.min(1, fraction)) * 100 + "%";
    return el("span", { class: "stats-bar", "aria-hidden": "true" }, fill);
  }

  function funnel(st) {
    var top = st.funnel[0].n;
    var list = el("ol", { class: "stats-funnel", "aria-label": "Entonnoir" });
    st.funnel.forEach(function (s) {
      list.appendChild(el("li", { class: "funnel-row", "data-stage": s.key }, [
        el("span", { class: "funnel-label", text: s.label }),
        bar(top ? s.n / top : 0),
        el("span", { class: "funnel-n num", text: String(s.n) }),
        el("span", { class: "funnel-rate num", text: s.of ? pct(s.rate) + " " + s.of : "" })
      ]));
    });
    var notes = [];
    if (st.orphans) notes.push(plural(st.orphans, "candidature dont l’offre a quitté l’instantané est comptée", "candidatures dont l’offre a quitté l’instantané sont comptées") + " en plus.");
    notes.push("Entretiens et refus se rapportent aux envoyées ; une réponse est un entretien, un refus ou un message lié du recruteur (hors accusé de réception).");
    return card("Entonnoir", "h-stats-funnel", [list].concat(notes.map(function (t) { return el("p", { class: "stats-note", text: t }); })), "stats-wide");
  }

  function tile(label, value, sub, key) {
    return el("div", { class: "stats-tile", "data-tile": key }, [
      el("p", { class: "stats-tile-label", text: label }),
      el("p", { class: "stats-tile-value num", text: value }),
      el("p", { class: "stats-tile-sub", text: sub })
    ]);
  }

  function tiles(st) {
    var d = st.delays;
    return el("div", { class: "stats-tiles" }, [
      tile("Garder → envoyer", fmtDays(d.keepToSend.days), d.keepToSend.n ? "moyenne sur " + plural(d.keepToSend.n, "candidature", "candidatures") : "aucune paire de dates", "keep-send"),
      tile("Envoyer → 1re réponse", fmtDays(d.sendToReply.days), d.sendToReply.n ? "moyenne sur " + plural(d.sendToReply.n, "réponse", "réponses") : "aucune réponse datée", "send-reply"),
      tile("Expirées", String(st.expired), "à candidater, offre fermée", "expired"),
      tile("Archivées", String(st.archived), "suivies, plus dans la liste (fermées ou anciennes)", "archived")
    ]);
  }

  /* Grouped bars, one group per week; a hit area per week carries the tooltip. */
  var MIN_CHART = 5;
  function weekTable(weeks) {
    return el("table", { class: "stats-table" }, [
      el("thead", null, el("tr", null, [el("th", { scope: "col", text: "Semaine du" })].concat(SERIES.map(function (s) { return el("th", { scope: "col", class: "num", text: s.label }); })))),
      el("tbody", null, weeks.map(function (w) {
        return el("tr", null, [el("td", { text: fmtDay(w.start) })].concat(SERIES.map(function (s) { return el("td", { class: "num", text: String(w[s.key]) }); })));
      }))
    ]);
  }

  function weekChart(st, width) {
    var weeks = st.weeks.list;
    var body = [];
    var legend = el("div", { class: "legend stats-legend" }, SERIES.map(function (s) {
      return el("span", { class: "legend-item" }, [el("i", { class: "swatch sw-" + s.key, "aria-hidden": "true" }), s.label]);
    }));
    body.push(legend);
    var events = weeks.reduce(function (n, w) { return n + SERIES.reduce(function (m, s) { return m + w[s.key]; }, 0); }, 0);
    if (!weeks.length) {
      body.push(el("p", { class: "stats-empty", text: "Aucun événement daté sur la période." }));
    } else if (events < MIN_CHART) {
      /* A handful of events: a chart would draw each one as a full-height bar (IMPECCABLE_AUDIT
         S1); the table says the same numbers plainly, without the chart's colour legend. */
      body.length = 0;
      body.push(el("p", { class: "stats-note", text: plural(events, "événement daté", "événements datés") + " sur la période : le graphe apparaît à partir de " + MIN_CHART + "." }));
      body.push(el("div", { class: "table-scroll" }, weekTable(weeks)));
    } else {
      var max = 1;
      weeks.forEach(function (w) { SERIES.forEach(function (s) { max = Math.max(max, w[s.key]); }); });
      var step = max <= 5 ? 1 : max <= 10 ? 2 : Math.ceil(max / 5);
      /* at least 4 on the axis: one event is never drawn as a full bar */
      var top = Math.max(4, Math.ceil(max / step) * step);
      var W = Math.max(width || 640, weeks.length * 44 + 40), H = 180, padL = 28, padB = 24, padT = 8;
      var plotH = H - padB - padT, groupW = (W - padL) / weeks.length;
      var barW = Math.max(3, Math.min(14, (groupW - 8) / 3 - 2));
      var svg = document.createElementNS(NS, "svg");
      function a(node, attrs) { Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); }); return node; }
      a(svg, { viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "week-chart", role: "img", "aria-label": "Gardées, envoyées et réponses par semaine" });
      for (var v = 0; v <= top; v += step) {
        var y = padT + plotH - (v / top) * plotH;
        svg.appendChild(a(document.createElementNS(NS, "line"), { x1: padL, x2: W, y1: y, y2: y, class: v === 0 ? "axis" : "grid" }));
        var t = a(document.createElementNS(NS, "text"), { x: padL - 6, y: y + 3, class: "tick", "text-anchor": "end" });
        t.textContent = String(v);
        svg.appendChild(t);
      }
      var tip = el("div", { class: "chart-tip", role: "status", hidden: true });
      weeks.forEach(function (w, i) {
        var gx = padL + i * groupW;
        var g = a(document.createElementNS(NS, "g"), { class: "week", "data-week": w.start });
        var x0 = gx + (groupW - (barW * 3 + 4)) / 2;
        SERIES.forEach(function (s, j) {
          if (!w[s.key]) return;
          var h = (w[s.key] / top) * plotH;
          var x = x0 + j * (barW + 2), y0 = padT + plotH;
          var r = Math.min(4, barW / 2, h);
          /* rounded at the data end, square on the baseline */
          var d = "M" + x + "," + y0 + "V" + (y0 - h + r) + "Q" + x + "," + (y0 - h) + " " + (x + r) + "," + (y0 - h) +
            "H" + (x + barW - r) + "Q" + (x + barW) + "," + (y0 - h) + " " + (x + barW) + "," + (y0 - h + r) + "V" + y0 + "Z";
          g.appendChild(a(document.createElementNS(NS, "path"), { d: d, class: "bar bar-" + s.key, "data-series": s.key, "data-n": w[s.key] }));
        });
        if (weeks.length <= 14 || i % 2 === 0) {
          var lab = a(document.createElementNS(NS, "text"), { x: gx + groupW / 2, y: H - 8, class: "tick", "text-anchor": "middle" });
          lab.textContent = fmtDay(w.start);
          g.appendChild(lab);
        }
        var hit = a(document.createElementNS(NS, "rect"), { x: gx, y: 0, width: groupW, height: H - padB, class: "hit" });
        g.appendChild(hit);
        function show() {
          clear(tip);
          tip.appendChild(el("strong", { text: "Semaine du " + fmtDay(w.start) }));
          SERIES.forEach(function (s) { tip.appendChild(el("span", null, [el("i", { class: "swatch sw-" + s.key, "aria-hidden": "true" }), s.label + " : " + w[s.key]])); });
          tip.hidden = false;
          /* beside the week, never over its bars: right of it, or left near the edge */
          var right = gx + groupW + 8;
          tip.style.left = (right + 170 <= W ? right : Math.max(0, gx - 178)) + "px";
          g.classList.add("is-hover");
        }
        function hide() { tip.hidden = true; g.classList.remove("is-hover"); }
        g.addEventListener("pointerenter", show);
        g.addEventListener("pointerleave", hide);
        svg.appendChild(g);
      });
      var wrap = el("div", { class: "chart-wrap" }, [svg, tip]);
      body.push(wrap);
      /* the same numbers as a table: identity never by colour alone */
      body.push(el("details", { class: "stats-details" }, [el("summary", { text: "Voir les chiffres" }), el("div", { class: "table-scroll" }, weekTable(weeks))]));
    }
    var u = st.undated, notes = [];
    if (u.kept) notes.push(plural(u.kept, "gardée", "gardées") + " sans date de décision");
    if (u.sent) notes.push(plural(u.sent, "envoyée", "envoyées") + " sans date d’envoi");
    if (u.replies) notes.push(plural(u.replies, "réponse", "réponses") + " sans message daté");
    if (notes.length) body.push(el("p", { class: "stats-note", text: "Hors graphique : " + notes.join(", ") + "." }));
    if (st.weeks.capped) body.push(el("p", { class: "stats-note", text: "Les 26 dernières semaines." }));
    return card("Par semaine", "h-stats-weeks", body, "stats-wide");
  }

  function rankList(items, total, cls) {
    var list = el("ul", { class: "rank " + cls });
    items.forEach(function (it) {
      list.appendChild(el("li", { class: "rank-row" }, [
        el("span", { class: "rank-label", text: it.label }),
        bar(total ? it.n / total : 0),
        el("span", { class: "rank-n num", text: String(it.n) })
      ]));
    });
    return list;
  }

  function reasons(st) {
    var items = st.reasons.map(function (r) { return { label: REASON_TEXT[r.label] || T.LABEL_TEXT[r.label], n: r.n }; });
    var named = items.slice(0, 4).sort(function (a, b) { return b.n - a.n; });
    var body = [el("p", { class: "stats-note", text: plural(st.dropped, "offre écartée", "offres écartées") + " sur la période." })];
    if (st.dropped) body.push(rankList(named.concat([items[4]]), st.dropped, "rank-reasons"));
    return card("Raisons d’écart", "h-stats-reasons", body);
  }

  function skills(st) {
    var body = [];
    if (!st.skills.length) body.push(el("p", { class: "stats-empty", text: st.keptWithPosting ? "Aucune compétence de l’offre absente de ton profil." : "Aucune offre gardée sur la période." }));
    else {
      body.push(el("p", { class: "stats-note", text: "Dans l’offre, pas dans ton profil, sur " + plural(st.keptWithPosting, "offre gardée", "offres gardées") + "." }));
      body.push(rankList(st.skills.map(function (s) { return { label: s.name, n: s.n }; }), st.keptWithPosting, "rank-skills"));
    }
    return card("Compétences manquantes", "h-stats-skills", body);
  }

  function breakdown(title, id, rows, first, extra) {
    var body = [];
    if (!rows.length) body.push(el("p", { class: "stats-empty", text: "Aucune offre sur la période." }));
    else {
      body.push(el("div", { class: "table-scroll" }, el("table", { class: "stats-table", "data-table": id }, [
        el("thead", null, el("tr", null, [el("th", { scope: "col", text: first }), el("th", { scope: "col", class: "num", text: "Éligibles" }),
          el("th", { scope: "col", class: "num", text: "Gardées" }), el("th", { scope: "col", class: "num", text: "Envoyées" })])),
        el("tbody", null, rows.map(function (r) {
          return el("tr", null, [el("td", { class: "stats-name", text: r.name }), el("td", { class: "num", text: String(r.eligible) }),
            el("td", { class: "num", text: String(r.kept) }), el("td", { class: "num", text: String(r.sent) })]);
        }))
      ])));
    }
    if (extra) body.push(el("p", { class: "stats-note", text: extra }));
    return card(title, id, body);
  }

  function renderStats() {
    var host = byId("stats-body"), off = byId("stats-off");
    var period = V().statsPeriod;
    Array.prototype.forEach.call(document.querySelectorAll("#panel-statistiques [data-period]"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-period") === period));
    });
    clear(host);
    var status = JM.track.status;
    if (status !== "ready") {
      off.hidden = false;
      off.textContent = status === "loading" ? "Chargement du suivi…"
        : "Les statistiques viennent du suivi (statuts, décisions, réponses) : il demande le tableau de bord hébergé.";
      byId("stats-sub").textContent = "";
      return;
    }
    off.hidden = true;
    var st = S.compute(input());
    byId("stats-sub").textContent = st.since
      ? "Offres collectées depuis le " + fmtDay(st.since) + ", suivies jusqu’à aujourd’hui"
      : "Toutes les offres de l’instantané et toutes les candidatures";
    host.appendChild(funnel(st));
    host.appendChild(tiles(st));
    /* the chart is drawn at the card's inner width (its padding and border off) */
    host.appendChild(weekChart(st, host.clientWidth ? host.clientWidth - 40 : 0));
    host.appendChild(reasons(st));
    host.appendChild(skills(st));
    host.appendChild(breakdown("Par source", "h-stats-sources", st.sources, "Source"));
    host.appendChild(breakdown("Par entreprise", "h-stats-companies", st.companies, "Entreprise",
      st.companyCount > st.companies.length ? "Les 10 premières sur " + st.companyCount + "." : null));
  }

  Array.prototype.forEach.call(document.querySelectorAll("#panel-statistiques [data-period]"), function (b) {
    b.addEventListener("click", function () {
      JM.v.statsPeriod = b.getAttribute("data-period");
      renderStats();
      JM.syncHash();
    });
  });

  /* A new width redraws the chart at that width. */
  var resizeTimer = null, lastWidth = 0;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var w = byId("stats-body").clientWidth;
      if (JM.v.tab === "statistiques" && w && w !== lastWidth) { lastWidth = w; renderStats(); }
    }, 150);
  });

  JM.renderStats = renderStats;
})(window.JM);
