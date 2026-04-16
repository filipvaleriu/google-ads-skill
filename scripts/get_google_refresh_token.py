"""
Helper: Obtine / reimprospateaza Refresh Token pentru Google Ads API
====================================================================
Ruleaza acest script oricand primesti eroarea:
    invalid_grant: Token has been expired or revoked

Prerequisite:
    pip install requests
    (client_id / client_secret sunt citite din config/google_ads.ini)

Utilizare:
    python get_google_refresh_token.py

Ce face:
    1. Citeste client_id / client_secret din config/google_ads.ini
    2. Iti afiseaza un URL de autorizare Google OAuth
    3. Il deschizi in browser, te loghezi, accepti permisiunile
    4. Google te redirecteaza la localhost (pagina nu se incarca - e normal)
    5. Lipesti URL-ul din bara browser in consola
    6. Scriptul extrage codul, il schimba pe refresh_token, si
       il scrie AUTOMAT inapoi in config/google_ads.ini (sectiunea [google_ads])
    7. Testeaza imediat refresh_token-ul obtinut — te anunta daca functioneaza

IMPORTANT despre expirarea refresh_token:
    - Daca OAuth consent screen este in modul **Testing**, refresh_token-urile
      EXPIRA automat dupa 7 ZILE. Aceasta e cauza cea mai frecventa a erorii
      "invalid_grant: Token has been expired or revoked".
    - Fix definitiv: muta consent screen-ul la "In production" in
      Google Cloud Console → APIs & Services → OAuth consent screen → Publish App.
    - Alte cauze posibile: user a revocat manual, 6 luni de inactivitate
      in productie, sau limita de 50 refresh tokens/user depasita.
"""

import sys
import urllib.parse
import configparser
from pathlib import Path

try:
    import requests
except ImportError:
    print("[!] Libraria requests nu e instalata. Ruleaza: pip install requests")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
# Fisierul real cu credentiale (gitignored). Template-ul traieste alaturi ca
# config/google_ads.template.ini si e commit-at.
CONFIG_FILE = SCRIPT_DIR.parent / "config" / "google_ads.ini"
REDIRECT_URI = "http://localhost"
SCOPES = "https://www.googleapis.com/auth/adwords"


def load_config():
    """Citeste client_id si client_secret din config/google_ads.ini [google_ads]."""
    if not CONFIG_FILE.exists():
        print(f"[!] Nu gasesc {CONFIG_FILE}")
        print(f"[!] Copiaza {CONFIG_FILE.parent / 'google_ads.template.ini'} ca {CONFIG_FILE}")
        sys.exit(1)

    cfg = configparser.ConfigParser()
    cfg.read(str(CONFIG_FILE), encoding='utf-8-sig')

    if "google_ads" not in cfg:
        print(f"[!] Sectiunea [google_ads] lipseste din {CONFIG_FILE}")
        sys.exit(1)

    client_id = cfg.get("google_ads", "client_id", fallback="").strip()
    client_secret = cfg.get("google_ads", "client_secret", fallback="").strip()

    if not client_id or not client_secret:
        print("[!] client_id sau client_secret lipsesc din [google_ads]")
        sys.exit(1)

    return cfg, client_id, client_secret


def save_refresh_token(cfg, new_token):
    """Scrie noul refresh_token inapoi in config/google_ads.ini, sectiunea [google_ads]."""
    cfg.set("google_ads", "refresh_token", new_token)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)
    print(f"[OK] refresh_token actualizat in {CONFIG_FILE}")


def test_refresh_token(client_id, client_secret, refresh_token):
    """Testeaza imediat daca refresh_token-ul obtinut e functional."""
    print("\n[test] Verific ca refresh_token-ul functioneaza...")
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if r.status_code == 200:
        data = r.json()
        expires_in = data.get("expires_in", 0)
        print(f"[OK] refresh_token valid. Access token expira in ~{expires_in}s "
              f"(se reimprospateaza automat la fiecare apel API).")
        return True
    else:
        print(f"[!] Test esuat: {r.status_code} — {r.text}")
        return False


