"""
Throwaway diagnostic script — France Travail search endpoint probe.
Prints status, Content-Range total, and exact query params for each probe.
Never prints the token or credentials.
Run: .venv\Scripts\python scripts/ft_probe.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import httpx  # noqa: E402

from job_match.config.loader import load_profile  # noqa: E402

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"


def _get_token(client: httpx.Client) -> str:
    resp = client.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["FT_CLIENT_ID"],
            "client_secret": os.environ["FT_CLIENT_SECRET"],
            "scope": SCOPE,
        },
        params={"realm": "/partenaire"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _probe(client: httpx.Client, token: str, label: str, params: dict) -> None:
    safe_params = {k: v for k, v in params.items()}  # no secrets in params
    resp = client.get(
        SEARCH_URL,
        headers={"Authorization": f"Bearer {token}", "Range": "0-9"},
        params=params,
        timeout=15,
    )
    total_header = resp.headers.get("Content-Range", "(none)")
    status = resp.status_code
    if status == 204:
        count_str = "0 results (204 No Content)"
    elif status == 200:
        body = resp.json()
        n = len(body.get("resultats") or [])
        total_match = total_header
        count_str = f"{n} items in page, Content-Range: {total_match}"
    else:
        count_str = f"unexpected {status}: {resp.text[:120]}"

    print(f"\n[{label}]")
    print(f"  params : {safe_params}")
    print(f"  status : {status}")
    print(f"  result : {count_str}")


def main() -> None:
    profile = load_profile(ROOT / "config" / "profile.yaml")
    kws = profile.ft_search.keywords
    romes = profile.ft_search.rome_codes
    adapter_keywords = " ".join(kws)
    adapter_romes = ",".join(romes)

    with httpx.Client() as client:
        print("Fetching token… ", end="", flush=True)
        token = _get_token(client)
        print("OK\n")

        _probe(client, token, "1 — dept 75 only", {"departement": "75"})
        _probe(client, token, "2 — dept 75 + motsCles=devops",
               {"departement": "75", "motsCles": "devops"})
        _probe(client, token, "3 — dept 75 + codeROME=M1801",
               {"departement": "75", "codeROME": "M1801"})
        _probe(client, token, "4 — dept 75 + motsCles=devops + codeROME=M1801",
               {"departement": "75", "motsCles": "devops", "codeROME": "M1801"})
        _probe(client, token, "5 — dept 75 + motsCles=devops,kubernetes (comma)",
               {"departement": "75", "motsCles": "devops,kubernetes"})
        _probe(client, token, "6 — dept 75 + motsCles=devops kubernetes (space)",
               {"departement": "75", "motsCles": "devops kubernetes"})
        _probe(client, token, "7 — exactly what the adapter sends",
               {"departement": "75", "motsCles": adapter_keywords, "codeROME": adapter_romes})
        if romes:
            _probe(client, token, "8 — adapter keywords, no ROME",
                   {"departement": "75", "motsCles": adapter_keywords})
        if kws:
            _probe(client, token, "9 — first keyword only, no ROME",
                   {"departement": "75", "motsCles": kws[0]})
        if len(kws) > 1:
            _probe(client, token, "10 — second keyword only, no ROME",
                   {"departement": "75", "motsCles": kws[1]})

    print()


if __name__ == "__main__":
    main()
