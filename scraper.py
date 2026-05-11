"""
scraper.py  —  Nuclear Deal Tracker v3.0
=========================================================================
Scrapes nuclear industry RSS feeds, classifies articles via Claude, and
writes structured announcement and deal data to the v0.4 6-tab schema:
  Sites · Reactor Units · Projects · Deals · Context Items · Announcements
  + operational tabs: Seen, Review

Design notes (v3 vs v2.2):
  - Targets v0.4 schema (multi-FK arrays: project_ids, context_ids, deal_ids,
    unit_ids, site_ids).  Replaces v2.2's single-FK fields.
  - Reference data: 5 entity tables loaded each run, used as Claude context.
  - Pass 1 (Haiku): early checks for is_us, is_fusion, deal-relevance.
    is_fusion=True is a hard exclude (project scope is fission).
    is_us=False is a hard exclude (scope is U.S. nuclear).
  - Pass 2 (Haiku, escalates to Sonnet on low confidence): full structured
    extraction including multi-FK linking + new_entity_flags for entities
    Claude saw mentioned but couldn't match to existing reference data.
  - Q5 mechanic: scraper writes proposed Deal rows with confirmation_status
    = "Proposed (scraper)" when very confident a new deal is real and matches
    a project. Dashboard filters them out by default; user reviews and flips
    to "Confirmed" in the Sheet.
  - Significance / Impact removed (not in v0.4).
  - Capital values moved off Announcements (live on Deals in v0.4).
  - announcement_scope vocabulary: Project-Specific · Context-Specific
    · Cross-Cutting · Industry Commentary
  - confidence vocabulary: High · Medium (Low → escalation only)
  - Deduplication via Seen tab fingerprint hash on (title + url).
  - All references to entities use snake_case lowercase IDs (e.g. tmi_1,
    palisades_smr300, microsoft_nuclear_initiative).

Environment variables required
-------------------------------
  ANTHROPIC_API_KEY              Claude API key
  GOOGLE_SHEET_ID                v2 Sheet ID
  GOOGLE_SERVICE_ACCOUNT_JSON    Full service account JSON content
  ANTHROPIC_MODEL  (optional)    Override Pass 1 model
  ESCALATION_MODEL (optional)    Override Pass 2 escalation model
"""

import os
import re
import json
import time
import hashlib
import datetime
from email.utils import parsedate_to_datetime

import feedparser
import requests
from bs4 import BeautifulSoup
import anthropic
import gspread
from google.oauth2.service_account import Credentials


# ─── CONFIG ─────────────────────────────────────────────────────────────────

MODEL            = os.environ.get("ANTHROPIC_MODEL",   "claude-haiku-4-5-20251001")
ESCALATION_MODEL = os.environ.get("ESCALATION_MODEL",  "claude-sonnet-4-5")
BODY_CHAR_LIMIT  = 9000     # full body for Pass 2
PASS1_CHAR_LIMIT = 4000     # truncated body for cheap Pass 1
MIN_YEAR         = 2024     # ignore articles older than this
MAX_FEEDS_PER_RUN = 80      # entries per feed cap (RSS gives ~25 typically)

# Tab names — must match what seed_v04.py created
TAB_SITES         = "Sites"
TAB_UNITS         = "Reactor Units"
TAB_PROJECTS      = "Projects"
TAB_DEALS         = "Deals"
TAB_CONTEXTS      = "Context Items"
TAB_ANNOUNCEMENTS = "Announcements"
TAB_SEEN          = "Seen"
TAB_REVIEW        = "Review"

# Column orderings (must match Sheet headers exactly)
ANNOUNCEMENT_COLS = [
    "announcement_id", "headline", "source", "source_url",
    "published_date", "captured_date",
    "site_ids", "unit_ids", "project_ids", "deal_ids", "context_ids",
    "announcement_scope", "new_entity_flags", "confidence",
    "summary", "notes",
]

# Deal columns: match the Sheet, including the v0.4 confirmation_status
DEAL_COLS = [
    "deal_id", "confirmation_status", "deal_name",
    "project_ids", "context_ids", "deal_type", "deal_stage",
    "economic_type", "capital_value_usd", "capital_value_disclosure",
    "cost_contribution_usd", "is_portfolio_deal", "allocations",
    "term_years", "lead_entity", "lead_entity_type",
    "partners", "technology_provider", "state", "region",
    "capacity_at_stake_mw", "cost_recovery", "government_support",
    "announcement_date", "close_date", "source_url", "notes",
]

REVIEW_COLS = [
    "review_id", "scraped_at", "article_title", "article_url",
    "reason", "raw_extraction",
]

SEEN_COLS = ["hash", "title", "url", "scraped_at"]


# ─── RSS FEEDS ──────────────────────────────────────────────────────────────
# nuclear_only=True: pre-filter entries to nuclear keywords before deal check
# (used for high-volume feeds covering many non-nuclear topics)

