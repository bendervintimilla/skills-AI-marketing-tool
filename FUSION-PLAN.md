# Fusion Plan — claude-ads + marketing-agency

**Goal**: Unify the two projects into one production-grade SaaS marketing platform that combines battle-tested audit intelligence (claude-ads) with the multi-tenant web product (marketing-agency).

**Target name**: `marketing-agency` (it has the foundation; claude-ads becomes its intelligence engine)

---

## Strategic Vision (one paragraph)

Marketing-agency already has the SaaS skeleton: Organization → Brand → Campaign → Ad multi-tenancy, Stripe billing, OAuth login, BullMQ workers, and an AI Brain module that generates recommendations from stored analytics. **What it lacks is structural audit intelligence**: the 162 weighted checks across Instagram, Meta, Google, TikTok, YouTube, and landing pages that claude-ads has spent months refining against real Sociedad Gourmet data. Claude-ads has the proven Python fetchers, audit logic, scoring system, and reference benchmarks. The fusion plugs that intelligence into the product, turning marketing-agency from "show me last week's CTR" into "score every brand 0–100 and tell me exactly what to fix."

---

## Architecture Decision: Hybrid Microservice

### Rejected alternatives

| Option | Why rejected |
|---|---|
| Direct git merge | Two unrelated histories, 322 file changes, mixes Python+TS in one repo without coherence |
| Rewrite Python audits in TypeScript | 14 fetchers + 162 checks = 2–3 weeks of porting; loses battle-tested logic; reinvents the wheel |
| Subprocess (worker spawns Python) | Brittle IPC, no type safety, hard to deploy, cold start on every audit |
| Keep two repos, integrate by file watch | Two deploys, two CI pipelines, sync nightmare |
| Embedded Python (PyO3, NAPI) | Brittle, hard to debug, deployment headaches |

### Chosen: Audit Microservice with Typed HTTP Boundary

```
┌─────────────────────────────────────────────────────────────┐
│  marketing-agency monorepo (single repo, single deploy)      │
│                                                              │
│  ┌────────────┐    ┌────────────┐    ┌──────────────┐      │
│  │ apps/web   │───▶│ apps/api   │───▶│ apps/worker  │      │
│  │ Next.js 14 │    │ Fastify    │    │ BullMQ       │      │
│  └────────────┘    └────────────┘    └──────┬───────┘      │
│                          │                  │              │
│                          │   POST /audits/run              │
│                          │                  │              │
│                          ▼                  ▼              │
│                    ┌─────────────────────────────┐         │
│                    │ apps/audits (Python)         │         │
│                    │ FastAPI on port 3002         │         │
│                    │ ↳ wraps claude-ads scripts   │         │
│                    │ ↳ /audit/instagram           │         │
│                    │ ↳ /audit/meta                │         │
│                    │ ↳ /audit/google              │         │
│                    │ ↳ /audit/landing             │         │
│                    └─────────────────────────────┘         │
│                                                              │
│  packages/                                                   │
│  ├── db          (Prisma — extended with audit models)       │
│  ├── shared      (TS types — auto-generated from OpenAPI)    │
│  ├── audits-sdk  (TS client — auto-generated)                │
│  └── ui          (shadcn/ui components)                      │
└─────────────────────────────────────────────────────────────┘
```

**Why this is the right call:**

1. **Each language plays to its strengths** — Python for data fetching/audit logic (already proven), TypeScript for product surface
2. **Type safety across the boundary** — FastAPI auto-generates OpenAPI; we generate TS clients from it
3. **Independently scalable** — audit service can scale horizontally; API stays small
4. **Zero rewrite** — claude-ads scripts plug in as-is, just wrapped with FastAPI routes
5. **Same monorepo, single deploy** — `docker-compose.yml` adds one service; Railway gets one new service definition
6. **Testable in isolation** — Python service has its own tests; TS API mocks the HTTP boundary
7. **Future-proof** — audit logic can be exposed to other consumers (e.g., a CLI, Zapier, n8n) without touching the product

---

## Database Schema Additions (Prisma)

Add 4 new models to `packages/db/prisma/schema.prisma`:

