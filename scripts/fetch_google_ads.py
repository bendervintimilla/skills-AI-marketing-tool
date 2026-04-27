#!/usr/bin/env python3
"""
fetch_google_ads.py — Google Ads API data fetcher for claude-ads audit pipeline.

Pulls campaigns, ad groups, ads, keywords, search terms, and conversion actions
via the Google Ads API (GAQL) and outputs a structured JSON snapshot.

SETUP (one-time):
  1. Developer token: apply at https://developers.google.com/google-ads/api/docs/get-started/dev-token
     → Set: export GOOGLE_ADS_DEVELOPER_TOKEN="your-developer-token"

  2. OAuth2 credentials: create a Desktop app credential in Google Cloud Console
     → https://console.cloud.google.com → APIs & Services → Credentials
     → Set: export GOOGLE_ADS_CLIENT_ID="your-client-id"
     → Set: export GOOGLE_ADS_CLIENT_SECRET="your-client-secret"
     → Set: export GOOGLE_ADS_REFRESH_TOKEN="your-refresh-token"
     → Generate refresh token: python3 ~/.claude/skills/ads/scripts/fetch_google_ads.py --auth

  3. Customer ID (no dashes):
     → Set: export GOOGLE_ADS_CUSTOMER_ID="1234567890"
     → Or pass: --customer-id 1234567890

  4. Install dependency: pip install google-ads>=22.0.0,<25.0.0

Usage:
  python3 fetch_google_ads.py --output google-snapshot.json
  python3 fetch_google_ads.py --output google-snapshot.json --days 30
  python3 fetch_google_ads.py --auth   # OAuth2 refresh token generator
  python3 fetch_google_ads.py --check  # Validate credentials without fetching

Output: google-snapshot.json
  {
    "fetched_at": "2026-04-23T...",
    "customer_id": "...",
    "account": { name, currency, timezone, descriptive_name },
    "campaigns": [ { id, name, status, budget_amount_micros, campaign_type, ... } ],
    "ad_groups": [ { id, name, status, campaign_id, cpc_bid_micros, ... } ],
    "ads": [ { id, type, status, ad_group_id, headlines, descriptions, ... } ],
    "keywords": [ { id, text, match_type, status, ad_group_id, quality_score, ... } ],
    "search_terms": [ { search_term, clicks, impressions, cost_micros, conversions, ... } ],
    "conversion_actions": [ { id, name, category, status, ... } ],
    "insights": { spend_30d, clicks_30d, impressions_30d, conversions_30d, ctr, avg_cpc, roas }
  }
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta


def check_credentials() -> dict:
    required = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
    ]
    creds = {}
    missing = []
    for key in required:
        val = os.environ.get(key)
        if val:
            creds[key] = val
        else:
            missing.append(key)
    return creds, missing


def build_client(creds: dict):
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        print("ERROR: google-ads not installed. Run: pip install 'google-ads>=22.0.0,<25.0.0'")
        sys.exit(2)

    config = {
        "developer_token": creds["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": creds["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": creds["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": creds["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(config)


def run_gaql(client, customer_id: str, query: str) -> list:
    service = client.get_service("GoogleAdsService")
    stream = service.search_stream(customer_id=customer_id, query=query)
    rows = []
    for batch in stream:
        for row in batch.results:
            rows.append(row)
    return rows


def fetch_account(client, customer_id: str) -> dict:
    rows = run_gaql(client, customer_id, """
        SELECT
          customer.id,
          customer.descriptive_name,
          customer.currency_code,
          customer.time_zone
        FROM customer
        LIMIT 1
    """)
    if not rows:
        return {}
    r = rows[0]
    return {
        "id": str(r.customer.id),
        "descriptive_name": r.customer.descriptive_name,
        "currency_code": r.customer.currency_code,
        "time_zone": r.customer.time_zone,
    }


def fetch_campaigns(client, customer_id: str, days: int) -> list:
    date_from = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = datetime.today().strftime("%Y-%m-%d")
    rows = run_gaql(client, customer_id, f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          campaign.bidding_strategy_type,
          campaign_budget.amount_micros,
          campaign_budget.has_recommended_budget,
          metrics.clicks,
          metrics.impressions,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.ctr,
          metrics.average_cpc
        FROM campaign
        WHERE campaign.status != 'REMOVED'
          AND segments.date BETWEEN '{date_from}' AND '{date_to}'
    """)

    campaigns = {}
    for r in rows:
        cid = str(r.campaign.id)
        if cid not in campaigns:
            campaigns[cid] = {
                "id": cid,
                "name": r.campaign.name,
                "status": r.campaign.status.name,
                "type": r.campaign.advertising_channel_type.name,
                "bidding_strategy": r.campaign.bidding_strategy_type.name,
                "budget_amount_micros": r.campaign_budget.amount_micros,
                "has_recommended_budget": r.campaign_budget.has_recommended_budget,
                "clicks": 0, "impressions": 0, "cost_micros": 0,
                "conversions": 0.0, "conversions_value": 0.0,
            }
        c = campaigns[cid]
        c["clicks"] += r.metrics.clicks
        c["impressions"] += r.metrics.impressions
        c["cost_micros"] += r.metrics.cost_micros
        c["conversions"] += r.metrics.conversions
        c["conversions_value"] += r.metrics.conversions_value

    for c in campaigns.values():
        c["ctr"] = round(c["clicks"] / c["impressions"], 4) if c["impressions"] else 0
        c["avg_cpc_micros"] = round(c["cost_micros"] / c["clicks"]) if c["clicks"] else 0
        c["roas"] = round(c["conversions_value"] / (c["cost_micros"] / 1_000_000), 2) \
            if c["cost_micros"] else 0

    return list(campaigns.values())


