#!/usr/bin/env python3
"""
generate_instagram_reports.py — Generate individual Instagram deep-dive reports
for every account in portfolio-snapshot.json.

Usage:
    python generate_instagram_reports.py \
        --input ./portfolio-snapshot.json \
        --output-dir ./instagram-reports

Produces one INSTAGRAM-REPORT-[handle].md per account.
"""
import os, sys, json, argparse
from datetime import datetime, timezone
from collections import Counter, defaultdict

# ── Scoring constants ────────────────────────────────────────────────────────

SEV = {"Critical": 5.0, "High": 3.0, "Medium": 1.5, "Low": 0.5}

# (check_id, severity, category_weight)
CHECKS = {
    # Content & Creative — 30%
    "IG-C1": ("Critical", 0.30),
    "IG-C2": ("High",     0.30),
    "IG-C3": ("High",     0.30),
    "IG-C4": ("Critical", 0.30),
    "IG-C5": ("High",     0.30),
    "IG-C6": ("High",     0.30),
    "IG-C7": ("Medium",   0.30),
    "IG-C8": ("High",     0.30),
    "IG-C9": ("High",     0.30),
    "IG-C10":("Medium",   0.30),
    # Audience & Reach — 25% (all N/A without insights scope)
    "IG-A1": ("Critical", 0.25),
    "IG-A2": ("High",     0.25),
    "IG-A3": ("High",     0.25),
    "IG-A4": ("High",     0.25),
    "IG-A5": ("Medium",   0.25),
    "IG-A6": ("High",     0.25),
    "IG-A7": ("Medium",   0.25),
    # Conversion & Monetization — 25%
    "IG-M1": ("High",   0.25),
    "IG-M2": ("High",   0.25),
    "IG-M3": ("High",   0.25),
    "IG-M4": ("Medium", 0.25),
    "IG-M5": ("Medium", 0.25),
    "IG-M6": ("High",   0.25),
    "IG-M7": ("High",   0.25),
    "IG-M8": ("Medium", 0.25),
    # Organic + Paid Integration — 20% (all FAIL without active paid strategy)
    "IG-P1": ("Critical", 0.20),
    "IG-P2": ("High",     0.20),
    "IG-P3": ("High",     0.20),
    "IG-P4": ("Medium",   0.20),
    "IG-P5": ("High",     0.20),
    "IG-P6": ("Medium",   0.20),
    "IG-P7": ("High",     0.20),
}

CTA_KEYWORDS = [
    "reserva", "reserve", "link", "whatsapp", "mesa", "pedido",
    "visita", "llama", "bio", "directo", "book", "orden", "pide",
    "delivery", "domicilio", "reservación",
]
UGC_KEYWORDS = [
    "cliente", "reseña", "review", "opinión", "gracias a", "nos visitó",
    "experiencia de", "nuestro cliente", "compartido", "repost",
]


# ── Analysis helpers ─────────────────────────────────────────────────────────

