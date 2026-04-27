#!/usr/bin/env python3
"""
fetch_landing_portfolio.py — Analyze all brand landing pages in the portfolio.

Fetches each brand's website, runs a full landing page audit (performance,
conversion, mobile, trust, SEO, restaurant-specific CTAs), and outputs
landing-snapshot.json for report generation.

Usage:
    python fetch_landing_portfolio.py \
        --input ./portfolio-snapshot.json \
        --output ./landing-snapshot.json
"""
import os, sys, json, argparse, re, time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-EC,es;q=0.9,en;q=0.8",
}

RESTAURANT_CTA_KEYWORDS = [
    "reserva", "reserve", "book", "reservar", "booking",
    "pedido", "order", "ordenar", "pedir",
    "whatsapp", "delivery", "domicilio",
    "menú", "menu",
    "contacto", "contact",
    "llama", "llámanos", "call",
    "mesa", "table",
]

TRUST_KEYWORDS = [
    "reseñas", "reviews", "opiniones", "testimonios",
    "calificaciones", "stars", "estrellas",
    "certificado", "certified", "award", "premio",
    "reconocido", "galardón",
]

SOCIAL_LINKS = ["instagram.com", "facebook.com", "tiktok.com", "twitter.com", "x.com"]


def fetch_url(url, timeout=15):
    """Fetch URL and return response + timing info."""
    if not url or not url.startswith("http"):
        return None, 0, "No URL"
    start = time.time()
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout,
                        allow_redirects=True)
        elapsed = (time.time() - start) * 1000
        return r, elapsed, None
    except requests.exceptions.Timeout:
        return None, timeout * 1000, "Timeout"
    except requests.exceptions.ConnectionError as e:
        return None, 0, f"Connection error: {e}"
    except Exception as e:
        return None, 0, str(e)


