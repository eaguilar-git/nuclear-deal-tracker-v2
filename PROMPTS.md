# Scraper Prompt Design

This document shows the exact prompts the scraper sends to Claude, along with the design rationale behind each piece. Useful for:
- Auditing why extractions came out a certain way
- Tuning the prompts when the scraper makes systematic mistakes
- Onboarding new team members to the system's logic

The scraper uses a two-pass classification pipeline. Pass 1 is a cheap screen; Pass 2 is full structured extraction. Both are JSON-output-only — no prose, no markdown fences.

---

## Pass 1 — screening

**Goal:** reject obvious non-fits before spending tokens on Pass 2.

**Model:** `claude-haiku-4-5-20251001` (cheapest model)
**Input size:** ~400 tokens (title + source + first 4000 chars of article body)
**Output size:** ~50 tokens (4-field JSON)

### System prompt

```
You are a U.S. nuclear industry analyst screening articles for a deal-tracking database.

Decide:
  1. Is this article about U.S. nuclear FISSION energy? (US scope; fusion is OUT)
  2. Does it describe a concrete deal, financing event, license action, deployment
     milestone, or significant policy/announcement worth tracking?

OUT of scope:
  - International-only stories (no US tie-in)
  - Fusion energy (CFS, Helion, ITER, tokamak, stellarator, TAE)
  - Pure science research without commercialization angle
  - Generic industry commentary
  - Retrospective analysis of past deals with no new development
  - Equity-research opinions

IN scope:
  - Signed agreements (PPA, MOU, JDA, EPC, supply contracts)
  - Financing events (equity rounds, DOE loans, grants, awards)
  - License actions (renewals, restarts, construction permits, applications, NRC approvals)
  - Deployment milestones (FID, COD, construction start, site selection)
  - State/federal policy action with quantitative target or commitment (capacity, dollars, deadline)
  - Hyperscaler procurement moves (offtake, equity, partnership)

Respond with ONLY this JSON (no markdown, no prose):
{"is_us": true/false, "is_fusion": true/false, "include": true/false, "reason": "one short sentence"}
```

### User prompt template

```
Article title: {title}
Source: {source}
Article text:
{body}
```

### Rationale

