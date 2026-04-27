#!/usr/bin/env python3
"""
fetch_youtube_ads.py — YouTube Ads data fetcher for claude-ads audit pipeline.

YouTube ads live inside Google Ads — this script fetches only VIDEO campaign types
(YOUTUBE, DEMAND_GEN, VIDEO) and their creative/performance data.

Uses the same Google Ads API credentials as fetch_google_ads.py.
Run fetch_google_ads.py --auth first to generate your refresh token.

SETUP: same as fetch_google_ads.py
  export GOOGLE_ADS_DEVELOPER_TOKEN="..."
  export GOOGLE_ADS_CLIENT_ID="..."
  export GOOGLE_ADS_CLIENT_SECRET="..."
  export GOOGLE_ADS_REFRESH_TOKEN="..."
  export GOOGLE_ADS_CUSTOMER_ID="..."

Usage:
  python3 fetch_youtube_ads.py --output youtube-snapshot.json
  python3 fetch_youtube_ads.py --days 30 --customer-id 1234567890
  python3 fetch_youtube_ads.py --check

Output: youtube-snapshot.json
  {
    "fetched_at": "...",
    "customer_id": "...",
    "campaigns": [ VIDEO/DEMAND_GEN campaigns with metrics ],
    "ads": [ video ads with format, duration, asset info ],
    "insights": { spend, views, view_rate, cpv, vtr, ... }
  }
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

VIDEO_CAMPAIGN_TYPES = {"VIDEO", "DEMAND_GEN", "YOUTUBE"}


def check_credentials() -> tuple[dict, list]:
    required = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
    ]
    creds, missing = {}, []
    for key in required:
        val = os.environ.get(key)
        (creds if val else missing)[key] = val or ""
        if not val:
            missing.append(key)
    missing = [k for k in required if not os.environ.get(k)]
    creds = {k: os.environ.get(k, "") for k in required if os.environ.get(k)}
    return creds, missing


def build_client(creds: dict):
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        print("ERROR: google-ads not installed. Run: pip install 'google-ads>=22.0.0'")
        sys.exit(2)
    return GoogleAdsClient.load_from_dict({
        "developer_token": creds["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": creds["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": creds["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": creds["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    })


def run_gaql(client, customer_id: str, query: str) -> list:
    service = client.get_service("GoogleAdsService")
    stream = service.search_stream(customer_id=customer_id, query=query)
    rows = []
    for batch in stream:
        for row in batch.results:
            rows.append(row)
    return rows


def fetch_video_campaigns(client, customer_id: str, days: int) -> list:
    date_from = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = datetime.today().strftime("%Y-%m-%d")
    rows = run_gaql(client, customer_id, f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.advertising_channel_type,
          campaign.advertising_channel_sub_type,
          campaign.bidding_strategy_type,
          campaign_budget.amount_micros,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.video_views,
          metrics.view_through_conversions,
          metrics.conversions,
          metrics.video_view_rate,
          metrics.average_cpv,
          metrics.video_quartile_p25_rate,
          metrics.video_quartile_p50_rate,
          metrics.video_quartile_p75_rate,
          metrics.video_quartile_p100_rate
        FROM campaign
        WHERE campaign.advertising_channel_type IN ('VIDEO', 'DEMAND_GEN')
          AND campaign.status != 'REMOVED'
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
                "subtype": r.campaign.advertising_channel_sub_type.name,
                "bidding": r.campaign.bidding_strategy_type.name,
                "budget_micros": r.campaign_budget.amount_micros,
                "impressions": 0, "clicks": 0, "cost_micros": 0,
                "video_views": 0, "conversions": 0.0,
                "view_through_conversions": 0,
                "video_view_rate": 0.0, "avg_cpv_micros": 0,
                "vtr_p25": 0.0, "vtr_p50": 0.0, "vtr_p75": 0.0, "vtr_p100": 0.0,
            }
        c = campaigns[cid]
        c["impressions"] += r.metrics.impressions
        c["clicks"] += r.metrics.clicks
        c["cost_micros"] += r.metrics.cost_micros
        c["video_views"] += r.metrics.video_views
        c["conversions"] += r.metrics.conversions
        c["view_through_conversions"] += r.metrics.view_through_conversions

    for c in campaigns.values():
        c["spend_usd"] = round(c["cost_micros"] / 1_000_000, 2)
        c["cpv_usd"] = round(c["cost_micros"] / 1_000_000 / c["video_views"], 4) \
            if c["video_views"] else None
        c["view_rate"] = round(c["video_views"] / c["impressions"] * 100, 1) \
            if c["impressions"] else 0

    return list(campaigns.values())


def fetch_video_ads(client, customer_id: str, days: int) -> list:
    date_from = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = datetime.today().strftime("%Y-%m-%d")
    rows = run_gaql(client, customer_id, f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.ad.name,
          ad_group_ad.ad.type,
          ad_group_ad.status,
          ad_group_ad.ad.video_ad.in_stream.video.resource_name,
          ad_group_ad.ad.video_responsive_ad.videos,
          ad_group_ad.ad.final_urls,
          campaign.id,
          campaign.name,
          ad_group.id,
          metrics.impressions,
          metrics.video_views,
          metrics.cost_micros,
          metrics.video_view_rate,
          metrics.average_cpv,
          metrics.video_quartile_p25_rate,
          metrics.video_quartile_p100_rate
        FROM ad_group_ad
        WHERE campaign.advertising_channel_type IN ('VIDEO', 'DEMAND_GEN')
          AND ad_group_ad.status != 'REMOVED'
          AND segments.date BETWEEN '{date_from}' AND '{date_to}'
    """)

    ads = {}
    for r in rows:
        aid = str(r.ad_group_ad.ad.id)
        if aid not in ads:
            ads[aid] = {
                "id": aid,
                "name": r.ad_group_ad.ad.name,
                "type": r.ad_group_ad.ad.type_.name,
                "status": r.ad_group_ad.status.name,
                "campaign_id": str(r.campaign.id),
                "campaign_name": r.campaign.name,
                "ad_group_id": str(r.ad_group.id),
                "final_urls": list(r.ad_group_ad.ad.final_urls),
                "impressions": 0, "video_views": 0, "cost_micros": 0,
            }
        a = ads[aid]
        a["impressions"] += r.metrics.impressions
        a["video_views"] += r.metrics.video_views
        a["cost_micros"] += r.metrics.cost_micros

    for a in ads.values():
        a["spend_usd"] = round(a["cost_micros"] / 1_000_000, 2)
        a["view_rate"] = round(a["video_views"] / a["impressions"] * 100, 1) \
            if a["impressions"] else 0

    return list(ads.values())


