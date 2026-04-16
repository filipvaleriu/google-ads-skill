"""
==========================================================================
SCRIPT: Extragere costuri campanii din Google Ads API + Meta Marketing API
==========================================================================
Output: CSV cu costurile pe campanie / luna, gata de import in analiza CAC
Output NOU: CSV cu perioadele campaniilor (start/end, status, prima/ultima luna spend)

Versiune: 2.0 — Adauga perioade campanie (start_date, end_date, status)

Prerequisite:
    pip install google-ads google-auth facebook-business

SETUP CREDENTIALS - CITESTE INAINTE DE PRIMA RULARE:

=== GOOGLE ADS ===
1. Acceseaza https://console.cloud.google.com/
2. Creeaza un proiect nou (sau foloseste unul existent)
3. Activeaza "Google Ads API" din Library
4. Mergi la APIs & Services -> Credentials -> Create Credentials -> OAuth 2.0 Client ID
   - Application type: Desktop app
   - Descarca JSON-ul -> salveaza ca "google_ads_credentials.json" in acelasi folder
5. Mergi la https://developers.google.com/google-ads/api/docs/get-started/oauth-cloud-project
   - Urmeaza pasii pentru a obtine un Refresh Token
   - Alternativ, ruleaza scriptul helper de mai jos (get_google_refresh_token)
6. Ai nevoie de un Developer Token:
   - Logheaza-te in Google Ads -> Tools & Settings -> API Center
   - Solicita un Developer Token (pentru test, Basic access e suficient)
7. Completeaza fisierul "google-ads.yaml" (vezi template-ul generat automat)

=== META / FACEBOOK ADS ===
1. Acceseaza https://developers.facebook.com/
2. Creeaza o aplicatie noua (tip: Business)
3. Adauga produsul "Marketing API"
4. Mergi la Tools -> Graph API Explorer
   - Selecteaza aplicatia ta
   - Adauga permisiunea: ads_read
   - Genereaza un User Access Token
5. Pentru token PERMANENT (recomandat):
   - Du-te la https://developers.facebook.com/tools/debug/accesstoken/
   - Introdu token-ul generat
   - Click "Extend Access Token" -> copiaza token-ul extins (valabil ~60 zile)
   - SAU: configureaza un System User in Business Manager pentru token permanent
6. Ai nevoie de Ad Account ID:
   - Mergi in Meta Ads Manager -> Account Overview
   - ID-ul e in URL: act_XXXXXXXXX (include "act_" prefix)
7. Completeaza in config.ini (vezi template-ul generat automat)

==========================================================================
"""

import os
import sys
import csv
import configparser
from datetime import datetime, timedelta
from pathlib import Path

# ========================================================================
# CONFIGURARE
# ========================================================================
SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_apis, ConfigError, CONFIG_DIR  # noqa: E402

OUTPUT_CSV = SCRIPT_DIR / "CosturiCampanii.csv"
OUTPUT_CAMPAIGNS_CSV = SCRIPT_DIR / "PerioadeCompanii.csv"
OUTPUT_CAMPAIGNS_SQL = SCRIPT_DIR / "PerioadeCompanii.sql"
# Output-uri per sursa (scrise aditional la cele combinate de mai sus)
OUTPUT_CSV_GOOGLE = SCRIPT_DIR / "CosturiCampanii_Google.csv"
OUTPUT_CSV_META = SCRIPT_DIR / "CosturiCampanii_Meta.csv"
OUTPUT_CAMPAIGNS_CSV_GOOGLE = SCRIPT_DIR / "PerioadeCompanii_Google.csv"
OUTPUT_CAMPAIGNS_CSV_META = SCRIPT_DIR / "PerioadeCompanii_Meta.csv"
# Sumar structurat citit de orchestrator (collect_google_meta_ads_and_GA4.py)
OUTPUT_SUMMARY_JSON = SCRIPT_DIR / "_pull_summary_ads.json"

