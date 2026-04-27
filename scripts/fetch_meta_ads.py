#!/usr/bin/env python3
"""
Fetch Meta Ads Manager data for audit via Meta Marketing API (Graph API v20).

Reads env vars, pulls campaigns / ad sets / ads / insights / creatives / pixels
for the configured ad account, and writes a structured JSON to stdout or a file
for consumption by the /ads meta skill.

Required env vars:
    META_ACCESS_TOKEN    System User access token with ads_read scope
    META_AD_ACCOUNT_ID   Ad account ID, with or without "act_" prefix (e.g. act_1234567890 or 1234567890)

Optional env vars:
    META_API_VERSION     Graph API version (default: v20.0)
    META_DATE_PRESET     Insights date preset (default: last_30d)

Usage:
    python fetch_meta_ads.py --output meta-snapshot.json
    python fetch_meta_ads.py --days 7 --json
    python fetch_meta_ads.py --account-id act_9999 --output ./meta-client-snapshot.json

Exit codes:
    0  success
    1  configuration error (missing env vars, invalid account id)
    2  auth error (token invalid/expired, insufficient permissions)
    3  API error (rate limit, network, server)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


DEFAULT_API_VERSION = "v20.0"
DEFAULT_DATE_PRESET = "last_30d"
GRAPH_API_BASE = "https://graph.facebook.com"

# Fields to pull at each level — chosen for audit relevance, not exhaustive
CAMPAIGN_FIELDS = [
    "id", "name", "objective", "status", "effective_status", "buying_type",
    "special_ad_categories", "daily_budget", "lifetime_budget", "budget_remaining",
    "bid_strategy", "start_time", "stop_time", "created_time", "updated_time",
]

ADSET_FIELDS = [
    "id", "name", "campaign_id", "status", "effective_status",
    "daily_budget", "lifetime_budget", "bid_amount", "bid_strategy",
    "optimization_goal", "billing_event", "destination_type",
    "targeting", "attribution_spec", "learning_stage_info",
    "start_time", "end_time", "created_time", "updated_time",
]

AD_FIELDS = [
    "id", "name", "adset_id", "campaign_id", "status", "effective_status",
    "creative", "tracking_specs", "conversion_specs",
    "created_time", "updated_time",
]

INSIGHT_FIELDS = [
    "spend", "impressions", "reach", "frequency",
    "clicks", "ctr", "cpc", "cpm", "cpp",
    "actions", "action_values", "cost_per_action_type",
    "conversions", "conversion_values", "cost_per_conversion",
    "purchase_roas", "website_purchase_roas",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p100_watched_actions",
    "quality_ranking", "engagement_rate_ranking", "conversion_rate_ranking",
]

CREATIVE_FIELDS = [
    "id", "name", "title", "body", "call_to_action_type",
    "image_url", "thumbnail_url", "video_id", "object_story_spec",
    "effective_object_story_id", "status",
]


def _sanitize(msg: str) -> str:
    """Strip access tokens from error strings before surfacing to user."""
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
            "Generate a System User token at https://business.facebook.com "
            "(Business Settings → System Users → Generate New Token with ads_read scope).\n"
            "Then: export META_ACCESS_TOKEN=\"your-token\"",
            file=sys.stderr,
        )
        sys.exit(1)

    if not account:
        print(
            "Error: META_AD_ACCOUNT_ID not set.\n"
            "Find it in Ads Manager URL: https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=XXXXXXXXX\n"
            "Then: export META_AD_ACCOUNT_ID=\"act_XXXXXXXXX\"",
            file=sys.stderr,
        )
        sys.exit(1)

    # Normalize account id: prepend "act_" if user passed raw number
    if not account.startswith("act_"):
        account = f"act_{account}"

    return {
        "token": token,
        "account_id": account,
        "api_version": os.environ.get("META_API_VERSION", DEFAULT_API_VERSION),
    }


def _graph_get(path: str, cfg: dict[str, str], params: dict[str, Any] | None = None) -> dict:
    """GET request with retry on rate limit. Handles pagination transparently."""
    url = f"{GRAPH_API_BASE}/{cfg['api_version']}/{path}"
    query = dict(params or {})
    query["access_token"] = cfg["token"]

    all_data: list = []
    next_url: str | None = url
    next_params: dict | None = query
    retries = 0
    max_retries = 5
    backoff = [2, 4, 8, 16, 32]

    while next_url:
        try:
            resp = requests.get(next_url, params=next_params, timeout=60)
        except requests.RequestException as e:
            print(f"Network error: {_sanitize(str(e))}", file=sys.stderr)
            sys.exit(3)

        if resp.status_code == 429 or (resp.status_code >= 500 and retries < max_retries):
            wait = backoff[min(retries, len(backoff) - 1)]
            print(f"Rate limit or server error ({resp.status_code}), retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
            retries += 1
            continue

        if resp.status_code == 401 or resp.status_code == 403:
            err_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"error": {"message": resp.text}}
            msg = err_body.get("error", {}).get("message", "Auth error")
            print(
                f"Auth error ({resp.status_code}): {_sanitize(msg)}\n"
                f"Common causes:\n"
                f"  - Token expired or revoked → regenerate System User token\n"
                f"  - Missing ads_read scope → add scope when generating token\n"
                f"  - System User not assigned to ad account {cfg['account_id']} → assign in Business Settings",
                file=sys.stderr,
            )
            sys.exit(2)

        if not resp.ok:
            err_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"error": {"message": resp.text}}
            msg = err_body.get("error", {}).get("message", f"HTTP {resp.status_code}")
            print(f"API error ({resp.status_code}): {_sanitize(msg)}", file=sys.stderr)
            sys.exit(3)

        body = resp.json()

        if "data" in body and isinstance(body["data"], list):
            all_data.extend(body["data"])
            paging = body.get("paging", {})
            next_url = paging.get("next")
            next_params = None  # next URL already has params baked in
            retries = 0
        else:
            return body

    return {"data": all_data}


def fetch_account_info(cfg: dict[str, str]) -> dict:
    fields = "id,name,currency,timezone_name,account_status,amount_spent,balance,business,owner,disable_reason,funding_source_details"
    return _graph_get(cfg["account_id"], cfg, {"fields": fields})


def fetch_campaigns(cfg: dict[str, str]) -> list[dict]:
    data = _graph_get(
        f"{cfg['account_id']}/campaigns",
        cfg,
        {"fields": ",".join(CAMPAIGN_FIELDS), "limit": 200},
    )
    return data.get("data", [])


def fetch_adsets(cfg: dict[str, str]) -> list[dict]:
    data = _graph_get(
        f"{cfg['account_id']}/adsets",
        cfg,
        {"fields": ",".join(ADSET_FIELDS), "limit": 200},
    )
    return data.get("data", [])


def fetch_ads(cfg: dict[str, str]) -> list[dict]:
    data = _graph_get(
        f"{cfg['account_id']}/ads",
        cfg,
        {"fields": ",".join(AD_FIELDS), "limit": 200},
    )
    return data.get("data", [])


def fetch_insights(cfg: dict[str, str], level: str, date_preset: str) -> list[dict]:
    """
    Fetch insights via async job (required for large accounts with 1000s of campaigns).
    Falls back to empty list with a warning if the job fails — structural audit still runs.
    """
    import json as _json

    # access_token must be in query string; all other params go in POST body for async jobs
    body = {
        "fields": ",".join(INSIGHT_FIELDS),
        "level": level,
        "date_preset": date_preset,
        "limit": 500,
    }

    # Start async job
    url = f"{GRAPH_API_BASE}/{cfg['api_version']}/{cfg['account_id']}/insights"
    try:
        resp = requests.post(url, params={"access_token": cfg["token"]}, data=body, timeout=60)
    except requests.RequestException as e:
        print(f"  ⚠ Insights network error: {_sanitize(str(e))} — skipping insights", file=sys.stderr)
        return []

    if not resp.ok:
        msg = resp.json().get("error", {}).get("message", f"HTTP {resp.status_code}") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        print(f"  ⚠ Async insights start failed ({resp.status_code}): {_sanitize(msg)} — skipping insights", file=sys.stderr)
        return []

    job_id = resp.json().get("report_run_id")
    if not job_id:
        print("  ⚠ No report_run_id in async insights response — skipping insights", file=sys.stderr)
        return []

    # Poll until complete (max 5 minutes)
    print(f"  Async job {job_id} started, polling...", file=sys.stderr)
    for attempt in range(60):
        time.sleep(5)
        try:
            status_resp = requests.get(
                f"{GRAPH_API_BASE}/{cfg['api_version']}/{job_id}",
                params={"access_token": cfg["token"], "fields": "async_status,async_percent_completion"},
                timeout=30,
            )
            status = status_resp.json()
        except Exception:
            continue

        pct = status.get("async_percent_completion", 0)
        job_status = status.get("async_status", "")
        print(f"  Job status: {job_status} ({pct}%)", file=sys.stderr)

        if job_status == "Job Completed":
            data = _graph_get(f"{job_id}/insights", cfg, {"limit": 500})
            return data.get("data", [])

        if job_status in ("Job Failed", "Job Skipped"):
            print(f"  ⚠ Async insights job failed ({job_status}) — skipping insights", file=sys.stderr)
            return []

    print("  ⚠ Async insights job timed out after 5 min — skipping insights", file=sys.stderr)
    return []


def fetch_creatives(cfg: dict[str, str]) -> list[dict]:
    data = _graph_get(
        f"{cfg['account_id']}/adcreatives",
        cfg,
        {"fields": ",".join(CREATIVE_FIELDS), "limit": 200},
    )
    return data.get("data", [])


def fetch_pixels(cfg: dict[str, str]) -> list[dict]:
    """Pixels (adspixels) — critical for tracking audit."""
    fields = "id,name,code,last_fired_time,is_created_by_business,data_use_setting,automatic_matching_fields,first_party_cookie_status"
    data = _graph_get(
        f"{cfg['account_id']}/adspixels",
        cfg,
        {"fields": fields, "limit": 50},
    )
    return data.get("data", [])


def build_snapshot(cfg: dict[str, str], date_preset: str) -> dict:
    """Pull all audit-relevant data into one structured dict."""
    print(f"→ Fetching account info for {cfg['account_id']}...", file=sys.stderr)
    account = fetch_account_info(cfg)

    print("→ Fetching campaigns...", file=sys.stderr)
    campaigns = fetch_campaigns(cfg)
    print(f"  found {len(campaigns)} campaigns", file=sys.stderr)

    print("→ Fetching ad sets...", file=sys.stderr)
    adsets = fetch_adsets(cfg)
    print(f"  found {len(adsets)} ad sets", file=sys.stderr)

    print("→ Fetching ads...", file=sys.stderr)
    ads = fetch_ads(cfg)
    print(f"  found {len(ads)} ads", file=sys.stderr)

    print(f"→ Fetching insights (date_preset={date_preset})...", file=sys.stderr)
    insights = {
        "campaign": fetch_insights(cfg, "campaign", date_preset),
        "adset": fetch_insights(cfg, "adset", date_preset),
        "ad": fetch_insights(cfg, "ad", date_preset),
    }
    print(f"  campaign-level: {len(insights['campaign'])}, adset-level: {len(insights['adset'])}, ad-level: {len(insights['ad'])}", file=sys.stderr)

    print("→ Fetching creatives...", file=sys.stderr)
    creatives = fetch_creatives(cfg)
    print(f"  found {len(creatives)} creatives", file=sys.stderr)

    print("→ Fetching pixels...", file=sys.stderr)
    pixels = fetch_pixels(cfg)
    print(f"  found {len(pixels)} pixels", file=sys.stderr)

    return {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "api_version": cfg["api_version"],
        "date_preset": date_preset,
        "account": account,
        "campaigns": campaigns,
        "adsets": adsets,
        "ads": ads,
        "insights": insights,
        "creatives": creatives,
        "pixels": pixels,
        "summary": {
            "campaigns_count": len(campaigns),
            "adsets_count": len(adsets),
            "ads_count": len(ads),
            "active_campaigns": sum(1 for c in campaigns if c.get("effective_status") == "ACTIVE"),
            "creatives_count": len(creatives),
            "pixels_count": len(pixels),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Meta Ads Manager data via Marketing API for /ads meta audit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
    META_ACCESS_TOKEN    (required) System User token with ads_read scope
    META_AD_ACCOUNT_ID   (required) act_XXXXXXXXX or raw number
    META_API_VERSION     (optional) default: v20.0
    META_DATE_PRESET     (optional) default: last_30d

Examples:
    python fetch_meta_ads.py --output meta-snapshot.json
    python fetch_meta_ads.py --days 7
    META_AD_ACCOUNT_ID=act_9999 python fetch_meta_ads.py --output client.json
""",
    )
    parser.add_argument("--output", "-o", metavar="FILE", help="Output file (default: stdout)")
    parser.add_argument("--account-id", metavar="ID", help="Override META_AD_ACCOUNT_ID env var")
    parser.add_argument("--date-preset",
                        choices=["today", "yesterday", "last_3d", "last_7d", "last_14d",
                                 "last_28d", "last_30d", "last_90d", "this_month", "last_month"],
                        default=None,
                        help="Insights time range (default: last_30d)")
    parser.add_argument("--days", type=int, metavar="N",
                        help="Shorthand: --days 7 → last_7d, --days 30 → last_30d, etc.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    args = parser.parse_args()

    if args.account_id:
        os.environ["META_AD_ACCOUNT_ID"] = args.account_id

    cfg = _get_config()

    # Resolve date preset
    date_preset = args.date_preset
    if not date_preset and args.days:
        day_map = {1: "today", 3: "last_3d", 7: "last_7d", 14: "last_14d",
                   28: "last_28d", 30: "last_30d", 90: "last_90d"}
        date_preset = day_map.get(args.days)
        if not date_preset:
            print(f"Error: --days must be one of {sorted(day_map.keys())}", file=sys.stderr)
            sys.exit(1)
    date_preset = date_preset or os.environ.get("META_DATE_PRESET", DEFAULT_DATE_PRESET)

    snapshot = build_snapshot(cfg, date_preset)

    output_json = json.dumps(snapshot, indent=2 if args.pretty else None, default=str)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_json)
        print(f"\n✓ Snapshot written to {args.output} ({len(output_json):,} bytes)", file=sys.stderr)
        print(f"  Campaigns: {snapshot['summary']['campaigns_count']} "
              f"(active: {snapshot['summary']['active_campaigns']})", file=sys.stderr)
        print(f"  Ads: {snapshot['summary']['ads_count']}  "
              f"Creatives: {snapshot['summary']['creatives_count']}  "
              f"Pixels: {snapshot['summary']['pixels_count']}", file=sys.stderr)
        print(f"\n  Next: run /ads meta in Claude Code to analyze.", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
