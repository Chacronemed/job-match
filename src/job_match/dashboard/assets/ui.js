/* Shared UI pieces (DESIGN.md "Components" and "Motion"). Every string reaches the DOM through
   textContent or setAttribute on an element built here; nothing is parsed as HTML.
   Motion: 120–200 ms ease-out on state changes only, hover and focus instant, everything off
   under prefers-reduced-motion. */
(function (root) {
  "use strict";
  var I = root.JMIcons;
  var S = root.JMScore;
  var EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

  function reduced() {
    return !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  /* el("button", {class, text, icon, "aria-label": …}, [children]): `icon` prepends a Lucide
     icon; children are nodes or strings (text nodes). */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "text") node.textContent = String(v);
        else if (k === "class") node.className = v;
        else if (k === "icon") return;
        else node.setAttribute(k, v === true ? "" : String(v));
      });
      if (attrs.icon) node.insertBefore(I.icon(attrs.icon), node.firstChild);
    }
    if (children !== undefined && children !== null) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (c === null || c === undefined || c === false || c === "") return;
        node.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
      });
    }
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  /* Keyboard hints: decorative (aria-hidden), the control's own label says the action. Arrows
     and Enter are icons: those glyphs are not in the Inter subset. */
  var KEY_ICONS = { "↵": "corner-down-left", "←": "arrow-left", "→": "arrow-right" };
  function kbd() {
    var keys = Array.prototype.slice.call(arguments);
    return el("span", { class: "kbd-group", "aria-hidden": "true" }, keys.map(function (k) {
      return KEY_ICONS[k] ? el("kbd", { class: "kbd-i", icon: KEY_ICONS[k] }) : el("kbd", { text: k });
    }));
  }

  function dot(hue, cls) {
    var d = el("span", { class: "dot" + (cls ? " " + cls : ""), "aria-hidden": "true" });
    if (hue) d.style.setProperty("--hue", hue);
    return d;
  }

  /* A view change or a layout change through the View Transitions API; a plain update when the
     API is missing or motion is reduced. `types` lets the CSS style one kind of transition. */
  function transition(update, types) {
    if (!document.startViewTransition || reduced()) { update(); return Promise.resolve(); }
    var vt;
    try { vt = document.startViewTransition({ update: update, types: types || [] }); }
    catch (e) { vt = document.startViewTransition(update); }  /* browsers without `types` */
    return vt.finished.catch(function () {});
  }

  /* FLIP: nodes carrying data-flip slide from where they were to where `mutate` put them, so a
     list updated in place never jumps. */
  function flip(container, mutate) {
    var before = {};
    container.querySelectorAll("[data-flip]").forEach(function (n) { before[n.getAttribute("data-flip")] = n.getBoundingClientRect(); });
    mutate();
    if (reduced()) return;
    container.querySelectorAll("[data-flip]").forEach(function (n) {
      var a = before[n.getAttribute("data-flip")], b = n.getBoundingClientRect();
      if (!a) { n.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: "ease-out" }); return; }
      var dx = a.left - b.left, dy = a.top - b.top;
      if (!dx && !dy) return;
      n.animate([{ transform: "translate(" + dx + "px, " + dy + "px)" }, { transform: "none" }], { duration: 200, easing: EASE });
    });
  }

  /* ---------- the Tri card's physics ---------- */

  function tilt(dx) { return Math.max(-14, Math.min(14, dx / 16)); }

  /* The card follows the pointer; released past 110 px, or flicked (velocity over the last
     90 ms), it is decided; otherwise it springs back. opts.onMove(dx) paints the stamps,
     opts.onDecide(dir, release) takes over the flight. */
  function draggable(card, opts) {
    var s = null;
    card.addEventListener("pointerdown", function (ev) {
      if (ev.button !== 0 || ev.target.closest("a, button, input, select, textarea") || (opts.canStart && !opts.canStart())) return;
      s = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, dx: 0, dy: 0, samples: [[ev.timeStamp, ev.clientX]] };
      card.setPointerCapture(ev.pointerId);
      card.classList.add("is-dragging");
    });
    card.addEventListener("pointermove", function (ev) {
      if (!s || ev.pointerId !== s.id) return;
      s.dx = ev.clientX - s.x;
      s.dy = ev.clientY - s.y;
      s.samples.push([ev.timeStamp, ev.clientX]);
      while (s.samples.length > 2 && ev.timeStamp - s.samples[0][0] > 90) s.samples.shift();
      card.style.transform = "translate(" + s.dx + "px, " + (s.dy * 0.25) + "px) rotate(" + tilt(s.dx) + "deg)";
      if (opts.onMove) opts.onMove(s.dx);
    });
    function end(ev) {
      if (!s || ev.pointerId !== s.id) return;
      var st = s;
      s = null;
      card.classList.remove("is-dragging");
      var a = st.samples[0], b = st.samples[st.samples.length - 1];
      var v = b[0] > a[0] ? (b[1] - a[1]) / (b[0] - a[0]) : 0;  /* px/ms */
      var fling = Math.abs(v) > 0.45 && (v > 0) === (st.dx > 0) && Math.abs(st.dx) > 24;
      if (ev.type !== "pointercancel" && (Math.abs(st.dx) > 110 || fling)) {
        opts.onDecide(st.dx > 0 ? 1 : -1, { dx: st.dx, dy: st.dy * 0.25, v: v });
        return;
      }
      var from = card.style.transform;
      card.style.transform = "";
      if (opts.onMove) opts.onMove(0);
      if (from && !reduced()) card.animate([{ transform: from }, { transform: "none" }], { duration: 200, easing: EASE });
    }
    card.addEventListener("pointerup", end);
    card.addEventListener("pointercancel", end);
  }

  /* The card leaves at the release speed (inertia); a keyboard or button decision uses a
     default speed. Returns the Animation, or null when motion is reduced. */
  function flyOut(card, dir, release) {
    if (reduced()) return null;
    var r = release || { dx: 0, dy: 0, v: 0 };
    var toX = dir * (root.innerWidth + 160);
    var speed = Math.max(Math.abs(r.v), 1.1);
    var dur = Math.max(140, Math.min(300, Math.abs(toX - r.dx) / speed));
    card.style.transform = "";
    return card.animate([
      { transform: "translate(" + r.dx + "px, " + r.dy + "px) rotate(" + tilt(r.dx) + "deg)" },
      { transform: "translate(" + toX + "px, " + (r.dy + 40) + "px) rotate(" + (dir * 22) + "deg)" }
    ], { duration: dur, easing: "cubic-bezier(0.3, 0.6, 0.5, 1)", fill: "forwards" });
  }

  /* Undo: the card comes back from the side it left by. */
  function flyIn(card, dir) {
    if (reduced() || !card) return;
    card.animate([
      { transform: "translate(" + (dir * (root.innerWidth + 160)) + "px, 40px) rotate(" + (dir * 22) + "deg)" },
      { transform: "none" }
    ], { duration: 240, easing: EASE });
  }

  /* The card underneath rises into place. */
  function rise(card) {
    if (reduced() || !card) return;
    card.animate([{ transform: "translateY(10px) scale(0.95)", opacity: 0.6 }, { transform: "none", opacity: 1 }], { duration: 200, easing: EASE });
  }

  /* ---------- « Relevé du score » ---------- */

  /* Whether collapsible ledgers start open: one choice for every card, kept across visits.
     Storage can be missing or full (private window): the choice then lasts for the page. */
  var LEDGER_KEY = "jm.ledger.open.v1";
  var ledgerOpen = null;
  function readLedgerOpen() {
    if (ledgerOpen === null) {
      try { ledgerOpen = root.localStorage.getItem(LEDGER_KEY) === "1"; } catch (e) { ledgerOpen = false; }
    }
    return ledgerOpen;
  }
  function writeLedgerOpen(on) {
    ledgerOpen = on;
    try { root.localStorage.setItem(LEDGER_KEY, on ? "1" : "0"); } catch (e) { /* kept in memory */ }
  }
  var ledgerSeq = 0;

  function skillCount(n) { return n + (n > 1 ? " compétences" : " compétence"); }

  /* The counters under the lines (opts.missing: preferred skills the offer does not cite, no
     effect on the score; opts.unlisted: skills the offer cites that the profile lacks). */
  function ledgerExtras(opts) {
    var out = [];
    var missing = opts.missing || [];
    if (missing.length) {
      var id = "ledger-miss-" + (++ledgerSeq);
      var list = el("p", { class: "ledger-pills", id: id, hidden: true }, missing.map(function (m) { return el("span", { class: "pill", text: m }); }));
      var btn = el("button", { type: "button", class: "ledger-count", "aria-expanded": "false", "aria-controls": id }, [
        chevron(), skillCount(missing.length) + " de ton profil " + (missing.length > 1 ? "absentes" : "absente") + " de l’offre"
      ]);
      btn.appendChild(el("span", { class: "ledger-count-note", text: "sans effet sur le score" }));
      btn.addEventListener("click", function () {
        var show = list.hidden;
        list.hidden = !show;
        btn.setAttribute("aria-expanded", show ? "true" : "false");
      });
      out.push(el("div", { class: "ledger-extra" }, [btn, list]));
    }
    var unlisted = opts.unlisted || [];
    if (unlisted.length) {
      out.push(el("p", { class: "ledger-unlisted" }, ["Dans l’offre, pas dans ton profil :"].concat(
        unlisted.map(function (u) { return el("span", { class: "pill", text: u }); }))));
    }
    return out;
  }
  function chevron() { return el("span", { class: "chev", "aria-hidden": "true" }, I.icon("chevron-right")); }

  /* « Selon l’IA » (ADR 0016): the model's score and level, its reasons, its red flags. Shown
     as the model said it, labelled as its opinion; it never changes the Python ledger above. */
  function aiBlock(v) {
    var band = S.aiBand(v.level);
    var head = el("div", { class: "ledger-ai-head" }, [
      el("h4", { class: "ledger-ai-title", text: "Selon l’IA" }),
      el("span", { class: "ledger-ai-score num", text: String(v.score) }),
      band ? el("span", { class: "band band-ai-" + band.key }, [el("span", { class: "dot", "aria-hidden": "true" }), band.label]) : null
    ]);
    var box = el("section", { class: "ledger-ai", "aria-label": "Avis de l’IA" }, [head]);
    var reasons = (v.reasons || []).filter(function (r) { return typeof r === "string"; });
    if (reasons.length) box.appendChild(el("ul", { class: "ledger-ai-reasons" }, reasons.map(function (r) { return el("li", { text: r }); })));
    var flags = (v.red_flags || []).filter(function (r) { return typeof r === "string"; });
    if (flags.length) box.appendChild(el("p", { class: "ledger-ai-flags" }, flags.map(function (f) { return el("span", { class: "pill pill-warn", text: f }); })));
    return box;
  }

  function countUp(node, from, to, dur) {
    var t0 = 0;
    node.textContent = String(from);
    var step = function (now) {
      if (!t0) t0 = now;
      var p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      node.textContent = String(Math.round(from + (to - from) * e));
      if (p < 1) root.requestAnimationFrame(step);
    };
    root.requestAnimationFrame(step);
  }

  /* opts.animate: the lines come in one after the other and the total counts up from the
     start, the one orchestrated moment of the page (closed: the summary's score counts up).
     opts.collapsible: one summary line (score, band, gap), closed by default, the choice kept. */
  function ledger(job, thresholds, opts) {
    opts = opts || {};
    var b = S.breakdown(job), bd = S.band(job);
    var t = thresholds || {};
    var rootEl = el("section", { class: "ledger" + (opts.compact ? " compact" : "") + (opts.collapsible ? " is-collapsible" : ""), "aria-label": "Relevé du score" });
    var bandEl = el("span", { class: "band band-" + bd.key }, [el("span", { class: "dot", "aria-hidden": "true" }), bd.label]);
    if (opts.collapsible) {
      var bodyId = "ledger-body-" + (++ledgerSeq);
      var sumN = el("span", { class: "ledger-sum-n num", text: b ? String(b.total) : "—" });
      var sum = el("button", { type: "button", class: "ledger-sum", "aria-controls": bodyId }, [
        el("span", { class: "sr-only", text: "Relevé du score : " }),
        sumN, bandEl, el("span", { class: "ledger-sum-gap", text: S.gapSentence(job, t) }), chevron()
      ]);
      var body = el("div", { class: "ledger-body", id: bodyId });
      var setOpen = function (on, animate) {
        rootEl.classList.toggle("is-open", on);
        sum.setAttribute("aria-expanded", on ? "true" : "false");
        body.hidden = !on;
        if (on && animate && !reduced()) body.animate([{ opacity: 0, transform: "translateY(-4px)" }, { opacity: 1, transform: "none" }], { duration: 160, easing: EASE });
      };
      sum.addEventListener("click", function () { var on = body.hidden; writeLedgerOpen(on); setOpen(on, true); });
      rootEl.appendChild(sum);
      rootEl.appendChild(body);
      var inner = ledgerBody(job, b, bd, t, opts, null);
      inner.forEach(function (n) { body.appendChild(n); });
      var open = readLedgerOpen();
      setOpen(open, false);
      if (opts.animate && !reduced() && b && b.start !== null) {
        if (open) { rootEl.classList.add("enter"); countUp(rootEl.querySelector(".ledger-total-n"), b.start, b.total, 120 + (b.lines.length + 1) * 45); }
        else countUp(sumN, b.start, b.total, 360);
      }
      return rootEl;
    }
    rootEl.appendChild(el("div", { class: "ledger-head" }, [el("h3", { class: "ledger-title", text: "Relevé du score" }), bandEl]));
    ledgerBody(job, b, bd, t, opts, rootEl);
    if (opts.animate && !reduced() && b && b.start !== null) {
      rootEl.classList.add("enter");
      countUp(rootEl.querySelector(".ledger-total-n"), b.start, b.total, 120 + (b.lines.length + 1) * 45);
    }
    return rootEl;
  }

  /* The lines, the total, the scale, the gap sentence and the counters; appended to `into`
     when given, returned as nodes otherwise. */
  function ledgerBody(job, b, bd, t, opts, into) {
    var nodes = [];
    var push = function (n) { if (into) into.appendChild(n); else nodes.push(n); };
    if (!b) {
      push(el("p", { class: "ledger-gap", text: "Score inconnu pour cette offre." }));
      ledgerExtras(opts).forEach(push);
      if (opts.ai) push(aiBlock(opts.ai));
      return nodes;
    }
    var list = el("dl", { class: "ledger-lines" });
    var rows = [];
    if (b.start !== null) rows.push(["start", "Point de départ", String(b.start)]);
    b.lines.forEach(function (l) { rows.push([l.kind, l.label, S.signed(l.value)]); });
    rows.forEach(function (r, i) {
      var line = el("div", { class: "ledger-line " + r[0] }, [el("dt", { text: r[1] }), el("dd", { class: "num", text: r[2] })]);
      line.style.setProperty("--i", String(i));
      list.appendChild(line);
    });
    if (!rows.length) list.appendChild(el("div", { class: "ledger-line start" }, [el("dt", { text: "Aucun facteur enregistré" }), el("dd", { text: "" })]));
    push(list);
    var total = el("span", { class: "ledger-total-n num", text: String(b.total) });
    push(el("div", { class: "ledger-total" }, [el("span", { text: b.capped ? "Total (plafonné)" : "Total" }), total]));

    if (typeof t.strong === "number" && typeof t.min_score === "number") {
      var scale = el("div", { class: "scale", role: "img",
        "aria-label": b.total + " sur 100. Digest dès " + t.min_score + ", forte dès " + t.strong + "." });
      var fill = el("span", { class: "scale-fill band-" + bd.key });
      fill.style.setProperty("--to", String(Math.max(0, Math.min(100, b.total)) / 100));
      scale.appendChild(el("span", { class: "scale-track" }, [fill]));
      [[t.min_score, "digest"], [t.strong, "forte"]].forEach(function (p) {
        var tick = el("span", { class: "scale-tick" }, [el("span", { class: "num", text: p[1] + " " + p[0] })]);
        tick.style.left = p[0] + "%";
        scale.appendChild(tick);
      });
      push(scale);
    }
    /* Collapsible: the summary line already says the gap. */
    if (!opts.collapsible) push(el("p", { class: "ledger-gap", text: S.gapSentence(job, t) }));
    ledgerExtras(opts).forEach(push);
    if (opts.ai) push(aiBlock(opts.ai));
    return nodes;
  }

  /* Placeholder rows while the tracking loads. */
  function skeletonRows(n) {
    var wrap = el("div", { class: "skeleton", "aria-hidden": "true" });
    for (var i = 0; i < n; i++) {
      var w = el("span", { class: "sk sk-text" });
      w.style.width = (30 + ((i * 17) % 34)) + "%";
      wrap.appendChild(el("div", { class: "sk-row" }, [el("span", { class: "sk sk-dot" }), w, el("span", { class: "sk sk-meta" })]));
    }
    return wrap;
  }

  var api = {
    el: el, clear: clear, kbd: kbd, dot: dot, icon: I.icon, reduced: reduced, transition: transition, flip: flip,
    draggable: draggable, flyOut: flyOut, flyIn: flyIn, rise: rise, ledger: ledger, skeletonRows: skeletonRows
  };
  root.JMUI = api;
})(this);
