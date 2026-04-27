# Claude Ads — Setup Guide
<!-- For the Sociedad Gourmet marketing team -->

## What this tool does

Claude Ads is a marketing analysis tool built into Claude Code. It audits Instagram accounts,
Meta Ads, Google Ads, and landing pages — then generates reports with specific action items.

It already has all of Sociedad Gourmet's 19 Instagram accounts analyzed. New analysis runs
in minutes against live API data.

---

## One-time setup (20 minutes)

### Step 1 — Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
claude   # opens the assistant
```

### Step 2 — Install claude-ads

```bash
curl -fsSL https://github.com/AgriciDaniel/claude-ads/raw/main/install.sh | bash
```

Or if you have the project files locally:

```bash
cd /path/to/claude-ads
bash install.sh --local
```

### Step 3 — Set up credentials

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
# Edit .env with your tokens (see instructions inside the file)
```

Add to your shell profile so they load automatically:

```bash
echo 'source ~/Desktop/claude-ads/.env' >> ~/.zshrc
source ~/.zshrc
```

Verify everything is connected:

```bash
python3 ~/.claude/skills/ads/scripts/fetch_portfolio.py --check
```

### Step 4 — Get the Meta Access Token

1. Go to: https://developers.facebook.com/tools/explorer/
2. Select App: **Sociedad Gourmet** (or your Business App)
3. Click **Generate Access Token**
4. Add these permissions: `ads_read`, `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`, `business_management`
5. Copy the token into `.env` as `META_ACCESS_TOKEN`
6. Convert to long-lived token (valid 60 days instead of 1 hour):

```bash
curl "https://graph.facebook.com/v20.0/oauth/access_token?grant_type=fb_exchange_token&client_id=YOUR_APP_ID&client_secret=YOUR_APP_SECRET&fb_exchange_token=YOUR_SHORT_TOKEN"
```

---

## Daily usage

Open Claude Code in any folder and run a slash command:

| What you want | Command |
|---------------|---------|
| Audit all Instagram accounts | `/ads instagram` |
| Audit Meta Ads campaigns | `/ads meta` |
| Review budget allocation | `/ads budget` |
| Check landing pages | `/ads landing` |
| Competitor analysis | `/ads competitor` |
| Full multi-platform audit | `/ads audit` |
| Generate content calendar | `/ads creative` |
| ROAS / CPA calculator | `/ads math` |
| Design A/B test | `/ads test` |
| Strategic ad plan | `/ads plan restaurant` |

### Refreshing portfolio data

Run before any audit to get the latest data:

```bash
python3 ~/.claude/skills/ads/scripts/fetch_portfolio.py \
  --output ~/Desktop/portfolio-snapshot.json
```

Then open Claude Code and run `/ads instagram`.

### Regenerating all 19 Instagram reports

```bash
python3 ~/.claude/skills/ads/scripts/generate_instagram_reports.py \
  --input ~/Desktop/portfolio-snapshot.json \
  --output-dir ~/Desktop/instagram-reports/
```

---

## Sociedad Gourmet account reference

### Meta Ads
- **Ad Account**: act_6046447143088
- **Business Manager**: Connected via marketingsociedadgourmetec@gmail.com
- **Current spend**: $39.20/day (post boosts only — see BUDGET-REPORT.md)

### Google Ads accounts
| Brand | Customer ID |
|-------|------------|
| La Única Cumbaya | 696-895-3180 |
| Negroni Quito | 279-922-0639 |
| La Única Cuenca | 961-397-6299 |

### Instagram accounts (19 active)
| Tier | Accounts |
|------|---------|
| 🔴 Flagship (>40K) | @negroni_gye (101K), @negroni_ec (89K), @lola_sky_bar (47K), @negroni_uio (48K), @lola_izakaya_grill (41K) |
| 🟡 Growth (20–40K) | @cafedelmuseoec (29K), @hotelsantalucia (25K), @royalpalmgalapagos (25K), @petit_palace_cue (24K), @cantina.launica.cue (23K), @sr_miyagi_ec (22K), @cantina.launica.uio (11K) |
| 🟠 Developing (<20K) | @melattec (15K), @darkburger_ec (13K), @gran_salon_negroni (6K), @lacreme_ec, @lolalolita, @cocotteec, @zucompra_ec |

---

## Reports already generated (Desktop)

| File | Contents |
|------|---------|
| `PORTFOLIO-REPORT.md` | All 19 IG accounts — score, followers, gaps |
| `META-ADS-REPORT.md` | Meta Ads 50-check audit — 23/100 score |
| `BUDGET-REPORT.md` | Budget architecture — $150/day recommendation |
| `LANDING-REPORT.md` | All 18 websites — schema, pixel, WhatsApp gaps |
| `COMPETITOR-REPORT.md` | El Mercado, Hilton Colón analysis |
| `CREATIVE-CALENDAR.md` | May 2026 calendar + brand playbooks |
| `GOOGLE-ADS-REPORT.md` | 3 Google Ads accounts — all campaigns stopped |
| `instagram-reports/` | 19 individual account reports |

---

## Token refresh schedule

| Token | Expiry | Where to refresh |
|-------|--------|-----------------|
| META_ACCESS_TOKEN | 60 days | developers.facebook.com/tools/explorer |
| TIKTOK_ACCESS_TOKEN | 1 year | python3 fetch_tiktok_ads.py --auth |
| Google Ads refresh token | Never* | Only if app credentials change |

*Google OAuth2 refresh tokens don't expire unless revoked.

---

## Troubleshooting

**"META_ACCESS_TOKEN not set"**
→ Run `source ~/.zshrc` or reopen terminal, then check: `echo $META_ACCESS_TOKEN`

**"instagram_manage_insights scope missing"**
→ Re-generate token at developers.facebook.com/tools/explorer with that scope added

**"portfolio-snapshot.json not found"**
→ Run `python3 fetch_portfolio.py` first to generate fresh data

**Script exits with code 2 (auth error)**
→ Token expired. Generate a new one and update `.env`

---

*Last updated: April 2026 | claude-ads v1.5*