# Template config vechi - pastrat momentan ca referinta, nu mai e folosit.
# Template-urile reale traiesc in config/*.template.ini si sunt gestionate
# de config_loader.py.
_LEGACY_CONFIG_TEMPLATE_UNUSED = """[google_ads]
# Developer Token din Google Ads API Center
developer_token = INSERT_DEVELOPER_TOKEN
# OAuth Client ID si Secret (din google cloud console)
client_id = INSERT_CLIENT_ID
client_secret = INSERT_CLIENT_SECRET
# Refresh token obtinut prin OAuth flow
refresh_token = INSERT_REFRESH_TOKEN
# Customer ID al contului Google Ads (fara cratime, ex: 1234567890)
customer_id = INSERT_CUSTOMER_ID
# Optional: MCC account ID daca folosesti un manager account
# login_customer_id = INSERT_MCC_ID

[meta_ads]
# Access Token (Long-lived sau System User token)
access_token = INSERT_ACCESS_TOKEN
# Ad Account ID (cu prefixul act_, ex: act_123456789)
ad_account_id = act_INSERT_ACCOUNT_ID

[settings]
# Perioada implicita: ultimele N luni (poate fi suprascris cu argumente CLI)
luni_inapoi = 24
# Moneda output (RON sau EUR) - daca API-ul returneaza EUR, se converteste
moneda_output = RON
# Curs EUR/RON aproximativ (actualizati periodic)
curs_eur_ron = 4.97
# Moneda contului Google Ads: RON sau EUR
# Daca contul e facturat in RON, pune RON (nu se aplica conversie)
# Daca contul e facturat in EUR, pune EUR (se converteste la RON cu cursul de mai sus)
moneda_cont_google = RON
# Moneda contului Meta Ads: RON sau EUR
# ATENTIE: Verifica in Meta Ads Manager → Settings → Account currency
# Daca contul e in RON, pune RON (altfel spend-ul se inmulteste gresit cu cursul EUR)
moneda_cont_meta = RON
# Platforme active: true/false - dezactiveaza ce nu ai configurat inca
extract_google = true
extract_meta = false
"""


def ensure_config():
    """Incarca config-urile din config/*.ini prin config_loader si valideaza."""
    try:
        config = load_apis(require_google_ads=True)
    except ConfigError as e:
        print(f"[!] {e}")
        sys.exit(1)

    # Platforme active (din config/settings.ini - defaults daca lipseste)
    extract_google = config.getboolean("settings", "extract_google", fallback=True)
    extract_meta = config.getboolean("settings", "extract_meta", fallback=False)

    checks = []
    if extract_google:
        checks.append(("google_ads", ["developer_token", "client_id", "client_secret", "refresh_token", "customer_id"]))
    if extract_meta:
        checks.append(("meta_ads", ["access_token", "ad_account_id"]))
        if not config.has_section("meta_ads"):
            print(f"[!] extract_meta = true dar config/facebook_ads.ini lipseste sau nu are [meta_ads].")
            print(f"    Copiaza {CONFIG_DIR / 'facebook_ads.template.ini'} -> config/facebook_ads.ini")
            sys.exit(1)

    if not extract_google and not extract_meta:
        print("[!] Nicio platforma activa. Seteaza extract_google = true sau extract_meta = true in config/settings.ini.")
        sys.exit(1)

    missing = []
    for section, keys in checks:
        for key in keys:
            val = config.get(section, key, fallback="")
            if not val or "INSERT_" in val or "YOUR_" in val:
                missing.append(f"[{section}] {key}")

    if missing:
        print(f"[!] Credentials incomplete in config/:")
        for m in missing:
            print(f"    - {m}")
        print(f"\n[!] Completeaza valorile in config/*.ini si reruleaza.")
        sys.exit(1)

    return config


def get_date_range(config, args):
    """Calculeaza intervalul de date pe baza config + argumente CLI."""
    luni = int(config.get("settings", "luni_inapoi", fallback="24"))

    if len(args) >= 3:
        data_start = args[1]
        data_end = args[2]
    else:
        today = datetime.today()
        start = today.replace(day=1) - timedelta(days=luni * 30)
        start = start.replace(day=1)
        data_start = start.strftime("%Y-%m-%d")
        data_end = today.strftime("%Y-%m-%d")

    print(f"[i] Perioada: {data_start} -> {data_end}")
    return data_start, data_end