```prisma
model AuditRun {
  id             String        @id @default(cuid())
  brandId        String
  brand          Brand         @relation(fields: [brandId], references: [id], onDelete: Cascade)
  platform       AuditPlatform // INSTAGRAM | META | GOOGLE | TIKTOK | YOUTUBE | LANDING
  status         AuditStatus   // QUEUED | RUNNING | COMPLETED | FAILED
  score          Float?        // 0-100
  grade          String?       // A | B | C | D | F
  summary        Json?         // category scores, top findings
  errorMessage   String?
  startedAt      DateTime      @default(now())
  completedAt    DateTime?
  durationMs     Int?
  triggeredBy    String?       // userId who started it (null = scheduled)
  scheduleId     String?       // if triggered by a recurring schedule

  checks         AuditCheck[]
  report         AuditReport?

  @@index([brandId, platform, startedAt])
  @@index([status])
}

model AuditCheck {
  id             String       @id @default(cuid())
  auditRunId     String
  auditRun       AuditRun     @relation(fields: [auditRunId], references: [id], onDelete: Cascade)
  checkId        String       // e.g. "IG-C1", "M-23", "G-47"
  category       String       // "Content & Creative", "Pixel/CAPI Health", etc.
  status         CheckStatus  // PASS | WARNING | FAIL | NA
  severity       String       // critical | high | medium | low
  message        String
  evidence       Json?        // raw data that backs the verdict
  recommendation String?

  @@index([auditRunId])
  @@index([checkId])
}

model AuditReport {
  id           String   @id @default(cuid())
  auditRunId   String   @unique
  auditRun     AuditRun @relation(fields: [auditRunId], references: [id], onDelete: Cascade)
  markdown     String   @db.Text
  pdfUrl       String?  // S3/MinIO URL when rendered
  generatedAt  DateTime @default(now())
}

model AuditSchedule {
  id          String        @id @default(cuid())
  brandId     String
  brand       Brand         @relation(fields: [brandId], references: [id], onDelete: Cascade)
  platform    AuditPlatform
  cron        String        // e.g. "0 9 * * 1" = every Monday 9am
  enabled     Boolean       @default(true)
  lastRunAt   DateTime?
  nextRunAt   DateTime?
  createdAt   DateTime      @default(now())

  @@index([enabled, nextRunAt])
}

enum AuditPlatform {
  INSTAGRAM
  META
  GOOGLE
  TIKTOK
  YOUTUBE
  LANDING
  PORTFOLIO
}

enum AuditStatus {
  QUEUED
  RUNNING
  COMPLETED
  FAILED
}

enum CheckStatus {
  PASS
  WARNING
  FAIL
  NA
}
```

Also extend the existing `Brand` model with audit relations:

```prisma
model Brand {
  // ... existing fields
  auditRuns      AuditRun[]
  auditSchedules AuditSchedule[]
}
```

**Why these models:**
- `AuditRun` is the immutable history — every run gets a row, never updated, only created
- `AuditCheck` lets us drill down per-check (the dashboard can render "12 checks failed in Pixel/CAPI Health")
- `AuditReport` separates the rendered Markdown from the structured data (UI uses structured; PDF/email uses Markdown)
- `AuditSchedule` enables "audit Negroni Rooftop every Monday" recurring runs via BullMQ delayed jobs

---

## Phased Migration

### Phase 0 — Setup (1 day)

**Deliverable**: working clone of marketing-agency on Desktop with `claude-ads` integrated as `apps/audits`.

- [ ] Clone `gabrielevanadia-ai/marketing-agency` to `~/Desktop/marketing-agency`
- [ ] Create `apps/audits/` directory
- [ ] Copy claude-ads scripts → `apps/audits/src/fetchers/` and `apps/audits/src/audits/`
- [ ] Move claude-ads `references/` → `apps/audits/src/references/`
- [ ] Add `apps/audits/pyproject.toml` (FastAPI, uvicorn, pydantic, requests, google-ads, beautifulsoup4)
- [ ] Add `apps/audits/Dockerfile` (Python 3.12 slim)
- [ ] Add audits service to `docker-compose.yml` (port 3002)
- [ ] Verify all 3 services boot: `pnpm dev` + `cd apps/audits && uvicorn src.main:app --reload`

**Acceptance**: `curl localhost:3002/health` returns `{"status": "ok"}`.

---

### Phase 1 — Audit Microservice (3 days)

**Deliverable**: FastAPI service that exposes 6 audit endpoints, each backed by claude-ads logic.