def main():
    print("=" * 66)
    print(" GOOGLE ADS — Obtinere / Reimprospatare Refresh Token")
    print("=" * 66)

    cfg, client_id, client_secret = load_config()
    current_token = cfg.get("google_ads", "refresh_token", fallback="").strip()

    # Pas 0: daca exista deja token, incearca sa-l testezi inainte de regenerare
    if current_token:
        print(f"\n[i] refresh_token existent in config: {current_token[:20]}...")
        if test_refresh_token(client_id, client_secret, current_token):
            print("\n[?] Token-ul actual inca functioneaza. Mai vrei sa-l regenerezi?")
            choice = input("    (y = regenerez, orice altceva = iesire): ").strip().lower()
            if choice != "y":
                print("Iesire fara modificari.")
                return
        else:
            print("\n[!] Token-ul actual NU mai functioneaza — trebuie regenerat.")
            print("    Cauza probabila: OAuth consent screen in modul 'Testing'")
            print("    (expirare la 7 zile) sau access revocat manual.")

    # Pas 1: Genereaza URL-ul de autorizare
    auth_url = (
        "https://accounts.google.com/o/oauth2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
        f"scope={urllib.parse.quote(SCOPES)}&"
        "response_type=code&"
        "access_type=offline&"
        "prompt=consent"
    )

    print()
    print("PASUL 1: Deschide acest URL in browser")
    print("-" * 66)
    print(auth_url)
    print("-" * 66)
    print()
    print("PASUL 2: Logheaza-te cu contul Google care are acces la Google Ads FGO")
    print("         si accepta permisiunile.")
    print()
    print("PASUL 3: Browser-ul te redirecteaza catre un URL tip:")
    print("         http://localhost/?code=4/0AX...&scope=...")
    print("         Pagina NU se incarca (localhost nu ruleaza) - e NORMAL.")
    print("         Copiaza INTREGUL URL din bara de adrese.")
    print()

    redirect_response = input("Lipeste URL-ul aici: ").strip()

    # Pas 2: Extrage codul de autorizare
    try:
        parsed = urllib.parse.urlparse(redirect_response)
        params = urllib.parse.parse_qs(parsed.query)
        auth_code = params["code"][0]
    except (KeyError, IndexError):
        print("[!] Nu am gasit parametrul 'code' in URL.")
        print("[!] Verifica ca ai copiat intreg URL-ul din bara.")
        sys.exit(1)

    # Pas 3: Schimba codul pe refresh_token
    print("\n[.] Schimb authorization code pe refresh_token...")
    token_response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": auth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )

    if token_response.status_code != 200:
        print(f"[!] Eroare la oauth2.googleapis.com/token:")
        print(f"    {token_response.status_code} — {token_response.text}")
        sys.exit(1)

    tokens = token_response.json()
    refresh_token = tokens.get("refresh_token")

    if not refresh_token:
        print(f"[!] Raspunsul nu contine refresh_token: {tokens}")
        print("[!] Daca ai mai facut deja consent, Google nu iti mai da refresh_token.")
        print("    Mergi la https://myaccount.google.com/permissions, sterge accesul")
        print("    aplicatiei, apoi ruleaza din nou scriptul.")
        sys.exit(1)

    print(f"[OK] Refresh token obtinut: {refresh_token[:20]}...")

    # Pas 4: Testeaza imediat ca functioneaza
    if not test_refresh_token(client_id, client_secret, refresh_token):
        print("[!] Token obtinut dar testul a esuat. Nu scriu in config.")
        sys.exit(1)

    # Pas 5: Salveaza in config/google_ads.ini
    save_refresh_token(cfg, refresh_token)

    print()
    print("=" * 66)
    print(" GATA — token salvat si verificat.")
    print("=" * 66)
    print()
    print(" Poti rula acum:")
    print("   python import_demografice_campanii.py")
    print()
    print(" ATENTIE: daca OAuth consent screen e in 'Testing' mode, vei primi")
    print(" aceeasi eroare in max 7 zile. Fix definitiv:")
    print("   Google Cloud Console → APIs & Services → OAuth consent screen")
    print("   → butonul 'Publish App' (sau 'In production')")
    print()


if __name__ == "__main__":
    main()
