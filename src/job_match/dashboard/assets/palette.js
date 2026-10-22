/* Command palette (Ctrl/Cmd+K) and the « ? » shortcuts sheet, Raycast-style. Native <dialog>
   for focus trapping and inertness; open and close are animated in CSS, and close waits for its
   animation. The page supplies the commands; matching is word-based and accent-folded, like the
   Offres search (tracking.js). `match` is pure and Node-tested. */
(function (root) {
  "use strict";

  function fold(s) { return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

  /* Highlight ranges for every word of `q` in `text`, or null if one word is missing. */
  function match(q, text) {
    var words = fold(q).split(/\s+/).filter(Boolean), f = fold(text), ranges = [];
    for (var i = 0; i < words.length; i++) {
      var at = f.indexOf(words[i]);
      if (at < 0) return null;
      ranges.push([at, at + words[i].length]);
    }
    return ranges.sort(function (a, b) { return a[0] - b[0]; });
  }

  var api = { match: match };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }

  var U = root.JMUI, el = U.el;
  var dlg, input, list, items = [], active = 0, provider, help;

  function highlighted(text, ranges) {
    var out = el("span", { class: "cmd-label" });
    var at = 0;
    (ranges || []).forEach(function (r) {
      if (r[0] < at) return;
      out.appendChild(document.createTextNode(text.slice(at, r[0])));
      out.appendChild(el("mark", { text: text.slice(r[0], r[1]) }));
      at = r[1];
    });
    out.appendChild(document.createTextNode(text.slice(at)));
    return out;
  }

  function setActive(i, scroll) {
    if (!items.length) { input.removeAttribute("aria-activedescendant"); return; }
    active = (i + items.length) % items.length;
    items.forEach(function (it, k) { it.opt.setAttribute("aria-selected", k === active ? "true" : "false"); });
    input.setAttribute("aria-activedescendant", items[active].opt.id);
    if (scroll) items[active].opt.scrollIntoView({ block: "nearest" });
  }

  function render() {
    var q = input.value.trim();
    var groups = provider(q);
    items = [];
    U.clear(list);
    groups.forEach(function (g, gi) {
      var shown = [];
      g.items.forEach(function (c) {
        if (!q) { shown.push({ c: c, ranges: [] }); return; }
        /* `text` is what is searched (title, company, place); only the label is highlighted. */
        var hit = match(q, c.text || c.label);
        if (hit) shown.push({ c: c, ranges: c.text ? match(q, c.label) || [] : hit });
      });
      if (q && g.limit) shown = shown.slice(0, g.limit);
      if (!shown.length) return;
      var gid = "cmd-g" + gi;
      var box = el("div", { role: "group", "aria-labelledby": gid, class: "cmd-group" }, [el("div", { id: gid, class: "cmd-group-title", text: g.title })]);
      shown.forEach(function (s) {
        var idx = items.length, c = s.c;
        var lead = c.hue ? U.dot(c.hue) : el("span", { class: "cmd-icon" }, c.icon ? U.icon(c.icon) : null);
        var opt = el("div", { role: "option", id: "cmd-" + idx, class: "cmd", "aria-selected": "false" }, [
          lead, highlighted(c.label, s.ranges),
          c.hint ? el("span", { class: "cmd-hint", text: c.hint }) : el("span", { class: "cmd-fill" }),
          typeof c.score === "number" ? el("span", { class: "cmd-score num", text: String(c.score) }) : null,
          c.keys ? U.kbd.apply(null, c.keys) : null
        ]);
        opt.addEventListener("pointermove", function () { if (active !== idx) setActive(idx, false); });
        opt.addEventListener("click", function () { exec(idx); });
        items.push({ c: c, opt: opt });
        box.appendChild(opt);
      });
      list.appendChild(box);
    });
    if (!items.length) {
      list.appendChild(el("p", { class: "cmd-empty", text: "Aucun résultat pour « " + q + " ». Essaie un titre, une entreprise ou une ville." }));
    }
    setActive(0, true);
  }

  function exec(i) {
    var it = items[i];
    if (!it) return;
    close(dlg).then(function () { it.c.run(); });
  }

  function close(d) {
    if (!d || !d.open) return Promise.resolve();
    if (U.reduced()) { d.close(); return Promise.resolve(); }
    d.classList.add("closing");
    return new Promise(function (res) {
      var done = function () { d.classList.remove("closing"); if (d.open) d.close(); res(); };
      d.addEventListener("animationend", done, { once: true });
      setTimeout(done, 300);  /* the animation may not run (hidden tab) */
    });
  }

  function build() {
    input = el("input", { class: "cmd-input", type: "text", name: "q", role: "combobox", "aria-expanded": "true",
      "aria-controls": "cmd-list", "aria-autocomplete": "list", "aria-label": "Commande ou offre",
      placeholder: "Aller à une vue, chercher une offre, changer un statut…", autocomplete: "off", spellcheck: "false" });
    list = el("div", { id: "cmd-list", role: "listbox", class: "cmd-list", "aria-label": "Résultats" });
    dlg = el("dialog", { class: "palette", "aria-label": "Palette de commandes" }, [
      el("div", { class: "cmd-search" }, [el("span", { class: "cmd-search-icon" }, U.icon("search")), input, U.kbd("Échap")]),
      list,
      el("div", { class: "cmd-foot" }, [
        el("span", { class: "cmd-foot-ctx", translate: "no", text: "job-match" }),
        el("span", { class: "cmd-foot-act is-primary" }, ["Ouvrir ", U.kbd("↵")]),
        el("span", { class: "cmd-foot-sep", "aria-hidden": "true" }),
        el("span", { class: "cmd-foot-act" }, ["Naviguer ", U.kbd("↑", "↓")])
      ])
    ]);
    input.addEventListener("input", render);
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown" || (ev.ctrlKey && ev.key === "n")) { ev.preventDefault(); setActive(active + 1, true); }
      else if (ev.key === "ArrowUp" || (ev.ctrlKey && ev.key === "p")) { ev.preventDefault(); setActive(active - 1, true); }
      else if (ev.key === "Enter") { ev.preventDefault(); exec(active); }
    });
    dlg.addEventListener("cancel", function (ev) { ev.preventDefault(); close(dlg); });
    dlg.addEventListener("click", function (ev) { if (ev.target === dlg) close(dlg); });
    document.body.appendChild(dlg);
  }

  /* sections: [[title, [[keys, label], …]], …] */
  function buildHelp(sections) {
    var shut = el("button", { type: "button", class: "icon-btn", "aria-label": "Fermer l’aide" }, U.icon("x"));
    help = el("dialog", { class: "help", "aria-labelledby": "help-title" }, [
      el("div", { class: "help-head" }, [el("h2", { id: "help-title", text: "Raccourcis clavier" }), shut]),
      el("div", { class: "help-cols" }, sections.map(function (s) {
        return el("section", null, [
          el("h3", { text: s[0] }),
          el("dl", null, s[1].map(function (r) {
            return el("div", { class: "help-row" }, [el("dt", { text: r[1] }), el("dd", null, U.kbd.apply(null, r[0]))]);
          }))
        ]);
      }))
    ]);
    shut.addEventListener("click", function () { close(help); });
    help.addEventListener("cancel", function (ev) { ev.preventDefault(); close(help); });
    help.addEventListener("click", function (ev) { if (ev.target === help) close(help); });
    document.body.appendChild(help);
  }

  api.init = function (commands, helpSections) { provider = commands; build(); buildHelp(helpSections); };
  api.open = function (prefill) {
    if (dlg.open) { input.select(); return; }
    if (help.open) help.close();
    dlg.classList.remove("closing");
    input.value = prefill || "";
    dlg.showModal();
    render();
    input.focus();
  };
  api.toggle = function () { if (dlg.open) close(dlg); else api.open(); };
  api.isOpen = function () { return !!(dlg && dlg.open) || !!(help && help.open); };
  api.openHelp = function () { if (dlg.open) dlg.close(); if (!help.open) { help.classList.remove("closing"); help.showModal(); } };
  root.JMPalette = api;
})(this);