def analyze_page(url, brand_name, category="restaurant"):
    """Full landing page analysis for a brand page."""
    result = {
        "url": url,
        "brand": brand_name,
        "category": category,
        "fetch_time_ms": 0,
        "status_code": None,
        "error": None,
        # Content
        "title": None,
        "h1": None,
        "h2_count": 0,
        "meta_description": None,
        "word_count": 0,
        "lang": None,
        # Conversion
        "has_reservation_cta": False,
        "has_phone": False,
        "has_whatsapp": False,
        "has_form": False,
        "has_map_embed": False,
        "has_menu_link": False,
        "cta_keywords_found": [],
        "cta_above_fold_estimate": False,
        # Mobile
        "has_viewport_meta": False,
        "is_responsive": False,
        # Trust
        "has_social_links": [],
        "has_reviews_section": False,
        "has_photos": False,
        "trust_keywords_found": [],
        # Schema
        "schema_types": [],
        "has_restaurant_schema": False,
        "has_local_business_schema": False,
        # Speed proxies
        "page_size_kb": 0,
        "image_count": 0,
        "script_count": 0,
        "css_count": 0,
        "has_lazy_loading": False,
        # UTM / tracking
        "has_pixel": False,
        "has_gtag": False,
        "has_gtm": False,
        # Checks
        "checks": {},
    }

    resp, elapsed, err = fetch_url(url)
    result["fetch_time_ms"] = round(elapsed)

    if err:
        result["error"] = err
        return result

    result["status_code"] = resp.status_code
    if resp.status_code != 200:
        result["error"] = f"HTTP {resp.status_code}"
        return result

    html = resp.text
    result["page_size_kb"] = round(len(html.encode("utf-8")) / 1024, 1)
    soup = BeautifulSoup(html, "html.parser")

    # ── Content ──────────────────────────────────────────────────────────────
    result["title"] = (soup.title.string or "").strip() if soup.title else None

    h1 = soup.find("h1")
    result["h1"] = h1.get_text(strip=True)[:120] if h1 else None

    result["h2_count"] = len(soup.find_all("h2"))

    meta_desc = soup.find("meta", {"name": "description"})
    result["meta_description"] = meta_desc.get("content", "")[:200] if meta_desc else None

    body_text = soup.get_text(separator=" ", strip=True)
    result["word_count"] = len(re.findall(r"\b\w{3,}\b", body_text))

    html_tag = soup.find("html")
    result["lang"] = html_tag.get("lang", "") if html_tag else ""

    # ── Conversion ───────────────────────────────────────────────────────────
    body_lower = body_text.lower()

    found_cta = [kw for kw in RESTAURANT_CTA_KEYWORDS if kw in body_lower]
    result["cta_keywords_found"] = found_cta
    result["has_reservation_cta"] = any(kw in found_cta for kw in [
        "reserva", "reserve", "book", "reservar", "booking", "mesa", "table"
    ])

    # Phone
    phone_links = soup.find_all("a", href=re.compile(r"tel:|wa\.me|whatsapp", re.I))
    result["has_phone"] = any("tel:" in (a.get("href", "")) for a in phone_links)
    result["has_whatsapp"] = any(
        "wa.me" in (a.get("href", "")) or "whatsapp" in (a.get("href", "")).lower()
        for a in soup.find_all("a", href=True)
    )

    # Form
    result["has_form"] = bool(soup.find("form"))

    # Map embed
    result["has_map_embed"] = bool(
        soup.find("iframe", src=re.compile(r"maps\.google|google\.com/maps|openstreetmap", re.I))
    )

    # Menu link
    result["has_menu_link"] = bool(
        soup.find("a", href=re.compile(r"menu|carta|platos", re.I))
        or "menú" in body_lower
        or "menu" in body_lower
    )

    # Rough above-fold CTA estimate: any button/link in first 2KB of body
    early_html = html[:2500].lower()
    result["cta_above_fold_estimate"] = any(
        kw in early_html for kw in ["reserva", "reserve", "book", "menu", "pedir", "whatsapp"]
    )

    # ── Mobile ───────────────────────────────────────────────────────────────
    viewport = soup.find("meta", {"name": "viewport"})
    result["has_viewport_meta"] = bool(viewport)
    result["is_responsive"] = bool(viewport and "width=device-width" in (viewport.get("content", "")))

    # ── Trust ────────────────────────────────────────────────────────────────
    social = []
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        for s in SOCIAL_LINKS:
            if s in href and s not in social:
                social.append(s.split(".")[0])
    result["has_social_links"] = social

    trust_found = [kw for kw in TRUST_KEYWORDS if kw in body_lower]
    result["trust_keywords_found"] = trust_found
    result["has_reviews_section"] = len(trust_found) > 0

    imgs = soup.find_all("img")
    result["has_photos"] = len(imgs) > 3
    result["image_count"] = len(imgs)

    # ── Schema ───────────────────────────────────────────────────────────────
    schema_types = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                t = data.get("@type")
                if t:
                    schema_types.append(t if isinstance(t, str) else str(t))
                graph = data.get("@graph", [])
                for item in graph:
                    if isinstance(item, dict) and item.get("@type"):
                        schema_types.append(item["@type"])
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type"):
                        schema_types.append(item["@type"])
        except Exception:
            pass

    result["schema_types"] = schema_types
    result["has_restaurant_schema"] = any(
        t in ["Restaurant", "FoodEstablishment", "CafeOrCoffeeShop", "BarOrPub", "FastFoodRestaurant"]
        for t in schema_types
    )
    result["has_local_business_schema"] = any(
        t in ["LocalBusiness", "Restaurant", "Hotel", "LodgingBusiness"] + [
            "FoodEstablishment", "CafeOrCoffeeShop", "BarOrPub"
        ]
        for t in schema_types
    )

    # ── Speed proxies ────────────────────────────────────────────────────────
    result["script_count"] = len(soup.find_all("script", src=True))
    result["css_count"] = len(soup.find_all("link", {"rel": "stylesheet"}))
    result["has_lazy_loading"] = bool(soup.find(attrs={"loading": "lazy"}))

    # ── Tracking ─────────────────────────────────────────────────────────────
    html_lower = html.lower()
    result["has_pixel"] = "fbq(" in html_lower or "facebook pixel" in html_lower
    result["has_gtag"] = "gtag(" in html_lower or "google-analytics.com" in html_lower
    result["has_gtm"] = "googletagmanager.com" in html_lower

    # ── Checks (30 checks mapped to pass/warning/fail) ───────────────────────
    checks = {}
    # Speed
    size_kb = result["page_size_kb"]
    checks["LP-S1"] = ("PASS" if size_kb < 500 else "WARNING" if size_kb < 2000 else "FAIL",
                       f"Page HTML size: {size_kb}KB")
    checks["LP-S2"] = ("WARNING" if result["script_count"] > 15 else "PASS",
                       f"{result['script_count']} external scripts")
    checks["LP-S3"] = ("PASS" if result["has_lazy_loading"] else "FAIL",
                       "Lazy loading on images")

    # Mobile
    checks["LP-M1"] = ("PASS" if result["is_responsive"] else "FAIL",
                       "Responsive viewport meta tag")
    # Content
    checks["LP-C1"] = ("PASS" if result["h1"] else "FAIL",
                       f"H1 tag: {(result['h1'] or 'MISSING')[:60]}")
    checks["LP-C2"] = ("PASS" if result["title"] else "FAIL",
                       f"Page title: {(result['title'] or 'MISSING')[:60]}")
    checks["LP-C3"] = ("PASS" if result["meta_description"] else "WARNING",
                       "Meta description present")
    checks["LP-C4"] = ("PASS" if result["word_count"] > 200 else "WARNING",
                       f"{result['word_count']} words on page")
    checks["LP-C5"] = ("PASS" if result["h2_count"] >= 2 else "WARNING",
                       f"{result['h2_count']} H2 headings")
    # Conversion
    checks["LP-CV1"] = ("PASS" if result["has_reservation_cta"] else "FAIL",
                        "Reservation/booking CTA present")
    checks["LP-CV2"] = ("PASS" if result["cta_above_fold_estimate"] else "WARNING",
                        "CTA likely visible above fold (estimate)")
    checks["LP-CV3"] = ("PASS" if result["has_whatsapp"] or result["has_phone"] else "FAIL",
                        "WhatsApp or phone contact link")
    checks["LP-CV4"] = ("PASS" if result["has_map_embed"] else "WARNING",
                        "Map embed for location")
    checks["LP-CV5"] = ("PASS" if result["has_menu_link"] else "WARNING",
                        "Menu accessible on page")
    # Trust
    checks["LP-T1"] = ("PASS" if result["has_photos"] else "FAIL",
                       f"{result['image_count']} images on page")
    checks["LP-T2"] = ("PASS" if result["has_reviews_section"] else "WARNING",
                       "Reviews/testimonials section")
    checks["LP-T3"] = ("PASS" if len(result["has_social_links"]) >= 2 else "WARNING",
                       f"Social links: {', '.join(result['has_social_links']) or 'none'}")
    # Schema
    checks["LP-SC1"] = ("PASS" if result["has_local_business_schema"] else "FAIL",
                        f"Local Business schema: {', '.join(schema_types) or 'none'}")
    checks["LP-SC2"] = ("PASS" if result["has_restaurant_schema"] else "WARNING",
                        "Restaurant/FoodEstablishment schema")
    # Tracking
    checks["LP-TR1"] = ("PASS" if result["has_pixel"] else "FAIL",
                        "Meta Pixel installed")
    checks["LP-TR2"] = ("PASS" if result["has_gtag"] or result["has_gtm"] else "WARNING",
                        "Google Analytics / GTM installed")

    result["checks"] = checks

    # ── Score ─────────────────────────────────────────────────────────────────
    weights = {
        "LP-S1": 1, "LP-S2": 1, "LP-S3": 1,
        "LP-M1": 3,
        "LP-C1": 3, "LP-C2": 2, "LP-C3": 1, "LP-C4": 1, "LP-C5": 1,
        "LP-CV1": 5, "LP-CV2": 3, "LP-CV3": 5, "LP-CV4": 2, "LP-CV5": 3,
        "LP-T1": 2, "LP-T2": 2, "LP-T3": 1,
        "LP-SC1": 3, "LP-SC2": 2,
        "LP-TR1": 5, "LP-TR2": 3,
    }
    earned = 0
    possible = 0
    for k, (res, _) in checks.items():
        w = weights.get(k, 1)
        possible += w
        if res == "PASS":
            earned += w
        elif res == "WARNING":
            earned += w * 0.5

    result["score"] = round(earned / possible * 100) if possible else 0

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="./portfolio-snapshot.json")
    parser.add_argument("--output", default="./landing-snapshot.json")
    parser.add_argument("--delay",  type=float, default=1.5,
                        help="Seconds between requests (default: 1.5)")
    args = parser.parse_args()

    with open(args.input) as f:
        portfolio = json.load(f)

    results = []
    seen_urls = set()

    for account in portfolio["accounts"]:
        profile = account.get("ig_profile") or {}
        url = profile.get("website") or ""
        brand = account["fb_page_name"]
        category = account.get("fb_category", "restaurant")

        if not url or url in seen_urls:
            print(f"  Skipping (no URL / duplicate): {brand}")
            continue

        seen_urls.add(url)
        print(f"  Analyzing: {brand} → {url}", flush=True)
        analysis = analyze_page(url, brand, category)
        results.append(analysis)

        status = analysis.get("status_code") or "ERR"
        score = analysis.get("score", 0)
        err = analysis.get("error") or ""
        print(f"    → {status} | {analysis['fetch_time_ms']}ms | score:{score}/100 {err}")

        time.sleep(args.delay)

    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_urls": len(results),
        "pages": results,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(results)} pages → {args.output}")


if __name__ == "__main__":
    main()