# ========================================================================
# GOOGLE ADS - Extragere costuri per campanie / luna
# ========================================================================
def extract_google_ads(config, data_start, data_end):
    """Extrage costurile campaniilor din Google Ads API."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        print("[!] Libraria google-ads nu e instalata. Ruleaza: pip install google-ads")
        return [], []

    # Configurare client
    credentials = {
        "developer_token": config.get("google_ads", "developer_token"),
        "client_id": config.get("google_ads", "client_id"),
        "client_secret": config.get("google_ads", "client_secret"),
        "refresh_token": config.get("google_ads", "refresh_token"),
        "use_proto_plus": True,
    }
    login_customer_id = config.get("google_ads", "login_customer_id", fallback=None)
    if login_customer_id and "INSERT_" not in login_customer_id:
        credentials["login_customer_id"] = login_customer_id

    client = GoogleAdsClient.load_from_dict(credentials)
    customer_id = config.get("google_ads", "customer_id").replace("-", "")
    curs = float(config.get("settings", "curs_eur_ron", fallback="4.97"))

    ga_service = client.get_service("GoogleAdsService")

    # ================================================================
    # Query 1: cost per campanie per luna (existent)
    # ================================================================
    query_costs = f"""
        SELECT
            campaign.id,
            campaign.name,
            segments.month,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{data_start}' AND '{data_end}'
          AND campaign.status != 'REMOVED'
        ORDER BY segments.month DESC, campaign.name
    """

    results = []
    print("[Google Ads] Extragere costuri...")
    try:
        response = ga_service.search_stream(customer_id=customer_id, query=query_costs)
        for batch in response:
            for row in batch.results:
                cost_micros = row.metrics.cost_micros
                cost_valuta = cost_micros / 1_000_000  # Google returneaza in micros

                # Conversie la RON doar daca contul e in EUR
                moneda_cont = config.get("settings", "moneda_cont_google", fallback="RON")
                cost_ron = cost_valuta * curs if moneda_cont == "EUR" else cost_valuta

                luna = row.segments.month  # format: YYYY-MM-DD (prima zi a lunii)
                luna_fmt = luna[:7] if isinstance(luna, str) else luna.strftime("%Y-%m")

                results.append({
                    "Sursa": "Google Ads",
                    "CampaignID": str(row.campaign.id),
                    "NumeCampanie": row.campaign.name,
                    "Luna": luna_fmt,
                    "Cost_RON": round(cost_ron, 2),
                    "Impressions": row.metrics.impressions,
                    "Clicks": row.metrics.clicks,
                    "Conversions": round(row.metrics.conversions, 2),
                })

        print(f"[Google Ads] {len(results)} randuri costuri extrase.")
    except Exception as e:
        print(f"[Google Ads] EROARE costuri: {e}")

    # ================================================================
    # Query 2: perioade campanii (status, channel type, budget)
    # ================================================================
    # NOTA: Google Ads API v23 NU are campaign.start_date / end_date.
    #       Perioada se deduce din datele de cost (prima/ultima luna cu spend).
    #       Extragem: status, tip canal, buget zilnic.
    query_campaigns = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            campaign.advertising_channel_sub_type,
            campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.status != 'REMOVED'
        ORDER BY campaign.name
    """

    campaigns_info = []
    print("[Google Ads] Extragere info campanii (status, tip, buget)...")
    try:
        response = ga_service.search_stream(customer_id=customer_id, query=query_campaigns)
        for batch in response:
            for row in batch.results:
                budget_micros = row.campaign_budget.amount_micros if row.campaign_budget.amount_micros else 0
                moneda_cont = config.get("settings", "moneda_cont_google", fallback="RON")
                budget_val = budget_micros / 1_000_000
                budget_ron = budget_val * curs if moneda_cont == "EUR" else budget_val

                campaigns_info.append({
                    "Sursa": "Google Ads",
                    "CampaignID": str(row.campaign.id),
                    "NumeCampanie": row.campaign.name,
                    "Status": str(row.campaign.status).replace("CampaignStatus.", ""),
                    "StartDate": "",  # Se deduce din prima luna cu spend
                    "EndDate": "",    # Se deduce din ultima luna cu spend
                    "ChannelType": str(row.campaign.advertising_channel_type).replace("AdvertisingChannelType.", ""),
                    "ChannelSubType": str(row.campaign.advertising_channel_sub_type).replace("AdvertisingChannelSubType.", ""),
                    "DailyBudget_RON": round(budget_ron, 2),
                })

        # Filtram: pastram doar campaniile care au cost in perioada ceruta
        campaign_ids_with_cost = set(r["CampaignID"] for r in results)
        all_count = len(campaigns_info)
        campaigns_info = [c for c in campaigns_info if c["CampaignID"] in campaign_ids_with_cost]
        print(f"[Google Ads] {all_count} campanii din API, pastram {len(campaigns_info)} (cu cost in perioada {data_start} → {data_end})")
    except Exception as e:
        print(f"[Google Ads] EROARE perioade: {e}")

    return results, campaigns_info


