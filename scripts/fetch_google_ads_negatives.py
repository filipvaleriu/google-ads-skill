"""
fetch_google_ads_negatives.py
------------------------------
Extrage din Google Ads API tot ce tine de negative keywords + un Search Terms
Report pe ultimele 90z, pentru a putea compara ce avem vs. ce ar trebui sa avem.

Scoate 4 fisiere in rezultate/:
  - negative_keywords_current.csv     - toate negative-urile curente
    (campaign-level + ad-group-level + shared-list-level)
  - shared_negative_lists.csv         - listele shared (names + attach status)
  - search_terms_90d.csv              - search terms report ultimele 90z
                                        sortat dupa cost desc
  - google_ads_negatives_summary.md   - interpretare, dedup, top missing

Usage:
    cd Analiza-Campanii
    python fetch_google_ads_negatives.py

Configurare: citeste din config/google_ads.ini (prin config_loader).
Foloseste google-ads Python SDK — instaleaza daca lipseste: pip install google-ads
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
OUT_DIR = SCRIPT_DIR / "rezultate"
OUT_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT))
from config_loader import load_google_ads, ConfigError  # noqa: E402


# ============================================================================
# Queries GAQL (Google Ads Query Language)
# ============================================================================
QUERY_CAMPAIGN_NEGATIVES = """
    SELECT
      campaign.id, campaign.name, campaign.status,
      campaign_criterion.negative,
      campaign_criterion.type,
      campaign_criterion.keyword.text,
      campaign_criterion.keyword.match_type
    FROM campaign_criterion
    WHERE campaign_criterion.negative = TRUE
      AND campaign_criterion.type = 'KEYWORD'
      AND campaign.status = 'ENABLED'
"""

QUERY_ADGROUP_NEGATIVES = """
    SELECT
      campaign.id, campaign.name,
      ad_group.id, ad_group.name, ad_group.status,
      ad_group_criterion.negative,
      ad_group_criterion.type,
      ad_group_criterion.keyword.text,
      ad_group_criterion.keyword.match_type
    FROM ad_group_criterion
    WHERE ad_group_criterion.negative = TRUE
      AND ad_group_criterion.type = 'KEYWORD'
      AND ad_group.status = 'ENABLED'
      AND campaign.status = 'ENABLED'
"""

# Shared negative keyword lists (shared_set of type NEGATIVE_KEYWORDS)
QUERY_SHARED_SETS = """
    SELECT
      shared_set.id, shared_set.name, shared_set.status, shared_set.type,
      shared_set.member_count, shared_set.reference_count
    FROM shared_set
    WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
"""

QUERY_SHARED_CRITERIA = """
    SELECT
      shared_set.id, shared_set.name,
      shared_criterion.type,
      shared_criterion.keyword.text,
      shared_criterion.keyword.match_type
    FROM shared_criterion
    WHERE shared_criterion.type = 'KEYWORD'
      AND shared_set.type = 'NEGATIVE_KEYWORDS'
