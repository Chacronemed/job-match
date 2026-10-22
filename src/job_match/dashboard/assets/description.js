/* An offer's description laid out for reading: the usual sections (Missions, Profil,
   Compétences, Avantages, Entreprise) when the text names them, lists from its bullet lines,
   paragraphs otherwise. The input is data.py's plain text (no markup, line breaks kept); the
   output is plain strings that `render` hands to the page's element builder, which sets them
   with textContent. Nothing here builds or parses HTML. Pure, so the Node tests cover it. */
(function (root) {
  "use strict";

  function fold(s) { return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

  /* Headings, matched on the folded line without its trailing colon. */
  var HEADING = new RegExp("^(?:" + [
    "(?:vos |les |tes )?missions?(?: principales)?", "(?:le |votre )?poste(?: propose)?", "description du poste", "descriptif du poste",
    "(?:vos |tes )?responsabilites", "(?:votre |le |ton )?profil(?: recherche| souhaite)?", "(?:les )?competences(?: requises| techniques| attendues| recherchees)?",
    "savoir[- ]faire", "savoir[- ]etre", "qualites(?: requises)?", "(?:les )?avantages(?: du poste)?", "(?:ce que )?nous (?:vous )?(?:offrons|proposons)",
    "pourquoi nous rejoindre", "pourquoi (?:rejoindre|choisir) .{1,30}", "l[’']entreprise", "(?:notre |la )?(?:entreprise|societe)",
    "qui sommes[- ]nous", "a propos(?: de nous| de l[’']entreprise)?", "conditions(?: de travail)?", "informations complementaires",
    "(?:le )?process(?:us)? de recrutement"
  ].join("|") + ")$");
  var BULLET = /^\s*(?:[-•·*–—✓▪►]|\d{1,2}[.)])\s+(.+)$/;
  var SALARY = /^(?:salaire|r[ée]mun[ée]ration)(?:\s+[^:]{0,24})?\s*[:\-–]\s*(.+)$/i;
  var INLINE_HEAD = /^([^:]{3,40}?)\s*:\s+(.+)$/;

  function headingOf(line) {
    var bare = line.replace(/\s*:\s*$/, "").trim();
    if (!bare || bare.length > 60 || BULLET.test(line)) return null;
    return HEADING.test(fold(bare)) ? bare : null;
  }

  /* {sections: [{title|null, blocks: [{p: text} | {list: [text]}]}], salary: text|null} */
  function parse(text) {
    var sections = [], cur = { title: null, blocks: [] }, para = [], list = null, salary = null;
    function flushPara() { if (para.length) { cur.blocks.push({ p: para.join("\n") }); para = []; } }
    function flushList() { if (list) { cur.blocks.push({ list: list }); list = null; } }
    function open(title) {
      flushPara(); flushList();
      if (cur.title !== null || cur.blocks.length) sections.push(cur);
      cur = { title: title, blocks: [] };
    }
    String(text || "").split("\n").forEach(function (raw) {
      var line = raw.trim();
      if (!line) { flushPara(); flushList(); return; }
      if (!salary) {
        var s = SALARY.exec(line);
        if (s && s[1].trim()) salary = s[1].trim().slice(0, 80);
      }
      var head = headingOf(line);
      if (head) { open(head); return; }
      var inline = INLINE_HEAD.exec(line);
      if (inline && headingOf(inline[1])) { open(inline[1].trim()); para.push(inline[2]); return; }
      var b = BULLET.exec(line);
      if (b) { flushPara(); (list = list || []).push(b[1].trim()); return; }
      flushList();
      para.push(line);
    });
    flushPara(); flushList();
    if (cur.title !== null || cur.blocks.length) sections.push(cur);
    return { sections: sections, salary: salary };
  }

  /* Elements only through `el(tag, {class, text}, children)`: section, h3, p, ul, li. */
  function render(parsed, el) {
    return parsed.sections.map(function (sec) {
      var kids = sec.title ? [el("h3", { class: "desc-title", text: sec.title })] : [];
      sec.blocks.forEach(function (b) {
        if (b.list) kids.push(el("ul", { class: "desc-list" }, b.list.map(function (t) { return el("li", { text: t }); })));
        else kids.push(el("p", { class: "desc-p", text: b.p }));
      });
      return el("section", { class: "desc-sec" }, kids);
    });
  }

  var api = { parse: parse, render: render };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JMDesc = api;
})(this);
