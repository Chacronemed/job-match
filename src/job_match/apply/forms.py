"""Fill a Greenhouse, Lever or Ashby application form in a Playwright page, never send it.

The one rule (ADR 0023): nothing here clicks. Fields are written with `fill`,
`select_option` and `set_input_files`; a radio answer uses `check` on that radio only, after
checking it is one. No button, link or checkbox is ever pressed, no form is submitted, no
account is created, no password field is touched, no CAPTCHA is solved. What is not filled
is outlined on the page and listed in the report. The report names fields by their label
and says where a value came from, never the value: it is printed to my terminal, and no
personal data goes to a log.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from job_match.apply.config import ApplyConfig
from job_match.apply.questions import Field, Questions, fold

log = logging.getLogger(__name__)

ATS_HOSTS = {"greenhouse": ("greenhouse.io",), "lever": ("lever.co",), "ashby": ("ashbyhq.com",)}
TODO_COLOR = "#d97706"  # amber: left for me
SENSITIVE_COLOR = "#dc2626"  # red: never filled (sensitive, consent, salary in manuel)
FILLED_COLOR = "#16a34a"


def detect_ats(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    for ats, suffixes in ATS_HOSTS.items():
        if any(host == s or host.endswith("." + s) for s in suffixes):
            return ats
    return None


def application_url(url: str, ats: str) -> str:
    """The page that holds the form: Lever's `/apply`, Ashby's `/application`; Greenhouse
    shows it on the job page itself."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if ats == "lever" and not path.endswith("/apply"):
        path += "/apply"
    elif ats == "ashby" and not path.endswith("/application"):
        path += "/application"
    return parts._replace(path=path, query=parts.query, fragment="").geturl()


# Marks every control of the form with data-jm-field and returns its description. Radios are
# grouped by name into one field. Hidden controls are skipped, except file inputs (ATS forms
# hide them behind an "Attach" button; set_input_files writes them directly).
_SCAN = r"""
() => {
  const forms = Array.from(document.querySelectorAll("form"));
  const anchors = "input[type=file], input[type=email]";
  const scored = forms.map((f) => [f, f.querySelectorAll(anchors).length]);
  scored.sort((a, b) => b[1] - a[1]);
  const root = scored.length && scored[0][1] ? scored[0][0] : document.body;
  const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const labelOf = (el) => {
    if (el.getAttribute("aria-label")) return el.getAttribute("aria-label");
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const t = by.split(/\s+/).map((id) => text(document.getElementById(id))).join(" ").trim();
      if (t) return t;
    }
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) return text(l);
    }
    const wrap = el.closest("label");
    if (wrap) return text(wrap);
    const box = el.closest("fieldset, .field, .application-question, "
      + ".ashby-application-form-field-entry, li, div");
    if (box) {
      const l = box.querySelector("legend, label, .application-label, .text");
      if (l) return text(l);
    }
    return el.getAttribute("placeholder") || el.name || "";
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const out = [];
  const radios = new Map();
  let n = 0;
  for (const el of root.querySelectorAll("input, textarea, select")) {
    const type = el.tagName === "INPUT" ? (el.getAttribute("type") || "text").toLowerCase() : "";
    if (["hidden", "submit", "button", "reset", "image"].includes(type)) continue;
    if (type !== "file" && !visible(el)) continue;
    if (type === "radio") {
      const key = el.name || ("radio" + n);
      if (!radios.has(key)) {
        const ref = String(n++);
        const group = el.closest("fieldset, [role=radiogroup], .application-question, div");
        const legend = group
          ? group.querySelector("legend, .application-label, label:not(:has(input))") : null;
        radios.set(key, { ref, tag: "radio", type: "radio", label: legend ? text(legend) : key,
          name: el.name || "", id: "", placeholder: "", autocomplete: "", required: el.required,
          options: [] });
        out.push(radios.get(key));
      }
      const f = radios.get(key);
      el.setAttribute("data-jm-field", f.ref);
      el.setAttribute("data-jm-option", String(f.options.length));
      const l = el.id
        ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : el.closest("label");
      f.options.push(text(l) || el.value || "");
      continue;
    }
    const ref = String(n++);
    el.setAttribute("data-jm-field", ref);
    out.push({
      ref, tag: el.tagName.toLowerCase(), type, label: labelOf(el), name: el.name || "",
      id: el.id || "", placeholder: el.getAttribute("placeholder") || "",
      autocomplete: el.getAttribute("autocomplete") || "",
      required: !!el.required || el.getAttribute("aria-required") === "true",
      options: el.tagName === "SELECT" ? Array.from(el.options).map((o) => text(o)) : [],
    });
  }
  return out;
}
"""

