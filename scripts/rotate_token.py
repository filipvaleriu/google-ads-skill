"""
rotate_token.py
---------------
Re-emite un refresh_token Google prin OAuth cu server local (browser auto, fara
lipit cod manual) si il salveaza DIRECT in Windows Credential Manager (keyring).

Utilizare:
    python rotate_token.py ga4        --ini <cale>/config/ga4.ini
    python rotate_token.py google_ads --ini <cale>/config/google_ads.ini

Flux:
  1. Citeste client_id + client_secret din .ini (sectiunea = numele serviciului).
  2. Deschide browserul -> alegi contul Google + accepti.
  3. Serverul local prinde redirectul, obtine refresh_token (access_type=offline,
     prompt=consent => garantat refresh_token nou).
  4. Salveaza refresh_token (si client_secret) in Credential Manager: FGO:<serviciu>.

Necesita: pip install google-auth-oauthlib keyring
"""

from __future__ import annotations

import argparse
import configparser
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

import secret_store

SCOPES: dict[str, list[str]] = {
    "ga4": ["https://www.googleapis.com/auth/analytics.readonly"],
    "google_ads": ["https://www.googleapis.com/auth/adwords"],
}


def _read_client(ini_path: Path, section: str) -> tuple[str, str]:
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(ini_path, encoding="utf-8")
    if not cp.has_section(section):
        sys.exit(f"[!] Sectiunea [{section}] lipseste din {ini_path}")
    cid = cp[section].get("client_id", "").strip().strip('"')
    csec = cp[section].get("client_secret", "").strip().strip('"')
    if not cid or not csec:
        sys.exit(f"[!] client_id/client_secret lipsesc in {ini_path} [{section}]")
    return cid, csec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("service", choices=SCOPES.keys())
    ap.add_argument("--ini", required=True, type=Path)
    ap.add_argument("--section", default=None,
                    help="sectiunea din .ini (default = numele serviciului)")
    args = ap.parse_args()

    section = args.section or args.service
    client_id, client_secret = _read_client(args.ini, section)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES[args.service])

    print(f"Se deschide browserul pentru {args.service} (scope: {SCOPES[args.service][0]})...")
    print("Alege contul Google potrivit si accepta.")
    creds = flow.run_local_server(
        port=0,
        access_type="offline",   # cere refresh_token
        prompt="consent",        # forteaza emiterea unuia nou
        success_message="Autorizat. Poti inchide acest tab si reveni in terminal.",
    )

    if not creds.refresh_token:
        return _fail("Nu am primit refresh_token (verifica access_type=offline/prompt=consent).")

    secret_store.set_secret(args.service, "refresh_token", creds.refresh_token)
    secret_store.set_secret(args.service, "client_secret", client_secret)
    print(f"OK: refresh_token NOU pentru '{args.service}' salvat in Credential Manager (FGO:{args.service}).")
    return 0


def _fail(msg: str) -> int:
    print(f"[!] {msg}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
