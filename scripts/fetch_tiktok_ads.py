#!/usr/bin/env python3
"""
fetch_tiktok_ads.py — TikTok Ads API data fetcher for claude-ads audit pipeline.

Pulls campaigns, ad groups, ads, creative performance, and pixel events
via the TikTok Marketing API and outputs a structured JSON snapshot.

SETUP (one-time):
  1. Create a TikTok for Business developer app:
     → https://business-api.tiktok.com/portal/apps → Create App
     → Enable: Ads Management, Reporting, Audience Management
     → Set: export TIKTOK_APP_ID="your-app-id"
     → Set: export TIKTOK_APP_SECRET="your-app-secret"

  2. Generate access token (long-lived, valid 1 year):
     → https://business-api.tiktok.com/portal/auth → OAuth2 flow
     → Or: python3 fetch_tiktok_ads.py --auth
     → Set: export TIKTOK_ACCESS_TOKEN="your-access-token"

  3. Advertiser ID (found in TikTok Ads Manager URL):
     → https://ads.tiktok.com/i18n/dashboard → check URL bar: advertiser_id=XXXXX
     → Set: export TIKTOK_ADVERTISER_ID="your-advertiser-id"
     → Or pass: --advertiser-id XXXXX

  4. Install dependency: pip install requests

Usage:
  python3 fetch_tiktok_ads.py --output tiktok-snapshot.json
  python3 fetch_tiktok_ads.py --output tiktok-snapshot.json --days 30
  python3 fetch_tiktok_ads.py --auth     # OAuth2 token generator
  python3 fetch_tiktok_ads.py --check    # Validate credentials

Output: tiktok-snapshot.json
  {
    "fetched_at": "...",
    "advertiser_id": "...",
    "account": { name, currency, timezone, status },
    "campaigns": [ { id, name, status, objective, budget, spend, ... } ],
    "ad_groups": [ { id, name, status, campaign_id, budget, placements, ... } ],
    "ads": [ { id, name, status, ad_group_id, video_id, creative_type, ... } ],
    "creative_performance": [ { ad_id, impressions, clicks, ctr, video_play_actions, ... } ],
    "insights": { spend, impressions, clicks, conversions, ctr, cpm, cpa, roas }
  }
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"


def check_credentials() -> tuple[dict, list]:
    required = [
        "TIKTOK_ACCESS_TOKEN",
        "TIKTOK_ADVERTISER_ID",
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


def api_get(endpoint: str, token: str, params: dict) -> dict:
    import requests
    headers = {"Access-Token": token, "Content-Type": "application/json"}
    resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"TikTok API error {data.get('code')}: {data.get('message')}")
    return data.get("data", {})


def api_post(endpoint: str, token: str, payload: dict) -> dict:
    import requests
    headers = {"Access-Token": token, "Content-Type": "application/json"}
    resp = requests.post(f"{BASE_URL}{endpoint}", headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"TikTok API error {data.get('code')}: {data.get('message')}")
    return data.get("data", {})


def fetch_account(token: str, advertiser_id: str) -> dict:
    data = api_get("/advertiser/info/", token, {
        "advertiser_ids": json.dumps([advertiser_id]),
        "fields": json.dumps(["name", "currency", "timezone", "status", "country"])
    })
    accounts = data.get("list", [])
    if not accounts:
        return {}
    a = accounts[0]
    return {
        "id": advertiser_id,
        "name": a.get("name"),
        "currency": a.get("currency"),
        "timezone": a.get("timezone"),
        "status": a.get("status"),
        "country": a.get("country"),
    }


def fetch_campaigns(token: str, advertiser_id: str) -> list:
    data = api_get("/campaign/get/", token, {
        "advertiser_id": advertiser_id,
        "fields": json.dumps([
            "campaign_id", "campaign_name", "status", "objective_type",
            "budget", "budget_mode", "is_smart_performance_campaign",
            "campaign_type", "create_time", "modify_time"
        ]),
        "page_size": 100,
    })
    campaigns = []
    for c in data.get("list", []):
        campaigns.append({
            "id": c.get("campaign_id"),
            "name": c.get("campaign_name"),
            "status": c.get("status"),
            "objective": c.get("objective_type"),
            "budget": c.get("budget"),
            "budget_mode": c.get("budget_mode"),
            "is_smart_performance": c.get("is_smart_performance_campaign", False),
            "type": c.get("campaign_type"),
        })
    return campaigns


def fetch_ad_groups(token: str, advertiser_id: str) -> list:
    data = api_get("/adgroup/get/", token, {
        "advertiser_id": advertiser_id,
        "fields": json.dumps([
            "adgroup_id", "adgroup_name", "campaign_id", "status",
            "budget", "budget_mode", "bid_price", "bid_type",
            "placements", "targeting", "optimization_goal",
            "bid_display_mode", "conversion_bid_price", "roas_bid"
        ]),
        "page_size": 100,
    })
    ad_groups = []
    for g in data.get("list", []):
        ad_groups.append({
            "id": g.get("adgroup_id"),
            "name": g.get("adgroup_name"),
            "campaign_id": g.get("campaign_id"),
            "status": g.get("status"),
            "budget": g.get("budget"),
            "budget_mode": g.get("budget_mode"),
            "bid_price": g.get("bid_price"),
            "bid_type": g.get("bid_type"),
            "optimization_goal": g.get("optimization_goal"),
            "placements": g.get("placements", []),
        })
    return ad_groups


def fetch_ads(token: str, advertiser_id: str) -> list:
    data = api_get("/ad/get/", token, {
        "advertiser_id": advertiser_id,
        "fields": json.dumps([
            "ad_id", "ad_name", "adgroup_id", "campaign_id",
            "status", "ad_format", "creative_type",
            "video_id", "image_ids", "ad_text",
            "call_to_action", "landing_page_url",
            "is_spark_ad", "spark_ad_post_id",
        ]),
        "page_size": 100,
    })
    ads = []
    for a in data.get("list", []):
        ads.append({
            "id": a.get("ad_id"),
            "name": a.get("ad_name"),
            "adgroup_id": a.get("adgroup_id"),
            "campaign_id": a.get("campaign_id"),
            "status": a.get("status"),
            "format": a.get("ad_format"),
            "creative_type": a.get("creative_type"),
            "has_video": bool(a.get("video_id")),
            "cta": a.get("call_to_action"),
            "landing_url": a.get("landing_page_url"),
            "is_spark_ad": a.get("is_spark_ad", False),
        })
    return ads


def fetch_campaign_insights(token: str, advertiser_id: str, days: int) -> list:
    date_end = datetime.today().strftime("%Y-%m-%d")
    date_start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    data = api_post("/report/integrated/get/", token, {
        "advertiser_id": advertiser_id,
        "report_type": "BASIC",
        "data_level": "AUCTION_CAMPAIGN",
        "dimensions": ["campaign_id"],
        "metrics": [
            "campaign_name", "spend", "impressions", "clicks", "ctr",
            "cpm", "cpc", "conversion", "cost_per_conversion",
            "video_play_actions", "video_watched_2s", "video_watched_6s",
            "video_views_p25", "video_views_p50", "video_views_p75", "video_views_p100",
            "reach", "frequency",
        ],
        "start_date": date_start,
        "end_date": date_end,
        "page_size": 100,
    })

    rows = []
    for r in data.get("list", []):
        m = r.get("metrics", {})
        d = r.get("dimensions", {})
        rows.append({
            "campaign_id": d.get("campaign_id"),
            "campaign_name": m.get("campaign_name"),
            "spend": float(m.get("spend", 0)),
            "impressions": int(m.get("impressions", 0)),
            "clicks": int(m.get("clicks", 0)),
            "ctr": float(m.get("ctr", 0)),
            "cpm": float(m.get("cpm", 0)),
            "cpc": float(m.get("cpc", 0)),
            "conversions": float(m.get("conversion", 0)),
            "cost_per_conversion": float(m.get("cost_per_conversion", 0)),
            "video_plays": int(m.get("video_play_actions", 0)),
            "video_2s": int(m.get("video_watched_2s", 0)),
            "video_6s": int(m.get("video_watched_6s", 0)),
            "video_p25": int(m.get("video_views_p25", 0)),
            "video_p50": int(m.get("video_views_p50", 0)),
            "video_p75": int(m.get("video_views_p75", 0)),
            "video_p100": int(m.get("video_views_p100", 0)),
            "reach": int(m.get("reach", 0)),
            "frequency": float(m.get("frequency", 0)),
        })
    return rows


def fetch_ad_insights(token: str, advertiser_id: str, days: int) -> list:
    date_end = datetime.today().strftime("%Y-%m-%d")
    date_start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    data = api_post("/report/integrated/get/", token, {
        "advertiser_id": advertiser_id,
        "report_type": "BASIC",
        "data_level": "AUCTION_AD",
        "dimensions": ["ad_id"],
        "metrics": [
            "ad_name", "spend", "impressions", "clicks", "ctr", "cpc",
            "conversion", "cost_per_conversion",
            "video_play_actions", "video_watched_2s", "video_views_p100",
            "reach", "frequency",
        ],
        "start_date": date_start,
        "end_date": date_end,
        "page_size": 100,
    })

    rows = []
    for r in data.get("list", []):
        m = r.get("metrics", {})
        d = r.get("dimensions", {})
        rows.append({
            "ad_id": d.get("ad_id"),
            "ad_name": m.get("ad_name"),
            "spend": float(m.get("spend", 0)),
            "impressions": int(m.get("impressions", 0)),
            "clicks": int(m.get("clicks", 0)),
            "ctr": float(m.get("ctr", 0)),
            "cpc": float(m.get("cpc", 0)),
            "conversions": float(m.get("conversion", 0)),
            "cpa": float(m.get("cost_per_conversion", 0)),
            "video_plays": int(m.get("video_play_actions", 0)),
            "video_2s": int(m.get("video_watched_2s", 0)),
            "video_p100": int(m.get("video_views_p100", 0)),
            "reach": int(m.get("reach", 0)),
            "frequency": float(m.get("frequency", 0)),
            "video_completion_rate": round(
                int(m.get("video_views_p100", 0)) / int(m.get("video_play_actions", 1)), 3
            ) if int(m.get("video_play_actions", 0)) > 0 else 0,
        })
    return rows


def compute_insights(campaign_insights: list) -> dict:
    spend = sum(r["spend"] for r in campaign_insights)
    impressions = sum(r["impressions"] for r in campaign_insights)
    clicks = sum(r["clicks"] for r in campaign_insights)
    conversions = sum(r["conversions"] for r in campaign_insights)

    return {
        "spend_usd": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": round(conversions, 1),
        "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
        "cpm": round(spend / impressions * 1000, 2) if impressions else 0,
        "cpc": round(spend / clicks, 2) if clicks else 0,
        "cpa": round(spend / conversions, 2) if conversions else None,
        "campaign_count": len(campaign_insights),
    }


def run_auth_flow(app_id: str, app_secret: str):
    """Open TikTok OAuth2 authorization page and exchange code for access token."""
    import urllib.parse, webbrowser, http.server, threading

    redirect_uri = "http://localhost:8080/callback"
    auth_url = (
        f"https://business-api.tiktok.com/portal/auth"
        f"?app_id={app_id}&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&state=claude-ads"
    )

    auth_code = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = dict(p.split("=") for p in self.path.split("?")[1].split("&") if "=" in p)
            auth_code.append(params.get("auth_code", ""))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Authorization successful. Return to terminal.</h1>")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", 8080), Handler)
    thread = threading.Thread(target=lambda: server.handle_request())
    thread.start()

    print(f"\n→ Opening browser for authorization...")
    webbrowser.open(auth_url)
    thread.join(timeout=120)

    if not auth_code:
        print("ERROR: No auth code received within 2 minutes.")
        sys.exit(1)

    import requests
    resp = requests.post(f"{BASE_URL}/oauth2/access_token/", json={
        "app_id": app_id,
        "secret": app_secret,
        "auth_code": auth_code[0],
        "grant_type": "authorization_code",
    }).json()

    if resp.get("code") != 0:
        print(f"ERROR: {resp.get('message')}")
        sys.exit(1)

    token_data = resp.get("data", {})
    print("\n✓ Authentication successful!")
    print(f"\nAdd to your shell profile:")
    print(f'  export TIKTOK_ACCESS_TOKEN="{token_data.get("access_token")}"')
    print(f'  export TIKTOK_ADVERTISER_ID="{token_data.get("advertiser_ids", [""])[0]}"')


def main():
    parser = argparse.ArgumentParser(description="Fetch TikTok Ads data for claude-ads audit")
    parser.add_argument("--output", default="tiktok-snapshot.json", help="Output JSON file")
    parser.add_argument("--days", type=int, default=30, help="Days of data to fetch (default: 30)")
    parser.add_argument("--advertiser-id", help="TikTok Advertiser ID (overrides env var)")
    parser.add_argument("--auth", action="store_true", help="Run OAuth2 token flow")
    parser.add_argument("--check", action="store_true", help="Validate credentials only")
    args = parser.parse_args()

    if args.auth:
        app_id = os.environ.get("TIKTOK_APP_ID")
        app_secret = os.environ.get("TIKTOK_APP_SECRET")
        if not app_id or not app_secret:
            print("ERROR: Set TIKTOK_APP_ID and TIKTOK_APP_SECRET first.")
            sys.exit(1)
        run_auth_flow(app_id, app_secret)
        return

    creds, missing = check_credentials()

    if args.check:
        if missing:
            print(f"MISSING: {', '.join(missing)}")
            sys.exit(1)
        print("✓ All credentials set")
        print(f"  Advertiser ID: {creds['TIKTOK_ADVERTISER_ID']}")
        return

    if missing:
        print(f"ERROR: Missing credentials: {', '.join(missing)}")
        print("\nSetup:")
        print("  1. Create dev app: https://business-api.tiktok.com/portal/apps")
        print("  2. Set TIKTOK_APP_ID and TIKTOK_APP_SECRET")
        print("  3. Run: python3 fetch_tiktok_ads.py --auth")
        sys.exit(1)

    token = creds["TIKTOK_ACCESS_TOKEN"]
    advertiser_id = args.advertiser_id or creds["TIKTOK_ADVERTISER_ID"]

    print(f"↓ Connecting to TikTok Ads (advertiser: {advertiser_id})...")

    print("↓ Fetching account info...")
    account = fetch_account(token, advertiser_id)

    print("↓ Fetching campaigns...")
    campaigns = fetch_campaigns(token, advertiser_id)
    print(f"  → {len(campaigns)} campaigns")

    print("↓ Fetching ad groups...")
    ad_groups = fetch_ad_groups(token, advertiser_id)
    print(f"  → {len(ad_groups)} ad groups")

    print("↓ Fetching ads...")
    ads = fetch_ads(token, advertiser_id)
    print(f"  → {len(ads)} ads")

    print(f"↓ Fetching campaign insights (last {args.days} days)...")
    campaign_insights = fetch_campaign_insights(token, advertiser_id, args.days)

    print(f"↓ Fetching ad-level insights (last {args.days} days)...")
    ad_insights = fetch_ad_insights(token, advertiser_id, args.days)

    insights = compute_insights(campaign_insights)

    # Creative health flags for /ads tiktok audit
    active_ads = [a for a in ads if a["status"] == "ENABLE"]
    spark_ads = [a for a in ads if a.get("is_spark_ad")]
    creative_health = {
        "total_ads": len(ads),
        "active_ads": len(active_ads),
        "spark_ads_count": len(spark_ads),
        "spark_ad_pct": round(len(spark_ads) / len(ads) * 100, 1) if ads else 0,
        "unique_ad_groups_with_ads": len(set(a["adgroup_id"] for a in ads)),
        "avg_ads_per_adgroup": round(len(ads) / max(len(ad_groups), 1), 1),
        "has_video_ads": any(a["has_video"] for a in ads),
    }

    snapshot = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "days_window": args.days,
        "advertiser_id": advertiser_id,
        "account": account,
        "insights": insights,
        "campaigns": campaigns,
        "ad_groups": ad_groups,
        "ads": ads,
        "campaign_insights": campaign_insights,
        "ad_insights": ad_insights,
        "creative_health": creative_health,
    }

    with open(args.output, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"\n✓ Saved: {args.output}")
    print(f"\n  Account:      {account.get('name', 'unknown')}")
    print(f"  Spend:        ${insights['spend_usd']:,.2f} (last {args.days}d)")
    print(f"  Campaigns:    {insights['campaign_count']}")
    print(f"  CTR:          {insights['ctr']}%  (benchmark: 0.84%)")
    print(f"  CPM:          ${insights['cpm']}  (benchmark: ~$4.26)")
    cpa = insights.get("cpa")
    print(f"  CPA:          ${cpa}" if cpa else "  CPA:          no conv tracking")
    print(f"  Spark Ads:    {creative_health['spark_ad_pct']}% of creatives")
    print(f"\nRun: /ads tiktok (in Claude Code) to analyze this data")


if __name__ == "__main__":
    main()