_MARK = r"""
([ref, color, note]) => {
  for (const el of document.querySelectorAll('[data-jm-field="' + ref + '"]')) {
    el.style.outline = "3px solid " + color;
    el.style.outlineOffset = "2px";
    el.setAttribute("data-jm-state", color);
    if (note) el.setAttribute("title", note);
  }
}
"""

# A visible challenge (an invisible reCAPTCHA badge is not one) or a sign-in page.
_BLOCKER = r"""
() => {
  const big = (el) => {
    const r = el.getBoundingClientRect();
    return r.width >= 150 && r.height >= 60;
  };
  const challenge = /recaptcha|hcaptcha|turnstile|challenges\.cloudflare|arkoselabs|funcaptcha/i;
  for (const f of document.querySelectorAll("iframe")) {
    const src = f.getAttribute("src") || "";
    if (/size=invisible/.test(src)) continue;
    if (challenge.test(src) && big(f)) return "captcha";
  }
  for (const el of document.querySelectorAll(".g-recaptcha, .h-captcha, .cf-turnstile")) {
    if (el.getAttribute("data-size") !== "invisible" && big(el)) return "captcha";
  }
  for (const p of document.querySelectorAll("input[type=password]")) {
    const r = p.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return "login";
  }
  return null;
}
"""


@dataclass
class Report:
    ats: str | None
    filled: list[tuple[str, str]] = field(default_factory=list)  # (label, source)
    left: list[tuple[str, str]] = field(default_factory=list)  # (label, reason)
    notes: list[str] = field(default_factory=list)  # e.g. the salary benchmark

    def lines(self) -> list[str]:
        out = [f"Formulaire {self.ats} : {len(self.filled)} champs remplis, "
               f"{len(self.left)} laissés pour toi (surlignés)."]
        out += [f"  ✓ {label} ← {source}" for label, source in self.filled]
        out += [f"  ✗ {label} : {reason}" for label, reason in self.left]
        out += [f"  ! {n}" for n in self.notes]
        return out


@dataclass(frozen=True)
class Inputs:
    """Everything a fill may use. `contact`: contact.yaml as a dict. `kit`: kit.json items
    (kit.js answerKit). `files`: {"resume": path, "cover_letter": path}. `letter_text`: the
    letter as plain text, for a cover-letter text box."""
    contact: dict
    kit: list[dict]
    apply: ApplyConfig
    files: dict[str, Path]
    letter_text: str = ""


def blocker(page) -> str | None:
    return page.evaluate(_BLOCKER)


def scan(page) -> list[Field]:
    return [Field(ref=f["ref"], tag=f["tag"], type=f["type"], label=f["label"][:200],
                  name=f["name"], id=f["id"], placeholder=f["placeholder"],
                  autocomplete=f["autocomplete"], required=f["required"],
                  options=tuple(f["options"]))
            for f in page.evaluate(_SCAN)]


def _label(f: Field) -> str:
    text = re.sub(r"\s*\*\s*$", "", f.label).strip() or f.name or f.id or "(sans libellé)"
    return text[:80]


def _numbers(text: str) -> list[int]:
    """Amounts in an option label: "40k", "40 000", "40-45 k€" -> [40000, 45000]."""
    t = text.lower().replace(" ", " ").replace("\xa0", " ")
    k = "k" in t
    out = []
    for m in re.finditer(r"\d[\d ]*(?:[.,]\d+)?", t):
        v = float(m.group().replace(" ", "").replace(",", "."))
        out.append(int(v * 1000 if k and v < 1000 else v))
    return out


def salary_option(options: tuple[str, ...], lo: int, hi: int) -> int | None:
    """The one option whose amounts sit inside my range, else None (out of range: left)."""
    hits = []
    for i, o in enumerate(options):
        nums = _numbers(o)
        if nums and lo <= min(nums) and max(nums) <= hi:
            hits.append(i)
    return hits[0] if len(hits) == 1 else None


def _match_option(options: tuple[str, ...], forms: list[str]) -> int | None:
    """The option that reads one of `forms` (folded: case and accents ignored), tried in
    order; else the one option starting with it. None when nothing or several match."""
    folded = [fold(o) for o in options]
    for want in forms:
        if want in folded:
            return folded.index(want)
    for want in forms:
        starts = [i for i, o in enumerate(folded) if o.startswith(want + " ") or o == want]
        if len(starts) == 1:
            return starts[0]
    return None


def _kit_text(kit: list[dict], key: str) -> str | None:
    for item in kit:
        if item.get("key") == key and item.get("text"):
            return item["text"]
    return None


def _salary_item(kit: list[dict]) -> dict:
    return next((i for i in kit if i.get("key") == "salary"), {"mode": "manuel"})