def compute_insights(campaigns: list) -> dict:
    spend = sum(c["spend_usd"] for c in campaigns)
    impressions = sum(c["impressions"] for c in campaigns)
    views = sum(c["video_views"] for c in campaigns)
    conversions = sum(c["conversions"] for c in campaigns)

    return {
        "spend_usd": round(spend, 2),
        "impressions": impressions,
        "video_views": views,
        "conversions": round(conversions, 1),
        "view_rate": round(views / impressions * 100, 1) if impressions else 0,
        "cpv_usd": round(spend / views, 4) if views else None,
        "cpm_usd": round(spend / impressions * 1000, 2) if impressions else None,
        "campaign_count": len(campaigns),
        "active_campaigns": sum(1 for c in campaigns if c["status"] == "ENABLED"),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube Ads data for claude-ads audit")
    parser.add_argument("--output", default="youtube-snapshot.json")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--customer-id")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    creds, missing = check_credentials()

    if args.check:
        if missing:
            print(f"MISSING: {', '.join(missing)}")
            print("  Same credentials as fetch_google_ads.py — run that --auth flow first.")
            sys.exit(1)
        print("✓ All credentials set")
        return

    if missing:
        print(f"ERROR: Missing: {', '.join(missing)}")
        print("  Run: python3 fetch_google_ads.py --auth")
        sys.exit(1)

    customer_id = (args.customer_id or creds["GOOGLE_ADS_CUSTOMER_ID"]).replace("-", "")
    print(f"↓ Connecting to Google Ads (YouTube campaigns, customer: {customer_id})...")
    client = build_client(creds)

    print(f"↓ Fetching VIDEO/DEMAND_GEN campaigns (last {args.days} days)...")
    campaigns = fetch_video_campaigns(client, customer_id, args.days)
    print(f"  → {len(campaigns)} video campaigns")

    if not campaigns:
        print("  No YouTube/video campaigns found in this account.")

    print(f"↓ Fetching video ads (last {args.days} days)...")
    ads = fetch_video_ads(client, customer_id, args.days)
    print(f"  → {len(ads)} video ads")

    insights = compute_insights(campaigns)

    snapshot = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "days_window": args.days,
        "customer_id": customer_id,
        "insights": insights,
        "campaigns": campaigns,
        "ads": ads,
    }

    with open(args.output, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"\n✓ Saved: {args.output}")
    print(f"\n  Campaigns:   {insights['campaign_count']} video campaigns")
    print(f"  Spend:       ${insights['spend_usd']:,.2f} (last {args.days}d)")
    print(f"  Views:       {insights['video_views']:,}")
    print(f"  View rate:   {insights['view_rate']}%  (benchmark: ~30% skippable)")
    cpv = insights.get("cpv_usd")
    print(f"  CPV:         ${cpv}" if cpv else "  CPV:         no views")
    print(f"\nRun: /ads youtube (in Claude Code) to analyze this data")


if __name__ == "__main__":
    main()
