#!/usr/bin/env python3
"""
fetch_portfolio.py — Fetch basic profile data for all Instagram accounts
in the Meta Business portfolio, output portfolio-snapshot.json.

Usage:
    python fetch_portfolio.py --output ./portfolio-snapshot.json
"""
import os, sys, json, argparse, time
from datetime import datetime, timezone
import requests

GRAPH_API_BASE = "https://graph.facebook.com"
API_VERSION = "v20.0"

IG_PROFILE_FIELDS = (
    "id,name,username,biography,website,followers_count,"
    "follows_count,media_count,profile_picture_url,ig_id"
)

MEDIA_FIELDS = (
    "id,media_type,media_product_type,timestamp,caption,like_count,comments_count,permalink,shortcode"
)


def get_token():
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        print("ERROR: META_ACCESS_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    return token


def graph_get(path, token, params=None):
    p = {"access_token": token, "limit": 50}
    if params:
        p.update(params)
    url = f"{GRAPH_API_BASE}/{API_VERSION}/{path}"
    r = requests.get(url, params=p, timeout=30)
    return r.json()


def fetch_all_pages(token):
    data = graph_get("me/accounts", token, {
        "fields": "id,name,category,fan_count,username,instagram_business_account",
        "limit": 50,
    })
    return data.get("data", [])


def fetch_ig_profile(ig_id, token):
    data = graph_get(ig_id, token, {"fields": IG_PROFILE_FIELDS})
    if "error" in data:
        return None
    return data


def fetch_ig_media(ig_id, token, limit=50):
    data = graph_get(f"{ig_id}/media", token, {"fields": MEDIA_FIELDS, "limit": limit})
    return data.get("data", [])


def analyze_media(media):
    from collections import Counter, defaultdict
    if not media:
        return {}

    types = Counter(m.get("media_type") for m in media)
    prod_types = Counter(m.get("media_product_type") for m in media)

    dates = []
    for m in media:
        ts = m.get("timestamp", "")
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            dates.append(dt)
    dates.sort(reverse=True)

    gaps = []
    if len(dates) > 1:
        gaps = [(dates[i] - dates[i + 1]).days for i in range(len(dates) - 1)]

    monthly = defaultdict(int)
    for dt in dates:
        monthly[dt.strftime("%Y-%m")] += 1

    now = datetime.now(timezone.utc)
    days_since_last = (now - dates[0]).days if dates else 999

    # Caption analysis
    cta_keywords = ["reserva", "reserve", "link", "whatsapp", "mesa", "pedido",
                    "visita", "llama", "bio", "directo", "book", "orden"]
    hashtag_counts = []
    cta_count = 0
    for m in media:
        cap = m.get("caption") or ""
        hashtag_counts.append(cap.count("#"))
        if any(kw in cap.lower() for kw in cta_keywords):
            cta_count += 1

    avg_hashtags = sum(hashtag_counts) / len(hashtag_counts) if hashtag_counts else 0
    pct_3_5_hashtags = sum(1 for h in hashtag_counts if 3 <= h <= 5) / len(hashtag_counts) * 100 if hashtag_counts else 0

    return {
        "total_posts_analyzed": len(media),
        "most_recent_post_days_ago": days_since_last,
        "content_mix": dict(types),
        "product_types": dict(prod_types),
        "reels_pct": round(prod_types.get("REELS", 0) / len(media) * 100, 1),
        "carousel_pct": round(types.get("CAROUSEL_ALBUM", 0) / len(media) * 100, 1),
        "avg_posts_per_month": round(sum(monthly.values()) / max(len(monthly), 1), 1),
        "max_gap_days": max(gaps) if gaps else 0,
        "avg_gap_days": round(sum(gaps) / len(gaps), 1) if gaps else 0,
        "pct_with_cta": round(cta_count / len(media) * 100, 1),
        "avg_hashtags": round(avg_hashtags, 1),
        "pct_3_5_hashtags": round(pct_3_5_hashtags, 1),
        "monthly_counts": dict(sorted(monthly.items(), reverse=True)[:6]),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch portfolio Instagram data")
    parser.add_argument("--output", default="./portfolio-snapshot.json")
    parser.add_argument("--media-limit", type=int, default=50,
                        help="Posts to fetch per account (default: 50)")
    args = parser.parse_args()

    token = get_token()

    print("Fetching Facebook Pages...", flush=True)
    pages = fetch_all_pages(token)
    print(f"Found {len(pages)} pages", flush=True)

    accounts = []
    for page in pages:
        ig_ref = page.get("instagram_business_account")
        ig_id = ig_ref.get("id") if ig_ref else None

        entry = {
            "fb_page_id": page["id"],
            "fb_page_name": page["name"],
            "fb_category": page.get("category", ""),
            "fb_fans": page.get("fan_count", 0),
            "fb_username": page.get("username", ""),
            "ig_id": ig_id,
            "ig_profile": None,
            "media_analysis": None,
            "media": [],
        }

        if ig_id:
            print(f"  Fetching IG: {page['name']} ({ig_id})...", flush=True)
            profile = fetch_ig_profile(ig_id, token)
            if profile:
                entry["ig_profile"] = profile
                media = fetch_ig_media(ig_id, token, limit=args.media_limit)
                entry["media_analysis"] = analyze_media(media)
                entry["media"] = media  # Store raw media for deep analysis
            time.sleep(0.3)  # Rate limiting
        else:
            print(f"  Skipping (no IG): {page['name']}", flush=True)

        accounts.append(entry)

    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "api_version": API_VERSION,
        "total_brands": len(accounts),
        "brands_with_instagram": sum(1 for a in accounts if a["ig_id"]),
        "accounts": accounts,
    }

    with open(args.output, "w") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nSaved to {args.output}")
    print(f"Brands: {len(accounts)} total, {snapshot['brands_with_instagram']} with Instagram")


if __name__ == "__main__":
    main()