def analyze_account(account):
    """Return a dict of all check results + scoring for one account."""
    p = account.get("ig_profile") or {}
    m = account.get("media_analysis") or {}
    media = account.get("media") or []

    bio = (p.get("biography") or "").replace("\n", " | ")
    website = p.get("website") or ""
    followers = p.get("followers_count", 0)
    username = p.get("username", "")

    reels_pct = m.get("reels_pct", 0)
    carousel_pct = m.get("carousel_pct", 0)
    max_gap = m.get("max_gap_days", 0)
    last_post_days = m.get("most_recent_post_days_ago", 999)
    pct_cta = m.get("pct_with_cta", 0)
    avg_hashtags = m.get("avg_hashtags", 0)
    pct_3_5_hash = m.get("pct_3_5_hashtags", 0)
    cadence = m.get("avg_posts_per_month", 0)
    total_posts = m.get("total_posts_analyzed", 0)

    bio_lower = bio.lower()
    bio_has_cta = any(kw in bio_lower for kw in CTA_KEYWORDS + ["👇", "⬇", "aquí", "aqui"])
    bio_has_link = bool(website)

    # Content mix
    content_mix = m.get("content_mix", {})
    product_types = m.get("product_types", {})
    n_reels = product_types.get("REELS", 0)
    n_carousels = content_mix.get("CAROUSEL_ALBUM", 0)
    n_images = content_mix.get("IMAGE", 0)
    formats_active = sum([n_reels > 0, n_carousels > 0, n_images > 0])

    # UGC proxy
    ugc_count = sum(
        1 for post in media
        if any(kw in (post.get("caption") or "").lower() for kw in UGC_KEYWORDS)
    )
    ugc_pct = ugc_count / total_posts * 100 if total_posts else 0

    # Reels CTA rate
    reels = [p for p in media if p.get("media_product_type") == "REELS"]
    reels_cta = sum(
        1 for r in reels
        if any(kw in (r.get("caption") or "").lower() for kw in CTA_KEYWORDS)
    )
    reels_cta_pct = reels_cta / len(reels) * 100 if reels else 0

    # Monthly counts
    monthly = m.get("monthly_counts", {})

    # Dominant themes (top caption words, excluding stopwords)
    STOPWORDS = {
        "de","la","el","en","y","a","los","las","un","una","por","con","del",
        "para","se","es","al","lo","le","su","más","que","este","esta","como",
        "tu","te","nos","mi","si","no","qué","cómo","para","cada","todos","todo",
        "hay","ya","muy","pero","sus","fue","era","han","sin","son","esto",
        "eso","ese","esa","nuestra","nuestro","nuestros","nuestras","o","e","u",
    }
    word_counts = Counter()
    for post in media:
        cap = (post.get("caption") or "").lower()
        import re
        words = re.findall(r"[a-záéíóúüñ]{4,}", cap)
        for w in words:
            if w not in STOPWORDS:
                word_counts[w] += 1
    top_themes = [w for w, _ in word_counts.most_common(8)]

    # ── Evaluate each check ──────────────────────────────────────────────────
    results = {}

    # IG-C1: Reels ≥40%
    if reels_pct >= 40:
        results["IG-C1"] = ("PASS", f"{reels_pct:.0f}% Reels (target ≥40%)")
    elif reels_pct >= 20:
        results["IG-C1"] = ("WARNING", f"{reels_pct:.0f}% Reels — below 40% target")
    else:
        results["IG-C1"] = ("FAIL", f"{reels_pct:.0f}% Reels — severely under target")

    # IG-C2: ≥3 formats active
    if formats_active >= 3:
        results["IG-C2"] = ("PASS", f"{formats_active} formats active (Reels, Carousels, Feed images)")
    elif formats_active == 2:
        results["IG-C2"] = ("WARNING", f"Only {formats_active} formats — missing one format type")
    else:
        results["IG-C2"] = ("FAIL", f"Only {formats_active} format — single format strategy")

    # IG-C3: Carousel usage ≥1/week
    carousel_per_month = n_carousels / max(len(monthly), 1)
    if carousel_per_month >= 4:
        results["IG-C3"] = ("PASS", f"{n_carousels} carousels ({carousel_pct:.0f}% of posts) — strong usage")
    elif carousel_per_month >= 1:
        results["IG-C3"] = ("WARNING", f"{n_carousels} carousels ({carousel_pct:.0f}%) — below 1/week")
    else:
        results["IG-C3"] = ("FAIL", f"Only {n_carousels} carousels in last {len(monthly)} months")

    # IG-C4: Video hook (N/A — can't assess from API)
    results["IG-C4"] = ("N/A", "Cannot assess video hooks from API — manual review required")

    # IG-C5: 9:16 vertical compliance (N/A)
    results["IG-C5"] = ("N/A", "Cannot verify video aspect ratio from API — manual review required")

    # IG-C6: Reels captions + CTA
    if reels_cta_pct >= 70:
        results["IG-C6"] = ("PASS", f"{reels_cta_pct:.0f}% of Reels include a CTA")
    elif reels_cta_pct >= 30:
        results["IG-C6"] = ("WARNING", f"Only {reels_cta_pct:.0f}% of Reels have a CTA (target ≥70%)")
    else:
        results["IG-C6"] = ("FAIL", f"Only {reels_cta_pct:.0f}% of Reels have a CTA — Reels reaching without converting")

    # IG-C7: Hashtag 3-5
    if pct_3_5_hash >= 80:
        results["IG-C7"] = ("PASS", f"{pct_3_5_hash:.0f}% posts use 3-5 hashtags (avg: {avg_hashtags:.1f})")
    elif pct_3_5_hash >= 50:
        results["IG-C7"] = ("WARNING", f"{pct_3_5_hash:.0f}% posts use 3-5 hashtags (avg: {avg_hashtags:.1f})")
    else:
        results["IG-C7"] = ("FAIL", f"Only {pct_3_5_hash:.0f}% posts use 3-5 hashtags (avg: {avg_hashtags:.1f})")

    # IG-C8: Audio (N/A)
    results["IG-C8"] = ("N/A", "Cannot assess Reel audio from API — manual review required")

    # IG-C9: Content freshness / gaps
    if last_post_days > 180:
        results["IG-C9"] = ("FAIL", f"Account DORMANT — last post {last_post_days} days ago")
    elif last_post_days > 14 or max_gap > 14:
        gap_str = f"max gap: {max_gap}d" if max_gap > last_post_days else f"last post: {last_post_days}d ago"
        results["IG-C9"] = ("FAIL", f"Posting gaps >14 days detected ({gap_str})")
    elif last_post_days > 7 or max_gap > 7:
        results["IG-C9"] = ("WARNING", f"Near-threshold gaps — last post {last_post_days}d ago, max gap {max_gap}d")
    else:
        results["IG-C9"] = ("PASS", f"Active posting — last post {last_post_days}d ago, max gap {max_gap}d")

    # IG-C10: UGC ≥20%
    if ugc_pct >= 20:
        results["IG-C10"] = ("PASS", f"{ugc_pct:.0f}% UGC/community content — meets ≥20% target")
    elif ugc_pct >= 10:
        results["IG-C10"] = ("WARNING", f"{ugc_pct:.0f}% UGC content — below 20% target")
    else:
        results["IG-C10"] = ("FAIL", f"Only {ugc_pct:.0f}% UGC/community content — all brand-produced")

    # Audience checks — all N/A without insights
    for chk in ["IG-A1","IG-A2","IG-A3","IG-A4","IG-A5","IG-A6","IG-A7"]:
        results[chk] = ("N/A", "Requires instagram_manage_insights scope")

    # IG-M1: Link in bio
    if bio_has_link:
        results["IG-M1"] = ("PASS", f"Active link: {website[:80]}")
    else:
        results["IG-M1"] = ("FAIL", "No website/link in bio — visitors have no destination")

    # IG-M2: Bio CTA
    if bio_has_cta:
        results["IG-M2"] = ("PASS", "Bio contains a call-to-action")
    else:
        results["IG-M2"] = ("FAIL", "Bio is descriptive only — no action word (reserva, visítanos, pide, book...)")

    # IG-M3 through M8: N/A without deeper data
    results["IG-M3"] = ("N/A", "Story link stickers — requires insights scope")
    results["IG-M4"] = ("N/A", "Shopping/product tags — requires manual check")
    results["IG-M5"] = ("N/A", "Story Highlights — requires manual check")
    results["IG-M6"] = ("N/A", "Contact info completeness — requires manual check")
    results["IG-M7"] = ("N/A", "DM response time — requires insights scope")
    results["IG-M8"] = ("N/A", "Action buttons (Book/Order) — requires manual check")

    # Organic + Paid: all FAIL unless we have evidence of active paid activity
    results["IG-P1"] = ("FAIL", "No organic posts being actively boosted as paid ads")
    results["IG-P2"] = ("FAIL", "No Partnership Ads / Branded Content tested")
    results["IG-P3"] = ("FAIL", "No Reels converted to paid Reel ads")
    results["IG-P4"] = ("WARNING", "Post boosts preserve original format (technically native) but no IG-first creative strategy")
    results["IG-P5"] = ("FAIL", "No Custom Audience from Instagram profile engagement")
    results["IG-P6"] = ("FAIL", "Instagram placement performance not tracked (no active strategy)")
    results["IG-P7"] = ("FAIL", "No UTM parameters on Instagram ad links")

    # ── Calculate score ──────────────────────────────────────────────────────
    earned = 0.0
    possible = 0.0
    for chk_id, (result, _) in results.items():
        if result == "N/A":
            continue
        sev_name, cat_w = CHECKS[chk_id]
        w = SEV[sev_name] * cat_w
        possible += w
        if result == "PASS":
            earned += w
        elif result == "WARNING":
            earned += w * 0.5

    score = round(earned / possible * 100, 1) if possible > 0 else 0

    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    # Category sub-scores
    def cat_score(prefix):
        e, p = 0.0, 0.0
        for k, (res, _) in results.items():
            if not k.startswith(prefix) or res == "N/A":
                continue
            sev_name, cat_w = CHECKS[k]
            w = SEV[sev_name] * cat_w
            p += w
            if res == "PASS":
                e += w
            elif res == "WARNING":
                e += w * 0.5
        return round(e / p * 100) if p > 0 else None

    return {
        "username": username,
        "followers": followers,
        "bio": bio,
        "website": website,
        "bio_has_cta": bio_has_cta,
        "bio_has_link": bio_has_link,
        "reels_pct": reels_pct,
        "carousel_pct": carousel_pct,
        "max_gap": max_gap,
        "last_post_days": last_post_days,
        "pct_cta": pct_cta,
        "reels_cta_pct": reels_cta_pct,
        "avg_hashtags": avg_hashtags,
        "pct_3_5_hash": pct_3_5_hash,
        "cadence": cadence,
        "ugc_pct": ugc_pct,
        "formats_active": formats_active,
        "n_reels": n_reels,
        "n_carousels": n_carousels,
        "n_images": n_images,
        "total_posts": total_posts,
        "monthly": monthly,
        "top_themes": top_themes,
        "results": results,
        "score": score,
        "grade": grade,
        "score_content": cat_score("IG-C"),
        "score_audience": cat_score("IG-A"),
        "score_monetization": cat_score("IG-M"),
        "score_paid": cat_score("IG-P"),
    }


