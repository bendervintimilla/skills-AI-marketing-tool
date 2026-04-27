#!/usr/bin/env python3
"""
Fetch Instagram Business Account data via Meta Graph API for /ads instagram audit.

Discovers the Instagram Business Account linked to the Meta Business Manager,
then pulls account metrics, recent media, post-level insights, audience demographics,
and Story analytics into a single JSON snapshot.

Required env vars:
    META_ACCESS_TOKEN      User or System User token (needs instagram_manage_insights
                           + instagram_basic + pages_read_engagement + business_management)
    META_AD_ACCOUNT_ID     act_XXXXXXXXX — used to discover the linked IG account

Optional env vars:
    META_BUSINESS_ID       Override business ID lookup
    META_API_VERSION       Graph API version (default: v20.0)
    IG_USER_ID             Override Instagram Business Account ID discovery

Usage:
    python fetch_instagram.py --output instagram-snapshot.json
    python fetch_instagram.py --days 30 --output ig-snapshot.json
    python fetch_instagram.py --ig-user-id 12345678 --output ig-snapshot.json

Exit codes:
    0  success
    1  configuration error
    2  auth error
    3  API error
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


DEFAULT_API_VERSION = "v20.0"
GRAPH_API_BASE = "https://graph.facebook.com"

MEDIA_FIELDS = [
    "id", "media_type", "media_product_type", "timestamp", "permalink",
    "caption", "like_count", "comments_count", "thumbnail_url", "media_url",
    "is_shared_to_feed", "shortcode", "children{id,media_type}",
]

ACCOUNT_INSIGHT_METRICS = [
    "reach", "impressions", "profile_views", "website_clicks",
    "email_contacts", "get_directions_clicks", "phone_call_clicks",
    "follower_count",
]

POST_INSIGHT_METRICS = [
    "reach", "impressions", "engagement", "saved", "shares",
    "likes", "comments", "video_views", "total_interactions",
]

REEL_INSIGHT_METRICS = [
    "reach", "impressions", "plays", "likes", "comments", "shares", "saved",
    "total_interactions", "ig_reels_avg_watch_time", "ig_reels_video_view_total_time",
]

STORY_INSIGHT_METRICS = [
    "reach", "impressions", "exits", "replies", "taps_forward", "taps_back",
    "total_interactions",
]


def _sanitize(msg: str) -> str:
    out = msg
    for needle in ("access_token=", "Bearer "):
        i = out.find(needle)
        while i != -1:
            end = out.find("&", i)
            end = end if end != -1 else len(out)
            out = out[:i + len(needle)] + "***" + out[end:]
            i = out.find(needle, i + 4)
    return out


def _get_config() -> dict[str, str]:
    token = os.environ.get("META_ACCESS_TOKEN")
    account = os.environ.get("META_AD_ACCOUNT_ID")

    if not token:
        print(
            "Error: META_ACCESS_TOKEN not set.\n"
            "Run /ads meta first to configure credentials.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not account and not os.environ.get("IG_USER_ID"):
        print(
            "Error: META_AD_ACCOUNT_ID not set.\n"
            "Set it in ~/.zshrc: export META_AD_ACCOUNT_ID=\"act_XXXXXXXXX\"",
            file=sys.stderr,
        )
        sys.exit(1)

    if account and not account.startswith("act_"):
        account = f"act_{account}"

    return {
        "token": token,
        "account_id": account or "",
        "business_id": os.environ.get("META_BUSINESS_ID", ""),
        "ig_user_id": os.environ.get("IG_USER_ID", ""),
        "api_version": os.environ.get("META_API_VERSION", DEFAULT_API_VERSION),
    }


def _get(path: str, cfg: dict, params: dict | None = None, silent_403: bool = False) -> dict | None:
    url = f"{GRAPH_API_BASE}/{cfg['api_version']}/{path}"
    query = dict(params or {})
    query["access_token"] = cfg["token"]

    retries = 0
    backoff = [2, 4, 8, 16, 32]

    while True:
        try:
            resp = requests.get(url, params=query, timeout=60)
        except requests.RequestException as e:
            print(f"Network error: {_sanitize(str(e))}", file=sys.stderr)
            sys.exit(3)

        if resp.status_code == 429 or (resp.status_code >= 500 and retries < 5):
            wait = backoff[min(retries, 4)]
            print(f"  Rate limit/server error ({resp.status_code}), retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
            retries += 1
            continue

        if resp.status_code in (401, 403):
            if silent_403:
                return None
            err = resp.json().get("error", {}) if resp.headers.get("content-type", "").startswith("application/json") else {}
            code = err.get("code", resp.status_code)
            msg = err.get("message", "Auth error")
            print(
                f"Auth error ({resp.status_code}, code {code}): {_sanitize(msg)}\n"
                f"Likely missing scope. Add to your OAuth token:\n"
                f"  instagram_basic, instagram_manage_insights, pages_read_engagement",
                file=sys.stderr,
            )
            sys.exit(2)

        if not resp.ok:
            if silent_403:
                return None
            err = resp.json().get("error", {}) if resp.headers.get("content-type", "").startswith("application/json") else {}
            print(f"API error ({resp.status_code}): {_sanitize(err.get('message', resp.text))}", file=sys.stderr)
            sys.exit(3)

        return resp.json()


def _get_paginated(path: str, cfg: dict, params: dict | None = None) -> list[dict]:
    url = f"{GRAPH_API_BASE}/{cfg['api_version']}/{path}"
    query = dict(params or {})
    query["access_token"] = cfg["token"]

    all_data: list = []
    next_url: str | None = url
    next_params: dict | None = query

    while next_url:
        try:
            resp = requests.get(next_url, params=next_params, timeout=60)
        except requests.RequestException as e:
            print(f"Network error: {_sanitize(str(e))}", file=sys.stderr)
            break

        if not resp.ok:
            break

        body = resp.json()
        if "data" in body and isinstance(body["data"], list):
            all_data.extend(body["data"])
            next_url = body.get("paging", {}).get("next")
            next_params = None
        else:
            if "data" not in body:
                all_data.append(body)
            break

    return all_data


def discover_ig_user_id(cfg: dict) -> str | None:
    """Find Instagram Business Account ID from ad account or business."""
    if cfg["ig_user_id"]:
        return cfg["ig_user_id"]

    # Try via ad account
    if cfg["account_id"]:
        print("→ Discovering Instagram Business Account from ad account...", file=sys.stderr)
        data = _get(cfg["account_id"], cfg, {"fields": "instagram_actor_id"}, silent_403=True)
        if data and data.get("instagram_actor_id"):
            ig_id = data["instagram_actor_id"]
            print(f"  Found via ad account: {ig_id}", file=sys.stderr)
            return ig_id

    # Try via business pages
    if cfg["business_id"]:
        print("→ Discovering Instagram via business pages...", file=sys.stderr)
        pages = _get_paginated(
            f"{cfg['business_id']}/instagram_accounts",
            cfg,
            {"fields": "id,name,username,followers_count"},
        )
        if pages:
            ig_id = pages[0]["id"]
            print(f"  Found via business: @{pages[0].get('username','?')} ({ig_id})", file=sys.stderr)
            return ig_id

    # Try via account's connected page
    if cfg["account_id"]:
        data = _get(cfg["account_id"], cfg, {"fields": "business"}, silent_403=True)
        biz_id = data.get("business", {}).get("id") if data else None
        if biz_id:
            pages = _get_paginated(
                f"{biz_id}/instagram_accounts",
                cfg,
                {"fields": "id,name,username"},
            )
            if pages:
                ig_id = pages[0]["id"]
                print(f"  Found via business {biz_id}: {ig_id}", file=sys.stderr)
                return ig_id

    print("⚠ Could not discover Instagram Business Account ID.", file=sys.stderr)
    print("  Set IG_USER_ID env var manually: export IG_USER_ID=\"your-ig-user-id\"", file=sys.stderr)
    print("  Find it: Instagram → Settings → Account → Professional Dashboard → About this account", file=sys.stderr)
    return None


def fetch_account_info(ig_id: str, cfg: dict) -> dict:
    fields = (
        "id,name,username,biography,website,followers_count,follows_count,"
        "media_count,profile_picture_url,ig_id"
    )
    data = _get(ig_id, cfg, {"fields": fields})
    return data or {}


def fetch_recent_media(ig_id: str, cfg: dict, limit: int = 50) -> list[dict]:
    return _get_paginated(
        f"{ig_id}/media",
        cfg,
        {"fields": ",".join(MEDIA_FIELDS), "limit": min(limit, 100)},
    )


def fetch_media_insights(media_id: str, media_type: str, cfg: dict) -> dict:
    """Fetch insights for a single media item. Returns {} on permission error."""
    if media_type == "REEL" or media_type == "VIDEO":
        metrics = REEL_INSIGHT_METRICS
    elif media_type == "STORY":
        metrics = STORY_INSIGHT_METRICS
    else:
        metrics = POST_INSIGHT_METRICS

    data = _get(
        f"{media_id}/insights",
        cfg,
        {"metric": ",".join(metrics)},
        silent_403=True,
    )
    if not data:
        return {}

    result = {}
    for item in data.get("data", []):
        result[item["name"]] = item.get("value", 0)
    return result


def fetch_account_insights(ig_id: str, cfg: dict, days: int = 30) -> dict:
    """Fetch account-level metrics for the last N days."""
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    until = int(datetime.now(timezone.utc).timestamp())

    result = {}
    for metric in ACCOUNT_INSIGHT_METRICS:
        data = _get(
            f"{ig_id}/insights",
            cfg,
            {
                "metric": metric,
                "period": "day",
                "since": since,
                "until": until,
            },
            silent_403=True,
        )
        if data and data.get("data"):
            values = [v.get("value", 0) for item in data["data"] for v in item.get("values", [])]
            result[metric] = {
                "total": sum(values),
                "avg_daily": sum(values) / len(values) if values else 0,
                "data_points": len(values),
            }

    return result


def fetch_audience_demographics(ig_id: str, cfg: dict) -> dict:
    """Fetch follower demographics. Requires instagram_manage_insights scope."""
    result = {}

    for breakdown in ["age", "gender", "city", "country"]:
        data = _get(
            f"{ig_id}/insights",
            cfg,
            {"metric": "follower_demographics", "period": "lifetime", "breakdown": breakdown},
            silent_403=True,
        )
        if data and data.get("data"):
            for item in data["data"]:
                result[breakdown] = item.get("total_value", {}).get("breakdowns", [])
                break

    return result


def build_snapshot(cfg: dict, days: int) -> dict:
    ig_id = discover_ig_user_id(cfg)
    if not ig_id:
        print("Error: Cannot proceed without an Instagram Business Account ID.", file=sys.stderr)
        sys.exit(1)

    print(f"→ Fetching account info for IG user {ig_id}...", file=sys.stderr)
    account = fetch_account_info(ig_id, cfg)
    username = account.get("username", ig_id)
    print(f"  @{username} — {account.get('followers_count', '?')} followers", file=sys.stderr)

    print(f"→ Fetching recent media (last {days} days of posts, up to 50)...", file=sys.stderr)
    media = fetch_recent_media(ig_id, cfg, limit=50)
    print(f"  Found {len(media)} posts", file=sys.stderr)

    # Categorize by type
    types: dict[str, int] = {}
    for m in media:
        t = m.get("media_type", "UNKNOWN")
        types[t] = types.get(t, 0) + 1
    print(f"  Types: {types}", file=sys.stderr)

    # Fetch insights for each post (silent on permission errors)
    print("→ Fetching post-level insights...", file=sys.stderr)
    insights_available = True
    media_with_insights = []
    for i, m in enumerate(media):
        ins = fetch_media_insights(m["id"], m.get("media_product_type", m.get("media_type", "")), cfg)
        if not ins and i == 0:
            insights_available = False
            print("  ⚠ Post insights unavailable (missing instagram_manage_insights scope)", file=sys.stderr)
            print("  Structural analysis will proceed without engagement metrics.", file=sys.stderr)
        m_copy = dict(m)
        m_copy["insights"] = ins
        media_with_insights.append(m_copy)
        if insights_available and i > 0 and i % 10 == 0:
            print(f"  {i}/{len(media)} posts processed...", file=sys.stderr)

    print("→ Fetching account-level insights...", file=sys.stderr)
    account_insights = fetch_account_insights(ig_id, cfg, days=days)
    if not account_insights:
        print("  ⚠ Account insights unavailable (missing scope)", file=sys.stderr)

    print("→ Fetching audience demographics...", file=sys.stderr)
    demographics = fetch_audience_demographics(ig_id, cfg)
    if not demographics:
        print("  ⚠ Demographics unavailable (missing scope)", file=sys.stderr)

    # Aggregate media stats
    reels = [m for m in media_with_insights if m.get("media_type") == "VIDEO" and m.get("is_shared_to_feed") is not None or
             m.get("media_product_type") == "REELS"]
    stories = [m for m in media_with_insights if m.get("media_product_type") == "STORY"]
    feed_images = [m for m in media_with_insights if m.get("media_type") in ("IMAGE",)]
    carousels = [m for m in media_with_insights if m.get("media_type") == "CAROUSEL_ALBUM"]

    def avg_insight(posts, metric):
        vals = [p["insights"].get(metric, 0) for p in posts if p.get("insights")]
        return sum(vals) / len(vals) if vals else None

    summary = {
        "ig_user_id": ig_id,
        "username": username,
        "followers": account.get("followers_count"),
        "following": account.get("follows_count"),
        "media_count": account.get("media_count"),
        "last_analyzed_posts": len(media),
        "content_mix": types,
        "insights_scope_available": insights_available,
        "reels_count": len(reels),
        "stories_count": len(stories),
        "feed_images_count": len(feed_images),
        "carousels_count": len(carousels),
        "avg_reach_reel": avg_insight(reels, "reach"),
        "avg_reach_image": avg_insight(feed_images, "reach"),
        "avg_reach_carousel": avg_insight(carousels, "reach"),
    }

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "api_version": cfg["api_version"],
        "days_analyzed": days,
        "account": account,
        "account_insights": account_insights,
        "demographics": demographics,
        "media": media_with_insights,
        "summary": summary,
        "scope_warnings": [] if insights_available else [
            "instagram_manage_insights missing — post-level engagement data unavailable",
            "Add scope and re-run for full engagement analysis",
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Instagram Business Account data for /ads instagram audit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
    META_ACCESS_TOKEN      (required) User token with instagram_manage_insights scope
    META_AD_ACCOUNT_ID     (required) act_XXXXXXXXX to auto-discover linked IG account
    IG_USER_ID             (optional) Override Instagram Business Account ID
    META_API_VERSION       (optional) default: v20.0

Scopes needed for full analysis:
    instagram_basic                  basic profile info
    instagram_manage_insights        post/account engagement metrics
    pages_read_engagement            page-connected IG account discovery
    business_management              business IG account discovery

Examples:
    python fetch_instagram.py --output instagram-snapshot.json
    python fetch_instagram.py --days 14 --output ig-snapshot.json
    IG_USER_ID=12345 python fetch_instagram.py --output ig-snapshot.json
""",
    )
    parser.add_argument("--output", "-o", metavar="FILE", help="Output file (default: stdout)")
    parser.add_argument("--days", type=int, default=30, metavar="N", help="Days of data to fetch (default: 30)")
    parser.add_argument("--ig-user-id", metavar="ID", help="Override IG_USER_ID env var")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    args = parser.parse_args()

    if args.ig_user_id:
        os.environ["IG_USER_ID"] = args.ig_user_id

    cfg = _get_config()
    snapshot = build_snapshot(cfg, days=args.days)

    output_json = json.dumps(snapshot, indent=2 if args.pretty else None, default=str)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_json)
        s = snapshot["summary"]
        print(f"\n✓ Snapshot written to {args.output} ({len(output_json):,} bytes)", file=sys.stderr)
        print(f"  @{s['username']} — {s['followers']:,} followers", file=sys.stderr)
        print(f"  Posts analyzed: {s['last_analyzed_posts']} | Content mix: {s['content_mix']}", file=sys.stderr)
        if snapshot.get("scope_warnings"):
            for w in snapshot["scope_warnings"]:
                print(f"  ⚠ {w}", file=sys.stderr)
        print(f"\n  Next: run /ads instagram in Claude Code to analyze.", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
