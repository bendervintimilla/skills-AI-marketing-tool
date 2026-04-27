# Image Generation Providers

<!-- Updated: 2026-04-22 -->
<!-- Used by: ads-generate, ads-photoshoot, ads-create, ads-dna, visual-designer agent -->

## Default Provider: Google Gemini / Imagen 4

All image generation runs through `scripts/generate_image.py`, which uses
the `google-genai` SDK to hit either the Gemini multimodal image endpoint
or the Imagen 4 dedicated text-to-image endpoint.

### Prerequisites

- `google-genai>=1.16.0` installed (comes with the skill's requirements.txt)
- `GOOGLE_API_KEY` environment variable set
- Get a key at https://aistudio.google.com/app/apikey

### Quality Presets

The `--quality` flag maps a short name to a current production model ID:

| Preset | Model ID | Cost / 1K img | Cost / 2K img | Best for |
|--------|----------|--------------:|--------------:|----------|
| `pro` **(default)** | `gemini-3-pro-image-preview` | $0.134 | $0.134 | Hero creatives, key visuals, professional asset production. Thinking mode, up to 6 reference images for objects / 5 for characters. Advanced text rendering. |
| `high` | `imagen-4.0-ultra-generate-001` | $0.06 | $0.06 | Photorealism, product shots, legible text-in-image (logos/CTAs). GA (stable). Text-to-image only. |
| `flash` | `gemini-3.1-flash-image-preview` | $0.067 | $0.101 | Multi-reference editing (up to 14 images), new aspect ratios (1:4, 4:1, 1:8, 8:1), Google Search grounding, controllable thinking. |
| `fast` | `gemini-2.5-flash-image` | $0.039 | N/A | High-volume iteration, A/B variants, simple multi-turn edits. GA (stable). |

Default can be overridden with the `ADS_IMAGE_QUALITY` env var.

### Usage Examples

```bash
# Hero creative (default — pro)
python generate_image.py "Executive product shot, SaaS dashboard on a modern desk, soft window light" \
    --ratio 16:9 --output hero.png

# Photoreal product shot (Imagen 4 Ultra)
python generate_image.py "Skincare bottle, white background, studio lighting, sharp focus" \
    --ratio 1:1 --quality high --output product.png

# Edit using a brand reference (Gemini 3.1 Flash Image)
python generate_image.py "Product on beach at sunset, maintain brand aesthetic" \
    --ratio 9:16 --quality flash --reference-image ./brand-screenshots/homepage.png

# Volume batch of variants (Gemini 2.5 Flash Image)
python generate_image.py --batch variants.json --output-dir ./ad-assets/ \
    --quality fast
```

### Aspect Ratios

`generate_image.py` accepts these shorthand ratios and maps to the closest
supported ratio per model:

| Ratio | Dimensions | Platform Use |
|-------|-----------|-------------|
| 1:1 | 1080×1080 | Meta Feed, LinkedIn, Carousel |
| 4:5 | 1080×1350 | Meta Feed (preferred), Instagram |
| 9:16 | 1080×1920 | TikTok, Reels, Shorts, Stories |
| 16:9 | 1920×1080 | YouTube, Google Display, LinkedIn |
| 4:3 | 1200×900 | Display standard |
| 3:4 | 900×1200 | Pinterest, portrait ads |
| 1.91:1 | 1200×628 | Google PMax / LinkedIn landscape (generated 16:9, crop in post) |
| 4:1 | 1200×300 | Website banners |
| 21:9 | 2520×1080 | Ultra-wide hero |

Note: Imagen 4 family natively supports 1:1, 3:4, 4:3, 9:16, 16:9. Other
ratios are mapped to the closest and cropped client-side if needed.
Gemini 3.1 Flash Image also natively supports 1:4, 4:1, 1:8, 8:1.

### When to Use Which Preset

| Situation | Preset | Why |
|-----------|--------|-----|
| Client-facing hero image | `pro` | Highest reasoning, composition, text rendering |
| Product packshots (e-commerce) | `high` | Imagen 4 Ultra is best-in-class for photoreal products |
| "Change the background of THIS image" | `flash` | Only Gemini 3.x accepts reference images + edits |
| 50 banner variants for A/B testing | `fast` | 3–4x cheaper per image |
| Logo / icon generation | `pro` or `high` | Advanced text rendering matters for brand marks |
| Character consistency across a series | `pro` | Up to 5 character references with identity preservation |
| Multi-reference composition (logo + product + setting) | `flash` | Handles up to 14 reference images |

### Watermarking

All Google-generated images include invisible **SynthID** watermarks that
mark them as AI-generated at a bit level. This matters for ad platforms
with disclosure requirements (Meta, Google, TikTok) — keep this in mind
when claiming imagery is human-created.

### Error Reference

| Error | Cause | Fix |
|-------|-------|-----|
| `GOOGLE_API_KEY not set` | Env var missing | `export GOOGLE_API_KEY="..."` |
| `IMAGE_SAFETY` | Safety filter triggered | Rephrase prompt; abstract or artistic framing |
| `429` / `RESOURCE_EXHAUSTED` | Rate limit | Script auto-retries with exponential backoff |
| `FAILED_PRECONDITION` | Billing not enabled | Enable billing in Google AI Studio |
| `NOT_FOUND` on model | Preview model rolled back | Use `--quality high` (Imagen 4 Ultra is GA) |
| `Imagen does not support reference images` | Used `--reference-image` with `--quality high` | Switch to `--quality flash` or `pro` |

### Rate Limits (Gemini / Imagen, Google AI Studio)

| Tier | RPM | Daily Images |
|------|-----|--------------|
| Free | 5–15 | 20–500 |
| Tier 1 (<$250 spend) | 150 | 1,500 |
| Tier 2 (>$250 spend) | 1,000+ | Higher / negotiable |

---

## Optional Alternative Providers

These are supported by `generate_image.py` but are **not installed by default**.
Install the provider's package separately and set its API key.

### OpenAI (gpt-image-1)
- Env: `OPENAI_API_KEY`, `ADS_IMAGE_PROVIDER=openai`
- Price: ~$0.040/image (1024×1024), ~$0.060 (1024×1536)
- Package: `pip install 'openai>=1.75.0'`

### Stability AI (stable-diffusion-3.5-large)
- Env: `STABILITY_API_KEY`, `ADS_IMAGE_PROVIDER=stability`
- Price: ~$0.065/image flat
- Package: `pip install 'stability-sdk>=0.8.4'`

### Replicate (FLUX.1 Pro)
- Env: `REPLICATE_API_TOKEN`, `ADS_IMAGE_PROVIDER=replicate`
- Price: ~$0.055/image
- Package: `pip install 'replicate>=1.0.4'`

---

## Script Interface Summary

```
python generate_image.py [PROMPT] [--ratio R | --size WxH]
                         [--quality {pro,high,flash,fast}]
                         [--model MODEL_ID]
                         [--reference-image FILE]
                         [--output FILE | --batch FILE --output-dir DIR]
                         [--provider {gemini,openai,stability,replicate}]
                         [--json]
```

`--model` always takes precedence over `--quality`. Use `--model` only when
you need a specific model ID not in the preset list (e.g.
`imagen-4.0-generate-001` for the standard Imagen 4 tier).