- [ ] `apps/audits/src/main.py` — FastAPI app with CORS, request ID middleware, error handler
- [ ] `apps/audits/src/auth.py` — internal API key validation (worker → audits service)
- [ ] `apps/audits/src/routers/instagram.py` — `POST /audit/instagram` returns `AuditResult`
- [ ] `apps/audits/src/routers/meta.py` — `POST /audit/meta`
- [ ] `apps/audits/src/routers/google.py` — `POST /audit/google`
- [ ] `apps/audits/src/routers/tiktok.py` — `POST /audit/tiktok`
- [ ] `apps/audits/src/routers/landing.py` — `POST /audit/landing`
- [ ] `apps/audits/src/routers/portfolio.py` — `POST /audit/portfolio` (batches all brands)
- [ ] `apps/audits/src/models.py` — Pydantic schemas matching Prisma (AuditResult, CheckResult, ScoreBreakdown)
- [ ] `apps/audits/src/scoring.py` — extract weighted scoring from claude-ads references
- [ ] `apps/audits/src/credentials.py` — accept credentials from request body OR env (no hard-coding)
- [ ] Tests: `apps/audits/tests/test_instagram.py` etc. (pytest, mock the Meta API)
- [ ] OpenAPI spec auto-generated at `/openapi.json`

**Request shape (example)**:
```json
POST /audit/instagram
{
  "brand_id": "cm5x...",
  "ig_user_id": "17841405...",
  "credentials": {
    "meta_access_token": "EAA..."  // encrypted at rest in API layer
  },
  "config": {
    "include_media": true,
    "lookback_days": 30
  }
}
```

**Response shape**:
```json
{
  "platform": "INSTAGRAM",
  "score": 38,
  "grade": "F",
  "category_scores": {
    "content_creative": 58,
    "audience_reach": null,
    "monetization": 50,
    "organic_paid_integration": 4
  },
  "checks": [
    {
      "check_id": "IG-C1",
      "category": "Content & Creative",
      "status": "FAIL",
      "severity": "high",
      "message": "Reels share is 33%, target ≥40%",
      "evidence": {"reels_pct": 33, "feed_pct": 67},
      "recommendation": "Produce 2 Reels per week for next 30 days"
    }
  ],
  "summary": "Petit Palace has strong food photography but no bio CTA, 0% paid integration.",
  "raw_data_url": "s3://audits/cm5x.../instagram-snapshot.json"
}
```

**Acceptance**: `pytest apps/audits/tests/` passes; OpenAPI spec validates; `curl POST /audit/instagram` with a real token returns a 38/100 result for `@petit_palace_cue`.

---

### Phase 2 — TypeScript SDK (1 day)

**Deliverable**: typed client library so the API and worker can call the audit service without raw fetch().

- [ ] `packages/audits-sdk/package.json` (depends on `openapi-fetch`)
- [ ] Generate `packages/audits-sdk/src/types.ts` from `apps/audits/openapi.json` via `openapi-typescript`
- [ ] `packages/audits-sdk/src/client.ts` — typed wrapper with `runInstagramAudit()`, `runMetaAudit()`, etc.
- [ ] Add npm script: `pnpm sdk:regen` regenerates types from running audits service
- [ ] Pre-commit hook: refuse commit if OpenAPI spec drifts from generated types

**Acceptance**: `import { runInstagramAudit } from '@agency/audits-sdk'` autocomplete works; type errors flag any field mismatch with the Python service.

---

### Phase 3 — Database Migration (0.5 day)

**Deliverable**: Prisma schema extended; migration applied; existing data untouched.

- [ ] Add 4 new models + 2 enums to `packages/db/prisma/schema.prisma`
- [ ] `pnpm --filter @agency/db prisma migrate dev --name add_audits`
- [ ] Add repository: `packages/db/src/repositories/audit.repository.ts` (CRUD + queries)
- [ ] Update `packages/db/src/index.ts` exports

**Acceptance**: `prisma studio` shows new tables; sample inserts work via repository.

---

### Phase 4 — Worker Integration (2 days)

**Deliverable**: BullMQ jobs that orchestrate audits end-to-end.