FEEDS = [
    # ── Tier 1: Industry trade press ───────────────────────────────────────
    {"name": "World Nuclear News",       "url": "https://www.world-nuclear-news.org/rss"},
    {"name": "ANS Nuclear Newswire",     "url": "https://www.ans.org/news/feed"},
    {"name": "NEI News",                 "url": "https://www.nei.org/rss"},
    {"name": "Power Magazine Nuclear",   "url": "https://www.powermag.com/category/nuclear/feed/"},
    {"name": "Power Engineering",        "url": "https://www.power-eng.com/feed/"},
    {"name": "Utility Dive",             "url": "https://www.utilitydive.com/feeds/news/"},
    {"name": "Neutron Bytes",            "url": "https://neutronbytes.com/feed/"},
    {"name": "Nuclear Engineering Intl", "url": "https://www.neimagazine.com/rss"},
    {"name": "Canary Media",             "url": "https://www.canarymedia.com/rss"},
    {"name": "Latitude Media",           "url": "https://www.latitudemedia.com/feed"},
    {"name": "Atomic Insights",          "url": "https://atomicinsights.com/feed"},
    {"name": "NucNet",                   "url": "https://nucnet.org/feed.rss"},

    # ── Tier 2: Government & regulatory ────────────────────────────────────
    {"name": "DOE Nuclear Energy",       "url": "https://www.energy.gov/ne/rss.xml"},
    {"name": "DOE News",                 "url": "https://www.energy.gov/news/rss.xml"},
    {"name": "NRC News",                 "url": "https://www.nrc.gov/reading-rm/doc-collections/news/rss.xml"},
    {"name": "NRC Press Releases",       "url": "https://www.nrc.gov/reading-rm/doc-collections/press-releases/rss.xml"},
    {"name": "IAEA Nuclear Power",       "url": "https://www.iaea.org/feeds/topical/nuclear-power.xml"},
    {"name": "IAEA Newscenter",          "url": "https://www.iaea.org/newscenter/feed"},

    # ── Tier 3: Company newsrooms (only those with verified working RSS) ──
    {"name": "Holtec News",              "url": "https://holtecinternational.com/feed/"},
    {"name": "NANO Nuclear IR",          "url": "https://ir.nanonuclearenergy.com/rss/news-releases.xml"},
    {"name": "Helion Energy",            "url": "https://www.helionenergy.com/feed/"},
    {"name": "X-energy News",            "url": "https://x-energy.com/news/feed/"},
    {"name": "TVA Newsroom",             "url": "https://www.tva.com/rss/news"},
    {"name": "Brookfield IR",            "url": "https://bam.brookfield.com/news-releases/rss", "nuclear_only": True},
    {"name": "Constellation IR",         "url": "https://investors.constellationenergy.com/rss/news-releases.xml"},
    {"name": "Westinghouse Blog",        "url": "https://info.westinghousenuclear.com/blog/rss.xml"},
    # Dropped due to dead/404 RSS endpoints (verified May 2026):
    #   TerraPower, Kairos Power, Oklo IR, Commonwealth Fusion, GE Vernova,
    #   NuScale, Duke Energy, Dominion Energy, Southern Company,
    #   Entergy, NextEra, Xcel, PSEG, Vistra, AEP, Energy Northwest,
    #   Last Energy, Aalo Atomics, Radiant, BWXT, Fermi America.
    #   Coverage for these comes via Google News queries below + trade press.

    # ── Tier 5: Google News queries (vendor & topic coverage proxy) ──
    # Google News doesn't have native RSS for many vendors, so we use Google News
    # search RSS as a backfill. Returns up to 100 entries per query, aggregated
    # from thousands of sources. nuclear_only filter NOT needed (queries already
    # constrain to nuclear).
    {"name": "Google News: TerraPower",          "url": "https://news.google.com/rss/search?q=%22TerraPower%22+Natrium+OR+Kemmerer+OR+reactor&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: NuScale",             "url": "https://news.google.com/rss/search?q=%22NuScale%22+nuclear+OR+SMR&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: Kairos Power",        "url": "https://news.google.com/rss/search?q=%22Kairos+Power%22+reactor+OR+Hermes&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: Oklo",                "url": "https://news.google.com/rss/search?q=%22Oklo%22+nuclear+OR+Aurora+OR+reactor&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: GE Vernova",          "url": "https://news.google.com/rss/search?q=%22GE+Vernova%22+nuclear+OR+BWRX&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: Duke Energy",         "url": "https://news.google.com/rss/search?q=%22Duke+Energy%22+nuclear+OR+reactor+OR+SMR&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: Dominion",            "url": "https://news.google.com/rss/search?q=%22Dominion+Energy%22+nuclear+OR+reactor+OR+SMR&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: NextEra",             "url": "https://news.google.com/rss/search?q=%22NextEra%22+nuclear+OR+Duane+Arnold&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: Southern Co",         "url": "https://news.google.com/rss/search?q=%22Southern+Company%22+nuclear+OR+Vogtle&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: Entergy",             "url": "https://news.google.com/rss/search?q=%22Entergy%22+nuclear+OR+reactor&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: Vistra",              "url": "https://news.google.com/rss/search?q=%22Vistra%22+nuclear+OR+Comanche+Peak&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Google News: BWRX-300",            "url": "https://news.google.com/rss/search?q=%22BWRX-300%22&hl=en-US&gl=US&ceid=US:en"},

    # ── Tier 6: Press wires & policy adjacents ──
    {"name": "PR Newswire Energy",       "url": "https://www.prnewswire.com/rss/energy-utilities-latest-news/energy-utilities-latest-news-list.rss",   "nuclear_only": True},
    {"name": "PR Newswire Utilities",    "url": "https://www.prnewswire.com/rss/utilities-news-releases-list.rss",                                     "nuclear_only": True},
    {"name": "GlobeNewswire Energy",     "url": "https://www.globenewswire.com/RssFeed/industry/2300%20-%20Energy/feedTitle/GlobeNewswire%20-%20Energy", "nuclear_only": True},
    {"name": "Inside Climate News",      "url": "https://insideclimatenews.org/feed/",                                                                  "nuclear_only": True},
    {"name": "CNBC Energy",              "url": "https://www.cnbc.com/id/19836768/device/rss/rss.html",                                                 "nuclear_only": True},
    {"name": "EIA Press",                "url": "https://www.eia.gov/rss/press_rss.xml",                                                                "nuclear_only": True},

    # ── Tier 4: Hyperscalers / finance ──
    {"name": "Google Blog",              "url": "https://blog.google/rss/",                       "nuclear_only": True},
    {"name": "Microsoft On the Issues",  "url": "https://blogs.microsoft.com/on-the-issues/feed/","nuclear_only": True},
    {"name": "Meta Newsroom",            "url": "https://about.fb.com/rss/",                      "nuclear_only": True},
    {"name": "Amazon About",             "url": "https://www.aboutamazon.com/news/rss",           "nuclear_only": True},
]


# ─── KEYWORD PRE-FILTERS ────────────────────────────────────────────────────
# Used to throw out obviously irrelevant entries before any LLM call.

DEAL_KEYWORDS = [
    "agreement", "deal", "contract", "ppa", "power purchase",
    "mou", "memorandum", "partnership", "collaboration",
    "investment", "funding", "loan", "grant", "award",
    "financing", "license renewal", "license extension", "subsequent license",
    "restart", "new build", "construction permit", "construction start",
    "offtake", "signed", "announced", "selected", "approved",
    "smr", "small modular", "advanced reactor",
    "uprate", "fid", "final investment", "early site permit",
    "commits", "commitment", "pledge", "executive order",
]

NUCLEAR_KEYWORDS = [
    "nuclear", "reactor", "smr", "fission",
    "uranium", "atomic", "nrc", "doe nuclear",
]

