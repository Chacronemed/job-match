/* Tri: the card stack (keep / drop / undo), its retry queue and its keys. The pure rules are in
   triage.js; this file is the DOM side. */
(function (JM) {
  "use strict";

  /* From the other files (app.js first; the screens after it): values are read once,
     functions through the namespace at call time, so the load order never matters. */
  var D = JM.D;
  var HTTP = JM.HTTP;
  var R = JM.rec;
  var S = JM.S;
  var T = JM.T;
  var U = JM.U;
  var X = JM.X;
  var ageText = function () { return JM.ageText.apply(null, arguments); };
  var aiOf = function () { return JM.aiOf.apply(null, arguments); };
  var api = JM.api;
  var byId = function () { return JM.byId.apply(null, arguments); };
  var clear = JM.clear;
  var closeRecord = function () { return JM.closeRecord.apply(null, arguments); };
  var el = JM.el;
  var failureText = function () { return JM.failureText.apply(null, arguments); };
  var fmtDate = function () { return JM.fmtDate.apply(null, arguments); };
  var openRecord = function () { return JM.openRecord.apply(null, arguments); };
  var record = JM.record;
  var refreshBadges = function () { return JM.refreshBadges.apply(null, arguments); };
  var rows = JM.rows;
  var runAt = JM.runAt;
  var showTab = function () { return JM.showTab.apply(null, arguments); };
  var thresholds = JM.thresholds;
  var track = JM.track;
  var updateCounts = function () { return JM.updateCounts.apply(null, arguments); };
  var wideScreen = function () { return JM.wideScreen.apply(null, arguments); };
  var yearsText = function () { return JM.yearsText.apply(null, arguments); };
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
    tri.items = X.triageQueue(rows, track.apps, runAt, thresholds.min_score, track.ai);
    tri.pos = 0;
    tri.built = true;
    tri.pausedAt = -1;
  }

  function canTriage() { return track.status === "ready" && !!api; }

  function focusTriCard() {
    var card = byId("tri-stage").querySelector(".tcard:not(.is-next)");
    if (card) card.focus({ preventScroll: true });
  }

  /* The ledger animates only when a card arrives (first view, or the one after a decision),
     not when the same card is drawn again. */
  var triArrive = true;

  /* One card (Focus): the score and its band first, the title (it opens the record), the
     company and place, the facts as chips, the ledger, one sentence of the offer behind the
     best skill, then the whole description laid out by description.js; the card's own content
     scrolls, the buttons stay. Everything from the data goes through textContent. */
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

    /* The score, big, in its band's hue; the band, the AI's score and the flags as badges. */
    var bd = S.band(j);
    var known = typeof j.score === "number";
    var badges = [el("span", { class: "band band-" + bd.key }, [el("span", { class: "dot", "aria-hidden": "true" }), known ? bd.label : "Score inconnu"])];
    var verdict = aiOf(j);
    if (verdict) {
      var aiBand = S.aiBand(verdict.level);
      badges.push(el("span", { class: "badge badge-ai" + (aiBand ? " ai-" + aiBand.key : ""), title: aiBand ? "Selon l’IA : " + aiBand.label : "Selon l’IA", text: "IA " + verdict.score }));
    }
    if (item.isNew) badges.push(el("span", { class: "badge badge-new", text: "Nouveau" }));
    if (j.postings) badges.push(el("span", { class: "badge", text: j.departments.length + " départements" }));
    body.appendChild(el("div", { class: "tcard-top" }, [
      el("span", { class: "score-big band-" + (known ? bd.key : "low"), "aria-label": known ? "Score " + j.score + " sur 100" : "Score inconnu" }, [
        el("span", { class: "num", text: known ? String(j.score) : "—" }), known ? el("small", { text: "/ 100" }) : null]),
      el("span", { class: "tcard-badges" }, badges)
    ]));

    /* The title opens the record; the company and the place under it; then the facts as
       chips, in a fixed order. Salary only when the text states it on its own line
       (description.js), word for word. Unknown facts say so. */
    var open = el("button", { type: "button", class: "tcard-open", title: "Ouvrir la fiche", text: j.title || "—", tabindex: isNext ? "-1" : null });
    open.addEventListener("click", function () { openRecord(j, open); });
    body.appendChild(el("div", null, [
      el("h2", { class: "tcard-title" }, open),
      el("p", { class: "tcard-sub", text: [j.company || "Entreprise non communiquée", j.location || (j.department ? "Département " + j.department : "Lieu non précisé")].join(" · ") })
    ]));
    function fact(label, value) {
      return el("div", { class: "fact" }, [el("dt", { text: label }), el("dd", null, value)]);
    }
    var facts = [
      fact("Contrat", j.contract && j.contract !== "UNKNOWN" ? j.contract : "Contrat inconnu"),
      fact("Expérience demandée", yearsText(j.required_years))
    ];
    if (desc.salary) facts.push(fact("Salaire", desc.salary));
    var posted = fact("Publiée", ageText(j.age_days));
    if (j.posted_at) posted.title = fmtDate(j.posted_at);
    facts.push(posted);
    body.appendChild(el("dl", { class: "tcard-facts" }, facts));

    body.appendChild(U.ledger(j, thresholds, {
      collapsible: true, animate: !isNext && triArrive, ai: verdict,
      missing: j.missing || [], unlisted: (w.unlisted || []).map(function (u) { return u.name; })
    }));

    /* One sentence of the offer, the one behind its strongest matched skill, word for word. */
    var quoted = (w.skills || []).filter(function (s) { return s && s.snippet; })
      .sort(function (a, b) { return (typeof b.weight === "number" ? b.weight : 0) - (typeof a.weight === "number" ? a.weight : 0); })[0];
    if (quoted) body.appendChild(el("blockquote", { class: "tcard-quote", "aria-label": "Extrait de l’annonce (" + quoted.name + ")", text: quoted.snippet }));

    if (desc.sections.length) {
      body.appendChild(el("div", { class: "tcard-desc", "aria-label": "Description de l’offre", role: "group" }, [el("p", { class: "tcard-desc-title", text: "L’annonce" })].concat(D.render(desc, el))));
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
    if (R.open && R.tab === "tri") closeRecord(false);
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
    var pr = X.triProgress(tri.pos, total, tri.pausedAt);
    var atBoundary = pr.atBoundary;
    var done = pr.done;
    byId("tri-progress-bar").hidden = total === 0;
    /* « Offre N sur T » over the whole queue, then what is left after this one and the batch;
       the bar fills with the batch (AUDIT P2-8). */
    var after = Math.max(0, pr.left - 1);
    byId("tri-count").textContent = total && !done ? "Offre " + Math.min(tri.pos + 1, total) + " sur " + total : "";
    byId("tri-left").textContent = total && !done
      ? after + (after > 1 ? " restantes" : " restante") + " après celle-ci · lot " + pr.batch + " de " + pr.batches : "";
    if (total) {
      byId("tri-progress-fill").style.transform = "scaleX(" + (pr.decided / Math.max(pr.size, 1)) + ")";
      var bar = byId("tri-progress-bar");
      bar.setAttribute("aria-valuenow", String(pr.decided));
      bar.setAttribute("aria-valuemax", String(pr.size));
      bar.setAttribute("aria-valuetext", pr.decided + " sur " + pr.size + " dans ce lot");
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
        end.appendChild(el("h2", { text: "Lot " + pr.batch + " terminé" }));
        end.appendChild(el("p", { text: session + " pendant cette session. " + (total - tri.pos) + " offres attendent encore." }));
        var next = el("button", { type: "button", class: "button primary", text: "Lot suivant" });
        next.addEventListener("click", function () { tri.pausedAt = tri.pos; triArrive = true; renderTri(); focusTriCard(); });
        end.appendChild(el("div", { class: "tri-end-actions" }, [next, toApps]));
        announce("Lot " + pr.batch + " de " + pr.batches + " terminé.");
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
    if (record.contains(document.activeElement) || (R.open && !wideScreen())) return false;
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

  /* Shared with the other files. */
  JM.canTriage = canTriage;
  JM.flushRetry = flushRetry;
  JM.focusTriCard = focusTriCard;
  JM.overlayPending = overlayPending;
  JM.renderPending = renderPending;
  JM.renderTri = renderTri;
  JM.retry = retry;
  JM.tri = tri;
  JM.triKeys = triKeys;
  JM.undo = undo;
  JM.undoLast = undoLast;
})(window.JM);
