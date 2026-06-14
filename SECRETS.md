# Gestionarea secretelor (Windows Credential Manager)

Secretele API (`client_secret`, `refresh_token`, `developer_token`) **nu se mai tin in clar**
in `config/*.ini`. Stau in **Windows Credential Manager** al fiecarei statii, prin libraria `keyring`.

- `.ini` ramane doar pentru ne-secrete: `property_id`, `customer_id`, `api_version`, etc.
- Secretele nu ajung niciodata in git sau zip. Codul e identic pe toate statiile (sincronizat prin git);
  fiecare statie isi are propriile secrete local.
- Backward-compatible: daca un secret nu e in Credential Manager, se foloseste valoarea din `.ini` (tranzitie).

## Setup pe o statie noua (o singura data)

```powershell
pip install -r requirements.txt        # include keyring

# Varianta A: ai deja un config/ga4.ini completat -> muta secretele in Credential Manager
python scripts/secret_store.py migrate google_ads config/google_ads.ini
#   -> muta developer_token + client_secret + refresh_token in Credential Manager si le goleste in .ini

# Varianta B: introducere manuala (valoarea e ascunsa la tastare)
python scripts/secret_store.py set google_ads client_secret
python scripts/secret_store.py set google_ads refresh_token

# Verificare (afiseaza doar prezent/lipsa, NU valorile)
python scripts/secret_store.py status google_ads
```

## Cum functioneaza in cod

`config_loader.load_ga4()` / `load_google_ads()` returneaza acelasi `ConfigParser` ca inainte —
scripturile NU se schimba. In spate, `overlay_secrets()` suprascrie campurile secrete cu valorile
din Credential Manager daca exista.

## Campuri considerate secrete

| Serviciu     | Secrete (in Credential Manager)                  | In `.ini` raman          |
|--------------|--------------------------------------------------|--------------------------|
| `ga4`        | `client_secret`, `refresh_token`                 | `client_id`, `property_id`, `api_version` |
| `google_ads` | `developer_token`, `client_secret`, `refresh_token` | `client_id`, `customer_id`, `api_version` |

Cheile sunt stocate sub numele de serviciu `FGO:<serviciu>` in Credential Manager.

## Rotatie

Daca un secret e compromis: regenereaza-l la furnizor (Google Cloud / Ads API Center),
apoi `python scripts/secret_store.py set <serviciu> <camp>` cu noua valoare.