# Hard exclude: fusion is out of scope. Match these and reject early.
FUSION_KEYWORDS = [
    "fusion energy", "fusion reactor", "fusion power",
    "tokamak", "stellarator", "iter project",
    "commonwealth fusion", "helion fusion", "tae technologies",
    "fusion startup", "fusion plant",
]


# ─── V0.4 CONTROLLED VOCABULARIES ───────────────────────────────────────────
# Drawn from actual v0.4 schema. Pass 2 prompt enumerates these so Claude
# stays inside the lines. New values would need schema-doc updates anyway.

PROJECT_TYPES = [
    "Extension / Renewal",
    "New Build — Advanced/SMR",
    "New Build — Large",
    "Restart",
    "Uprate",
]

PROJECT_STAGES = [
    "Announcement",
    "Pre-application / Planning",
    "Permitting / Licensing",
    "Permitted / Licensed",
    "Construction",
    "Operation",
    "Decommissioning",
]

PROJECT_STATUSES = [
    "Active", "Completed", "Paused", "Cancelled",
]

DEAL_TYPES = [
    "PPA", "MOU", "LOI", "Joint Development Agreement",
    "Loan", "Loan Guarantee", "Equity Investment", "Grant",
    "Construction Contract", "Service Contract", "EPC",
    "Subsidy/Credit", "Off-take Agreement", "Master Power Agreement",
    "Funding Agreement", "License Action", "Strategic Partnership",
]

DEAL_STAGES = [
    "Announced", "MOU", "LOI", "FID", "Closed", "Withdrawn",
]

ECONOMIC_TYPES = [
    "Grant", "Equity", "Debt", "Refinancing",
    "Subsidy/Credit Program", "Revenue Contract",
    "Service Contract", "Partnership",
]

LEAD_ENTITY_TYPES = [
    "Government", "Hyperscaler", "Utility", "Reactor Vendor",
    "Investor", "Industrial", "Fuel Supplier",
]

CONTEXT_TYPES = [
    "Federal Program", "Federal Policy", "State Policy", "State Program",
    "Hyperscaler Portfolio", "Vendor/Corporate", "Aspirational Pipeline",
    "Industry Framework",
]

ANNOUNCEMENT_SCOPES = [
    "Project-Specific", "Context-Specific", "Cross-Cutting", "Industry Commentary",
]

GOVERNMENT_SUPPORT = [
    "Federal Loan", "Loan Guarantee", "USDA Loan",
    "Tax Credit (PTC)", "Tax Credit (ITC)",
    "DOE Cost-Share", "DOE Grant", "ARDP",
    "Civil Nuclear Credit", "State Tax Credit",
    "State Subsidy", "ZEC", "None",
]



# ─── PROMPTS ────────────────────────────────────────────────────────────────

PASS1_SYSTEM = """You are a U.S. nuclear industry analyst screening articles for a deal-tracking database.

Decide:
  1. Is this article about U.S. nuclear FISSION energy? (US scope; fusion is OUT)
  2. Does it describe a concrete deal, financing event, license action, deployment milestone, or significant policy/announcement worth tracking?

OUT of scope: international-only stories (no US tie-in), fusion energy (CFS, Helion, ITER, tokamak, stellarator, TAE), pure science research without commercialization angle, generic industry commentary, retrospective analysis of past deals with no new development, equity-research opinions.

IN scope:
  - Signed agreements (PPA, MOU, JDA, EPC, supply contracts)
  - Financing events (equity rounds, DOE loans, grants, awards)
  - License actions (renewals, restarts, construction permits, applications, NRC approvals)
  - Deployment milestones (FID, COD, construction start, site selection)
  - State/federal policy action with quantitative target or commitment (capacity, dollars, deadline)
  - Hyperscaler procurement moves (offtake, equity, partnership)

Respond with ONLY this JSON (no markdown, no prose):
{"is_us": true/false, "is_fusion": true/false, "include": true/false, "reason": "one short sentence"}"""

PASS1_USER_TMPL = """Article title: {title}
Source: {source}
Article text:
{body}"""


PASS2_SYSTEM = """You are a nuclear deal analyst extracting structured data from U.S. nuclear news for a v0.4 schema database.

The database has 6 entity types, all using snake_case lowercase IDs:
  - Sites (geographic locations, e.g. tmi, vogtle, kemmerer)
  - Reactor Units (physical reactors, e.g. tmi_1, vogtle_3, kemmerer_1)
  - Projects (development efforts, e.g. tmi_restart, long_mott_xe100)
  - Deals (specific transactions, e.g. ms_tmi_ppa_2024, doe_loan_palisades_2025)
  - Context Items (federal programs, hyperscaler portfolios, state policies, aspirational pipelines, e.g. doe_ardp, microsoft_nuclear_initiative, ny_nuclear_backbone)

An announcement can link to multiple entities. Always link to:
  - All projects the article concretely concerns
  - All context items (federal programs, state policies, hyperscaler portfolios) the article touches
  - Any specific deal_ids if the article references existing deals
  - Specific unit_ids only if the article names individual reactors
  - Specific site_ids only when site is the primary subject

ANNOUNCEMENT SCOPE (pick exactly one):
  - "Project-Specific":      About one specific project's progression
  - "Context-Specific":      About a federal program, state policy, hyperscaler portfolio, or vendor activity (not tied to a single project)
  - "Cross-Cutting":         Touches multiple projects AND a context item, or spans the whole industry with specifics
  - "Industry Commentary":   Analysis or trend piece without a specific concrete action

CONFIDENCE:
  - "High":   Clear extraction, all key fields confidently set
  - "Medium": Some ambiguity in entity matching or fields

PROPOSED DEAL CREATION (Q5 mechanic):
Only propose a new Deal when ALL of these are true:
  - Article describes a specific bilateral transaction (PPA, MOU, loan, grant, equity investment, JDA)
  - Counterparties are clearly named
  - At least one project_id can be matched from the reference list (no orphan deals)
  - Either capital_value_usd is disclosed OR deal_type is clearly identifiable
Otherwise return propose_deal = false. The user will manually create the deal record.

NEW ENTITY FLAGGING:
If the article mentions a specific project, site, or context that is NOT in the reference data and seems important enough to add later, list it under new_entity_flags as a short string like "project: Alabama Power SMR site selection" or "context: AL nuclear incentive program".

ID MATCHING RULES:
  - Use IDs EXACTLY as written in the reference data
  - Multiple IDs are comma-separated (no spaces): "tmi_restart,palisades_restart"
  - Empty string "" means no link in that dimension
  - Don't invent IDs not in the reference data — flag them as new_entity_flags instead

Respond with ONLY valid JSON (no markdown fences, no prose)."""


