"""`job-match apply <job_key>`: prepare the documents, open the form, fill it, stop (ADR 0023).

1. The offer from the local jobs DB (its URL), the latest ready documents version from D1 and
   its content.json from R2; the CV and the letter rendered here as PDF with the dashboard's
   render.js (scripts/apply-render.mjs), with the kit, into private/out/apply/ (gitignored).
2. A visible Chromium on a persistent profile (private/browser-profile/, gitignored: a
   sign-in I make by hand stays), on the application page.
3. A CAPTCHA or a sign-in page: pause, « à toi ». An unknown ATS: « formulaire non pris en
   charge », the page stays open. Else the form is filled (forms.fill_form) and the report
   printed. The browser stays open on the ready page until I press Enter: I send it myself.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from job_match.apply.config import ApplyConfig
from job_match.apply.forms import Inputs, Report, application_url, blocker, detect_ats, fill_form
from job_match.apply.questions import Questions

FORM_SELECTOR = "input[type=email], input[type=file], textarea"
UNSUPPORTED = ("Formulaire non pris en charge (Greenhouse, Lever ou Ashby seulement) :"
               " la page reste ouverte, à toi.")


@dataclass(frozen=True)
class Offer:
    key: str
    url: str
    title: str
    company: str
    location: str


def find_offer(db_path: Path, key: str) -> Offer | None:
    source, _, source_id = key.partition(":")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT url, title, company, location FROM jobs"
            " WHERE source_id = ? AND source_job_id = ?",
            (source, source_id),
        ).fetchone()
    finally:
        conn.close()
    return Offer(key, *row) if row else None


def safe_dir_name(key: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in key)[:120]


def render_local(bundle: dict, out_dir: Path, location: str,
                 run: Callable | None = None) -> dict:
    """{cv, letter, kit} paths, from scripts/apply-render.mjs. Raises RuntimeError on a
    failure, with Node's exit code only (its stderr could quote a document)."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js introuvable : il rend le CV et la lettre"
                           " (npm ci --prefix worker)")
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / "bundle.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    script = Path(__file__).resolve().parents[3] / "scripts" / "apply-render.mjs"
    if not script.exists():
        script = Path("scripts") / "apply-render.mjs"
    run = run or subprocess.run
    try:
        result = run([node, str(script), str(bundle_path), str(out_dir), "--location", location],
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
    finally:
        bundle_path.unlink(missing_ok=True)  # it holds the contact sheet
    if result.returncode != 0:
        raise RuntimeError(f"rendu local en échec (node exit {result.returncode})")
    return json.loads(result.stdout)


def load_inputs(paths: dict | None, contact: dict, apply: ApplyConfig) -> Inputs:
    if not paths:
        return Inputs(contact=contact, kit=[], apply=apply, files={})
    kit = json.loads(Path(paths["kit"]).read_text(encoding="utf-8"))
    return Inputs(contact=contact, kit=kit.get("items", []), apply=apply,
                  files={"resume": Path(paths["cv"]), "cover_letter": Path(paths["letter"])},
                  letter_text=kit.get("letter_text", ""))


def pause_on_blockers(page, wait_for_user: Callable[[str], None], say: Callable[[str], None],
                      tries: int = 5) -> None:
    for _ in range(tries):
        b = blocker(page)
        if b is None:
            return
        what = "CAPTCHA" if b == "captcha" else "Page de connexion"
        say(f"{what} détecté : à toi. Je ne crée aucun compte et ne résous aucun CAPTCHA.")
        wait_for_user("Appuie sur Entrée quand c'est réglé…")


def fill_page(page, url: str, questions: Questions, inputs: Inputs,
              wait_for_user: Callable[[str], None], say: Callable[[str], None],
              form_timeout_ms: int = 15000) -> Report | None:
    """Open, pause on a blocker, fill. None when the ATS or the form is not supported."""
    ats = detect_ats(url)
    target = application_url(url, ats) if ats else url
    page.goto(target, wait_until="domcontentloaded")
    pause_on_blockers(page, wait_for_user, say)
    if ats is None:
        say(UNSUPPORTED)
        return None
    try:
        page.wait_for_selector(FORM_SELECTOR, timeout=form_timeout_ms)
    except Exception:  # noqa: BLE001 - Playwright's TimeoutError; the page stays for me
        pause_on_blockers(page, wait_for_user, say)
        if page.locator(FORM_SELECTOR).count() == 0:
            say(UNSUPPORTED)
            return None
    report = fill_form(page, questions, inputs, ats)
    for line in report.lines():
        say(line)
    return report


def launch(profile_dir: Path):
    """(playwright, context, page): headed Chromium on the persistent profile."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    profile_dir.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(str(profile_dir), headless=False,
                                                accept_downloads=False, viewport=None)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, ctx, page


def say_stdout(text: str) -> None:
    print(text, flush=True)


def wait_stdin(prompt: str) -> None:
    try:
        input(prompt)
    except EOFError:
        sys.stderr.write("stdin closed: not waiting\n")
