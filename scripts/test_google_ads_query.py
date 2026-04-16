"""
test_google_ads_query.py
------------------------
Diagnostic: incearca o interogare reala SearchStream pe account, cu
trei variante pentru login_customer_id si raporteaza care merge.

Ruleaza:
    python test_google_ads_query.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_google_ads, ConfigError  # noqa: E402


def try_variant(label: str, google_config: dict, customer_id: str) -> bool:
    print(f"\n--- Varianta: {label} ---")
    print(f"    customer_id={customer_id}, login_customer_id={google_config.get('login_customer_id', '(gol)')}")
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        print("    [!] google-ads nu e instalat: pip install google-ads")
        return False
    try:
        client = GoogleAdsClient.load_from_dict(google_config)
        svc = client.get_service("GoogleAdsService")
        query = """
            SELECT customer.id, customer.descriptive_name
            FROM customer
            LIMIT 1
        """
        stream = svc.search_stream(customer_id=customer_id, query=query)
        for batch in stream:
            for row in batch.results:
                print(f"    [OK] customer.id={row.customer.id} name={row.customer.descriptive_name}")
        return True
    except Exception as e:
        msg = str(e)
        head = msg.split('\n', 1)[0][:200]
        print(f"    [FAIL] {type(e).__name__}: {head}")
        return False


def main():
    try:
        cfg = load_google_ads()
    except ConfigError as e:
        print(e)
        return 1

    g = cfg["google_ads"]
    customer_id = g.get("customer_id", "").replace('-', '').strip()
    other_id = "1621381358" if customer_id == "2338940880" else "2338940880"

    base = {
        "developer_token": g.get("developer_token"),
        "client_id": g.get("client_id"),
        "client_secret": g.get("client_secret"),
        "refresh_token": g.get("refresh_token"),
        "use_proto_plus": False,
    }

    # B: fara login_customer_id
    b_cfg = dict(base)
    ok_b = try_variant("B (fara login_customer_id)", b_cfg, customer_id)

    # A: swap - customer_id=other, login_customer_id=current customer_id
    a_cfg = dict(base)
    a_cfg["login_customer_id"] = customer_id
    ok_a = try_variant(f"A (customer_id={other_id}, login={customer_id})", a_cfg, other_id)

    # C: varianta originala (login=other, customer=current)
    c_cfg = dict(base)
    c_cfg["login_customer_id"] = other_id
    ok_c = try_variant(f"C (customer_id={customer_id}, login={other_id}) = config initial", c_cfg, customer_id)

    print("\n=== Rezumat ===")
    print(f"  B (fara login): {'OK' if ok_b else 'FAIL'}")
    print(f"  A (swap):       {'OK' if ok_a else 'FAIL'}")
    print(f"  C (initial):    {'OK' if ok_c else 'FAIL'}")
    print("\nFoloseste combinatia care afiseaza [OK] in config/google_ads.ini.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
