---
name: ads-generate
description: "AI image generation for paid ad creatives. Reads campaign-brief.md and brand-profile.json to produce platform-sized ad images using Google Gemini 3 Pro Image / Imagen 4 via the google-genai SDK. Triggers on: generate ads, create images, make ad creatives, generate visuals, create ad images, generate campaign images, make the images, generate from brief."
user-invokable: false
---

# Ads Generate: AI Ad Image Generator

Generates platform-sized ad creative images from your campaign brief and
brand profile. Uses Google Gemini / Imagen 4 via `scripts/generate_image.py`.

## Quick Reference

| Command | What it does |
|---------|-------------|
| `/ads generate` | Generate all images from campaign-brief.md (default quality: pro) |
| `/ads generate --platform meta` | Generate Meta assets only |
| `/ads generate --quality high` | Force Imagen 4 Ultra for photoreal product shots |
| `/ads generate --quality fast` | High-volume variants with Gemini 2.5 Flash Image |
| `/ads generate --prompt "text" --ratio 9:16` | Standalone generation without brief |

## Environment Setup

**Required before running:**

- `GOOGLE_API_KEY` environment variable set
  (get a key at https://aistudio.google.com/app/apikey)
- `google-genai>=1.16.0` installed (included in the skill's `requirements.txt`)

If `GOOGLE_API_KEY` is not set, this skill will display setup instructions
and stop. It will never fail silently.

Optional alternative providers (OpenAI, Stability AI, Replicate) are documented
in `~/.claude/skills/ads/references/image-providers.md`. Switch via
`ADS_IMAGE_PROVIDER` env var.

## Quality Presets

The `--quality` flag controls which Google model is used:

| Preset | Model | Cost/img | Use |
|--------|-------|---------:|-----|
| `pro` **(default)** | Gemini 3 Pro Image Preview | $0.134 | Hero creatives, key visuals |
| `high` | Imagen 4 Ultra | $0.06 | Photoreal product shots |
| `flash` | Gemini 3.1 Flash Image Preview | $0.067 | Multi-reference editing |
| `fast` | Gemini 2.5 Flash Image | $0.039 | Volume / A-B variants |

## Process

### Step 1: Verify Prerequisites

Check that `GOOGLE_API_KEY` is set. If not, display setup instructions:

```
export GOOGLE_API_KEY="your-key"
# Get a key at https://aistudio.google.com/app/apikey
```

### Step 2: Locate Source Files

Check for:
- `campaign-brief.md` → primary source for prompts and dimensions
- `brand-profile.json` → brand color/style injection (optional but recommended)

**If campaign-brief.md is found**: Use `## Image Generation Briefs` section as the
generation job list.

**If no campaign-brief.md**: Enter standalone mode (Step 2b).

#### Step 2b: Standalone Mode

Ask the user:
1. Generation prompt (what should the image show?)
2. Target platform (to set correct dimensions)
3. Quality preset (pro/high/flash/fast, default: pro)
4. Output filename (optional)

Then skip to Step 5.

### Step 3: Read Provider Config

Load `~/.claude/skills/ads/references/image-providers.md` to confirm:
- Current model pricing (show user the cost estimate)
- Rate limits for current tier
- Aspect ratio support per model

### Step 4: Read Platform Specs

For each platform in the campaign brief, load the relevant spec reference:
- `~/.claude/skills/ads/references/meta-creative-specs.md`
- `~/.claude/skills/ads/references/google-creative-specs.md`
- `~/.claude/skills/ads/references/tiktok-creative-specs.md`
- `~/.claude/skills/ads/references/linkedin-creative-specs.md`
- `~/.claude/skills/ads/references/youtube-creative-specs.md`
- `~/.claude/skills/ads/references/microsoft-creative-specs.md`

### Step 5: Select Quality Per Asset

Map each brief entry to the right `--quality` preset based on its purpose:

| Asset type | Preset | Why |
|------------|--------|-----|
| Hero / key visual | `pro` | Maximum reasoning + text rendering |
| Product packshot | `high` | Imagen 4 Ultra is best-in-class for photoreal products |
| Brand-reference edit | `flash` | Only Gemini 3.x accepts reference images |
| Many variants of same concept | `fast` | 3–4× cheaper per image |

### Step 6: Spawn Visual Designer Agent

Spawn the `visual-designer` agent using the Task tool with `context: fork`,
passing the selected quality preset and brand profile.

The agent will:
- Parse the image generation briefs from campaign-brief.md
- Inject brand colors and mood from brand-profile.json into each prompt
- Invoke `python ~/.claude/skills/ads/scripts/generate_image.py` per asset
- Save to `./ad-assets/[platform]/[concept]/` directory structure
- Write `generation-manifest.json`

Example call the agent runs:

```bash
python ~/.claude/skills/ads/scripts/generate_image.py \
    "Minimalist SaaS dashboard screenshot, dark UI with teal accents, clean data viz" \
    --ratio 16:9 \
    --quality pro \
    --output ./ad-assets/linkedin/concept-1/hero-1920x1080.png \
    --json
```

### Step 7: Validate with Format Adapter

After the visual-designer completes, spawn the `format-adapter` agent
with `context: fork` to validate dimensions and report missing formats.

### Step 8: Quality Gate

Use Claude vision to assess each generated image against the brief (score 1 to 10
on brand alignment, composition, platform fit). If any image scores below 6,
regenerate once with an adjusted prompt.

Quality Gate Rubric:
- 9-10: Professional quality, brand-aligned, platform-optimized, no issues
- 7-8: Good quality, minor composition or brand alignment improvements possible
- 5-6: Acceptable but needs regeneration. Text readability issues, poor composition, or brand mismatch
- Below 5: Reject. Regenerate with adjusted prompt

### Step 9: Aggregate Costs

Sum costs from each generation's JSON output (script emits `quality` and
`model` per image). Compute total using the pricing table in
`image-providers.md` and include in `generation-manifest.json`.

### Step 10: Report Results

Present a summary:
```
Generation complete:

  Generated assets:
    ✓ ./ad-assets/meta/concept-1/feed-1080x1350.png       [quality: pro, $0.134]
    ✓ ./ad-assets/tiktok/concept-1/vertical-1080x1920.png [quality: fast, $0.039]
    ✗ ./ad-assets/google/concept-1/landscape-1200x628.png [error: SAFETY]

  Format validation: See format-report.md

  Cost: $[N] total creative spend (X images)

  Next steps:
    1. Review assets in ./ad-assets/
    2. Check format-report.md for any missing formats
    3. Upload to your ad platform managers
```

## Cost Transparency

Before generating, estimate and show the cost:
- Count the number of image briefs in campaign-brief.md
- Multiply by the per-image cost of the chosen preset
- If total >$1.00, ask for confirmation before proceeding
- Suggest dropping non-hero assets to `--quality fast` to reduce spend

## Standalone Mode (No campaign-brief.md)

When running without a campaign brief:

```
Platform target → dimensions used:
  meta-feed     → 1080×1350 (4:5)
  meta-reels    → 1080×1920 (9:16)
  tiktok        → 1080×1920 (9:16)
  google-pmax   → 1200×628 (1.91:1)
  linkedin      → 1080×1080 (1:1)
  youtube       → 1280×720 (16:9)
  youtube-short → 1080×1920 (9:16)
```

Invoke the script directly:

```bash
python ~/.claude/skills/ads/scripts/generate_image.py \
    "<prompt>" --ratio <ratio> --quality <preset> --output <file>
```

## Reference Files

- `~/.claude/skills/ads/references/image-providers.md`: model config, pricing, limits, presets
- `~/.claude/skills/ads/references/[platform]-creative-specs.md`: per-platform specs
- `~/.claude/skills/ads/references/brand-dna-template.md`: brand injection schema