# ========================================================================
# META / FACEBOOK ADS - Extragere costuri per campanie / luna
# ========================================================================
def extract_meta_ads(config, data_start, data_end):
    """Extrage costurile + perioadele campaniilor din Meta Marketing API."""
    try:
        from facebook_business.api import FacebookAdsApi
        from facebook_business.adobjects.adaccount import AdAccount
        from facebook_business.adobjects.campaign import Campaign
    except ImportError:
        print("[!] Libraria facebook-business nu e instalata. Ruleaza: pip install facebook-business")
        return [], []

    access_token = config.get("meta_ads", "access_token")
    ad_account_id = config.get("meta_ads", "ad_account_id")

    FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(ad_account_id)

    curs = float(config.get("settings", "curs_eur_ron", fallback="4.97"))
    results = []

    # ================================================================
    # Insights: costuri per campanie per luna
    # ================================================================
    print("[Meta Ads] Extragere costuri...")
    try:
        params = {
            "time_range": {"since": data_start, "until": data_end},
            "time_increment": "monthly",
            "level": "campaign",
            "fields": [
                "campaign_id",
                "campaign_name",
                "spend",
                "impressions",
                "clicks",
                "actions",
            ],
        }
        insights = account.get_insights(params=params)

        for row in insights:
            spend = float(row.get("spend", 0))
            moneda_cont = config.get("settings", "moneda_cont_meta", fallback="RON")
            cost_ron = spend * curs if moneda_cont == "EUR" else spend

            conversions = 0
            actions = row.get("actions", [])
            for action in actions or []:
                if action.get("action_type") in ("lead", "complete_registration", "offsite_conversion.fb_pixel_lead"):
                    conversions += int(action.get("value", 0))

            luna_raw = row.get("date_start", "")
            luna_fmt = luna_raw[:7] if luna_raw else "N/A"

            results.append({
                "Sursa": "Meta Ads",
                "CampaignID": row.get("campaign_id", ""),
                "NumeCampanie": row.get("campaign_name", ""),
                "Luna": luna_fmt,
                "Cost_RON": round(cost_ron, 2),
                "Impressions": int(row.get("impressions", 0)),
                "Clicks": int(row.get("clicks", 0)),
                "Conversions": conversions,
            })

        print(f"[Meta Ads] {len(results)} randuri costuri extrase.")
    except Exception as e:
        print(f"[Meta Ads] EROARE costuri: {e}")

    # ================================================================
    # Campaigns: perioade, status, objective
    # ================================================================
    campaigns_info = []
    print("[Meta Ads] Extragere perioade campanii...")
    try:
        campaigns = account.get_campaigns(
            fields=[
                Campaign.Field.id,
                Campaign.Field.name,
                Campaign.Field.status,
                Campaign.Field.effective_status,
                Campaign.Field.objective,
                Campaign.Field.start_time,
                Campaign.Field.stop_time,
                Campaign.Field.created_time,
                Campaign.Field.updated_time,
                Campaign.Field.daily_budget,
                Campaign.Field.lifetime_budget,
            ]
        )
        for c in campaigns:
            start_time = c.get("start_time", "")[:10] if c.get("start_time") else ""
            stop_time = c.get("stop_time", "")[:10] if c.get("stop_time") else ""
            daily_budget = float(c.get("daily_budget", 0)) / 100 if c.get("daily_budget") else 0
            lifetime_budget = float(c.get("lifetime_budget", 0)) / 100 if c.get("lifetime_budget") else 0

            moneda_cont = config.get("settings", "moneda_cont_meta", fallback="RON")
            if moneda_cont == "EUR":
                daily_budget *= curs
                lifetime_budget *= curs

            campaigns_info.append({
                "Sursa": "Meta Ads",
                "CampaignID": c.get("id", ""),
                "NumeCampanie": c.get("name", ""),
                "Status": c.get("effective_status", c.get("status", "")),
                "StartDate": start_time,
                "EndDate": stop_time,
                "ChannelType": c.get("objective", ""),
                "ChannelSubType": "",
                "DailyBudget_RON": round(daily_budget, 2),
            })

        print(f"[Meta Ads] {len(campaigns_info)} campanii cu perioade extrase.")
    except Exception as e:
        print(f"[Meta Ads] EROARE perioade: {e}")

    return results, campaigns_info