def _benchmark_note(item: dict) -> str:
    b = item.get("benchmark")
    if not b:
        return "aucun repère de zone dans private/apply.yaml"
    return f"repère {b.get('zone') or 'de la zone'} : {b.get('text', '')}"


def _value(kind_cat: str, inputs: Inputs, fixed_index: int | None) -> tuple[str | None, str]:
    """(value, source) for a text-like answer, value None when there is none."""
    c = inputs.contact
    first, last = c.get("first_name", ""), c.get("last_name", "")
    contact = {
        "first_name": first, "last_name": last, "full_name": f"{first} {last}".strip(),
        "email": c.get("email", ""), "phone": c.get("phone", ""),
        "linkedin": _https(c.get("linkedin", "")), "github": _https(c.get("github", "")),
    }
    if kind_cat in contact:
        v = contact[kind_cat]
        return (v or None), "contact.yaml"
    if kind_cat == "fixed" and fixed_index is not None:
        return inputs.apply.reponses_fixes[fixed_index].reponse, "apply.yaml"
    if kind_cat == "cover_letter":
        return (inputs.letter_text or None), "lettre"
    v = _kit_text(inputs.kit, kind_cat)
    return v, "kit"


def _https(value: str) -> str:
    v = (value or "").strip()
    if v and not re.match(r"^https?://", v):
        v = "https://" + v
    return v


_LEFT_REASON = {
    "sensitive": "question sensible, jamais remplie",
    "consent": "case de consentement, à cocher toi-même",
    "unknown": "question inconnue",
    "password": "mot de passe : jamais rempli",
}


def fill_form(page, questions: Questions, inputs: Inputs, ats: str | None) -> Report:
    report = Report(ats=ats)

    def left(f: Field, reason: str, color: str = TODO_COLOR, note: str = "") -> None:
        report.left.append((_label(f), reason))
        page.evaluate(_MARK, [f.ref, color, note])

    def done(f: Field, source: str) -> None:
        report.filled.append((_label(f), source))
        page.evaluate(_MARK, [f.ref, FILLED_COLOR, ""])

    for f in scan(page):
        kind = questions.classify(f, inputs.apply)
        cat = kind.category
        loc = page.locator(f'[data-jm-field="{f.ref}"]')
        if cat in _LEFT_REASON:
            left(f, _LEFT_REASON[cat], SENSITIVE_COLOR if cat != "unknown" else TODO_COLOR)
            continue
        if cat == "salary":
            item = _salary_item(inputs.kit)
            note = _benchmark_note(item)
            rng = item.get("range") if item.get("mode") == "fourchette" else None
            if rng is None:
                left(f, f"salaire en mode manuel, {note}", SENSITIVE_COLOR, note)
                report.notes.append(f"Salaire « {_label(f)} » : à toi, {note}")
                continue
            if f.tag in ("select", "radio"):
                i = salary_option(f.options, int(rng["min"]), int(rng["max"]))
                if i is None:
                    left(f, f"aucune option dans ma fourchette, {note}", SENSITIVE_COLOR, note)
                    continue
                _choose(loc, f, i)
                done(f, "apply.yaml (fourchette)")
            elif f.tag == "textarea" or f.type in ("text", ""):
                loc.fill(item["text"])
                done(f, "apply.yaml (fourchette)")
            else:  # a number box takes one figure: not mine to choose
                left(f, f"un seul montant demandé, {note}", SENSITIVE_COLOR, note)
            continue
        if cat in ("resume", "cover_letter") and f.type == "file":
            path = inputs.files.get(cat)
            if not path:
                left(f, "pas de document prêt")
                continue
            loc.set_input_files(str(path))
            done(f, "CV PDF" if cat == "resume" else "lettre PDF")
            continue
        value, source = _value(cat, inputs, kind.fixed_index)
        if value is None:
            left(f, "réponse absente du kit" if source == "kit" else f"vide dans {source}")
            continue
        if f.tag in ("select", "radio"):
            alt = (inputs.apply.reponses_fixes[kind.fixed_index].label_en
                   if cat == "fixed" and kind.fixed_index is not None else "")
            i = _match_option(f.options, questions.option_forms(value, alt))
            if i is None:
                left(f, f"aucune option ne correspond à la réponse ({source})")
                continue
            _choose(loc, f, i)
            done(f, source)
            continue
        loc.fill(value)
        done(f, source)
    log.info("apply form: %s filled, %s left", len(report.filled), len(report.left))
    return report


def _choose(loc, f: Field, index: int) -> None:
    if f.tag == "select":
        loc.select_option(index=index)
        return
    radio = loc.nth(index)
    if radio.get_attribute("type") != "radio":
        raise RuntimeError("refusing to press a control that is not a radio")
    radio.check()
