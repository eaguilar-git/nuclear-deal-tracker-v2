# Nuclear Deal Tracker v2

A semi-automated market intelligence system that monitors U.S. nuclear energy deployment activity, extracts structured deal data, and surfaces it through a live dashboard.

**Live dashboard:** https://eaguilar-git.github.io/nuclear-deal-tracker-v2/
**Source:** https://github.com/eaguilar-git/nuclear-deal-tracker-v2 (public)
**Maintainer:** Edgar Aguilar (Research Associate, EFI Foundation Nuclear Scaling Initiative) — pending migration to a successor at EFI, see MIGRATION.md.
**Last updated:** May 2026

---

## What this system does

Every day at 6am EST, an automated scraper:

1. Fetches ~48 RSS feeds covering nuclear industry trade press, government regulators (NRC, DOE, IAEA), company newsrooms, and Google News topic queries
2. Filters out non-U.S. articles, fusion articles, and non-deal content
3. Uses Claude (Anthropic's LLM) to extract structured data — linking each new announcement to existing projects, deals, sites, and context items in a Google Sheet
4. Writes new rows to the Sheet, flagging ambiguous extractions for human review
5. Proposes new deal records when it sees clear bilateral transactions

A dashboard hosted on GitHub Pages reads the Sheet and renders it as an Activity Feed and Entity Explorer for the EFI team and external stakeholders.

---

## The data model (v0.4 schema)

The database has **six entity tables** plus two operational tables. Everything ties together with foreign keys using snake_case lowercase IDs (e.g. `tmi_1`, `palisades_smr300`, `microsoft_nuclear_initiative`).

### Entity tables

**1. Sites** — geographic locations hosting one or more reactors.
Example: `vogtle` = the Vogtle Electric Generating Plant in Burke County, GA, hosting Units 1–4.

**2. Reactor Units** — individual physical reactors. Each unit has an `asset_status` (Operating · Planned · Shut Down · Decommissioning).
Example: `vogtle_3` and `vogtle_4` are two distinct reactor units at the `vogtle` site.

**3. Projects** — development efforts that create, restart, uprate, or extend one or more reactor units. A project has a `project_type` (Extension/Renewal · New Build—Large · New Build—Advanced/SMR · Restart · Uprate), a `project_stage` (where it is in the deployment lifecycle), and a `project_status` (Active · Completed · Paused · Cancelled).
Example: `vogtle_34_newbuild` is the single project that produced reactor units `vogtle_3` and `vogtle_4`. `tmi_restart` is one project covering one unit (`tmi_1`).

**4. Deals** — specific transactions tied to one or more projects. PPAs, MOUs, loans, grants, equity investments, etc.
Example: `microsoft_tmi1_ppa` is the deal where Microsoft committed to purchase TMI-1's output. It links to project `tmi_restart`.

**5. Context Items** — cross-cutting frameworks that don't fit cleanly into a single project: federal programs (DOE ARDP, DOE Launch Pad), hyperscaler portfolios (Microsoft's broader nuclear strategy), state policies (NY's 5 GW initiative), aspirational pipelines (utility plans without specific projects yet).
Example: `microsoft_nuclear_initiative` is a portfolio-level context that links to multiple Microsoft deals and projects.

**6. Announcements** — news events. Each announcement can link to multiple sites, units, projects, deals, and context items it concerns. This is the table the scraper writes to most often.

### Operational tables

**Seen** — fingerprint hashes of articles already processed, so the scraper doesn't reprocess yesterday's news.
**Review** — extractions Claude flagged as Medium confidence (after escalation to a stronger model), for human spot-checking.

### Why projects ≠ reactor units

A reactor unit is **one physical reactor with one status**. A project is **a development effort touching one or more units**. They're separated because:

- A site can have units that are not part of any current project (a fleet's operating reactors, just running)
- A unit can be inside multiple projects over time (Clinton has an Uprate project AND a License Renewal project — same physical reactor, two efforts)
- A project can wrap multiple units (Vogtle 3&4 is one project, two units; Long Mott Energy is one project, four units)

The dashboard surfaces both: the **Physical Fleet KPIs** count reactor units (94 operating, 5 in construction, 23 planned, 5 shut down), and the **Pipeline Activity KPIs** count projects (47 total, 29 active).

---

## The Nuclear Layer Cake

The EFI Nuclear Scaling Initiative organizes nuclear deployment into four layers. The framework was developed by synthesizing Sonia's Nuclear Deal Tracker spreadsheet with the World Nuclear Association's U.S. country profile and Outlook Report. The schema's `project_type` field maps directly onto these layers:

| Layer | What it is | Project types in the DB |
|-------|------------|-------------------------|
| **Layer 1** | Fleet Preservation — keeping existing reactors operating | Extension / Renewal, Uprate |
| **Layer 2** | Restarts — bringing shut-down reactors back online | Restart |
| **Layer 3** | New Large Reactors — gigawatt-scale conventional builds | New Build — Large |
| **Layer 4** | Advanced Reactors / SMRs — next-generation designs | New Build — Advanced/SMR |

The dashboard's active project breakdown panel groups projects by these layers, making it the operational view of the framework.

---

## Where data comes from

### The reference data (seeded manually)

The six entity tables were seeded with ~439 rows of curated reference data, built from three primary sources:

- **Sonia's Nuclear Deal Tracker spreadsheet** — the original deal dataset she built. This was the foundation for the Deals table and informed many of the Projects and Context Items entries.
- **World Nuclear Association U.S. country profile** — the canonical reference for current U.S. reactor fleet status, sites, license renewals, and historical context. Source for most Sites and Reactor Units rows.
- **World Nuclear Association Outlook Report** — forward-looking projections on advanced reactor deployment, restart pipelines, and supply chain. Informed Project taxonomy and Context Items.

The Nuclear Layer Cake framework itself emerged from synthesizing these three sources during the original briefing-document work.

Seed contents:

- **69 sites** — every U.S. nuclear site, operating or otherwise
- **126 reactor units** — every U.S. reactor (94 operating, 23 planned, 5 shut down, etc.)
- **47 projects** — current development efforts
- **35 deals** — known financing and offtake transactions
- **48 context items** — federal programs, state policies, hyperscaler portfolios
- **114 seed announcements** — historical announcements covering 2024-2026

This reference data is the **single source of truth**. The scraper's job is to add *new* announcements (and occasionally propose new deals); it does **not** modify the reference tables.

The maintainer keeps the Sites, Units, Projects, and Context Items tables curated manually. Deals get added either manually or via scraper proposals (which require human confirmation before they're treated as real).

### The scraper's contribution

The scraper adds rows to the **Announcements** table and occasionally proposes new rows in the **Deals** table (always flagged as `Proposed (scraper)` until a maintainer reviews and confirms them).

The scraper does NOT invent new entities. If it sees an article about a new project or context that isn't in the reference data, it flags it in the `new_entity_flags` column of the announcement so a maintainer can decide whether to add it to the reference tables.

---

## How the scraper works

The scraper is a Python script (`scraper.py`) that runs once per day via GitHub Actions. The schedule lives in `.github/workflows/daily_scrape.yml`.

### Run sequence

```
1. Connect to Anthropic API + Google Sheets
2. Load reference data from the live Sheet (5 entity tabs)
3. Compute next IDs (ann_NNNN, deal_NNNN, rev_NNNN)
4. Fetch all 48 RSS feeds
5. For each candidate article:
   5a. Skip if URL/hash already in Seen tab
   5b. Skip if article is pre-2024
   5c. Fetch full article body (max 9000 chars)
   5d. Pass 1 (Haiku): is_us / is_fusion / include screen
   5e. Pass 2 (Haiku, escalates to Sonnet on Medium confidence): full extraction
   5f. Build Announcement row (and Deal row if propose_deal=true)
6. Batched write to Announcements, Deals, Review, Seen tabs
```

### Pass 1 — cheap screening (~400 tokens per article)

**Purpose:** reject obviously irrelevant articles before the expensive Pass 2.

The Pass 1 prompt asks Claude three questions:

> 1. Is this article about U.S. nuclear FISSION energy? (US scope; fusion is OUT)
> 2. Does it describe a concrete deal, financing event, license action, deployment milestone, or significant policy/announcement worth tracking?
> 3. Return a JSON object with `is_us`, `is_fusion`, `include`, and `reason`.

The prompt lists explicit IN/OUT criteria:

**IN scope:**
- Signed agreements (PPA, MOU, JDA, EPC, supply contracts)
- Financing events (equity rounds, DOE loans, grants, awards)
- License actions (renewals, restarts, construction permits, applications, NRC approvals)
- Deployment milestones (FID, COD, construction start, site selection)
- State/federal policy action with quantitative target or commitment (capacity, dollars, deadline)
- Hyperscaler procurement moves (offtake, equity, partnership)

**OUT of scope:**
- International-only stories (no US tie-in)
- Fusion energy (CFS, Helion, ITER, tokamak, stellarator, TAE)
- Pure science research without commercialization angle
- Generic industry commentary, retrospective analysis with no new development
- Equity-research opinions

Pass 1 outputs a JSON object. If `is_fusion=true` or `is_us=false` or `include=false`, the article is skipped and only its hash is logged to the Seen tab.

### Pass 2 — structured extraction (~9,300 tokens per article)

**Purpose:** for articles that survive Pass 1, extract structured data and link to existing entities.

The Pass 2 prompt is much longer. It enumerates:

1. **The 6 entity types** and how to think about them
2. **Linking rules** — an announcement can link to multiple entities of each type
3. **The 4 announcement scopes** and how to distinguish them:
   - `Project-Specific` — about one specific project's progression
   - `Context-Specific` — about a federal program, state policy, hyperscaler portfolio, or vendor activity (not tied to a single project)
   - `Cross-Cutting` — touches multiple projects AND a context item, or spans the industry with specifics
   - `Industry Commentary` — analysis or trend piece without a specific concrete action
4. **Confidence** levels — High (all key fields confidently set) vs Medium (some ambiguity)
5. **Proposed Deal Creation (the Q5 mechanic)** — Claude only proposes a new deal when ALL of:
   - The article describes a specific bilateral transaction
   - Counterparties are clearly named
   - At least one project_id can be matched from the reference data (no orphan deals)
   - Either capital value is disclosed OR deal_type is clearly identifiable
6. **New entity flagging** — if Claude sees an entity not in the reference data that seems important, it lists it under `new_entity_flags` (e.g. "project: Alabama Power SMR site selection") rather than inventing an ID
7. **ID matching rules** — use IDs exactly as written in reference data, no inventions

The prompt then injects the full reference data — formatted as compact one-line summaries of all 47 projects, 48 contexts, 35 deals, 126 reactor units, and 69 sites — so Claude has the complete picture of the existing database when matching new articles.

Pass 2 returns a JSON object with all the fields needed for an Announcement row, plus optionally a `proposed_deal` block with fields for a new Deal row.

### When Pass 2 escalates to Sonnet

Pass 1 uses Claude Haiku (cheap, fast). Pass 2 starts with Haiku too. If Haiku's confidence is `Medium`, the same Pass 2 prompt is re-run with Sonnet (slower, more capable). Sonnet's output is usually more careful about entity linking and edge cases.

If the final extraction (whether from Haiku or escalated Sonnet) is still `Medium` confidence, the announcement is written but a row is also added to the **Review** tab for human audit. The data entry app's Review queue surfaces these for clearing.

### Confirmation status on deals

When the scraper proposes a deal, the row is written with `confirmation_status = "Proposed (scraper)"`. The dashboard's default view filters these out — they only appear when the "Show proposed deals" toggle is enabled.

A maintainer reviews each proposed deal (via the data entry app's Review queue, or directly in the Sheet), then either:
- Edits the row to fill in missing fields and changes status to `Confirmed`, OR
- Deletes the row if the proposal was wrong

This is the **Q5 mechanic** — the scraper can propose, but only a human confirms.

---

## Feed sources (48 total)

### Tier 1: Industry trade press (12)
World Nuclear News, ANS Nuclear Newswire, NEI News, Power Magazine Nuclear, Power Engineering, Utility Dive, Neutron Bytes, Nuclear Engineering International, Canary Media, Latitude Media, Atomic Insights, NucNet

### Tier 2: Government & regulatory (6)
DOE Nuclear Energy, DOE News, NRC News, NRC Press Releases, IAEA Nuclear Power, IAEA Newscenter

### Tier 3: Company newsrooms (8)
Holtec, NANO Nuclear IR, Helion, X-energy, TVA, Brookfield IR, Constellation IR, Westinghouse Blog

Most vendor newsrooms (TerraPower, Kairos, Oklo, NuScale, GE Vernova, Duke, Dominion, NextEra, etc.) have killed RSS or hide it behind JavaScript. Coverage for those entities comes via Tier 5 below.

### Tier 4: Hyperscalers & finance (4)
Google Blog, Microsoft On the Issues, Meta Newsroom, Amazon About (all with `nuclear_only=True` filter so we only pull entries mentioning nuclear keywords)

### Tier 5: Google News queries (12)
Vendor and topic-specific Google News RSS searches. Google News aggregates from thousands of sources and exposes free RSS for any search query — this is our backfill for vendors with dead native RSS:

- `"TerraPower" Natrium OR Kemmerer OR reactor`
- `"NuScale" nuclear OR SMR`
- `"Kairos Power" reactor OR Hermes`
- `"Oklo" nuclear OR Aurora OR reactor`
- `"GE Vernova" nuclear OR BWRX`
- `"Duke Energy" nuclear OR reactor OR SMR`
- `"Dominion Energy" nuclear OR reactor OR SMR`
- `"NextEra" nuclear OR Duane Arnold`
- `"Southern Company" nuclear OR Vogtle`
- `"Entergy" nuclear OR reactor`
- `"Vistra" nuclear OR Comanche Peak`
- `"BWRX-300"` (specific technology used in several U.S. projects)

The scraper follows Google News redirect URLs to the real publisher URL before fingerprinting, so the same article appearing in multiple GN queries is deduplicated correctly.

### Tier 6: Press wires & policy adjacents (6)
PR Newswire Energy, PR Newswire Utilities, GlobeNewswire Energy, Inside Climate News, CNBC Energy, EIA Press. All use `nuclear_only=True` to filter non-nuclear noise.

---

## Pre-filters

Before sending an article to Claude, the scraper applies cheap keyword filters:

**Nuclear keyword filter** (applied to high-volume non-nuclear feeds like Google Blog, Microsoft, Reuters):
- `nuclear`, `reactor`, `smr`, `fission`, `uranium`, `atomic`, `nrc`, `doe nuclear`

**Deal keyword filter** (applied to every feed):
- `agreement`, `deal`, `contract`, `ppa`, `power purchase`, `mou`, `memorandum`, `partnership`, `collaboration`, `investment`, `funding`, `loan`, `grant`, `award`, `financing`, `license renewal`, `license extension`, `subsequent license`, `restart`, `new build`, `construction permit`, `construction start`, `offtake`, `signed`, `announced`, `selected`, `approved`, `smr`, `small modular`, `advanced reactor`, `uprate`, `fid`, `final investment`, `early site permit`, `commits`, `commitment`, `pledge`, `executive order`

**Fusion exclude filter** (hard reject before LLM):
- `fusion energy`, `fusion reactor`, `fusion power`, `tokamak`, `stellarator`, `iter project`, `commonwealth fusion`, `helion fusion`, `tae technologies`, `fusion startup`, `fusion plant`

**Minimum year filter:** articles dated before 2024 are skipped.

---

## Dashboard

The dashboard lives at `index.html` (REPO ROOT, not in `/docs`) and is hosted on GitHub Pages at https://eaguilar-git.github.io/nuclear-deal-tracker-v2/. It's a single HTML file that fetches the six entity tables as published CSVs from the live Google Sheet, then renders them.

The dashboard has two tabs.

### Tab 1 — Activity Feed

The chronological stream of everything new — milestones, partnerships, capital, regulatory actions — scraped daily.

**Filters (3 rows):**

- Row 1 (specific entity): Site · Project · Deal · Context item
- Row 2 (categorical): Reactor class · State · Lead entity
- Row 3 (dates + toggles): From · To · 30d / 90d / 1y / All time presets · Show needs review · New entities only

The four entity dropdowns (and any dropdown with more than 12 options) include a search-as-you-type box so you can type "vogtle" instead of scrolling.

**Active project pipeline panel** at the top shows the same 47 active projects sliced two ways — by project type and by project stage — each with a totals row.

**Table:**
- Sortable, paginated (25 / 50 / 100 per page)
- Source column is a clickable link to the article
- "Linked to" column shows the primary entity(ies) the announcement concerns, with a tooltip explaining the linkage model
- All cells wrap text instead of truncating
- Click any row to expand the full announcement detail inline
- Download Excel button exports the current filtered view

### Tab 2 — Entity Explorer

"What's this for?" panel at the top explains the view is for checking the status of a specific project, company, or technology.

**Browse-by cards** at the top show the four entry points with their counts and short descriptions: Sites (69) · Projects (47) · Deals (42) · Context items (48). Click a card to switch mode.

**Per-mode filters:**

- **Sites:** State · Project type at site · Operator · Reactor class · Reactor technology · Manufacturer · "Only sites with active projects" toggle
- **Projects:** Project type · Project stage · Project status · State · Reactor class · Reactor tech · Manufacturer · Has deal type · Has deal stage · Has deal w/ lead · Lead entity type
- **Deals:** Deal type · Deal stage · Economic type · Lead entity · Lead entity type · Partner mentioned · State
- **Context items:** Context type · Status · Scope

Plus a free-text search and a dropdown of all entities for direct selection.

**Inline expansion of linked entities.** Inside a project detail view, clicking a linked deal expands a mini deal-card right below it — type, stage, lead, capital, partners, cost contribution, notes, source link — without leaving the project view. Same for linked context items in project view, project cards in site/deal views, etc. Each inline card has an "Open full view →" button for when you need to drill in.

**Inline announcement expansion.** Clicking an announcement in any entity's timeline expands the full detail inline (summary, tags, source link, related entities) instead of switching tabs.

**Download Excel button** exports the currently-filtered list of entities (Sites OR Projects OR Deals OR Contexts) with native columns plus derived counts.

### Hero KPIs

Two tiers of metrics at the top of the dashboard, with explainer text clarifying how they relate:

**Physical fleet** (counts reactor units):
- Operating · Construction · Planned · Shut down · Sites

**Pipeline activity** (counts projects/deals/announcements):
- Projects · Project cost · PPA exposure · Deals · Announcements (last 12 months)

KPIs are clickable where useful — click "Projects" to jump into Project mode in Entity Explorer.

### Tooltips

Hover any KPI label or other annotated element for a definition.

---

## Repository structure

```
nuclear-deal-tracker-v2/
├── README.md                                       ← this file
├── MIGRATION.md                                    ← departure handoff runbook
├── PROMPTS.md                                      ← scraper prompt design + rationale
├── requirements.txt                                ← Python dependencies
├── scraper.py                                      ← the daily scraper (v3.3)
├── index.html                                      ← dashboard (served by GitHub Pages from repo root)
├── seed_v04.py                                     ← one-time Sheet bootstrapper (already run)
├── clean_existing_urls.py                          ← one-time URL cleanup utility
├── diagnose_feeds.py                               ← optional: check which RSS feeds work
├── test_candidate_feeds.py / _v2.py                ← optional: test new feed candidates
├── data_entry/
│   ├── data_entry.html                             ← editing UI (FK validation, dropdowns, review queue)
│   ├── data_entry_server.py                        ← Flask server (reads/writes the Sheet)
│   └── start_data_entry.sh                         ← convenience launcher
├── reference/
│   └── Nuclear_Deal_Tracker_v2_Pass5.xlsx          ← canonical seed data
└── .github/workflows/
    └── daily_scrape.yml                            ← cron schedule (11:00 UTC daily)
```

---

## Data entry app

A local Flask + HTML app for adding rows and editing the Sheet with safety rails: foreign-key validation (can't link to a deal that doesn't exist), controlled vocabularies (dropdowns for project_stage etc.), ID auto-generation, and a pending-changes drawer that batches writes for review before pushing.

**Run it:**

```bash
cd ~/Documents/nuclear-deal-tracker-v2/data_entry
./start_data_entry.sh
```

This launches the Flask server on port 8001 and opens the UI in your browser. The first run installs the Python deps (Flask, gspread, openpyxl). All edits stage locally in your browser; click "Push to Sheet" to commit them.

**Review queue tab** (first tab in the data entry app) consolidates three kinds of items the scraper flags for human review:

1. **Medium-confidence announcements** — Pass-2 Claude was unsure about the extraction. Quick "Mark reviewed" button sets confidence to High after you eyeball the summary.
2. **New entity flagged** — scraper saw a name (project, company, context) not in the database. Click "Edit record" to either create the new entity in its tab, or correct the linkage.
3. **Proposed deals** — scraper drafted a new deal row. Click "Edit record" to fill missing fields and change confirmation_status from "Proposed (scraper)" to "Confirmed" (or delete it).

Filter chips at the top show counts per type and let you focus on one group at a time.

---

## Environment variables

The scraper needs three environment variables to run:

| Variable | What it is | Where to get it |
|----------|------------|-----------------|
| `ANTHROPIC_API_KEY` | Claude API key | console.anthropic.com → API Keys |
| `GOOGLE_SHEET_ID` | The Sheet's ID from its URL | `1UHKrpeS56Bgt5ZQ2si6i9LunogM88V4VDKZ93PoqTeg` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON content of the service account key | from the credentials file |

Locally these are set per-terminal session via `export`. In production they're set as GitHub Actions Secrets in the repo's Settings → Secrets and variables → Actions.

The service account is `nuclear-scraper@rugged-abacus-405804.iam.gserviceaccount.com` — it has Editor access on the live Sheet.

---

## Running the scraper

### Locally (for testing)

```bash
cd ~/Documents/nuclear-deal-tracker-v2

# Set env vars
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat ~/Documents/credentials_deal_tracker/rugged-abacus-405804-effe0cb0fe9b.json)"
export GOOGLE_SHEET_ID="1UHKrpeS56Bgt5ZQ2si6i9LunogM88V4VDKZ93PoqTeg"
export ANTHROPIC_API_KEY="$(cat ~/Documents/credentials_deal_tracker/anthropic_key_v2.txt)"

# Install dependencies (first time only)
pip3 install -r requirements.txt

# Run
python3 scraper.py
```

A run takes 10–20 minutes depending on candidate count. Output shows per-article decisions and a final summary.

### In production

The scraper runs automatically every day at 11:00 UTC (6am EST / 7am EDT) via GitHub Actions. The cron is configured in `.github/workflows/daily_scrape.yml`. Manual trigger is available from the repo's Actions tab.

---

## Reviewing scraper output

After each run, three things to check:

**1. The Review tab** — any rows here flagged Medium confidence after Sonnet escalation. Spot-check that the linked entities are right.

**2. The Deals tab, filtered to `confirmation_status = "Proposed (scraper)"`** — these are deals the scraper wants to propose. Edit fields as needed, change status to `Confirmed`, or delete if wrong.

**3. New announcement rows with non-empty `new_entity_flags`** — Claude saw a project, site, or context item that's worth adding to the reference data. Decide whether to add it manually.

---

## Cost expectations

Approximate Anthropic API costs:

- **Pass 1 (Haiku):** ~$0.0001 per article
- **Pass 2 (Haiku):** ~$0.003 per article (in tokens)
- **Pass 2 escalated to Sonnet:** ~$0.05 per article

Typical daily run after dedup: ~30 new articles processed = ~$0.30/day = **~$5-10/month**.

GitHub Actions free tier covers the compute (well under the 2000 minute/month allowance for public repos).

---

## When something goes wrong

### Scraper fails to fetch a feed
A few feeds fail per run with timeout or 403 errors — that's expected. As long as the run summary shows most feeds returning candidates, the system is healthy.

If many feeds fail, run `diagnose_feeds.py` to test each one individually:

```bash
python3 diagnose_feeds.py
```

### Sheet writes fail
Usually a permissions issue. Re-share the Sheet with `nuclear-scraper@rugged-abacus-405804.iam.gserviceaccount.com` (Editor).

### Out of Anthropic credits
Add credits at console.anthropic.com → Billing.

### Anthropic key leaked
Revoke immediately at console.anthropic.com → API Keys → ⋮ → Delete. Create a fresh key. Update `~/Documents/credentials_deal_tracker/anthropic_key_v2.txt` locally AND update the `ANTHROPIC_API_KEY` secret in the GitHub repo settings.

---

## Schema versioning

The schema doc is locked at v0.4: `reference/Nuclear_Deal_Tracker_Schema_Backbone_v0.4_locked.docx`.

If the schema changes in the future:

1. Update the locked schema doc
2. Update the column definitions at the top of `scraper.py` (`ANNOUNCEMENT_COLS`, `DEAL_COLS`)
3. Update the dashboard's CSV parsing
4. Update this README

Treat schema changes as major version bumps (v0.4 → v0.5). The scraper writes to specific column names; renaming a column without updating the scraper breaks the run.

---

## Future improvements (not yet built)

- **Better entity-resolution prompts** — current scraper sometimes links to plausibly-related context items (e.g. DOE ARDP) when the article only loosely connects. Tuning the Pass 2 prompt for stricter matching is a future iteration. See PROMPTS.md for the current Pass 2 logic and known failure modes.
- **PowerPoint export workflow** — the team has used scraper output to brief leadership; a one-click export for slide-ready summaries would save time.
- **Health/status indicator on the dashboard** — e.g. "Last scraper run: 4 hours ago · 0 errors." Useful for at-a-glance system health.
- **Hosted version of the data entry app** — currently the editor is local-only (each user installs Python + runs locally). A hosted version with simple auth would let any team member clear review items from any device. Was deferred pre-departure due to security and maintenance complexity.

---

## Quick reference: project types

| project_type value | Layer | Example |
|--------------------|-------|---------|
| Extension / Renewal | Layer 1 | TMI-1 SLR (Subsequent License Renewal) |
| Uprate | Layer 1 | Clinton Power Uprate |
| Restart | Layer 2 | Palisades Restart, TMI-1 Restart, Duane Arnold Restart |
| New Build — Large | Layer 3 | Vogtle 3&4, VC Summer 2&3 Completion |
| New Build — Advanced/SMR | Layer 4 | TerraPower Natrium Kemmerer, Long Mott Energy (Xe-100), Palisades SMR-300 (Pioneer), Clinch River BWRX-300 |

## Quick reference: project stages

In approximate order of advancement:

1. **Announcement** — public statement of intent, no formal action yet
2. **Pre-application / Planning** — feasibility studies, site evaluation, internal FID prep
3. **Permitting / Licensing** — NRC construction permit, environmental impact statement, etc.
4. **Permitted / Licensed** — all approvals received, awaiting financial close or construction start
5. **Construction** — physical construction underway
6. **Operation** — commercial operation date achieved
7. **Decommissioning** — end of useful life

Note: project stage is independent from deal stage. A project at "Permitting / Licensing" may have multiple deals at "Closed" stage (e.g. DOE loan, PPA) — the legal/financial transactions are separate from the physical project advancement.

## Quick reference: deal types

| deal_type | Economic nature | Example |
|-----------|-----------------|---------|
| PPA | Revenue contract | Microsoft buys TMI-1 power for 20 years |
| MOU | Memorandum of Understanding (non-binding) | Two parties agree to explore collaboration |
| LOI | Letter of Intent (more committal than MOU) | Specific terms outlined, not yet final |
| Joint Development Agreement | Partnership | Brookfield + The Nuclear Company on VC Summer |
| Loan | Debt | DOE Loan Programs Office to Palisades |
| Loan Guarantee | Debt facility | Federal guarantee on private loan |
| Equity Investment | Equity | X-energy Series D round |
| Grant | Non-dilutive funding | DOE ARDP award |
| Construction Contract | Service | EPC contractor signed for a project |
| Service Contract | Service | Operations or fuel services contract |
| EPC | Engineering, Procurement, Construction | Full project delivery contract |
| Subsidy/Credit | Tax/policy support | Production Tax Credit, Civil Nuclear Credit |
| Off-take Agreement | Revenue contract | Like PPA but for industrial steam, isotopes, etc. |
| Master Power Agreement | Revenue contract framework | Umbrella agreement covering multiple PPAs |
| Funding Agreement | Mixed financing | Combination of grant + loan + cost-share |
| License Action | Regulatory | NRC issues a license, renews one, approves restart |
| Strategic Partnership | Open-ended | Long-term collaboration without specific deal terms |

## Quick reference: deal stages

In order of advancement:

1. **Announced** — publicly known but no formal documents
2. **MOU** — non-binding memorandum signed
3. **LOI** — letter of intent with terms
4. **FID** — Final Investment Decision (board-approved commitment)
5. **Closed** — fully executed, money flowing
6. **Withdrawn** — terminated before close

A PPA that's "Announced" has different significance than one that's "Closed." The dashboard's Deal type and Deal stage filters help distinguish committed capital from pipeline signaling.

## Quick reference: context types

| context_type | What it is | Example |
|--------------|------------|---------|
| Federal Program | A specific DOE or other agency program | DOE ARDP, DOE Launch Pad |
| Federal Policy | An executive order, legislation, regulatory framework | Trump nuclear EOs (May 2025), IRA Section 45U |
| State Policy | A specific state law or executive action | NJ lifting nuclear moratorium |
| State Program | A specific state program with capacity/funding targets | NY 5GW Initiative, TX HB14 TANEO |
| Hyperscaler Portfolio | A tech company's overall nuclear strategy | Microsoft Nuclear Initiative, Amazon's nuclear bets |
| Vendor/Corporate | A vendor's deployment strategy across multiple sites | X-energy's 11 GW commercial pipeline |
| Aspirational Pipeline | Plans not yet at project stage | Utility's stated SMR consideration without specifics |
| Industry Framework | Cross-industry initiative | NRC Reform EO, NRC Part 53/57 framework |

Context items capture activity that doesn't fit a single project but creates the conditions in which projects happen. A federal grant program might fund a dozen projects over time — the program is one context, the funded projects are separate entities.

## Quick reference: announcement scope

This is the single most important field for filtering. Every announcement gets one of four scopes:

| scope | When to use it |
|-------|----------------|
| Project-Specific | About one specific project's progression — an NRC approval, construction start, deal closing, FID |
| Context-Specific | About a federal program, state policy, hyperscaler portfolio, or vendor activity (not tied to a single project) |
| Cross-Cutting | Touches multiple projects AND a context item, or spans the industry with specifics |
| Industry Commentary | Analysis or trend piece without a specific concrete action |

The dashboard's Activity Feed defaults to showing all four scopes. Filter to "Project-Specific" to focus on physical deployment milestones; filter to "Context-Specific" to focus on policy and portfolio-level activity.

---

## Credits & contact

Built by Edgar Aguilar (Research Associate, EFI Foundation Nuclear Scaling Initiative). Maintainership is in transition to a successor at EFI — see MIGRATION.md.

Schema design contributor: Lin (EFI)
Foundational dataset: Sonia's Nuclear Deal Tracker spreadsheet
Reference sources for Nuclear Layer Cake framework: World Nuclear Association U.S. country profile, World Nuclear Association Outlook Report
Built with Claude (Anthropic), Python, Google Sheets, and GitHub Pages.

For questions about the data model or to propose schema changes, contact the current maintainer per MIGRATION.md.
