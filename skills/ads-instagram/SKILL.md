---
name: ads-instagram
description: "Instagram Business audit covering organic content performance, audience health, conversion optimization, and organic-to-paid integration. Evaluates 32 checks across content strategy, reach, monetization, and Meta Ads sync. Use when user says Instagram, IG, Instagram marketing, Instagram ads, Reels strategy, or Instagram organic."
user-invokable: true
---

# Instagram Business Deep Analysis

## Context: 2026 Instagram Algorithm

Instagram's ranking engine prioritizes in this order:
1. **Send rate** — Reels/posts shared via DM. Most powerful reach signal.
2. **Watch-through rate** — Finishing a Reel (>60% = strong signal)
3. **Saves** — "I'll come back to this." Strongest content value signal for Feed.
4. **Comments** — Especially multi-word replies; emoji-only comments weighted less.
5. **Likes** — Weighted lower than saves/comments.

**Carousels** get 2.8× more dwell time than single images.
**Reels** reach 2-4× more non-followers than static posts.
**Stories** are a relationship channel, not a discovery channel.

---

## Process

### Step 1: Collect Instagram Data

**Live API mode (preferred):** If `META_ACCESS_TOKEN` and `META_AD_ACCOUNT_ID` are set, fetch fresh data:

```bash
python ~/.claude/skills/ads/scripts/fetch_instagram.py \
    --output ./instagram-snapshot.json \
    --days 30
```

This pulls: profile info, recent media (Reels/Feed/Stories/Carousels), post-level insights (reach, engagement, saves, watch-through), account-level trends, and audience demographics.

> **Scope note:** Full engagement metrics require `instagram_manage_insights` scope.
> If post insights return empty, the script will warn and continue with structural analysis.
> To add the scope: re-run the OAuth flow adding `instagram_manage_insights,instagram_basic,pages_read_engagement` to the scope parameter.

If the script errors with exit code 2 (auth), check:
- Token has `instagram_manage_insights` scope
- Instagram Business Account is linked to the Business Manager
- Set `IG_USER_ID` manually if auto-discovery fails

**Manual mode (fallback):** If no env vars, ask the user to provide:
- A screenshot of Instagram Insights → Overview (last 30 days)
- A screenshot of Instagram Insights → Content (sorted by reach)
- Their Instagram handle for profile analysis

### Step 2: Analyze

1. Read `ads/references/instagram-audit.md` for full 32-check audit
2. Read `ads/references/benchmarks.md` for Instagram benchmarks
3. Read `ads/references/scoring-system.md` for weighted scoring
4. Parse `instagram-snapshot.json` if available, otherwise analyze from screenshots/manual data
5. Evaluate all 32 checks as PASS, WARNING, or FAIL
6. Calculate Instagram Health Score (0-100)
7. Generate findings report with action plan

---

## What to Analyze

### Content & Creative (30% weight)

**Format mix assessment:**
- What % of recent posts are Reels? Target ≥40%.
- Are carousels being used? (2.8× dwell time vs single image)
- Is video in 9:16 format? Horizontal video is penalized in Reels.
- What's the posting cadence? Gaps >14 days hurt algorithmic priority.

**Quality signals:**
- Do Reels have a strong hook in the first 1-3 seconds?
- Are captions optimized? (Reels: ≤72 chars visible, CTA included)
- Are 3-5 relevant hashtags used? (Not 30-hashtag spam — deprecated)
- Is trending or original audio used in ≥50% of Reels?
- Is there UGC or community content (≥20% target)?

### Audience & Reach (25% weight)

**Engagement health:**
- Overall engagement rate vs industry benchmark (food: 2-4%)
- Reel watch-through rate (>60% = strong)
- Saves rate per post (>1% of reach = save-worthy content)
- Story completion rate (>70% = good)
- Follower growth trend (MoM %)
- Is the audience in the right geography for the business?
- Profile-to-follow conversion rate

### Conversion & Monetization (25% weight)

**Profile optimization:**
- Is the link in bio active and pointing to a conversion destination?
- Does the bio have a clear CTA?
- Are Story link stickers used on relevant Stories?
- Are Highlights organized by customer journey?
- Is contact info complete (phone, email, WhatsApp, address)?
- What's the DM response speed? (Meta shows a response badge at <1h avg)

**For restaurants specifically:**
- Is there a reservation/order CTA in the bio?
- Are "Book" or "Order Food" action buttons enabled?
- Are special offers/events announced with direct links?

### Organic + Paid Integration (20% weight)

**Meta Ads sync:**
- Are the top-performing organic posts being boosted as paid ads?
- Are Reels being converted to paid Reel ads?
- Partnership Ads (Branded Content) tested with creators?
- Is a Custom Audience built from Instagram profile engagers?
- Is Instagram placement performance tracked monthly in Ads Manager?
- Do all Instagram ad links have UTM parameters?
- Are Instagram-native formats (9:16) used in paid ads vs repurposed FB formats?

---

## Scoring Algorithm

Uses the weighted scoring from `scoring-system.md`:
- PASS = full points (severity × category weight)
- WARNING = 50% points
- FAIL = 0 points
- N/A = excluded from possible total

**Instagram Health Score thresholds:**
| Score | Grade | Meaning |
|-------|-------|---------|
| 90-100 | A | Benchmark-setting account |
| 75-89 | B | Strong presence, minor gaps |
| 60-74 | C | Functional but missing key formats |
| 40-59 | D | Significant structural gaps |
| <40 | F | Urgent rebuild needed |

---

## Output

### Instagram Health Score

```
Instagram Health Score: XX/100 (Grade: X)

Content & Creative:          XX/100  ████████░░  (30%)
Audience & Reach:            XX/100  ██████░░░░  (25%)
Conversion & Monetization:   XX/100  █████░░░░░  (25%)
Organic + Paid Integration:  XX/100  ████░░░░░░  (20%)
```

### Deliverables
- `INSTAGRAM-REPORT.md`: Full 32-check findings with pass/warning/fail
- Top 5 posts by reach (and whether they're being boosted as ads)
- Content mix gap analysis (what formats are missing)
- Quick Wins sorted by impact
- Scope upgrade path if `instagram_manage_insights` is missing

---

## Restaurant / Food Brand Specific Notes

For accounts like Sociedad Gourmet:

**Content that typically performs best:**
- Reels: plating process, kitchen behind-scenes, table setup, cocktail making
- Carousels: "Nuestros X platos más pedidos", event recap in 8 slides
- Stories: daily specials, polls ("¿Qué prefieres?"), countdown to event
- Feed: hero dish photography, event announcements, team spotlight

**Conversion focus:**
- Every post should have a path to action: "Reserva en el link 👆", "WhatsApp directo en bio"
- Seasonal/limited menus get highest save rates (scarcity signal)
- Behind-scenes videos have highest share rate (shareability = DM sends = reach multiplier)

**Organic + Paid pipeline for restaurants:**
1. Post Reel organically → monitor 48h → if >avg reach, boost immediately
2. Best monthly carousel → convert to Instagram Feed ad (4:5 crop)
3. Event announcement → boost Story with "Swipe Up" link to reservations
4. Use Instagram engagers Custom Audience for retargeting (30-day window)