def fetch_ad_groups(client, customer_id: str) -> list:
    rows = run_gaql(client, customer_id, """
        SELECT
          ad_group.id,
          ad_group.name,
          ad_group.status,
          ad_group.type,
          campaign.id,
          campaign.name,
          ad_group.cpc_bid_micros,
          ad_group.target_cpa_micros,
          ad_group.target_roas
        FROM ad_group
        WHERE ad_group.status != 'REMOVED'
          AND campaign.status != 'REMOVED'
    """)
    return [{
        "id": str(r.ad_group.id),
        "name": r.ad_group.name,
        "status": r.ad_group.status.name,
        "type": r.ad_group.type_.name,
        "campaign_id": str(r.campaign.id),
        "campaign_name": r.campaign.name,
        "cpc_bid_micros": r.ad_group.cpc_bid_micros,
        "target_cpa_micros": r.ad_group.target_cpa_micros,
        "target_roas": r.ad_group.target_roas,
    } for r in rows]


def fetch_ads(client, customer_id: str, days: int) -> list:
    date_from = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = datetime.today().strftime("%Y-%m-%d")
    rows = run_gaql(client, customer_id, f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.ad.type,
          ad_group_ad.status,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group_ad.ad.final_urls,
          ad_group_ad.ad_strength,
          ad_group.id,
          campaign.id,
          metrics.clicks,
          metrics.impressions,
          metrics.cost_micros,
          metrics.ctr
        FROM ad_group_ad
        WHERE ad_group_ad.status != 'REMOVED'
          AND campaign.status != 'REMOVED'
          AND segments.date BETWEEN '{date_from}' AND '{date_to}'
    """)

    ads = {}
    for r in rows:
        aid = str(r.ad_group_ad.ad.id)
        if aid not in ads:
            rsa = r.ad_group_ad.ad.responsive_search_ad
            headlines = [h.text for h in rsa.headlines] if rsa else []
            descriptions = [d.text for d in rsa.descriptions] if rsa else []
            ads[aid] = {
                "id": aid,
                "type": r.ad_group_ad.ad.type_.name,
                "status": r.ad_group_ad.status.name,
                "ad_group_id": str(r.ad_group.id),
                "campaign_id": str(r.campaign.id),
                "headlines": headlines,
                "descriptions": descriptions,
                "final_urls": list(r.ad_group_ad.ad.final_urls),
                "ad_strength": r.ad_group_ad.ad_strength.name,
                "clicks": 0, "impressions": 0, "cost_micros": 0,
            }
        a = ads[aid]
        a["clicks"] += r.metrics.clicks
        a["impressions"] += r.metrics.impressions
        a["cost_micros"] += r.metrics.cost_micros

    for a in ads.values():
        a["ctr"] = round(a["clicks"] / a["impressions"], 4) if a["impressions"] else 0
        a["unique_headlines"] = len(set(a["headlines"]))
        a["unique_descriptions"] = len(set(a["descriptions"]))

    return list(ads.values())


def fetch_keywords(client, customer_id: str, days: int) -> list:
    date_from = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = datetime.today().strftime("%Y-%m-%d")
    rows = run_gaql(client, customer_id, f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group_criterion.quality_info.quality_score,
          ad_group_criterion.quality_info.creative_quality_score,
          ad_group_criterion.quality_info.post_click_quality_score,
          ad_group_criterion.quality_info.search_predicted_ctr,
          ad_group.id,
          campaign.id,
          metrics.clicks,
          metrics.impressions,
          metrics.cost_micros,
          metrics.conversions,
          metrics.average_cpc
        FROM keyword_view
        WHERE ad_group_criterion.status != 'REMOVED'
          AND campaign.status != 'REMOVED'
          AND segments.date BETWEEN '{date_from}' AND '{date_to}'
    """)

    keywords = {}
    for r in rows:
        kid = f"{r.ad_group.id}_{r.ad_group_criterion.criterion_id}"
        if kid not in keywords:
            qi = r.ad_group_criterion.quality_info
            keywords[kid] = {
                "id": kid,
                "text": r.ad_group_criterion.keyword.text,
                "match_type": r.ad_group_criterion.keyword.match_type.name,
                "status": r.ad_group_criterion.status.name,
                "ad_group_id": str(r.ad_group.id),
                "campaign_id": str(r.campaign.id),
                "quality_score": qi.quality_score,
                "creative_quality": qi.creative_quality_score.name,
                "landing_page_quality": qi.post_click_quality_score.name,
                "expected_ctr": qi.search_predicted_ctr.name,
                "clicks": 0, "impressions": 0,
                "cost_micros": 0, "conversions": 0.0,
            }
        k = keywords[kid]
        k["clicks"] += r.metrics.clicks
        k["impressions"] += r.metrics.impressions
        k["cost_micros"] += r.metrics.cost_micros
        k["conversions"] += r.metrics.conversions

    for k in keywords.values():
        k["ctr"] = round(k["clicks"] / k["impressions"], 4) if k["impressions"] else 0
        k["avg_cpc_micros"] = round(k["cost_micros"] / k["clicks"]) if k["clicks"] else 0
        k["cpa_micros"] = round(k["cost_micros"] / k["conversions"]) if k["conversions"] else None

    return list(keywords.values())


