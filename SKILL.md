---
name: google-ads
description: |
  Skill for pulling campaign costs, negative keywords, and performance data from Google Ads API.
  Use this skill whenever the user asks about Google Ads campaigns, costs, keywords, search terms,
  ad spend, ROAS, or wants to extract data from their Google Ads account. Also trigger when the
  user mentions GAQL queries, Google Ads API, developer tokens, or needs to refresh OAuth tokens
  for Google Ads.
---

# Google Ads API Skill

This skill provides everything needed to connect to the Google Ads API, extract campaign cost data,
audit negative keywords, and run custom GAQL queries against a Google Ads account.

## Quick Start

1. Ensure `config/google_ads.ini` exists (copy from `config/google_ads.template.ini`)
2. If no refresh token yet, run `python scripts/get_google_refresh_token.py`
3. Test connectivity: `python scripts/test_google_ads.py`
4. Pull campaign costs: `python scripts/ExtrageCosturiCampanii.py`

## Prerequisites

```bash
pip install google-ads google-auth requests
```

## Authentication Setup

Google Ads API requires 4 credentials:

1. **Developer Token** — from Google Ads UI > Tools & Settings > API Center (requires MCC/Manager account)
2. **OAuth Client ID + Secret** — from Google Cloud Console > APIs & Services > Credentials > OAuth 2.0 Desktop app
3. **Refresh Token** — obtained via OAuth flow using `get_google_refresh_token.py`
4. **Customer ID** — the 10-digit Google Ads account ID (no hyphens)

All credentials go in `config/google_ads.ini` (gitignored). See `config/google_ads.template.ini` for the format.

### Obtaining a Refresh Token

```bash
python scripts/get_google_refresh_token.py
```

The script reads `client_id` and `client_secret` from config, opens an OAuth URL, and writes the refresh token back to `config/google_ads.ini` automatically.

**Critical**: If the OAuth consent screen is in "Testing" mode, refresh tokens expire after **7 days**. Move to "In production" in Google Cloud Console for permanent tokens.

### API Version Management

Google Ads releases new API versions every ~3 months and retires old ones after ~18 months. The version is configured in `google_ads.ini` (`api_version`). Always start with the latest version. If it returns 404, step down one version.

Current version as of April 2026: `v21`

## Available Scripts

### `ExtrageCosturiCampanii.py` — Campaign Cost Extraction

Primary script for pulling campaign spend data. Supports both Google Ads and Meta (Meta portion uses separate config).

```bash
python scripts/ExtrageCosturiCampanii.py                     # default: last 6 months
python scripts/ExtrageCosturiCampanii.py --months 12         # last 12 months
python scripts/ExtrageCosturiCampanii.py --start 2024-11-01 --end 2026-03-31  # custom range
```

**Output**: CSV with campaign costs per month + SQL INSERT statements compatible with `sp_Import_Costuri_Campanii`.

Also generates a campaigns period file (start/end dates, status, first/last month with spend).

### `fetch_google_ads_negatives.py` — Negative Keywords Audit

Extracts all negative keyword lists and search terms report for the last 90 days.

```bash
python scripts/fetch_google_ads_negatives.py
```

**Output**: CSV with negative keywords and search terms, useful for campaign optimization audits.

### `test_google_ads.py` — Connection Test

Validates credentials by calling `listAccessibleCustomers`.

```bash
python scripts/test_google_ads.py
```

### `test_google_ads_query.py` — GAQL Query Test

Runs specific GAQL queries for debugging.

### `get_google_refresh_token.py` — OAuth Token Helper

Interactive OAuth flow to obtain or refresh the token. Writes directly to `config/google_ads.ini`.

## Config Loader

All scripts use `config_loader.py` (included in `scripts/`) which provides:

- `load_google_ads()` — reads `config/google_ads.ini`, validates all fields are non-placeholder
- Placeholder detection: flags values containing `YOUR_`, `INSERT_`, `PASTE_`, `PUNE`, `0000000000`
- Clear error messages when config is missing or incomplete

## Common Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `invalid_grant: Token has been expired or revoked` | Refresh token expired (Testing mode = 7 days) | Run `get_google_refresh_token.py`; move consent screen to Production |
| `invalid_client` | client_secret empty or wrong | Run `config_loader.py` to dump masked config; re-copy secret from Cloud Console |
| `PERMISSION_DENIED` | customer_id wrong or no access | Verify customer_id; check Manager account access |
| `404` on API version | Retired version | Update `api_version` in config to latest |

## Credential Security

- `config/google_ads.ini` is gitignored — never commit credentials
- `config/google_ads.template.ini` is the committed template with `YOUR_*` placeholders
- Refresh tokens should be obtained interactively (not via automated scripts with stdout redirection)
- If a secret leaks to GitHub, Google auto-revokes it