PASS2_USER_TMPL = """Article title: {title}
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
{{
  "headline":           "short factual headline (≤120 chars)",
  "summary":            "1–3 sentence factual summary, plain prose",
  "announcement_date":  "YYYY-MM-DD or YYYY-MM or YYYY",
  "announcement_scope": "Project-Specific | Context-Specific | Cross-Cutting | Industry Commentary",
  "confidence":         "High | Medium",
  "site_ids":           "comma-separated existing site_ids or \\"\\"",
  "unit_ids":           "comma-separated existing unit_ids or \\"\\"",
  "project_ids":        "comma-separated existing project_ids or \\"\\"",
  "deal_ids":           "comma-separated existing deal_ids or \\"\\"",
  "context_ids":        "comma-separated existing context_ids or \\"\\"",
  "new_entity_flags":   "comma-separated list like \\"project: X / context: Y\\" or \\"\\"",
  "is_duplicate":       true/false,
  "duplicate_reason":   "string or null",
  "notes":              "any nuance worth recording or \\"\\"",
  "propose_deal":       true/false,
  "proposed_deal":      null OR {{
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
  }}
}}"""


# ─── GOOGLE SHEETS ──────────────────────────────────────────────────────────

def get_gsheet_client():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def load_tab(spreadsheet, tab_name, retries=3):
    """Load a sheet tab as list of dicts, with retry on 429."""
    for attempt in range(retries):
        try:
            ws = spreadsheet.worksheet(tab_name)
            time.sleep(0.5)
            return ws.get_all_records()
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and attempt < retries - 1:
                wait = 20 * (attempt + 1)
                print(f"    Rate limited — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def ensure_tab(spreadsheet, tab_name, headers):
    existing = [ws.title for ws in spreadsheet.worksheets()]
    if tab_name not in existing:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=2000, cols=len(headers) + 2)
        ws.append_row(headers)
        print(f"  Created tab: {tab_name}")
    return spreadsheet.worksheet(tab_name)


def append_rows_batch(spreadsheet, tab_name, rows, retries=3):
    """Batch-append rows. Each row is a dict keyed by sheet column name."""
    if not rows:
        return
    for attempt in range(retries):
        try:
            ws = spreadsheet.worksheet(tab_name)
            headers = ws.row_values(1)
            values = [[str(row.get(h, "") or "") for h in headers] for row in rows]
            ws.append_rows(values, value_input_option="RAW")
            time.sleep(1)
            return
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and attempt < retries - 1:
                wait = 20 * (attempt + 1)
                print(f"    Rate limited on write — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def get_next_id_num(spreadsheet, tab, prefix, col_idx=1, pad=4):
    """Read existing IDs and return next integer suffix.
    e.g. prefix='ann_', col_idx=1 → reads col A, finds ann_0114, returns 115.
    """
    try:
        ws = spreadsheet.worksheet(tab)
        existing = [v for v in ws.col_values(col_idx)[1:] if v.startswith(prefix)]
        nums = []
        for v in existing:
            try:
                nums.append(int(v[len(prefix):]))
            except Exception:
                pass
        return max(nums) + 1 if nums else 1
    except Exception:
        return 1


def load_seen_hashes(spreadsheet):
    try:
        ws = spreadsheet.worksheet(TAB_SEEN)
        return set(ws.col_values(1)[1:])
    except Exception:
        return set()



# ─── REFERENCE DATA ─────────────────────────────────────────────────────────

def load_reference_data(spreadsheet):
    """Load all 5 reference entity tabs + announcement fingerprints."""
    print("  Loading Sites...")
    sites = load_tab(spreadsheet, TAB_SITES)
    site_lookup = [(r["site_id"], r["site_name"], r.get("state",""))
                   for r in sites if r.get("site_id")]

    print("  Loading Reactor Units...")
    units = load_tab(spreadsheet, TAB_UNITS)
    unit_lookup = [
        (r["unit_id"], r["unit_name"], r.get("site_id",""), r.get("asset_status",""))
        for r in units if r.get("unit_id")
    ]

    print("  Loading Projects...")
    projects = load_tab(spreadsheet, TAB_PROJECTS)
    project_lookup = [
        (r["project_id"], r["project_name"], r.get("project_type",""),
         r.get("project_stage",""), r.get("lead_developer",""))
        for r in projects if r.get("project_id")
    ]

    print("  Loading Deals...")
    deals = load_tab(spreadsheet, TAB_DEALS)
    deal_lookup = [
        (r["deal_id"], r["deal_name"], r.get("deal_type",""), r.get("deal_stage",""))
        for r in deals if r.get("deal_id")
    ]

    print("  Loading Context Items...")
    contexts = load_tab(spreadsheet, TAB_CONTEXTS)
    context_lookup = [
        (r["context_id"], r["context_name"], r.get("context_type",""),
         r.get("lead_entity",""))
        for r in contexts if r.get("context_id")
    ]

    print("  Loading existing Announcements for deduplication...")
    try:
        announcements = load_tab(spreadsheet, TAB_ANNOUNCEMENTS)
        # Fingerprint = compact identity string (project_ids + scope + first 80 chars of summary)
        fingerprints = [
            f"{r.get('project_ids','')}|{r.get('context_ids','')}|"
            f"{r.get('announcement_scope','')}|{str(r.get('summary',''))[:80]}"
            for r in announcements
        ]
    except Exception:
        fingerprints = []

    return {
        "site_lookup":    site_lookup,
        "unit_lookup":    unit_lookup,
        "project_lookup": project_lookup,
        "deal_lookup":    deal_lookup,
        "context_lookup": context_lookup,
        "fingerprints":   fingerprints,
    }


def format_ref_list(items, fmt, max_items=80):
    """Format a list of tuples into reference lines for prompt injection.
    fmt is a function that takes a tuple and returns a string."""
    lines = []
    for item in items[:max_items]:
        lines.append("  " + fmt(item))
    if len(items) > max_items:
        lines.append(f"  ... and {len(items) - max_items} more")
    return "\n".join(lines) if lines else "  (none)"


def format_reference_data(ref):
    """Build the long reference-data string for Pass 2 prompt.
    Sites are most numerous so we cap them tightest. Active reactor units only."""
    sites_str = format_ref_list(
        ref["site_lookup"],
        lambda t: f"{t[0]}: {t[1]} | {t[2]}",
        max_items=80,
    )
    # Filter to operational and planned units (skip decom-only) to control size
    active_units = [u for u in ref["unit_lookup"]
                    if u[3] in ("Operating", "Planned", "Shut Down")]
    units_str = format_ref_list(
        active_units,
        lambda t: f"{t[0]}: {t[1]} | site={t[2]} | {t[3]}",
        max_items=80,
    )
    projects_str = format_ref_list(
        ref["project_lookup"],
        lambda t: f"{t[0]}: {t[1]} | {t[2]} | {t[3]} | lead={t[4]}",
        max_items=80,
    )
    contexts_str = format_ref_list(
        ref["context_lookup"],
        lambda t: f"{t[0]}: {t[1]} | {t[2]} | lead={t[3]}",
        max_items=80,
    )
    deals_str = format_ref_list(
        ref["deal_lookup"],
        lambda t: f"{t[0]}: {t[1]} | {t[2]} | {t[3]}",
        max_items=80,
    )
    return {
        "sites":    sites_str,
        "units":    units_str,
        "projects": projects_str,
        "contexts": contexts_str,
        "deals":    deals_str,
    }


# ─── UTILITIES ──────────────────────────────────────────────────────────────

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def clean_url(url):
    """Normalize URLs: collapse accidental double slashes in path, strip whitespace.
    Preserves the // after the protocol (https://)."""
    if not url:
        return ""
    url = str(url).strip()
    # Preserve scheme://, then collapse any other // in the rest of the URL
    m = re.match(r'^(https?://)(.*)$', url)
    if m:
        scheme, rest = m.group(1), m.group(2)
        rest = re.sub(r'/{2,}', '/', rest)
        return scheme + rest
    return url


def resolve_google_news_url(url):
    """Google News RSS gives URLs like https://news.google.com/rss/articles/CBM...
    Follow the redirect to get the real publisher URL, so dedup catches the same
    article appearing in multiple GN queries.

    Returns the resolved URL on success, or the original URL on any failure.
    Returns quickly (5s timeout) — we don't want this to slow down feed parsing.
    """
    if not url or "news.google.com" not in url:
        return url
    try:
        r = requests.head(
            url, timeout=5, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NuclearDealBot/3.0)"}
        )
        return r.url if r.url else url
    except Exception:
        return url