- [ ] `apps/worker/src/queues/audit.queue.ts` — defines `audit:run` queue
- [ ] `apps/worker/src/processors/audit.processor.ts`:
  1. Receives `{ auditRunId, brandId, platform, credentials }`
  2. Marks `AuditRun.status = RUNNING`
  3. Calls `auditsSdk.runXAudit(...)`
  4. Stores `AuditCheck` rows from response
  5. Renders Markdown report → stores in `AuditReport`
  6. Optionally uploads PDF to MinIO/S3
  7. Marks `AuditRun.status = COMPLETED` with score
  8. Emits Redis pub/sub event `audit:completed:{auditRunId}` for WebSocket UI updates
  9. On failure: catches, marks FAILED, stores `errorMessage`
- [ ] `apps/worker/src/processors/audit-schedule.processor.ts` — cron-driven enqueue from `AuditSchedule` table
- [ ] Retry policy: 2 retries with exponential backoff; max job time 5 minutes
- [ ] Concurrency: 3 parallel audits per worker (Meta API rate limits)

**Acceptance**: enqueue a job manually, watch it complete, see rows in `AuditRun` + `AuditCheck` + `AuditReport`.

---

### Phase 5 — API Endpoints (1.5 days)

**Deliverable**: REST endpoints for the dashboard.

- [ ] `apps/api/src/modules/audits/audits.router.ts`:
  - `POST /audits` — start audit (auth + plan limits + enqueue)
  - `GET /audits/:id` — get audit status (poll)
  - `GET /audits/:id/checks` — list all checks
  - `GET /audits/:id/report` — Markdown or HTML
  - `GET /audits/:id/report.pdf` — signed S3 URL
  - `GET /brands/:brandId/audits` — list runs for a brand
  - `GET /brands/:brandId/audits/score-history` — chart data
  - `POST /brands/:brandId/audit-schedules` — create recurring schedule
- [ ] WebSocket route `/ws/audits/:id` — real-time progress events
- [ ] Plan limits: free tier = 5 audits/month; pro = unlimited (use existing `planLimits` middleware)
- [ ] OpenAPI documentation via Fastify Swagger plugin

**Acceptance**: Postman collection passes for all 8 endpoints; rate limiting works; auth blocks cross-org access.

---

### Phase 6 — Frontend Dashboard (3 days)

**Deliverable**: complete UI for running, viewing, and comparing audits.

Pages to add in `apps/web/src/app/dashboard/`:
- [ ] `/dashboard/brands/[brandId]/audits` — table of past runs, score badge, "Run Audit" button per platform
- [ ] `/dashboard/brands/[brandId]/audits/[auditId]` — single audit deep dive:
  - Score gauge (0–100)
  - Category breakdown bar chart
  - Failed checks accordion grouped by category
  - "Apply recommendations" CTA
  - Markdown report tab
- [ ] `/dashboard/audits/compare` — multi-brand comparison (portfolio view, picks 2–10 brands)
- [ ] `/dashboard/audits/history` — score trends over time per brand
- [ ] Components in `packages/ui/`:
  - `<ScoreGauge value={38} grade="F" />`
  - `<CheckList checks={...} groupBy="category" />`
  - `<AuditRunCard run={...} />`
  - `<AuditProgressBar runId={...} />` (subscribes to WebSocket)
- [ ] State: TanStack Query for fetches; Zustand for live audit progress

**Acceptance**: complete user flow — click "Run Audit" on Negroni Rooftop → progress bar fills → score displays → drill-down works → compare view shows all 19 brands side-by-side.

---

### Phase 7 — Credential Vault (1 day)

**Deliverable**: per-brand encrypted credentials in DB instead of global env vars.

- [ ] Extend `SocialAccount` model with: `metaAdAccountId`, `googleAdsCustomerId`, `tiktokAdvertiserId`, `developerToken` (encrypted with `apps/api/src/lib/crypto.ts`)
- [ ] UI: "Connect Meta Ads" button → OAuth → stores encrypted token in `SocialAccount`
- [ ] Worker: when running audit, decrypts credentials, passes to audit service
- [ ] Rotation: token expiry detection + auto-refresh for OAuth tokens

**Why this matters**: in the current claude-ads, `META_ACCESS_TOKEN` is a single global env var. In a SaaS with multiple Organizations, each Org needs its own credentials.

**Acceptance**: two organizations can run audits simultaneously, each using their own Meta token; no env var dependency on the audit service.