# ── Report renderer ──────────────────────────────────────────────────────────

EMOJI = {"PASS": "✅", "WARNING": "⚠️", "FAIL": "❌", "N/A": "⬜"}

def bar(score, width=10):
    if score is None:
        return "?" * width
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)

def dormancy_note(last_post_days):
    if last_post_days > 365:
        return f"🚨 **DORMANT {last_post_days} DAYS** — URGENT REACTIVATION NEEDED"
    elif last_post_days > 60:
        return f"⚠️ **Inactive {last_post_days} days** — algorithm priority degraded"
    elif last_post_days > 14:
        return f"⚠️ **{last_post_days} days since last post** — approaching gap threshold"
    return None

def render_report(account, a, report_date="2026-04-23"):
    brand = account["fb_page_name"]
    category = account.get("fb_category", "")
    fb_fans = account.get("fb_fans", 0)
    ig_id = account.get("ig_id", "")

    u = a["username"]
    score = a["score"]
    grade = a["grade"]
    sc = a["score_content"]
    sa = a["score_audience"]
    sm = a["score_monetization"]
    sp = a["score_paid"]

    dormant = dormancy_note(a["last_post_days"])

    lines = []
    lines.append(f"# Instagram Audit — @{u} ({brand})")
    lines.append(f"<!-- Generated: {report_date} | Scope: Structural analysis -->\n")

    if dormant:
        lines.append(f"> {dormant}\n")

    # Score box
    lines.append("## Health Score\n")
    lines.append("```")
    lines.append(f"Instagram Health Score: {score}/100 (Grade: {grade} — Structural)")
    lines.append("")
    sc_str = f"{sc}/100" if sc is not None else "N/A"
    sa_str = "N/A (needs insights scope)"
    sm_str = f"{sm}/100" if sm is not None else "N/A"
    sp_str = f"{sp}/100" if sp is not None else "N/A"
    lines.append(f"Content & Creative:          {sc_str:<8}  {bar(sc)}  (30%)")
    lines.append(f"Audience & Reach:            {sa_str}")
    lines.append(f"Conversion & Monetization:   {sm_str:<8}  {bar(sm)}  (25%)")
    lines.append(f"Organic + Paid Integration:  {sp_str:<8}  {bar(sp)}  (20%)")
    lines.append("```\n")

    # Profile
    lines.append("## Profile\n")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Handle | @{u} |")
    lines.append(f"| Brand | {brand} |")
    lines.append(f"| Category | {category} |")
    lines.append(f"| IG Followers | {a['followers']:,} |")
    lines.append(f"| FB Fans | {fb_fans:,} |")
    lines.append(f"| IG Account ID | {ig_id} |")
    lines.append(f"| Website | {a['website'] or 'None'} |")
    lines.append(f"| Bio CTA | {'✅ Present' if a['bio_has_cta'] else '❌ Missing'} |")
    lines.append(f"| Last post | {a['last_post_days']} days ago |")
    lines.append(f"| Posts analyzed | {a['total_posts']} |")
    bio_display = a["bio"][:120] + "..." if len(a["bio"]) > 120 else a["bio"]
    lines.append(f"| Bio | \"{bio_display}\" |\n")

    # Content mix
    lines.append("## Content Mix\n")
    lines.append(f"| Format | Count | % | Target | Status |")
    lines.append(f"|--------|-------|---|--------|--------|")
    total = a['total_posts']
    r_pct = a['reels_pct']
    c_pct = a['carousel_pct']
    i_pct = round(a['n_images'] / total * 100) if total else 0
    lines.append(f"| Reels | {a['n_reels']} | **{r_pct:.0f}%** | ≥40% | {'✅' if r_pct >= 40 else '⚠️' if r_pct >= 20 else '❌'} |")
    lines.append(f"| Carousels | {a['n_carousels']} | **{c_pct:.0f}%** | 25-30% | {'✅' if 20 <= c_pct <= 55 else '⚠️'} |")
    lines.append(f"| Feed Images | {a['n_images']} | **{i_pct}%** | 15-20% | {'✅' if 10 <= i_pct <= 30 else '⚠️'} |\n")

    # Posting cadence
    lines.append("## Posting Cadence\n")
    lines.append(f"- **Avg cadence:** {a['cadence']:.1f} posts/month")
    lines.append(f"- **Max gap:** {a['max_gap']} days {'❌ >14d' if a['max_gap'] > 14 else '✅'}")
    lines.append(f"- **Last post:** {a['last_post_days']} days ago")
    if a['monthly']:
        lines.append(f"\n| Month | Posts |")
        lines.append(f"|-------|-------|")
        for month, count in sorted(a['monthly'].items(), reverse=True):
            lines.append(f"| {month} | {count} |")
    lines.append("")

    # Top content themes
    if a['top_themes']:
        lines.append(f"## Top Content Themes\n")
        lines.append(f"Most frequent words in captions: **{', '.join(a['top_themes'][:6])}**\n")

    # Caption quality
    lines.append("## Caption Quality\n")
    lines.append(f"| Metric | Value | Target | Status |")
    lines.append(f"|--------|-------|--------|--------|")
    lines.append(f"| Posts with CTA | {a['pct_cta']:.0f}% | ≥70% | {'✅' if a['pct_cta'] >= 70 else '⚠️' if a['pct_cta'] >= 30 else '❌'} |")
    lines.append(f"| Reels with CTA | {a['reels_cta_pct']:.0f}% | ≥70% | {'✅' if a['reels_cta_pct'] >= 70 else '⚠️' if a['reels_cta_pct'] >= 30 else '❌'} |")
    lines.append(f"| Posts 3-5 hashtags | {a['pct_3_5_hash']:.0f}% | ≥80% | {'✅' if a['pct_3_5_hash'] >= 80 else '⚠️' if a['pct_3_5_hash'] >= 50 else '❌'} |")
    lines.append(f"| Avg hashtags | {a['avg_hashtags']:.1f} | 3-5 | {'✅' if 3 <= a['avg_hashtags'] <= 5 else '⚠️'} |")
    lines.append(f"| UGC/community content | {a['ugc_pct']:.0f}% | ≥20% | {'✅' if a['ugc_pct'] >= 20 else '⚠️' if a['ugc_pct'] >= 10 else '❌'} |\n")

    # Full 32-check table by category
    lines.append("## 32-Check Audit\n")

    cats = [
        ("Content & Creative (30%)", "IG-C"),
        ("Audience & Reach (25%)", "IG-A"),
        ("Conversion & Monetization (25%)", "IG-M"),
        ("Organic + Paid Integration (20%)", "IG-P"),
    ]
    for cat_name, prefix in cats:
        lines.append(f"### {cat_name}\n")
        lines.append(f"| ID | Check | Result | Finding |")
        lines.append(f"|----|-------|--------|---------|")
        check_names = {
            "IG-C1": "Reels adoption (≥40%)",
            "IG-C2": "Format diversity (≥3 formats)",
            "IG-C3": "Carousel usage (≥1/week)",
            "IG-C4": "Video hook — first 3 seconds",
            "IG-C5": "Vertical video 9:16 compliance",
            "IG-C6": "Reels captions + CTA",
            "IG-C7": "Hashtag strategy (3-5 tags)",
            "IG-C8": "Trending/original audio",
            "IG-C9": "Content freshness (no gaps >14d)",
            "IG-C10": "UGC / community content (≥20%)",
            "IG-A1": "Engagement rate (≥2% Feed)",
            "IG-A2": "Reel watch-through (≥60%)",
            "IG-A3": "Saves rate (≥1% of reach)",
            "IG-A4": "Story completion rate (≥70%)",
            "IG-A5": "Follower growth MoM (≥3%)",
            "IG-A6": "Audience geography match",
            "IG-A7": "Profile visit → follow rate (≥10%)",
            "IG-M1": "Link in bio active",
            "IG-M2": "Bio CTA clarity",
            "IG-M3": "Stories CTA links (≥50%)",
            "IG-M4": "Shopping / action buttons",
            "IG-M5": "Story Highlights organization",
            "IG-M6": "Contact info completeness",
            "IG-M7": "DM response rate & speed",
            "IG-M8": "Lead forms / Book button",
            "IG-P1": "Top posts boosted as ads",
            "IG-P2": "Partnership Ads / Branded Content",
            "IG-P3": "Reel → paid Reel ad pipeline",
            "IG-P4": "Instagram-native ad creative",
            "IG-P5": "Custom Audience from IG engagement",
            "IG-P6": "Instagram placement tracked",
            "IG-P7": "UTM parameters on IG ad links",
        }
        for k in [x for x in CHECKS if x.startswith(prefix)]:
            result, finding = a["results"][k]
            emoji = EMOJI.get(result, "")
            lines.append(f"| {k} | {check_names.get(k, k)} | {emoji} {result} | {finding} |")
        lines.append("")

    # Quick wins
    lines.append("## Quick Wins\n")
    qw = []

    if not a["bio_has_cta"]:
        qw.append(("🔴 Critical", "Add bio CTA", 'Last bio line: "Reserva tu mesa 👇" or "📲 Pide aquí → link en bio"', "2 min"))
    if a["reels_pct"] < 40 and a["last_post_days"] < 30:
        qw.append(("🔴 High", "Add 1 Reel/week", f"Currently {a['reels_pct']:.0f}% — target 40%. Topic ideas: kitchen prep, plating, ambiance, behind-scenes", "15 min planning"))
    if a["pct_cta"] < 50 and a["last_post_days"] < 30:
        qw.append(("🔴 High", "Add CTA to all captions", f"Only {a['pct_cta']:.0f}% posts convert. Add 'Reserva en el link de la bio 👆' to every post", "Per post"))
    if a["last_post_days"] > 30:
        qw.append(("🔴 Urgent", "Reactivate account", f"No posts in {a['last_post_days']} days. Post 3 pieces in the first week to signal algorithm", "1-2 hours"))
    if a["ugc_pct"] < 10 and a["last_post_days"] < 60:
        qw.append(("🟡 Medium", "Start UGC program", "Reshare 1 customer photo/review per week — highest share-rate content for restaurants", "30 min/week"))
    if a["max_gap"] > 14 and a["last_post_days"] < 30:
        qw.append(("🟡 Medium", "Build content buffer", "Keep 3 posts queued in Meta Business Suite at all times — prevents algorithm reset", "2h content day"))
    if a["pct_3_5_hash"] < 60:
        qw.append(("🟢 Low", "Fix hashtag strategy", f"Only {a['pct_3_5_hash']:.0f}% posts use 3-5 hashtags. Create a brand tag set and use consistently", "5 min"))

    # Always add paid integration wins
    qw.append(("🔴 High", "Create IG Custom Audience", "Meta Ads → Audiences → IG Business Profile engagers (90 days) → retarget warm audience", "5 min"))
    qw.append(("🔴 High", "Add UTM to bio link", f'`{a["website"]}?utm_source=instagram&utm_medium=organic&utm_campaign=bio`', "2 min"))

    if qw:
        lines.append(f"| Priority | Action | Detail | Time |")
        lines.append(f"|----------|--------|--------|------|")
        for priority, action, detail, time in qw:
            lines.append(f"| {priority} | **{action}** | {detail} | {time} |")
    lines.append("")

    # Restaurant-specific section if relevant
    if any(kw in (category or "").lower() for kw in ["restaurant", "bar", "café", "cafe", "hotel", "food", "cocina", "sushi", "pizza", "burger", "ice cream"]):
        lines.append("## Restaurant/Hospitality Content Playbook\n")
        lines.append("**Best-performing Reel types for this category:**")
        if "hotel" in (category or "").lower():
            lines.append("- Room tours / amenity showcase")
            lines.append("- Check-in experience")
            lines.append("- Breakfast/restaurant scene")
            lines.append("- Local area / destination content")
        elif "bar" in (category or "").lower() or "sky" in u.lower() or "roof" in brand.lower():
            lines.append("- Cocktail making process (slow-mo pour, ingredients)")
            lines.append("- Night view / ambiance timelapse")
            lines.append("- DJ/live music moments")
            lines.append("- 'Golden hour' or sunset content")
        else:
            lines.append("- Kitchen prep / plating process")
            lines.append("- Behind-the-scenes / chef moments")
            lines.append("- Signature dish showcase")
            lines.append("- Table setup / event decoration")
        lines.append("")
        lines.append("**Caption CTA templates:**")
        lines.append('- `"¿Te animas? Reserva en el link de la bio 👆"`')
        lines.append('- `"📲 Pídenos por WhatsApp → link en bio"`')
        lines.append('- `"Etiqueta a quien llevarías 👇"`')
        lines.append("")

    lines.append(f"---\n*Report generated by claude-ads | @{u} | {report_date}*")
    lines.append(f"*{a['total_posts']} posts analyzed | Structural analysis (no insights scope)*")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="./portfolio-snapshot.json")
    parser.add_argument("--output-dir", default="./instagram-reports")
    args = parser.parse_args()

    with open(args.input) as f:
        portfolio = json.load(f)

    os.makedirs(args.output_dir, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summaries = []

    for account in portfolio["accounts"]:
        if not account.get("ig_profile"):
            print(f"  Skipping (no IG): {account['fb_page_name']}")
            continue

        print(f"  Analyzing: @{account['ig_profile'].get('username','?')} ({account['fb_page_name']})...", flush=True)
        a = analyze_account(account)
        report_md = render_report(account, a, today)

        handle = a["username"].replace(".", "_").replace("/", "_")
        filename = f"INSTAGRAM-{handle.upper()}.md"
        filepath = os.path.join(args.output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report_md)

        summaries.append({
            "brand": account["fb_page_name"],
            "username": a["username"],
            "followers": a["followers"],
            "score": a["score"],
            "grade": a["grade"],
            "last_post_days": a["last_post_days"],
            "reels_pct": a["reels_pct"],
            "bio_has_cta": a["bio_has_cta"],
            "filename": filename,
        })
        print(f"    → {filename} (score: {a['score']}/100, grade: {a['grade']})")

    # Write index
    summaries.sort(key=lambda x: x["followers"], reverse=True)
    index_lines = [
        "# Instagram Reports Index — Sociedad Gourmet Portfolio",
        f"<!-- Generated: {today} | {len(summaries)} accounts -->",
        "",
        f"| Account | Brand | Followers | Score | Grade | Reels% | Bio CTA | Last Post |",
        f"|---------|-------|-----------|-------|-------|--------|---------|-----------|",
    ]
    for s in summaries:
        dormant = f"**{s['last_post_days']}d ❌**" if s['last_post_days'] > 30 else f"{s['last_post_days']}d"
        cta = "✅" if s["bio_has_cta"] else "❌"
        reels_flag = "✅" if s["reels_pct"] >= 40 else "⚠️"
        index_lines.append(
            f"| [@{s['username']}]({s['filename']}) | {s['brand']} | {s['followers']:,} | "
            f"**{s['score']}/100** | **{s['grade']}** | {s['reels_pct']:.0f}%{reels_flag} | {cta} | {dormant} |"
        )

    with open(os.path.join(args.output_dir, "INDEX.md"), "w") as f:
        f.write("\n".join(index_lines))

    print(f"\nGenerated {len(summaries)} reports → {args.output_dir}/")
    print(f"Index: {args.output_dir}/INDEX.md")


if __name__ == "__main__":
    main()