def entry_hash(title, url):
    return hashlib.md5(f"{title}{url}".encode()).hexdigest()


def has_nuclear_keyword(text):
    t = text.lower()
    return any(kw in t for kw in NUCLEAR_KEYWORDS)


def is_deal_candidate(title, summary):
    t = (title + " " + summary).lower()
    return any(kw in t for kw in DEAL_KEYWORDS)


def looks_like_fusion(text):
    t = text.lower()
    return any(kw in t for kw in FUSION_KEYWORDS)


def parse_entry_date(entry):
    """Safely parse RSS entry date to YYYY-MM-DD string."""
    if entry.get("published"):
        try:
            return parsedate_to_datetime(entry.published).strftime("%Y-%m-%d")
        except Exception:
            pass
    if entry.get("published_parsed"):
        try:
            return datetime.date(*entry.published_parsed[:3]).isoformat()
        except Exception:
            pass
    return entry.get("published", "")[:10]


# ─── ARTICLE FETCHER ────────────────────────────────────────────────────────

def fetch_article_text(url):
    """Fetch and clean article body, capped at BODY_CHAR_LIMIT chars."""
    try:
        r = requests.get(
            url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NuclearDealBot/3.0)"},
            allow_redirects=True,
        )
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "iframe", "noscript", "figure"]):
            tag.decompose()
        body = (
            soup.find("article") or
            soup.find("main") or
            soup.find(class_=re.compile(r"article|content|story|post|body", re.I)) or
            soup.body
        )
        text = clean(body.get_text(separator=" ")) if body else ""
        return text[:BODY_CHAR_LIMIT]
    except requests.exceptions.Timeout:
        print("    Fetch timeout")
        return ""
    except Exception as e:
        print(f"    Fetch error: {e}")
        return ""


# ─── CLAUDE CALLS ───────────────────────────────────────────────────────────
#
# call_claude returns a tuple: (result, error_kind)
#   - (dict, None)         → success, parsed JSON dict
#   - (None, "parse")      → response received but JSON unparseable (deterministic, OK to mark as Seen)
#   - (None, "api")        → API rejected/errored (transient, do NOT mark as Seen)
#   - (None, "other")      → unexpected exception (treat as transient — do NOT mark as Seen)
#
# The "api" vs "parse" distinction matters because API errors are usually transient
# (credit balance, rate limit, network) and the article should be re-tried on the
# next scraper run. Logging it to Seen would lose it forever.

# Anthropic API error codes that indicate transient/external problems (don't mark Seen)
TRANSIENT_API_STATUSES = {
    400,  # invalid_request_error — includes "credit balance too low"
    401,  # auth — wrong key, transient until fixed
    403,  # permission — transient until fixed
    408,  # request timeout
    429,  # rate limit
    500, 502, 503, 504,  # server errors
    529,  # overloaded
}