# ========================================================================
# EXPORT CSV
# ========================================================================
def write_csv(results, output_path):
    """Scrie rezultatele combinate intr-un CSV (costuri pe luna)."""
    if not results:
        print("[!] Niciun rezultat de scris.")
        return

    fieldnames = ["Sursa", "CampaignID", "NumeCampanie", "Luna", "Cost_RON",
                  "Impressions", "Clicks", "Conversions"]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(results)

    print(f"\n[OK] CSV costuri generat: {output_path}")
    print(f"[OK] Total randuri: {len(results)}")
    print(f"[OK] Total cost: {sum(r['Cost_RON'] for r in results):,.2f} RON")


def write_campaigns_csv(campaigns_info, cost_results, output_path):
    """
    Scrie CSV cu perioadele campaniilor + prima/ultima luna cu spend.
    Combina info din API (start/end date) cu insights (spend per luna).
    """
    if not campaigns_info:
        print("[!] Nicio campanie de scris.")
        return

    # Calculeaza prima/ultima luna cu spend per campaign_id
    spend_by_id = {}
    for r in cost_results:
        cid = r["CampaignID"]
        if cid not in spend_by_id:
            spend_by_id[cid] = {"months": [], "total_spend": 0}
        spend_by_id[cid]["months"].append(r["Luna"])
        spend_by_id[cid]["total_spend"] += r["Cost_RON"]

    fieldnames = [
        "Sursa", "CampaignID", "NumeCampanie",
        "Status", "StartDate", "EndDate",
        "ChannelType", "ChannelSubType", "DailyBudget_RON",
        "PrimaLunaSpend", "UltimaLunaSpend", "NrLuniActive", "TotalSpend",
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for c in campaigns_info:
            cid = c["CampaignID"]
            spend_info = spend_by_id.get(cid, {})
            months = sorted(spend_info.get("months", []))

            row = dict(c)
            row["PrimaLunaSpend"] = months[0] if months else ""
            row["UltimaLunaSpend"] = months[-1] if months else ""
            row["NrLuniActive"] = len(months)
            row["TotalSpend"] = f"{spend_info.get('total_spend', 0):.2f}"
            writer.writerow(row)

    with_spend = sum(1 for c in campaigns_info if c["CampaignID"] in spend_by_id)
    print(f"\n[OK] CSV perioade generat: {output_path}")
    print(f"[OK] Total campanii: {len(campaigns_info)} ({with_spend} cu spend)")


def write_campaigns_sql(campaigns_info, cost_results, output_path):
    """
    Genereaza SQL cu INSERT/MERGE in dbo.PerioadeCompanii pentru TOATE campaniile
    (Google + Meta). Include: CampaignID, NumeCampanie, Sursa, Status,
    StartDate, StopDate, PrimaLunaSpend, UltimaLunaSpend, NrLuniSpend, TotalSpend.
    """
    if not campaigns_info:
        print("[!] Nicio campanie de scris in SQL.")
        return

    # Calculeaza prima/ultima luna cu spend per campaign_id
    spend_by_id = {}
    for r in cost_results:
        cid = r["CampaignID"]
        if cid not in spend_by_id:
            spend_by_id[cid] = {"months": [], "total_spend": 0}
        spend_by_id[cid]["months"].append(r["Luna"])
        spend_by_id[cid]["total_spend"] += r["Cost_RON"]

    lines = []
    lines.append("-- =====================================================")
    lines.append("-- PERIOADE CAMPANII — generat automat de ExtrageCosturiCampanii.py")
    lines.append(f"-- Data generare: {datetime.today().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"-- Campanii: {len(campaigns_info)} (Google + Meta)")
    lines.append("-- =====================================================")
    lines.append("")
    lines.append("-- Asigura-te ca tabelul dbo.PerioadeCompanii exista")
    lines.append("-- (ruleaza Setup_Perioade_Campanii.sql PAS 1 mai intai)")
    lines.append("")
    lines.append("-- Sterge datele vechi si reinserteaza (full refresh)")
    lines.append("-- TRUNCATE TABLE dbo.PerioadeCompanii  -- decommenteaza daca vrei full refresh")
    lines.append("")

    count_google = 0
    count_meta = 0

    for c in campaigns_info:
        cid = c["CampaignID"]
        name = c["NumeCampanie"].replace("'", "''")
        sursa = c["Sursa"]
        status = c["Status"]
        start_date = c.get("StartDate", "")
        end_date = c.get("EndDate", "")

        spend_info = spend_by_id.get(cid, {})
        months = sorted(spend_info.get("months", []))
        total_spend = spend_info.get("total_spend", 0)

        start_sql = f"'{start_date}'" if start_date else "NULL"
        stop_sql = f"'{end_date}'" if end_date else "NULL"
        prima = f"'{months[0]}'" if months else "NULL"
        ultima = f"'{months[-1]}'" if months else "NULL"

        # MERGE — insert daca nu exista, update daca exista
        lines.append(
            f"MERGE dbo.PerioadeCompanii AS tgt "
            f"USING (SELECT '{cid}' AS CampaignID, '{sursa}' AS Sursa) AS src "
            f"ON tgt.CampaignID = src.CampaignID AND tgt.Sursa = src.Sursa "
            f"WHEN MATCHED THEN UPDATE SET "
            f"NumeCampanie = N'{name}', StatusCampanie = '{status}', "
            f"StartDate = {start_sql}, StopDate = {stop_sql}, "
            f"PrimaLunaSpend = {prima}, UltimaLunaSpend = {ultima}, "
            f"NrLuniSpend = {len(months)}, TotalSpend = {total_spend:.2f}, "
            f"DataActualizare = GETDATE() "
            f"WHEN NOT MATCHED THEN INSERT "
            f"(CampaignID, NumeCampanie, Sursa, StatusCampanie, StartDate, StopDate, "
            f"PrimaLunaSpend, UltimaLunaSpend, NrLuniSpend, TotalSpend) "
            f"VALUES ('{cid}', N'{name}', '{sursa}', '{status}', "
            f"{start_sql}, {stop_sql}, {prima}, {ultima}, {len(months)}, {total_spend:.2f});"
        )

        if sursa == "Google Ads":
            count_google += 1
        else:
            count_meta += 1

    lines.append("")
    lines.append(f"-- Total: {count_google} Google Ads + {count_meta} Meta Ads = {count_google + count_meta} campanii")
    lines.append(f"-- Ruleaza acest script in SSMS dupa ce tabelul dbo.PerioadeCompanii exista.")
    lines.append("")
    lines.append("-- Verificare rapida:")
    lines.append("SELECT Sursa, COUNT(*) AS Nr, SUM(TotalSpend) AS Spend")
    lines.append("FROM dbo.PerioadeCompanii GROUP BY Sursa")

    with open(str(output_path), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n[OK] SQL perioade generat: {output_path}")
    print(f"[OK] Google Ads: {count_google}, Meta Ads: {count_meta}")


# ========================================================================
# MAIN
# ========================================================================
def main():
    print("=" * 60)
    print("EXTRAGERE COSTURI CAMPANII - Google Ads + Meta Ads")
    print("=" * 60)

    config = ensure_config()
    data_start, data_end = get_date_range(config, sys.argv)

    # Extragere din platformele active
    extract_google = config.getboolean("settings", "extract_google", fallback=True)
    extract_meta = config.getboolean("settings", "extract_meta", fallback=False)

    all_results = []
    all_campaigns = []

    if extract_google:
        costs, campaigns = extract_google_ads(config, data_start, data_end)
        all_results += costs
        all_campaigns += campaigns
    else:
        print("[i] Google Ads: DEZACTIVAT (extract_google = false in config)")

    if extract_meta:
        costs, campaigns = extract_meta_ads(config, data_start, data_end)
        all_results += costs
        all_campaigns += campaigns
    else:
        print("[i] Meta Ads: DEZACTIVAT (extract_meta = false in config)")

    # Export costuri combinate (existent)
    write_csv(all_results, OUTPUT_CSV)

    # Export perioade campanii combinate (existent)
    write_campaigns_csv(all_campaigns, all_results, OUTPUT_CAMPAIGNS_CSV)
    write_campaigns_sql(all_campaigns, all_results, OUTPUT_CAMPAIGNS_SQL)

    # Export per-sursa (NOU) — pentru vizibilitate si trazare mai usoara
    google_results = [r for r in all_results if r.get("Sursa") == "Google Ads"]
    meta_results = [r for r in all_results if r.get("Sursa") == "Meta Ads"]
    google_campaigns = [c for c in all_campaigns if c.get("Sursa") == "Google Ads"]
    meta_campaigns = [c for c in all_campaigns if c.get("Sursa") == "Meta Ads"]
    if google_results:
        write_csv(google_results, OUTPUT_CSV_GOOGLE)
    if meta_results:
        write_csv(meta_results, OUTPUT_CSV_META)
    if google_campaigns:
        write_campaigns_csv(google_campaigns, google_results, OUTPUT_CAMPAIGNS_CSV_GOOGLE)
    if meta_campaigns:
        write_campaigns_csv(meta_campaigns, meta_results, OUTPUT_CAMPAIGNS_CSV_META)

    # Sumar pe sursa
    print("\n--- SUMAR ---")
    summary_per_source = {}
    for sursa in ["Google Ads", "Meta Ads"]:
        rows = [r for r in all_results if r["Sursa"] == sursa]
        camps = [c for c in all_campaigns if c["Sursa"] == sursa]
        total = sum(r["Cost_RON"] for r in rows)
        active = sum(1 for c in camps if c["Status"] in ("ENABLED", "ACTIVE", "PAUSED", "CAMPAIGN_PAUSED"))
        ended = len(camps) - active
        summary_per_source[sursa] = {
            "rows": len(rows),
            "spend_ron": round(total, 2),
            "campaigns_total": len(camps),
            "campaigns_active": active,
            "campaigns_ended": ended,
            "extracted": bool(rows or camps),
        }
        if rows or camps:
            print(f"  {sursa}: {len(rows)} campanii-luna, {total:,.2f} RON")
            print(f"    Campanii: {len(camps)} total ({active} active, {ended} incheiate)")

    # Summary JSON — folosit de orchestrator
    import json as _json
    from datetime import datetime as _dt
    summary_payload = {
        "timestamp": _dt.now().isoformat(timespec="seconds"),
        "interval": {"start": data_start, "end": data_end},
        "sources": summary_per_source,
        "outputs": {
            "combined_csv": str(OUTPUT_CSV),
            "combined_campaigns_csv": str(OUTPUT_CAMPAIGNS_CSV),
            "combined_sql": str(OUTPUT_CAMPAIGNS_SQL),
            "google_csv": str(OUTPUT_CSV_GOOGLE) if google_results else None,
            "meta_csv": str(OUTPUT_CSV_META) if meta_results else None,
            "google_campaigns_csv": str(OUTPUT_CAMPAIGNS_CSV_GOOGLE) if google_campaigns else None,
            "meta_campaigns_csv": str(OUTPUT_CAMPAIGNS_CSV_META) if meta_campaigns else None,
        },
    }
    try:
        with open(OUTPUT_SUMMARY_JSON, "w", encoding="utf-8") as _f:
            _json.dump(summary_payload, _f, ensure_ascii=False, indent=2)
    except Exception as _e:
        print(f"[!] Nu am putut scrie summary JSON: {_e}")

    print(f"\n  Output costuri (combinat):    {OUTPUT_CSV}")
    if google_results:
        print(f"  Output costuri Google:        {OUTPUT_CSV_GOOGLE}")
    if meta_results:
        print(f"  Output costuri Meta:          {OUTPUT_CSV_META}")
    print(f"  Output perioade (combinat):   {OUTPUT_CAMPAIGNS_CSV}")
    if google_campaigns:
        print(f"  Output perioade Google:       {OUTPUT_CAMPAIGNS_CSV_GOOGLE}")
    if meta_campaigns:
        print(f"  Output perioade Meta:         {OUTPUT_CAMPAIGNS_CSV_META}")
    print(f"  Output SQL:                   {OUTPUT_CAMPAIGNS_SQL}")
    print(f"  Summary JSON:                 {OUTPUT_SUMMARY_JSON}")


if __name__ == "__main__":
    main()