The prompt asks for three booleans because they're independent:
- `is_us=false` → hard reject (we don't track non-US activity)
- `is_fusion=true` → hard reject (out of scope per project definition)
- `include=false` → reject as not-actionable content

Listing 6 IN categories and 5 OUT categories explicitly catches edge cases that "what is a deal?" alone would miss:
- A NRC construction permit approval isn't a "deal" but is a license action → IN
- An earnings call mentioning a previously-announced deal isn't a new development → OUT
- An executive order with a quantitative target (e.g. "10 GW by 2035") is policy IN-scope; same EO with no targets would be commentary

The `reason` field forces Claude to articulate its decision. Useful for debugging when the scraper rejects something that should have been included.

### Why we screen instead of just running Pass 2 on everything

Pass 1 is ~25x cheaper than Pass 2. Most candidate articles are duplicates, retrospective analysis, or non-US news. Filtering at Pass 1 saves ~$0.10 per rejected article — across hundreds of daily candidates this matters.

---

## Pass 2 — structured extraction

**Goal:** extract a complete announcement row plus optionally a proposed deal row.

**Model:** `claude-haiku-4-5-20251001`, escalating to `claude-sonnet-4-5` on Medium confidence
**Input size:** ~9,300 tokens (full system prompt + article body + reference data + fingerprints)
**Output size:** ~600 tokens (structured JSON)

### System prompt

```
You are a nuclear deal analyst extracting structured data from U.S. nuclear news
for a v0.4 schema database.

The database has 6 entity types, all using snake_case lowercase IDs:
  - Sites (geographic locations, e.g. tmi, vogtle, kemmerer)
  - Reactor Units (physical reactors, e.g. tmi_1, vogtle_3, kemmerer_1)
  - Projects (development efforts that create, restart, uprate, or extend one
    or more reactor units, e.g. tmi_restart, long_mott_xe100)
  - Deals (specific transactions tied to one or more projects,
    e.g. ms_tmi_ppa_2024, doe_loan_palisades_2025)
  - Context Items (federal programs, hyperscaler portfolios, state policies,
    aspirational pipelines, e.g. doe_ardp, microsoft_nuclear_initiative,
    ny_nuclear_backbone)

An announcement can link to multiple entities. Always link to:
  - All projects the article concretely concerns
  - All context items (federal programs, state policies, hyperscaler portfolios)
    the article touches
  - Any specific deal_ids if the article references existing deals
  - Specific unit_ids only if the article names individual reactors
  - Specific site_ids only when site is the primary subject

ANNOUNCEMENT SCOPE (pick exactly one):
  - "Project-Specific":      About one specific project's progression
  - "Context-Specific":      About a federal program, state policy, hyperscaler
                             portfolio, or vendor activity (not tied to a single project)
  - "Cross-Cutting":         Touches multiple projects AND a context item, or
                             spans the whole industry with specifics
  - "Industry Commentary":   Analysis or trend piece without a specific concrete action

CONFIDENCE:
  - "High":   Clear extraction, all key fields confidently set
  - "Medium": Some ambiguity in entity matching or fields

PROPOSED DEAL CREATION (Q5 mechanic):
Only propose a new Deal when ALL of these are true:
  - Article describes a specific bilateral transaction (PPA, MOU, loan, grant,
    equity investment, JDA)
  - Counterparties are clearly named
  - At least one project_id can be matched from the reference list (no orphan deals)
  - Either capital_value_usd is disclosed OR deal_type is clearly identifiable
Otherwise return propose_deal = false. The user will manually create the deal record.

NEW ENTITY FLAGGING:
If the article mentions a specific project, site, or context that is NOT in the
reference data and seems important enough to add later, list it under
new_entity_flags as a short string like "project: Alabama Power SMR site selection"
or "context: AL nuclear incentive program".

ID MATCHING RULES:
  - Use IDs EXACTLY as written in the reference data
  - Multiple IDs are comma-separated (no spaces): "tmi_restart,palisades_restart"
  - Empty string "" means no link in that dimension
  - Don't invent IDs not in the reference data — flag them as new_entity_flags instead

Respond with ONLY valid JSON (no markdown fences, no prose).
```

### User prompt template

```
Article title: {title}
Article URL: {url}
Article date: {date}
Source: {source}

Article text:
{body}

═══ REFERENCE DATA (existing entities you can link to) ═══

PROJECTS (id: name | type | stage | lead):
{projects}

CONTEXTS (id: name | type | lead_entity):
{contexts}

DEALS (id: name | type | stage):
{deals}

REACTOR UNITS (id: name | site | status):
{units}

SITES (id: name | state):
{sites}

═══ EXISTING ANNOUNCEMENT FINGERPRINTS (avoid duplicating) ═══
{fingerprints}

Extract and return this JSON exactly:
{
  "headline":           "short factual headline (≤120 chars)",
  "summary":            "1–3 sentence factual summary, plain prose",
  "announcement_date":  "YYYY-MM-DD or YYYY-MM or YYYY",
  "announcement_scope": "Project-Specific | Context-Specific | Cross-Cutting | Industry Commentary",
  "confidence":         "High | Medium",
  "site_ids":           "comma-separated existing site_ids or \"\"",
  "unit_ids":           "comma-separated existing unit_ids or \"\"",
  "project_ids":        "comma-separated existing project_ids or \"\"",
  "deal_ids":           "comma-separated existing deal_ids or \"\"",
  "context_ids":        "comma-separated existing context_ids or \"\"",
  "new_entity_flags":   "comma-separated list like \"project: X / context: Y\" or \"\"",
  "is_duplicate":       true/false,
  "duplicate_reason":   "string or null",
  "notes":              "any nuance worth recording or \"\"",
  "propose_deal":       true/false,
  "proposed_deal":      null OR {
    "deal_name":             "human-readable deal name",
    "deal_type":             "one of the controlled values",
    "deal_stage":            "Announced | MOU | LOI | FID | Closed | Withdrawn",
    "economic_type":         "Grant | Equity | Debt | Refinancing | Subsidy/Credit Program | Revenue Contract | Service Contract | Partnership",
    "capital_value_usd":     number or null,
    "capital_value_disclosure": "Disclosed | Estimated | Undisclosed",
    "term_years":            number or null,
    "lead_entity":           "name of lead party",
    "lead_entity_type":      "Government | Hyperscaler | Utility | Reactor Vendor | Investor | Industrial | Fuel Supplier",
    "partners":              "comma-separated counterparties",
    "state":                 "two-letter US state code or empty",
    "capacity_at_stake_mw":  number or null,
    "government_support":    "comma-separated values from [Federal Loan, Loan Guarantee, USDA Loan, Tax Credit (PTC), Tax Credit (ITC), DOE Cost-Share, DOE Grant, ARDP, Civil Nuclear Credit, State Tax Credit, State Subsidy, ZEC, None]",
    "linked_project_ids":    "comma-separated project_ids the deal funds (must be in reference)",
    "linked_context_ids":    "comma-separated context_ids the deal sits within (must be in reference)"
  }
}
```

The `{projects}`, `{contexts}`, `{deals}`, `{units}`, `{sites}` placeholders are filled with formatted one-line summaries of all reference data (up to 80 entries per table). `{fingerprints}` lists the last 60 announcements' fingerprints so Claude can spot duplicates.

### Example of injected reference data

What Claude actually sees under "PROJECTS":

```
PROJECTS (id: name | type | stage | lead):
  turkey_point_slr: Turkey Point 3&4 SLR | Extension / Renewal | Operation | lead=Florida Power & Light (NextEra)
  peach_bottom_slr: Peach Bottom 2&3 SLR | Extension / Renewal | Operation | lead=Constellation Energy
  surry_slr: Surry 1&2 SLR | Extension / Renewal | Operation | lead=Dominion Energy
  ...
  tmi_restart: Three Mile Island Unit 1 Restart | Restart | Construction | lead=Constellation Energy
  palisades_restart: Palisades Restart | Restart | Construction | lead=Holtec International
  duane_arnold_restart: Duane Arnold Restart | Restart | Pre-application / Planning | lead=NextEra Energy
  ...
  vogtle_34_newbuild: Vogtle Units 3 & 4 New Build | New Build — Large | Operation | lead=Southern Nuclear Operating Company / Georgia Power
  long_mott_xe100: Long Mott Energy Center (Dow + X-energy) | New Build — Advanced/SMR | Pre-application / Planning | lead=Dow / X-energy
  palisades_smr300: Palisades SMR-300 (Pioneer Units) | New Build — Advanced/SMR | Pre-application / Planning | lead=Holtec International
  ...
```

And similar formats for the other 5 entity tables. Claude has the complete reference data inline in every Pass 2 call — there's no separate retrieval step.

### Rationale for the structure

**Why explicit enumeration of entity types at top:** without this, Claude tends to confuse projects with sites, or sites with reactor units. The 5-type distinction is non-obvious and the prompt teaches it.

**Why multi-FK rather than single-FK:** the v0.3 schema used single foreign keys (project_id OR program_id OR reactor_id) and constantly fought with reality. Real announcements often touch a federal program, a vendor's portfolio, AND a specific project simultaneously. v0.4 multi-FK lets the announcement properly represent this.

**Why announcement_scope:** the 4 scope buckets are the single most-used filter in the dashboard. Forcing Claude to pick one disambiguates "is this an article about X project, or is X project just the example of a broader story about Y context?" — those are different scopes.

**Why the Q5 mechanic (propose_deal):** earlier iterations had Claude eagerly create deal rows for any mention of a financial transaction. Result: many garbage deal rows for "DOE announces $50M for vague things." The current four-condition gate forces Claude to only propose deals when bilateral counterparties + valid project linkage + identifiable value/type are all present. Edgar still reviews each proposal before it's confirmed.

**Why new_entity_flags instead of inventing IDs:** if Claude is allowed to invent IDs, the database fragments fast. "DOE Reactor Pilot Program" might be coined as `doe_reactor_pilot`, then later as `pilot_program_doe`, then as `nrc_reactor_pilot`. Edgar wants exactly one ID per real entity, controlled centrally. The flag tells Edgar "this entity is worth adding to the reference data" without polluting the FK columns.

**Why fingerprints from existing announcements:** primary deduplication is by article URL (in the Seen tab). But the same event sometimes gets covered by two outlets with different URLs (Reuters + Bloomberg of the same NRC ruling). The fingerprint of "project_ids + context_ids + scope + first 80 chars of summary" gives Claude a way to flag these as `is_duplicate=true` before they get written as duplicate announcement rows.

### Confidence calibration

The prompt only allows High or Medium (not Low). When Pass 2 returns Medium, the scraper escalates to Sonnet for a second attempt. If Sonnet also returns Medium, the row is written but flagged in the Review tab for human spot-check.

This is deliberate — "Low" without an escalation path just creates a row in Review that Claude itself didn't trust. With escalation, we get one more attempt with a stronger model before bothering a human.

---

## Pre-filters (no LLM cost)

Before Pass 1 ever runs, three keyword filters reject candidates cheaply:

### Nuclear keyword filter (applied only to high-volume non-nuclear feeds)

```
nuclear, reactor, smr, fission, uranium, atomic, nrc, doe nuclear
```

Used on feeds like Google Blog, Microsoft, Reuters where most content isn't nuclear-related. If none of these keywords appear in the title+summary, the entry is dropped before Pass 1.

### Deal keyword filter (applied to every feed)

```
agreement, deal, contract, ppa, power purchase, mou, memorandum, partnership,
collaboration, investment, funding, loan, grant, award, financing, license
renewal, license extension, subsequent license, restart, new build, construction
permit, construction start, offtake, signed, announced, selected, approved, smr,
small modular, advanced reactor, uprate, fid, final investment, early site permit,
commits, commitment, pledge, executive order
```

Generic check that an article has *any* deal-shaped vocabulary. Roughly 80% of trade-press entries pass this filter; the rest get dropped.

### Fusion exclude filter (hard reject before LLM)

```
fusion energy, fusion reactor, fusion power, tokamak, stellarator, iter project,
commonwealth fusion, helion fusion, tae technologies, fusion startup, fusion plant
```

Even before Pass 1, if any of these phrases appear in the title or summary, the article is dropped. This catches fusion stories from feeds like ANS where fusion and fission coexist.

### Minimum year filter

Articles dated before 2024 are dropped before any LLM call. The v0.4 database starts in 2024; older articles aren't relevant.

---

## Debugging extraction issues

When the scraper produces a wrong extraction, here's the debugging workflow:

**1. Find the Review row** (if confidence was Medium) and check `raw_extraction` for what Claude returned.

**2. Check the source URL** — was the article body fetchable, or did the scraper fall back to the RSS summary? If summary-only, the extraction is inherently limited.

**3. Check entity linking** — did Claude link to the right projects/contexts? Common error modes:
   - Loose context linking (e.g., linking everything to `doe_ardp` because DOE is mentioned)
   - Missing context linking (e.g., article about NY 5GW initiative not linked to `ny_nuclear_backbone`)
   - Wrong project linked (e.g., generic "Vogtle" linked to `vogtle_3` specifically when article was about the broader site)

**4. Decide whether the fix is in:**
   - The prompt (add a clearer instruction)
   - The reference data (the entity wasn't named clearly enough in the reference)
   - The pre-filter (the article shouldn't have been processed at all)
   - Acceptable as-is (single-instance miss, not systemic)

Most extraction issues we've seen fall into **loose context linking** — Claude reaches for plausible-sounding context items when the article only loosely connects. Tightening the Pass 2 prompt with examples of when NOT to link is a future iteration.

---

## When to update prompts

Edit `PASS1_SYSTEM`, `PASS1_USER_TMPL`, `PASS2_SYSTEM`, or `PASS2_USER_TMPL` in `scraper.py` when:

- **Schema changes** (new field added to Announcements or Deals) → update Pass 2 output JSON spec
- **New scope category added** → update enum in Pass 2 prompt + dashboard filter
- **Systematic mistake observed** in extractions (e.g., scraper keeps confusing Sites with Projects) → add corrective instruction to system prompt
- **Cost optimization** (Pass 1 over- or under-inclusive) → tune IN/OUT criteria

Always test prompt changes manually on 5–10 articles before committing. Run `python3 scraper.py` locally and watch the per-article output. A bad prompt edit can cause the daily scheduled run to write garbage to the live Sheet.

Schema-level changes (new entity type, renamed column) require coordinated updates to: the locked schema doc, the scraper column constants, the prompt JSON spec, the dashboard's CSV parsing, and this document.