def call_claude(client, system, user_msg, model=None, max_tokens=2200):
    """Single Claude call. Returns (result_dict_or_None, error_kind)."""
    use_model = model or MODEL
    try:
        resp = client.messages.create(
            model=use_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        # Strip optional markdown fences
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        try:
            return json.loads(raw), None
        except json.JSONDecodeError as e:
            print(f"    JSON parse error ({use_model}): {e}")
            return None, "parse"
    except anthropic.APIStatusError as e:
        print(f"    API error ({use_model}): {e.status_code} {e.message}")
        # All API status errors treated as transient (will retry next run)
        return None, "api"
    except anthropic.APIConnectionError as e:
        print(f"    API connection error ({use_model}): {e}")
        return None, "api"
    except anthropic.APITimeoutError as e:
        print(f"    API timeout ({use_model}): {e}")
        return None, "api"
    except Exception as e:
        # Unknown error: be conservative and treat as transient
        print(f"    Claude error ({use_model}): {type(e).__name__}: {e}")
        return None, "other"


def unwrap_result(result):
    """If Claude returned a list, unwrap first dict element."""
    if isinstance(result, list):
        return result[0] if result and isinstance(result[0], dict) else None
    return result


def pass1_screen(client, title, body, source):
    """Pass 1: is_us, is_fusion, include screen. Cheap Haiku call.
    Returns (is_us, is_fusion, include, reason, error_kind).
    error_kind is None on success, or 'api'/'parse'/'other' on failure."""
    user_msg = PASS1_USER_TMPL.format(
        title=title, source=source, body=body[:PASS1_CHAR_LIMIT]
    )
    result, error_kind = call_claude(client, PASS1_SYSTEM, user_msg, max_tokens=300)
    if not result:
        return False, False, False, "claude error", error_kind
    return (
        bool(result.get("is_us", False)),
        bool(result.get("is_fusion", False)),
        bool(result.get("include", False)),
        result.get("reason", ""),
        None,
    )


def pass2_extract(client, article, ref_text, model=None):
    """Pass 2: full structured extraction with FK linking.
    Returns (result_dict_or_None, error_kind)."""
    user_msg = PASS2_USER_TMPL.format(
        title=article["title"],
        url=article["link"],
        date=article.get("date", "unknown"),
        source=article.get("source", "unknown"),
        body=article.get("body", "")[:BODY_CHAR_LIMIT],
        sites=ref_text["sites"],
        units=ref_text["units"],
        projects=ref_text["projects"],
        contexts=ref_text["contexts"],
        deals=ref_text["deals"],
        fingerprints=(
            "\n".join(f"  {f}" for f in ref_text.get("fingerprints", [])[-60:])
            or "  (none)"
        ),
    )
    result, error_kind = call_claude(client, PASS2_SYSTEM, user_msg, model=model, max_tokens=2500)
    return unwrap_result(result), error_kind


# ─── RSS SCRAPER ────────────────────────────────────────────────────────────

def fetch_feed(url, retries=2, timeout=30):
    """Fetch an RSS feed with browser-like headers and retry on timeout.
    Returns a feedparser-parsed feed object."""
    BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)
            if r.status_code == 200:
                return feedparser.parse(r.content)
            last_err = f"HTTP {r.status_code}"
        except requests.exceptions.Timeout:
            last_err = "timeout"
        except requests.exceptions.ConnectionError as e:
            last_err = f"conn error: {str(e)[:40]}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:40]}"
        if attempt < retries:
            time.sleep(2 * (attempt + 1))  # 2s, then 4s
    # Last resort: try feedparser direct (different network stack)
    try:
        parsed = feedparser.parse(url)
        if parsed.entries:
            return parsed
    except Exception:
        pass
    # Create an empty feed object that signals failure
    empty = feedparser.FeedParserDict()
    empty.entries = []
    empty.bozo = True
    empty.bozo_exception = Exception(last_err or "unknown error")
    return empty


def scrape_feeds():
    """Fetch all RSS feeds and return deduplicated candidate articles."""
    candidates = []
    failed = []

    for feed_cfg in FEEDS:
        name         = feed_cfg["name"]
        nuclear_only = feed_cfg.get("nuclear_only", False)
        print(f"  Fetching: {name} ...", end=" ", flush=True)
        try:
            feed = fetch_feed(feed_cfg["url"])
            if feed.bozo and not feed.entries:
                err = str(feed.bozo_exception)[:40] if hasattr(feed, 'bozo_exception') else "unreadable"
                print(f"SKIP ({err})")
                failed.append(name)
                continue

            matched = 0
            # Google News returns 100 entries per query — limit to 25 to control noise
            # (most older entries are duplicates of trade press we already have)
            entry_cap = 25 if "Google News:" in name else MAX_FEEDS_PER_RUN
            for entry in feed.entries[:entry_cap]:
                title   = clean(entry.get("title", ""))
                link    = clean_url(entry.get("link", ""))
                # For Google News entries: follow redirect to get real publisher URL
                # (so dedup catches same article across multiple GN queries)
                if "news.google.com" in link:
                    link = resolve_google_news_url(link)
                    link = clean_url(link)
                summary = clean(
                    BeautifulSoup(entry.get("summary", ""), "html.parser").get_text()
                )
                if not title or not link:
                    continue
                # Hard filter on fusion at the feed-fetch stage to skip Helion/CFS noise
                if looks_like_fusion(title + " " + summary):
                    continue
                # Nuclear pre-filter for high-volume non-nuclear feeds
                if nuclear_only and not has_nuclear_keyword(title + " " + summary):
                    continue
                if is_deal_candidate(title, summary):
                    candidates.append({
                        "title":   title,
                        "link":    link,
                        "summary": summary,
                        "date":    parse_entry_date(entry),
                        "source":  name,
                    })
                    matched += 1

            print(f"{matched} candidates")

        except Exception as e:
            print(f"ERROR: {e}")
            failed.append(name)

    if failed:
        print(f"\n  ⚠ {len(failed)} feeds skipped: {', '.join(failed)}")

    # Deduplicate by URL within this run
    seen_links = set()
    unique = []
    for c in candidates:
        if c["link"] not in seen_links:
            seen_links.add(c["link"])
            unique.append(c)
    return unique



# ─── MAIN RUN ───────────────────────────────────────────────────────────────

