/* Leads: who raised, how much, in which round, whether they say they hire (with the sentence
   that says so), and the jump to that company's offers when the list has some. */
(function (JM) {
  "use strict";

  var el = JM.el, clear = JM.clear, byId = JM.byId, cell = JM.cell, link = JM.link, dateCell = JM.dateCell;
  var fmtAmount = JM.fmtAmount, leads = JM.leads, rows = JM.rows;
  var showTab = JM.showTab, state = function () { return JM.state; };

  /* The listed offers of this company, by its name as the page shows it. */
  function offersOf(l) {
    var name = String(l.company || "").toLowerCase();
    if (!name) return 0;
    return rows.filter(function (r) { return String(r.company || "").toLowerCase() === name; }).length;
  }

  /* Opens Offres filtered on the company (the search matches the company name). */
  function jumpTo(l, n) {
    var b = el("button", { type: "button", class: "link-btn lead-jump", text: n + (n > 1 ? " offres" : " offre"), "aria-label": n + " offre(s) de " + l.company + " dans Offres" });
    b.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var s = state();
      s.q = String(l.company).toLowerCase();
      byId("f-search").value = l.company;
      JM.renderJobs();
      showTab("offres", true, true);
    });
    return b;
  }

  function leadDetails(l) {
    var td = el("td", { colspan: "6" });
    var box = el("div", { class: "details" });
    var meta = [];
    if (l.reason) meta.push(l.reason);
    if (l.country) meta.push(l.country);
    if (l.source) meta.push("source : " + l.source);
    if (l.article_title) meta.push(l.article_title);
    box.appendChild(el("p", { class: "meta", text: meta.join(" · ") }));
    var grid = el("div", { class: "details-grid" });
    var left = el("div");
    left.appendChild(el("h3", { text: "Preuves, phrase par phrase" }));
    var keys = Object.keys(l.evidence || {});
    if (keys.length) {
      left.appendChild(el("dl", { class: "lead-evidence" }, keys.map(function (k) {
        return el("div", { class: "lead-ev" }, [el("dt", { text: k }), el("dd", null, el("q", { class: "why-ev", text: l.evidence[k] }))]);
      })));
    } else {
      left.appendChild(el("p", { class: "note", text: "Aucune phrase de preuve enregistrée." }));
    }
    grid.appendChild(left);
    var right = el("div");
    if (l.investors && l.investors.length) {
      right.appendChild(el("h3", { text: "Investisseurs" }));
      right.appendChild(el("div", { class: "tags" }, l.investors.map(function (t) { return el("span", { class: "tag", text: t }); })));
    }
    right.appendChild(el("h3", { text: "Offres de cette entreprise" }));
    var n = offersOf(l);
    right.appendChild(n ? el("p", { class: "note" }, [jumpTo(l, n), " affichées dans Offres"])
      : el("p", { class: "note", text: (l.open_jobs || 0) + " offre(s) éligible(s) récente(s) en base, aucune affichée." }));
    grid.appendChild(right);
    box.appendChild(grid);
    td.appendChild(box);
    return el("tr", { class: "details", id: "lead-details-" + l.id }, td);
  }

  function renderLeads() {
    var body = byId("leads-body");
    clear(body);
    byId("leads-rowcount").textContent = leads.length + " leads de financement · priorité haute d’abord";
    byId("leads-empty").hidden = leads.length > 0;
    var frag = document.createDocumentFragment();
    leads.forEach(function (l) {
      var row = el("tr", { class: "row", tabindex: "0", "aria-expanded": "false" });
      var btn = el("button", { type: "button", class: "expand", "aria-expanded": "false", "aria-controls": "lead-details-" + l.id },
        [el("span", { class: "dot " + (l.priority === "high" ? "dot-strong" : ""), "aria-hidden": "true", title: l.priority === "high" ? "Priorité haute" : null }), el("span", { class: "title-text", text: l.company || "—" })]);
      row.appendChild(cell("col-title", "Entreprise", btn));
      var raise = [fmtAmount(l.amount, l.currency), l.round].filter(Boolean).join(" · ");
      row.appendChild(cell("col-raise", "Levée", raise ? el("span", { class: "num", text: raise }) : el("span", { class: "unknown", text: "—" })));
      var hiring = el("span", { class: "lead-hiring" });
      if (l.hiring) {
        hiring.appendChild(el("span", { class: "tag tag-pos", text: l.hiring }));
        if (l.evidence && l.evidence.hiring) hiring.appendChild(el("q", { class: "why-ev lead-hiring-ev", text: l.evidence.hiring, title: l.evidence.hiring }));
      } else {
        hiring.appendChild(el("span", { class: "unknown", text: "non dit" }));
      }
      row.appendChild(cell("col-hiring", "Recrutement", hiring));
      var n = offersOf(l);
      row.appendChild(cell("col-open", "Offres", n ? jumpTo(l, n) : el("span", { class: "unknown", text: "—" })));
      row.appendChild(dateCell("col-date", "Publiée", l.published_at || l.created_at));
      row.appendChild(cell("link-col", "Article", link(l.article_url, "Lire")));
      var open = false;
      function toggle() {
        open = !open;
        row.setAttribute("aria-expanded", open ? "true" : "false");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        var existing = byId("lead-details-" + l.id);
        if (open && !existing) row.parentNode.insertBefore(leadDetails(l), row.nextSibling);
        if (!open && existing) existing.parentNode.removeChild(existing);
      }
      row.addEventListener("click", function (ev) { if (!ev.target.closest("a, .lead-jump")) toggle(); });
      row.addEventListener("keydown", function (ev) {
        if (ev.target !== row) return;
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); }
      });
      frag.appendChild(row);
    });
    body.appendChild(frag);
  }

  /* Shared with the other files. */
  JM.renderLeads = renderLeads;
})(window.JM);
