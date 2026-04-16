# google-ads-skill

Skill Cowork pentru extragere date din Google Ads API: costuri campanii, negative keywords, search terms, si query-uri GAQL custom.

## Structura

```
google-ads-skill/
├── SKILL.md                                    # Instructiuni principale
├── README.md                                   # Acest fisier
├── .gitignore
├── config/
│   └── google_ads.template.ini                 # Template config (placeholdere)
└── scripts/
    ├── config_loader.py                        # Loader centralizat configurari
    ├── ExtrageCosturiCampanii.py               # Extragere costuri campanii (Google + Meta)
    ├── fetch_google_ads_negatives.py           # Audit negative keywords
    ├── get_google_refresh_token.py             # Helper OAuth refresh token
    ├── test_google_ads.py                      # Test conexiune
    └── test_google_ads_query.py                # Test query GAQL
```

## Prerequisite

```bash
pip install google-ads google-auth requests
```

## Setup rapid

1. `cp config/google_ads.template.ini config/google_ads.ini`
2. Completeaza credentialele in `config/google_ads.ini`
3. `python scripts/get_google_refresh_token.py` (prima data)
4. `python scripts/ExtrageCosturiCampanii.py`

## Changelog

- 2026-04-16: Creat ca repo separat din proiectul principal de marketing