def run():
    today = datetime.date.today().isoformat()
    now   = datetime.datetime.utcnow().isoformat()

    print(f"\n{'='*70}")
    print(f"Nuclear Deal Tracker v3.0 — Scraper run {today}")
    print(f"  Pass 1 model: {MODEL}")
    print(f"  Escalation:   {ESCALATION_MODEL}")
    print(f"{'='*70}\n")

    # Clients
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    gc     = get_gsheet_client()
    sheet  = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])

    # Ensure operational tabs exist (defensive — seeder already created them)
    ensure_tab(sheet, TAB_SEEN,   SEEN_COLS)
    ensure_tab(sheet, TAB_REVIEW, REVIEW_COLS)

    # Load reference data
    print("Loading reference data...")
    ref = load_reference_data(sheet)
    seen_hashes = load_seen_hashes(sheet)
    print(
        f"  {len(ref['site_lookup'])} sites · "
        f"{len(ref['unit_lookup'])} units · "
        f"{len(ref['project_lookup'])} projects · "
        f"{len(ref['deal_lookup'])} deals · "
        f"{len(ref['context_lookup'])} contexts · "
        f"{len(ref['fingerprints'])} existing announcements\n"
    )

    # Pre-format reference data once (used in every Pass 2 call)
    ref_text = format_reference_data(ref)
    ref_text["fingerprints"] = ref["fingerprints"]

    # Compute base IDs ONCE before loop (avoid all-same-ID bug)
    base_ann_num   = get_next_id_num(sheet, TAB_ANNOUNCEMENTS, "ann_", col_idx=1, pad=4)
    base_deal_num  = get_next_id_num(sheet, TAB_DEALS, "deal_", col_idx=1, pad=4)
    base_review_num = get_next_id_num(sheet, TAB_REVIEW, "rev_", col_idx=1, pad=4)
    print(f"  Next announcement_id: ann_{base_ann_num:04d}")
    print(f"  Next deal_id:         deal_{base_deal_num:04d}")
    print(f"  Next review_id:       rev_{base_review_num:04d}\n")

    # Scrape feeds
    print("Scraping feeds...")
    candidates = scrape_feeds()
    print(f"\n  {len(candidates)} total candidates after dedup\n")

    # Output collectors
    new_seen      = []
    new_anns      = []
    new_deals     = []
    review_rows   = []
    skipped       = 0
    excluded_us   = 0
    excluded_fus  = 0
    duplicates    = 0
    too_old       = 0
    already_seen  = 0
    extraction_failed = 0
    deals_proposed = 0
    api_errors    = 0

    print("Processing candidates...\n")
    for article in candidates:
        h = entry_hash(article["title"], article["link"])

        if h in seen_hashes:
            already_seen += 1
            continue

        print(f"  ⟳ [{article['source']}] {article['title'][:80]}")

        # MIN_YEAR filter before any LLM call
        year_str = article.get("date", "")[:4]
        try:
            if year_str and int(year_str) < MIN_YEAR:
                print(f"    ↷ Too old ({year_str})")
                new_seen.append({"hash": h, "title": article["title"],
                                 "url": article["link"], "scraped_at": now})
                too_old += 1
                continue
        except ValueError:
            pass

        # Fetch full article body
        body = fetch_article_text(article["link"])
        article["body"] = body if body else article["summary"]

        # ── PASS 1: is_us, is_fusion, include screen ─────────────────────
        is_us, is_fusion, include, reason, pass1_error = pass1_screen(
            client, article["title"], article["body"], article["source"]
        )

        # API error during Pass 1: skip without marking Seen (will retry next run)
        if pass1_error == "api":
            print(f"    ⚠ API error in Pass 1 — skipping, will retry on next run")
            api_errors += 1
            continue
        if pass1_error == "other":
            print(f"    ⚠ Unexpected error in Pass 1 — skipping, will retry on next run")
            api_errors += 1
            continue

        if is_fusion:
            print(f"    ↷ Fusion (out of scope): {reason}")
            new_seen.append({"hash": h, "title": article["title"],
                             "url": article["link"], "scraped_at": now})
            excluded_fus += 1
            continue

        if not is_us:
            print(f"    ↷ Not US: {reason}")
            new_seen.append({"hash": h, "title": article["title"],
                             "url": article["link"], "scraped_at": now})
            excluded_us += 1
            continue

        if not include:
            print(f"    ↷ Excluded: {reason}")
            new_seen.append({"hash": h, "title": article["title"],
                             "url": article["link"], "scraped_at": now})
            skipped += 1
            continue

        print(f"    ✓ Included: {reason}")

        # ── PASS 2: structured extraction ────────────────────────────────
        result, pass2_error = pass2_extract(client, article, ref_text)

        # API error during Pass 2: skip without marking Seen (will retry next run)
        if pass2_error in ("api", "other"):
            print(f"    ⚠ {pass2_error} error in Pass 2 — skipping, will retry on next run")
            api_errors += 1
            continue

        # Escalate to stronger model on Medium confidence (treated as low for v0.4)
        if result and result.get("confidence", "").lower() not in ("high",):
            print(f"    ↑ Escalating to {ESCALATION_MODEL} (confidence: {result.get('confidence', 'unknown')})")
            escalated, esc_error = pass2_extract(client, article, ref_text, model=ESCALATION_MODEL)
            if esc_error in ("api", "other"):
                # Escalation failed transiently — keep the original (non-escalated) result if we have one
                print(f"    ⚠ Escalation hit {esc_error} error — keeping unescalated result")
            elif escalated:
                result = escalated

        if not result:
            # Pass 2 returned None but it wasn't transient (parse error or empty JSON).
            # OK to log to Seen since re-trying would likely fail the same way.
            print(f"    ✗ Extraction failed → Review")
            review_rows.append({
                "review_id":      f"rev_{base_review_num + len(review_rows):04d}",
                "scraped_at":     now,
                "article_title":  article["title"],
                "article_url":    article["link"],
                "reason":         "Pass 2 extraction failed (parse error / unparseable JSON)",
                "raw_extraction": "",
            })
            new_seen.append({"hash": h, "title": article["title"],
                             "url": article["link"], "scraped_at": now})
            extraction_failed += 1
            continue

        # Duplicate flagged by Claude
        if result.get("is_duplicate"):
            print(f"    ≡ Duplicate: {result.get('duplicate_reason', '')}")
            new_seen.append({"hash": h, "title": article["title"],
                             "url": article["link"], "scraped_at": now})
            duplicates += 1
            continue

        # ── BUILD ANNOUNCEMENT ROW ──────────────────────────────────────
        ann_id = f"ann_{base_ann_num + len(new_anns):04d}"
        announcement = {
            "announcement_id":    ann_id,
            "headline":           clean(result.get("headline", article["title"])),
            "source":             article["source"],
            "source_url":         article["link"],
            "published_date":     result.get("announcement_date") or article.get("date", ""),
            "captured_date":      today,
            "site_ids":           result.get("site_ids", "") or "",
            "unit_ids":           result.get("unit_ids", "") or "",
            "project_ids":        result.get("project_ids", "") or "",
            "deal_ids":           result.get("deal_ids", "") or "",
            "context_ids":        result.get("context_ids", "") or "",
            "announcement_scope": result.get("announcement_scope", "") or "",
            "new_entity_flags":   result.get("new_entity_flags", "") or "",
            "confidence":         result.get("confidence", "Medium"),
            "summary":            clean(result.get("summary", "")),
            "notes":              clean(result.get("notes", "")),
        }
        new_anns.append(announcement)

        # Update fingerprints in-memory so duplicate-detection works within the same run
        ref_text["fingerprints"].append(
            f"{announcement['project_ids']}|{announcement['context_ids']}|"
            f"{announcement['announcement_scope']}|{announcement['summary'][:80]}"
        )

        # ── BUILD PROPOSED DEAL ROW (Q5) ────────────────────────────────
        proposed = result.get("proposed_deal")
        if result.get("propose_deal") and proposed and isinstance(proposed, dict):
            # Validate that linked_project_ids are real (no orphans)
            linked_pids = [x.strip() for x in
                           str(proposed.get("linked_project_ids","")).split(",") if x.strip()]
            valid_pids = set(t[0] for t in ref["project_lookup"])
            linked_pids_valid = [p for p in linked_pids if p in valid_pids]

            if linked_pids_valid:
                deal_id = f"deal_{base_deal_num + len(new_deals):04d}"
                deal_row = {
                    "deal_id":                 deal_id,
                    "confirmation_status":     "Proposed (scraper)",
                    "deal_name":               clean(proposed.get("deal_name","")),
                    "project_ids":             ",".join(linked_pids_valid),
                    "context_ids":             proposed.get("linked_context_ids","") or "",
                    "deal_type":               proposed.get("deal_type","") or "",
                    "deal_stage":              proposed.get("deal_stage","") or "",
                    "economic_type":           proposed.get("economic_type","") or "",
                    "capital_value_usd":       proposed.get("capital_value_usd") or "",
                    "capital_value_disclosure": proposed.get("capital_value_disclosure","") or "",
                    "cost_contribution_usd":   "",   # leave blank for human review
                    "is_portfolio_deal":       "",
                    "allocations":             "",
                    "term_years":              proposed.get("term_years") or "",
                    "lead_entity":             proposed.get("lead_entity","") or "",
                    "lead_entity_type":        proposed.get("lead_entity_type","") or "",
                    "partners":                proposed.get("partners","") or "",
                    "technology_provider":     "",
                    "state":                   proposed.get("state","") or "",
                    "region":                  "",
                    "capacity_at_stake_mw":    proposed.get("capacity_at_stake_mw") or "",
                    "cost_recovery":           "",
                    "government_support":      proposed.get("government_support","") or "",
                    "announcement_date":       announcement["published_date"],
                    "close_date":              "",
                    "source_url":              article["link"],
                    "notes":                   "Proposed by scraper — review and confirm",
                }
                new_deals.append(deal_row)
                # Add the new deal_id back into the announcement's deal_ids
                if announcement["deal_ids"]:
                    announcement["deal_ids"] += "," + deal_id
                else:
                    announcement["deal_ids"] = deal_id
                deals_proposed += 1
                print(f"    💼 Proposed deal: {deal_id} — {deal_row['deal_name'][:60]}")

        # ── REVIEW ROW (only if confidence is Medium/Low after escalation) ──
        if result.get("confidence", "").lower() != "high":
            review_rows.append({
                "review_id":      f"rev_{base_review_num + len(review_rows):04d}",
                "scraped_at":     now,
                "article_title":  article["title"],
                "article_url":    article["link"],
                "reason":         f"confidence={result.get('confidence')}; ann_id={ann_id}",
                "raw_extraction": json.dumps(result, default=str)[:5000],
            })

        # ── DEDUP HASH ──────────────────────────────────────────────────
        new_seen.append({"hash": h, "title": article["title"],
                         "url": article["link"], "scraped_at": now})

        # Friendly per-row summary
        conf_icon = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}.get(
            result.get("confidence",""), "⚪"
        )
        scope     = announcement["announcement_scope"] or "?"
        link_pids = announcement["project_ids"] or ""
        link_cids = announcement["context_ids"] or ""
        link_summary = link_pids if link_pids else (link_cids if link_cids else "no entity link")
        new_ent_marker = " 🆕" if announcement["new_entity_flags"] else ""
        print(f"    ✚ {ann_id} | {scope} | {result.get('confidence','?')} {conf_icon} | {link_summary[:60]}{new_ent_marker}")

        # Pace API calls a touch
        time.sleep(0.3)

    # ── Run summary ──────────────────────────────────────────────────────
    print(f"\n{'─'*70}")
    print(f"Run summary — {today}")
    print(f"  Total feed candidates    : {len(candidates)}")
    print(f"  Already seen (skip)      : {already_seen}")
    print(f"  Too old (pre-{MIN_YEAR})       : {too_old}")
    print(f"  Excluded — fusion        : {excluded_fus}")
    print(f"  Excluded — non-US        : {excluded_us}")
    print(f"  Excluded — Pass 1 reject : {skipped}")
    print(f"  Duplicates flagged       : {duplicates}")
    print(f"  Extraction failed        : {extraction_failed}")
    print(f"  API errors (will retry)  : {api_errors}")
    print(f"  New announcements        : {len(new_anns)}")
    print(f"  Proposed deals (Q5)      : {deals_proposed}")
    print(f"  Review rows              : {len(review_rows)}")
    print(f"{'─'*70}\n")

    if api_errors > 0:
        print(f"⚠ {api_errors} article(s) hit API errors and were NOT logged to Seen.")
        print(f"  They'll be retried on the next scraper run.")
        print(f"  Common causes: low Anthropic credit balance, rate limiting, transient network.")
        print()

    # ── Batch writes ─────────────────────────────────────────────────────
    if new_anns:
        print(f"Writing {len(new_anns)} announcement(s)...")
        append_rows_batch(sheet, TAB_ANNOUNCEMENTS, new_anns)
        print("  ✓ Done.")

    if new_deals:
        print(f"Writing {len(new_deals)} proposed deal(s)...")
        append_rows_batch(sheet, TAB_DEALS, new_deals)
        print("  ✓ Done.")

    if review_rows:
        print(f"Writing {len(review_rows)} review row(s)...")
        append_rows_batch(sheet, TAB_REVIEW, review_rows)
        print("  ✓ Done.")

    if new_seen:
        print(f"Logging {len(new_seen)} seen hash(es)...")
        append_rows_batch(sheet, TAB_SEEN, new_seen)
        print("  ✓ Done.")

    print(f"\n✅ Scraper complete — {today}\n")


if __name__ == "__main__":
    run()