def fetch_search_terms(client, customer_id: str, days: int, min_spend_micros: int = 500_000) -> list:
    """Fetch top search terms by spend (default: ≥$0.50 spend to limit output size)."""
    date_from = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = datetime.today().strftime("%Y-%m-%d")
    rows = run_gaql(client, customer_id, f"""
        SELECT
          search_term_view.search_term,
          search_term_view.status,
          campaign.id,
          campaign.name,
          ad_group.id,
          metrics.clicks,
          metrics.impressions,
          metrics.cost_micros,
          metrics.conversions,
          metrics.ctr
        FROM search_term_view
        WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
          AND metrics.cost_micros >= {min_spend_micros}
        ORDER BY metrics.cost_micros DESC
        LIMIT 1000
    """)
    return [{
        "search_term": r.search_term_view.search_term,
        "status": r.search_term_view.status.name,
        "campaign_id": str(r.campaign.id),
        "campaign_name": r.campaign.name,
        "ad_group_id": str(r.ad_group.id),
        "clicks": r.metrics.clicks,
        "impressions": r.metrics.impressions,
        "cost_micros": r.metrics.cost_micros,
        "conversions": r.metrics.conversions,
        "ctr": round(r.metrics.ctr, 4),
    } for r in rows]


def fetch_conversion_actions(client, customer_id: str) -> list:
    rows = run_gaql(client, customer_id, """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.category,
          conversion_action.status,
          conversion_action.type,
          conversion_action.counting_type,
          conversion_action.tag_snippets
        FROM conversion_action
        WHERE conversion_action.status != 'REMOVED'
    """)
    return [{
        "id": str(r.conversion_action.id),
        "name": r.conversion_action.name,
        "category": r.conversion_action.category.name,
        "status": r.conversion_action.status.name,
        "type": r.conversion_action.type_.name,
        "counting_type": r.conversion_action.counting_type.name,
        "has_tag": len(r.conversion_action.tag_snippets) > 0,
    } for r in rows]


def compute_insights(campaigns: list) -> dict:
    spend_micros = sum(c["cost_micros"] for c in campaigns)
    clicks = sum(c["clicks"] for c in campaigns)
    impressions = sum(c["impressions"] for c in campaigns)
    conversions = sum(c["conversions"] for c in campaigns)
    conv_value = sum(c["conversions_value"] for c in campaigns)

    return {
        "spend_usd": round(spend_micros / 1_000_000, 2),
        "clicks": clicks,
        "impressions": impressions,
        "conversions": round(conversions, 1),
        "conversions_value_usd": round(conv_value, 2),
        "ctr": round(clicks / impressions, 4) if impressions else 0,
        "avg_cpc_usd": round((spend_micros / 1_000_000) / clicks, 2) if clicks else 0,
        "cpa_usd": round((spend_micros / 1_000_000) / conversions, 2) if conversions else None,
        "roas": round(conv_value / (spend_micros / 1_000_000), 2) if spend_micros else None,
        "campaign_count": len(campaigns),
        "active_campaign_count": sum(1 for c in campaigns if c["status"] == "ENABLED"),
    }