---

### Phase 8 — AI Brain Integration (1 day)

**Deliverable**: existing `ai-brain` module consumes audit results to generate richer recommendations.

- [ ] Update `apps/api/src/modules/ai-brain/services/recommendation-engine.ts` to query `AuditCheck` rows
- [ ] When generating recommendations: if any FAIL checks exist, prioritize those
- [ ] When user asks AI brain chat ("what should I fix?"), include latest audit summary in Gemini context
- [ ] New recommendation type: `AUDIT_FIX` (links to specific `AuditCheck.id`)

**Acceptance**: AI brain chat answers "what should I do for Petit Palace?" with audit-grounded specifics, not generic platitudes.

---

### Phase 9 — Polish (2 days)

- [ ] Caching: fetched data (e.g., Instagram media) cached in Redis for 30 min — avoid re-pulling on retry
- [ ] Rate limit awareness: if Meta API returns 429, requeue with backoff
- [ ] Error reporting: Sentry integration for both Python and Node
- [ ] Audit comparison diff view — "what changed since last week?"
- [ ] Email notifications: weekly audit summary per brand (uses existing `notifications` module)
- [ ] PDF export polish — branded header, ToC, executive summary

---

### Phase 10 — Migration & Cleanup (0.5 day)

- [ ] Import all 19 Sociedad Gourmet IG audit reports into the new system as historical `AuditRun` records (so the dashboard isn't empty on first login)
- [ ] Archive `claude-ads` repo with a README pointing to the unified repo
- [ ] Update `SETUP.md` for the new combined project
- [ ] Keep Claude Code skills as a *developer* extension (not part of the product) — `claude-skills/` directory pointing to the same audits service

---

## Total Effort Estimate

| Phase | Days |
|---|---|
| 0. Setup | 1 |
| 1. Audit microservice | 3 |
| 2. TS SDK | 1 |
| 3. DB schema | 0.5 |
| 4. Worker integration | 2 |
| 5. API endpoints | 1.5 |
| 6. Frontend dashboard | 3 |
| 7. Credential vault | 1 |
| 8. AI brain integration | 1 |
| 9. Polish | 2 |
| 10. Migration | 0.5 |
| **TOTAL** | **16.5 days (3.5 weeks)** |

Realistic with 1 engineer full-time. Can compress to 2 weeks with parallelization (frontend in parallel with worker work).

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FastAPI/Fastify CORS issues | Medium | Low | API key auth + same-origin via Docker network |
| Meta API rate limits during portfolio audit | High | Medium | Sequential audits per token + Redis cache + backoff |
| Python deps bloat Docker image | Medium | Low | Multi-stage build; alpine where possible |
| Auto-generated TS types drift | Low | Medium | CI check on every PR |
| BullMQ job failures lose data | Low | High | Retry policy + dead letter queue |
| Cost of running audits service 24/7 | Medium | Low | Scale-to-zero on Railway when idle |
| OpenAPI schema breaking changes | Medium | Medium | Semver the audits service; pin SDK version |

---

## Decision Points (need your input)

1. **Repo strategy**: keep `marketing-agency` name or rename to something Sociedad Gourmet-branded?
2. **Hosting**: stay on Railway, or move to Vercel (web) + Railway (API/worker/audits)?
3. **First customer**: ship with Sociedad Gourmet as pilot tenant, or build for general public?
4. **Public launch timing**: 4-week MVP for Sociedad Gourmet, then 2-week polish for general launch?
5. **Pricing**: free tier limits — how many audits/month?

---

## Why This Plan is Right

- **Nothing gets thrown away** — every line of claude-ads Python code stays useful
- **Nothing gets duplicated** — audit logic lives in exactly one place (Python)
- **The boundary is typed** — OpenAPI + auto-gen TS = no string typos crossing the wire
- **Each layer is testable in isolation** — Python service, API, worker, frontend all have their own test suite
- **Single deploy target** — `docker-compose up` (or one Railway project) brings up everything
- **Future-proof** — audit logic can later be exposed as CLI, MCP server, n8n node, Zapier action — all of those just call the FastAPI service
- **Multi-tenant from day 1** — no rip-and-replace later when adding the second client

---

*Authored: 2026-04-24 | claude-ads + marketing-agency fusion architecture*
