"""The CV download in a real browser, timed (ADR 0019 amendment): the first ⬇ PDF in under
1.5 s once Candidatures has preloaded the renderer, the second click in under 300 ms (the file
rendered this session is kept), and the PDF still a real one (fonts embedded with their
ToUnicode map, so an ATS extracts the text; the extraction and the accents themselves are checked
by worker/test/render.test.mjs).

The CV is full size: three experiences, four projects, an Engagement line, so the layout search
goes through several candidates as a real one does. Every value is made up.
"""
import json
import re
import time
import zlib
from urllib.parse import quote

FIRST_MS = 1500
AGAIN_MS = 300
MEASURES = """() => performance.getEntriesByType('measure')
  .filter((m) => m.name.startsWith('jm:'))
  .map((m) => ({ name: m.name, ms: Math.round(m.duration), detail: m.detail }))"""
PRELOADED = """() => ['jm:module', 'jm:fonts']
  .every((n) => performance.getEntriesByName(n).length)"""


def _bullet(i, j):
    text = (f"Mise en place d’une chaîne GitLab CI/CD pour {j + 12} services Kubernetes (GKE) : "
            "déploiements Helm, supervision Prometheus élargie.")
    return {"id": f"e{i}.b{j}", "text": text}


def _bundle(key):
    experiences = [{"id": f"e{i}", "employer": f"Société Générale d’Études {i}",
                    "title": "Ingénieur DevOps", "start": f"202{i}-01",
                    "end": None if i == 0 else "2024-06", "location": "Lyon",
                    "bullets": [_bullet(i, j) for j in range(4)]}
                   for i in range(3)]
    projects = [{"id": f"p{i}", "name": f"Projet {i}", "start": "2024-01", "end": "2024-05",
                 "bullets": [_bullet(10 + i, 0)]} for i in range(4)]
    letter = {"paragraphs": [{"sentences": [{"text": "Votre offre m’intéresse.", "sources": []}]}]}
    content = {
        "job_key": key, "version": 1, "language": "fr", "model": "test", "prompt_version": "5",
        "generated_at": "2026-11-04T09:00:00Z",
        "offer": {"key": key, "title": "Ingénieur DevOps", "company": "Initech"},
        "profile": "Ingénieur DevOps orienté Kubernetes et GCP, à l’aise en production : "
                   "Terraform, Ansible, observabilité. Disponible à partir de janvier 2027.",
        "selected_bullets": [],
        "skill_groups": [
            {"group": "Conteneurs & IaC", "items": ["Kubernetes (GKE)", "Helm", "Terraform"]},
            {"group": "CI/CD", "items": ["GitLab CI/CD", "Jenkins"]}],
        "headline_techs": ["Kubernetes", "Terraform"],
        "letter": letter,
        "highlights": ["kubernetes", "terraform"],
        "availability": "Disponible à partir de janvier 2027.",
        "cv": {"experiences": experiences, "projects": projects},
    }
    master = {
        "headline": "Ingénieur DevOps", "skill_groups": [],
        "education": [{"degree": "Diplôme d’ingénieur", "school": "ENSIAS", "location": "Rabat",
                       "start": "2022-09", "end": "2025-06"}],
        "languages": [{"name": "Français", "level": "bilingue"},
                      {"name": "Anglais", "level": "courant"}],
        "extras": ["Ex-président de la branche étudiante IEEE : organisation de conférences."]}
    contact = {"first_name": "Jean-Élie", "last_name": "Trapmarker", "title": "Ingénieur DevOps",
               "email": "jean@example.com", "phone": "+33 6 00 00 00 00", "linkedin": "",
               "github": "", "location": "Île-de-France"}
    return {"content": content, "master": master, "contact": contact}


def _api(key):
    app = {"job_key": key, "status": "to_apply", "applied_at": None, "follow_up_at": None,
           "note": None, "cv_url": None, "updated_at": "2026-11-04T08:00:00Z",
           "sent_documents_version": None}
    doc = {"job_key": key, "version": 1, "status": "ready", "language": "fr", "error_code": None,
           "updated_at": "2026-11-04T09:00:00Z", "files": False}
    return {"applications": [app], "decisions": [], "skill_overrides": [], "ai_verdicts": [],
            "ai_runs": [], "documents": [doc], "documents_budget": None}


def _objects(pdf):
    """The PDF's text once every Flate stream is inflated: pdf-lib packs its dictionaries
    (fonts, ToUnicode maps) into object streams."""
    out = [pdf]
    for m in re.finditer(rb"stream\r?\n", pdf):
        try:
            out.append(zlib.decompressobj().decompress(pdf[m.end():m.end() + 200_000]))
        except zlib.error:
            pass
    return b"\n".join(out)


def _timed_download(page, link):
    link.hover()  # the pointer reaches the link first, as a person's does
    start = time.perf_counter()
    with page.expect_download() as info:
        link.click()
    download = info.value
    ms = (time.perf_counter() - start) * 1000
    with open(download.path(), "rb") as fh:
        return ms, download.suggested_filename, fh.read()


def test_first_cv_pdf_under_1_5_s_and_the_second_click_under_300_ms(open_dashboard, job_keys):
    key = job_keys[0]
    path = f"/api/documents/{quote(key, safe='')}/v1/content.json"
    headers = {"content-type": "application/json", "cache-control": "no-store"}
    routes = {("GET", path): (200, headers, json.dumps(_bundle(key)))}
    page, errors = open_dashboard(_api(key), hash_="#candidatures?view=table", routes=routes)
    link = page.locator("#kb-table a.doc-dl", has_text="⬇ PDF").first
    link.wait_for()
    page.wait_for_function(PRELOADED)  # requestIdleCallback after the view opened

    first_ms, name, pdf = _timed_download(page, link)
    page.wait_for_function("() => !document.querySelector('#kb-table a.doc-dl[aria-busy]')")
    again_ms, again_name, again = _timed_download(page, link)
    measures = page.evaluate(MEASURES)
    print("\nfirst click", round(first_ms), "ms, second", round(again_ms), "ms", measures)

    assert first_ms < FIRST_MS, measures
    assert again_ms < AGAIN_MS, measures
    assert name == again_name == "CV_Jean_Elie_Trapmarker_Initech.pdf"
    assert again == pdf  # the same bytes, not a second render
    assert [m["name"] for m in measures].count("jm:render:pdf") == 1
    assert [m["name"] for m in measures].count("jm:content") == 1
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    objects = _objects(pdf)
    assert objects.count(b"/ToUnicode") == 2 and objects.count(b"/FontFile2") == 2  # regular + bold
    # one click renders one file: no DOCX, no letter alongside the CV's PDF
    assert not [m for m in measures if m["name"] == "jm:render:docx"]
    assert errors == []