def run_auth_flow():
    """Generate OAuth2 refresh token via browser flow."""
    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: Set GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET first.")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: Install google-auth-oauthlib: pip install google-auth-oauthlib")
        sys.exit(2)

    scopes = ["https://www.googleapis.com/auth/adwords"]
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
    credentials = flow.run_local_server(port=0)

    print("\n✓ Authentication successful!")
    print(f"\nAdd to your shell profile:")
    print(f'  export GOOGLE_ADS_REFRESH_TOKEN="{credentials.refresh_token}"')


def main():
    parser = argparse.ArgumentParser(description="Fetch Google Ads account data for claude-ads audit")
    parser.add_argument("--output", default="google-snapshot.json", help="Output JSON file")
    parser.add_argument("--days", type=int, default=30, help="Days of data to fetch (default: 30)")
    parser.add_argument("--customer-id", help="Google Ads customer ID (overrides env var)")
    parser.add_argument("--auth", action="store_true", help="Run OAuth2 refresh token flow")
    parser.add_argument("--check", action="store_true", help="Validate credentials only")
    args = parser.parse_args()

    if args.auth:
        run_auth_flow()
        return

    creds, missing = check_credentials()

    if args.check:
        if missing:
            print(f"MISSING: {', '.join(missing)}")
            sys.exit(1)
        print("✓ All credentials set")
        print(f"  Customer ID: {creds['GOOGLE_ADS_CUSTOMER_ID']}")
        return

    if missing:
        print(f"ERROR: Missing credentials: {', '.join(missing)}")
        print("\nSetup instructions:")
        print("  1. Developer token: https://developers.google.com/google-ads/api/docs/get-started/dev-token")
        print("  2. OAuth credentials: https://console.cloud.google.com")
        print("  3. Run auth flow: python3 fetch_google_ads.py --auth")
        print("  4. Customer ID: find in Google Ads → Admin → Account access")
        sys.exit(1)

    customer_id = args.customer_id or creds["GOOGLE_ADS_CUSTOMER_ID"]
    customer_id = customer_id.replace("-", "")

    print(f"↓ Connecting to Google Ads (customer: {customer_id})...")
    client = build_client(creds)

    print("↓ Fetching account info...")
    account = fetch_account(client, customer_id)

    print(f"↓ Fetching campaigns (last {args.days} days)...")
    campaigns = fetch_campaigns(client, customer_id, args.days)
    print(f"  → {len(campaigns)} campaigns")

    print("↓ Fetching ad groups...")
    ad_groups = fetch_ad_groups(client, customer_id)
    print(f"  → {len(ad_groups)} ad groups")

    print(f"↓ Fetching ads (last {args.days} days)...")
    ads = fetch_ads(client, customer_id, args.days)
    print(f"  → {len(ads)} ads")

    print(f"↓ Fetching keywords (last {args.days} days)...")
    keywords = fetch_keywords(client, customer_id, args.days)
    print(f"  → {len(keywords)} keywords")

    print(f"↓ Fetching search terms (last {args.days} days, ≥$0.50 spend)...")
    search_terms = fetch_search_terms(client, customer_id, args.days)
    print(f"  → {len(search_terms)} search terms")

    print("↓ Fetching conversion actions...")
    conversion_actions = fetch_conversion_actions(client, customer_id)
    print(f"  → {len(conversion_actions)} conversion actions")

    insights = compute_insights(campaigns)

    snapshot = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "days_window": args.days,
        "customer_id": customer_id,
        "account": account,
        "insights": insights,
        "campaigns": campaigns,
        "ad_groups": ad_groups,
        "ads": ads,
        "keywords": keywords,
        "search_terms": search_terms,
        "conversion_actions": conversion_actions,
    }

    with open(args.output, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"\n✓ Saved: {args.output}")
    print(f"\n  Account:     {account.get('descriptive_name', 'unknown')}")
    print(f"  Spend:       ${insights['spend_usd']:,.2f} (last {args.days}d)")
    print(f"  Campaigns:   {insights['campaign_count']} total, {insights['active_campaign_count']} active")
    print(f"  Clicks:      {insights['clicks']:,}")
    print(f"  Conversions: {insights['conversions']}")
    roas = insights.get("roas")
    print(f"  ROAS:        {roas:.2f}x" if roas else "  ROAS:        no conv tracking")
    print(f"\nRun: /ads google (in Claude Code) to analyze this data")


if __name__ == "__main__":
    main()