"""

# Search Terms ultimele 90 zile. GAQL NU are LAST_90_DAYS predefinit ->
# construim range-ul dinamic cu BETWEEN (format YYYY-MM-DD).
def _search_terms_query(days_back: int = 90) -> str:
    from datetime import date, timedelta
    end_d = date.today()
    start_d = end_d - timedelta(days=days_back)
    return f"""
        SELECT
          campaign.id, campaign.name,
          ad_group.id, ad_group.name,
          search_term_view.search_term,
          search_term_view.status,
          metrics.clicks, metrics.impressions,
          metrics.cost_micros,
          metrics.conversions, metrics.conversions_value,
          metrics.ctr, metrics.average_cpc
        FROM search_term_view
        WHERE segments.date BETWEEN '{start_d.isoformat()}' AND '{end_d.isoformat()}'
          AND campaign.advertising_channel_type IN ('SEARCH', 'PERFORMANCE_MAX')
          AND metrics.impressions > 0
    """


# ============================================================================
# Client + helpers
# ============================================================================
def build_client():
    try:
        cfg = load_google_ads()
    except ConfigError as e:
        sys.exit(f"[EROARE CONFIG] {e}")

    g = cfg["google_ads"]
    customer_id = g.get("customer_id", "").replace('-', '').strip()
    if not customer_id:
        sys.exit("[EROARE] customer_id lipseste in config/google_ads.ini")

    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        sys.exit("[EROARE] google-ads nu e instalat. Ruleaza:\n  pip install google-ads")

    base = {
        "developer_token": g.get("developer_token"),
        "client_id": g.get("client_id"),
        "client_secret": g.get("client_secret"),
        "refresh_token": g.get("refresh_token"),
        "use_proto_plus": False,
    }
    login_customer_id = g.get("login_customer_id", "").replace('-', '').strip()
    if login_customer_id:
        base["login_customer_id"] = login_customer_id

    client = GoogleAdsClient.load_from_dict(base)
    return client, customer_id


def run_query(client, customer_id: str, query: str, label: str):
    """Ruleaza un GAQL query si returneaza lista de row obiecte."""
    print(f"[GAds] Query: {label}")
    svc = client.get_service("GoogleAdsService")
    rows = []
    try:
        stream = svc.search_stream(customer_id=customer_id, query=query)
        for batch in stream:
            for row in batch.results:
                rows.append(row)
    except Exception as e:
        print(f"  [WARN] {label}: {type(e).__name__}: {str(e)[:200]}")
        return []
    print(f"  -> {len(rows)} rows")
    return rows


# ============================================================================
# Extractors (row -> dict plat)
# ============================================================================
def ext_campaign_neg(r):
    return {
        "level": "campaign",
        "campaign_id": r.campaign.id,
        "campaign_name": r.campaign.name,
        "ad_group_id": "",
        "ad_group_name": "",
        "keyword": r.campaign_criterion.keyword.text,
        "match_type": str(r.campaign_criterion.keyword.match_type).split('.')[-1],
    }


def ext_adgroup_neg(r):
    return {
        "level": "ad_group",
        "campaign_id": r.campaign.id,
        "campaign_name": r.campaign.name,
        "ad_group_id": r.ad_group.id,
        "ad_group_name": r.ad_group.name,
        "keyword": r.ad_group_criterion.keyword.text,
        "match_type": str(r.ad_group_criterion.keyword.match_type).split('.')[-1],
    }


def ext_shared_neg(r):
    return {
        "level": "shared_list",
        "campaign_id": "",
        "campaign_name": f"[LIST] {r.shared_set.name}",
        "ad_group_id": r.shared_set.id,
        "ad_group_name": r.shared_set.name,
        "keyword": r.shared_criterion.keyword.text,
        "match_type": str(r.shared_criterion.keyword.match_type).split('.')[-1],
    }


def ext_search_term(r):
    cost = r.metrics.cost_micros / 1_000_000 if r.metrics.cost_micros else 0
    return {
        "campaign_id": r.campaign.id,
        "campaign_name": r.campaign.name,
        "ad_group_id": r.ad_group.id,
        "ad_group_name": r.ad_group.name,
        "search_term": r.search_term_view.search_term,
        "status": str(r.search_term_view.status).split('.')[-1],
        "impressions": r.metrics.impressions,
        "clicks": r.metrics.clicks,
        "cost_ron": round(cost, 2),
        "ctr_pct": round(r.metrics.ctr * 100, 2) if r.metrics.ctr else 0,
        "avg_cpc_ron": round(r.metrics.average_cpc / 1_000_000, 2) if r.metrics.average_cpc else 0,
        "conversions": round(r.metrics.conversions, 2),
        "conv_value_ron": round(r.metrics.conversions_value, 2),
    }


def write_csv(path: Path, rows: list, fields: list):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  [OUT] {path.name} ({len(rows)} rows)")


# ============================================================================
# Analiza & markdown summary
# ============================================================================
# Listele mele propuse (din tab Iteratii & Livrabile / discutie 2026-04-15)
PROPOSED_NEGATIVES = {
    "NAV - FGO brand": [
        "fgo login", "fgo conectare", "fgo platforma", "fgo app",
        "fgo contact", "fgo parola", "fgo cont", "fgo client",
    ],
    "NAV - ANAF/SPV": [
        "spv", "spv anaf", "anaf spv login", "mesaje spv",
        "efactura spv", "anaf contact", "anaf program",
        "anaf telefon", "anaf login", "contul meu anaf",
    ],
    "NAV - Competitor logins": [
        "smartbill login", "smartbill conectare", "smartbill cont",
        "oblio login", "oblio conectare", "oblio cont",
        "saga c login", "ciel login", "necta login",
    ],
    "INFORMATIONAL - educational gratuit": [
        "ce este efactura", "cum se face declaratie 394",
        "efactura obligatie cand", "anaf termene",
        "cod caen", "cum platesc impozit",
    ],
    "COMMERCIAL EXCLUSION - gratis/crack": [
        "facturare gratis", "software facturare free download",
        "crack smartbill", "serial number", "keygen",
        "torrent", "nulled",
    ],
    "INTENT GRESIT - jobs": [
        "contabil angajare", "job contabilitate", "salariu contabil",
        "curs contabilitate", "angajare contabilitate",
    ],
}


def summarize_md(all_negs, search_terms, shared_sets, out_path: Path):
    # Dedup set de cuvinte negative curente (case-insensitive, trimmed)
    current_set = set()
    for n in all_negs:
        k = (n.get("keyword") or "").strip().lower()
        if k:
            current_set.add(k)

    # Flatten propose list
    proposed_flat = {}
    for list_name, kws in PROPOSED_NEGATIVES.items():
        for k in kws:
            proposed_flat[k.lower()] = list_name

    missing = [(k, proposed_flat[k]) for k in proposed_flat if k not in current_set]
    covered = [(k, proposed_flat[k]) for k in proposed_flat if k in current_set]

    # Top search terms by cost (top 50), flag intent
    def intent_flag(term: str) -> str:
        t = term.lower()
        red_flags = [
            ("fgo", ["login", "conectare", "cont", "parola", "platforma", "aplicatie"]),
            ("anaf", []), ("spv", []),
            ("smartbill", ["login", "conectare"]),
            ("oblio", ["login", "conectare"]),
            ("gratis", []), ("free", []), ("crack", []), ("torrent", []),
            ("job", []), ("angajare", []), ("salariu", []), ("curs", []),
        ]
        for base, required_any in red_flags:
            if base in t:
                if not required_any or any(r in t for r in required_any):
                    return "🔴"
        # Neutral commercial keywords
        green_flags = ["program facturare", "software contabilitate", "aplicatie facturare",
                       "efactura firme", "soft contabilitate", "factura online"]
        if any(g in t for g in green_flags):
            return "🟢"
        return "⚪"

    top_terms = sorted(search_terms, key=lambda x: x.get("cost_ron", 0), reverse=True)[:50]

    lines = []
    lines.append(f"# Google Ads — Audit Negative Keywords")
    lines.append(f"")
    lines.append(f"**Generat:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Account:** vezi `google_ads.ini` / customer_id")
    lines.append(f"")
    lines.append(f"## Rezumat")
    lines.append(f"")
    lines.append(f"- Negative keywords active (campaign + ad_group + shared): **{len(all_negs)}**")
    lines.append(f"- Distincte (case-insensitive): **{len(current_set)}**")
    lines.append(f"- Shared negative lists: **{len(shared_sets)}**")
    lines.append(f"- Search terms ultimele 90z: **{len(search_terms)}**")
    lines.append(f"")
    lines.append(f"## Shared Negative Lists")
    lines.append(f"")
    if shared_sets:
        lines.append("| Nume listă | # keywords | # campaigns atașate |")
        lines.append("|---|---|---|")
        for s in shared_sets:
            lines.append(f"| {s.get('name')} | {s.get('member_count', '?')} | {s.get('reference_count', '?')} |")
    else:
        lines.append("_Nicio listă shared găsită_")
    lines.append(f"")
    lines.append(f"## Comparație: propus vs. curent")
    lines.append(f"")
    lines.append(f"### 🔴 Lipsă — de adăugat ({len(missing)} keywords)")
    lines.append(f"")
    if missing:
        lines.append("| Keyword propus | Listă recomandată |")
        lines.append("|---|---|")
        for k, l in sorted(missing, key=lambda x: (x[1], x[0])):
            lines.append(f"| `{k}` | {l} |")
    else:
        lines.append("_Toate keyword-urile propuse sunt deja acoperite ✅_")
    lines.append(f"")
    lines.append(f"### ✅ Deja acoperite ({len(covered)} keywords)")
    lines.append(f"")
    if covered:
        for k, l in sorted(covered, key=lambda x: (x[1], x[0])):
            lines.append(f"- `{k}` — {l}")
    lines.append(f"")
    lines.append(f"## Top 50 Search Terms (cost desc, ultimele 90z)")
    lines.append(f"")
    lines.append(f"Intent flag: 🔴 = candidat negative · 🟢 = keep · ⚪ = review manual")
    lines.append(f"")
    lines.append("| Flag | Search term | Cost RON | Clicks | Conv | Campaign |")
    lines.append("|---|---|---:|---:|---:|---|")
    for t in top_terms:
        term = t.get("search_term", "")
        flag = intent_flag(term)
        lines.append(f"| {flag} | `{term[:60]}` | {t.get('cost_ron', 0):.2f} | {t.get('clicks', 0)} | {t.get('conversions', 0):.1f} | {t.get('campaign_name', '')[:40]} |")
    lines.append(f"")
    lines.append(f"## Acțiuni recomandate")
    lines.append(f"")
    lines.append(f"1. **Adaugă cele {len(missing)} keyword-uri lipsă** în shared lists sau campaign-level negatives.")
    lines.append(f"2. **Review 🔴 în top 50 search terms** — cele cu cost mare & 0 conversii = candidat imediat.")
    lines.append(f"3. **Consolidare:** dacă ai >2-3 shared lists cu overlap, combină-le în 1 listă master.")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [OUT] {out_path.name}")


# ============================================================================
# Main
# ============================================================================
def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Start fetch_google_ads_negatives.py")
    client, customer_id = build_client()
    print(f"[GAds] customer_id={customer_id}")

    camp_rows = run_query(client, customer_id, QUERY_CAMPAIGN_NEGATIVES, "campaign negatives")
    ag_rows = run_query(client, customer_id, QUERY_ADGROUP_NEGATIVES, "ad_group negatives")
    shared_rows = run_query(client, customer_id, QUERY_SHARED_CRITERIA, "shared negative criteria")
    shared_sets_rows = run_query(client, customer_id, QUERY_SHARED_SETS, "shared sets (lists)")
    st_rows = run_query(client, customer_id, _search_terms_query(90), "search terms 90d")

    # Extract
    all_negs = (
        [ext_campaign_neg(r) for r in camp_rows]
        + [ext_adgroup_neg(r) for r in ag_rows]
        + [ext_shared_neg(r) for r in shared_rows]
    )
    search_terms = [ext_search_term(r) for r in st_rows]
    search_terms.sort(key=lambda x: x["cost_ron"], reverse=True)

    def _safe_type(obj):
        # SDK cu use_proto_plus=False expune 'type' ca 'type_' (cuv rezervat)
        v = getattr(obj, 'type_', None)
        if v is None:
            v = getattr(obj, 'type', None)
        return str(v).split('.')[-1] if v is not None else ""

    shared_sets = [{
        "id": r.shared_set.id,
        "name": r.shared_set.name,
        "status": str(r.shared_set.status).split('.')[-1],
        "type": _safe_type(r.shared_set),
        "member_count": r.shared_set.member_count,
        "reference_count": r.shared_set.reference_count,
    } for r in shared_sets_rows]

    # Write CSVs
    write_csv(
        OUT_DIR / "negative_keywords_current.csv",
        all_negs,
        ["level", "campaign_id", "campaign_name", "ad_group_id", "ad_group_name", "keyword", "match_type"],
    )
    write_csv(
        OUT_DIR / "shared_negative_lists.csv",
        shared_sets,
        ["id", "name", "status", "type", "member_count", "reference_count"],
    )
    write_csv(
        OUT_DIR / "search_terms_90d.csv",
        search_terms,
        ["campaign_name", "ad_group_name", "search_term", "status",
         "impressions", "clicks", "cost_ron", "ctr_pct", "avg_cpc_ron",
         "conversions", "conv_value_ron", "campaign_id", "ad_group_id"],
    )

    # Markdown summary
    summarize_md(all_negs, search_terms, shared_sets, OUT_DIR / "google_ads_negatives_summary.md")

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Done. Output in {OUT_DIR}")


if __name__ == "__main__":
    main()
