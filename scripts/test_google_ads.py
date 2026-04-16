"""
test_google_ads.py
------------------
Test minimal de conectare la Google Ads API.
Citeste credentialele din config/google_ads.ini prin config_loader si apeleaza
endpoint-ul customers:listAccessibleCustomers ca sanity check.

Rulare:
    cd Analiza-Campanii
    python test_google_ads.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

# Adaugam root-ul proiectului la sys.path ca sa importam config_loader
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_google_ads, ConfigError

TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> int:
    try:
        cp = load_google_ads()
    except ConfigError as e:
        print(f"[EROARE CONFIG]\n{e}")
        return 1

    g = cp["google_ads"]
    required = ["developer_token", "client_id", "client_secret", "refresh_token"]
    missing = [k for k in required if not g.get(k, "").strip()]
    if missing:
        print(f"[EROARE] Lipsesc chei in [google_ads]: {', '.join(missing)}")
        return 1

    api_version = g.get("api_version", "v21").strip() or "v21"
    list_url = f"https://googleads.googleapis.com/{api_version}/customers:listAccessibleCustomers"

    print(f"Folosesc Google Ads API {api_version}")

    print("Pas 1: obtinere access_token din refresh_token...")
    token_resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": g["client_id"].strip(),
            "client_secret": g["client_secret"].strip(),
            "refresh_token": g["refresh_token"].strip(),
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if token_resp.status_code != 200:
        print(f"[EROARE] Token refresh a esuat: HTTP {token_resp.status_code}")
        print(token_resp.text)
        return 1
    access_token = token_resp.json().get("access_token")
    if not access_token:
        print("[EROARE] Raspuns fara access_token:", token_resp.text)
        return 1
    print(f"  OK - access_token obtinut (len={len(access_token)})")

    print("Pas 2: apel listAccessibleCustomers...")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": g["developer_token"].strip(),
    }
    login_customer_id = g.get("login_customer_id", "").strip()
    if login_customer_id:
        headers["login-customer-id"] = login_customer_id.replace("-", "")

    resp = requests.get(list_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"[EROARE] API call a esuat: HTTP {resp.status_code}")
        print(resp.text)
        return 1

    data = resp.json()
    resources = data.get("resourceNames", [])
    print(f"  OK - {len(resources)} conturi accesibile:")
    for r in resources:
        print(f"    - {r}")

    configured_cid = g.get("customer_id", "").strip().replace("-", "")
    if configured_cid:
        match = any(configured_cid in r for r in resources)
        status = "gasit in lista" if match else "NU e in lista accesibila"
        print(f"\nCustomer_id configurat: {configured_cid} -> {status}")

    print("\n[SUCCES] Conectare Google Ads OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
