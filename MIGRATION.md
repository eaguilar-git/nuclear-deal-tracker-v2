# Migration to EFI Foundation infrastructure

This document is the runbook for migrating the Nuclear Deal Tracker v2 from Edgar's personal accounts to EFI Foundation-controlled infrastructure, ahead of Edgar's departure from EFI.

**Status:** time-sensitive. Edgar is leaving EFI in less than 2 weeks. This migration must complete before then, or the tracker will go dark when his personal credentials are no longer monitored.

**Current state (May 2026):** the system runs entirely on Edgar's personal accounts — Google Sheet ownership and service account in personal GCP project, personal Anthropic API account, GitHub repo at `eaguilar-git/nuclear-deal-tracker-v2` with GitHub Pages dashboard.

**Target state:** all four assets owned by EFI Foundation, with a named EFI staff member as the new maintainer, daily scraper continuing to run on schedule, and the dashboard accessible at an EFI-controlled URL.

---

## Critical decisions to confirm in the first 48 hours

These cannot wait. Block out time with EFI leadership to settle:

### 1. Who is the new maintainer?

A specific named individual on the EFI team needs to inherit this system. They don't need to be a deep technical owner, but they do need to:

- Have admin access to all four infrastructure pieces (Sheet, Anthropic, GitHub, GCP)
- Know how to spot when the daily scraper has failed (Actions tab on the repo)
- Know who to escalate to inside EFI if it breaks
- Have receive permissions on the alerting (if any is configured)

**If no maintainer is named:** the system will continue to run, but there will be nobody to fix it when something breaks. Suggested fallback: assign joint ownership to the Nuclear Scaling Initiative lead and one technical staff member as a backup.

### 2. Does EFI have the infrastructure to receive the handoff?

The migration needs four EFI-controlled assets. Confirm which of these already exist:

- **EFI Google Workspace** (for the Sheet) — likely yes, but the new maintainer needs admin access
- **EFI GitHub organization** (for the repo) — may or may not exist; if not, can be created in 15 minutes by an EFI admin
- **EFI Anthropic Console organization** (for the API key) — almost certainly does not exist yet, needs to be created and billing set up
- **EFI Google Cloud Project** (for the service account) — likely does not exist for this purpose, needs to be created (free)

If any of these don't exist, EFI IT needs to provision them in week 1 of this migration window.

### 3. Where do credentials live?

Three sensitive credentials need a secure storage location:

- The new Anthropic API key (single string)
- The new Google service account JSON file
- The new Google Sheet ID (less sensitive, but should be documented somewhere)

Options: EFI IT-managed password vault (1Password Business, Bitwarden Business, etc.), or a shared encrypted file in EFI Workspace. The new maintainer needs access to all three from day one of inheriting the system.

### 4. Dashboard URL

The current dashboard is at `https://eaguilar-git.github.io/nuclear-deal-tracker-v2/`. After the migration, it lives at whatever the new EFI org/repo URL is, e.g. `https://efi-foundation.github.io/nuclear-deal-tracker/`. GitHub provides automatic redirects from the old URL for at least 90 days, but external bookmarks and any reports citing the URL should be updated.

If EFI wants a custom domain (e.g. `tracker.efifoundation.org`), set it up as part of this migration — adding it later is harder.

---

## Pre-migration checklist (complete before kicking off)

- [ ] **Named successor identified** with admin rights to inherit the system. (Until this is filled, every other step is provisional.)
- [ ] **EFI GitHub organization** exists (or created during this migration). The successor needs admin rights on the org.
- [ ] **EFI Anthropic Console organization** created with a payment method on file. Successor invited as a member with API key permissions.
- [ ] **Successor has EFI Google Workspace access** with permission to create Sheets and share them externally.
- [ ] **Successor has Google Cloud Console access** (with their EFI account) and permission to create projects.
- [ ] **Credential vault location agreed** — where the new API key, service account JSON, and Sheet ID will be stored.
- [ ] **Migration window scheduled** with the successor present for at least Steps 1–9 (~2.5 hours active work).
- [ ] **Knowledge transfer call scheduled** with Edgar and the successor to walk through the system, ideally before the migration window (~1 hour).

---

## Migration steps (in order)

The order is important. Set up new EFI infrastructure first, cut over, then decommission the old. Don't revoke personal credentials until the EFI version has run successfully for several days.

The successor should do these steps with Edgar present (in person or screen-share). Edgar drives the technical execution; the successor watches and asks questions so they understand the system.

### Step 1 — Stand up the EFI Google Sheet

This is the data layer. Everything else points at it.

1. **Successor**, in EFI Google Workspace, create a new Google Sheet named `Nuclear Deal Tracker v2 (Live)`.
2. **Edgar**, from the current live Sheet, copy all 8 tabs to the new one:
   - Open the source Sheet (`1UHKrpeS56Bgt5ZQ2si6i9LunogM88V4VDKZ93PoqTeg`)
   - Right-click each tab → Copy to → Other spreadsheet → select the new EFI Sheet
   - Repeat for all 8 tabs: Sites, Reactor Units, Projects, Deals, Context Items, Announcements, Seen, Review
3. **Verify row counts match** between old and new Sheets — Sites=69, Units=126, Projects=47, Deals=41+, Context Items=48, Announcements=160+, Seen=current count, Review=current count.
4. **Re-publish the six entity tabs as CSVs** in the new Sheet. For each tab (Sites, Units, Projects, Deals, Contexts, Announcements):
   - File → Share → Publish to web → choose the tab → CSV format → Publish.
   - Copy the published URL (looks like `https://docs.google.com/spreadsheets/d/e/2PACX-1vXXXX.../pub?gid=NNNN&single=true&output=csv`).
   - Note the **base URL** (everything before `?gid=`) — same for all six tabs.
   - Note each tab's **gid** (different number for each).
5. **Record both the Sheet ID and the 6 gids** in the credential vault. Successor will need them in Step 6.

### Step 2 — Create the EFI Google Cloud project & service account

This gives the scraper write access to the new Sheet.

1. **Successor** (using their EFI Google account), in Google Cloud Console, create a new project named `efi-nuclear-tracker` (or similar).
2. **Enable two APIs**: Sheets API and Drive API. (IAM & Admin → Library, search and enable both.)
3. **Create service account**: IAM & Admin → Service Accounts → Create. Name it `nuclear-scraper`. No project-level roles needed.
4. **Generate JSON key**: Click the new service account → Keys → Add Key → JSON. Download the file. Store the file in the credential vault immediately.
5. **Note the service account email** (looks like `nuclear-scraper@efi-nuclear-tracker-NNNN.iam.gserviceaccount.com`).
6. **Share the new EFI Sheet with this service account email** as Editor.

### Step 3 — Set up the EFI Anthropic API key

1. **Successor** (or whoever owns the EFI Anthropic Console org), navigate to API Keys.
2. **Create a new API key** named `nuclear-deal-tracker-production`.
3. **Copy the key immediately** — only shown once. Store in the credential vault.
4. **Confirm billing is active** on the EFI org with a payment method. Recommended: set a $50/month spending cap as a safeguard (actual cost is ~$5-10/month, so this gives 5-10x headroom).
5. **Verify the key works** — in a terminal, run:
   ```bash
   export TEST_KEY="<paste the new key>"
   curl https://api.anthropic.com/v1/messages \
     -H "x-api-key: $TEST_KEY" \
     -H "anthropic-version: 2023-06-01" \
     -H "content-type: application/json" \
     -d '{"model": "claude-haiku-4-5-20251001", "max_tokens": 20, "messages": [{"role": "user", "content": "say hello"}]}'
   ```
   If you get a JSON response with a `content` field, the key works.

### Step 4 — Transfer the GitHub repo

Two options. Option A (transfer) is recommended.

**Option A — Transfer existing repo to EFI org:**

1. **Edgar** opens the GitHub repo settings (`eaguilar-git/nuclear-deal-tracker-v2`) → General → Danger Zone → Transfer.
2. Enter the EFI organization name as new owner. Confirm.
3. The repo moves to `<efi-org>/nuclear-deal-tracker-v2` (or rename during/after transfer).
4. GitHub redirects the old URL automatically for ≥90 days.
5. **All commit history, issues, and PRs travel with the transfer.** Workflows continue to work but secrets need to be re-set (Step 5).
6. **Edgar grants the successor admin rights** on the transferred repo immediately.

**Option B — Fresh repo in EFI org:**

1. Create new repo in EFI org with the desired name.
2. On Edgar's machine: `git remote set-url origin https://github.com/<efi-org>/<repo>.git`, then `git push -u origin main`.
3. Configure GitHub Pages on the new repo (Settings → Pages → main branch → /docs folder).
4. Add successor as admin.

### Step 5 — Re-set GitHub Actions secrets

Whichever transfer option chosen, secrets do NOT travel with the repo. The successor needs to set them.

In the new repo: Settings → Secrets and variables → Actions → New repository secret. Add three:

| Secret name | Value source |
|-------------|--------------|
| `ANTHROPIC_API_KEY` | The new EFI Anthropic key from Step 3 |
| `GOOGLE_SHEET_ID` | The new Sheet ID from Step 1 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The full JSON content of the file from Step 2 (paste as a multi-line value) |

### Step 6 — Update hardcoded values in the code

Most of the codebase is config-driven, but two files have hardcoded values pointing at the old Sheet:

**`docs/index.html`** — the dashboard fetches the published CSVs by URL. Find and replace:
- The current base URL `https://docs.google.com/spreadsheets/d/e/2PACX-1vQM7PNhnJ1LIuREfARO3eyxpbVtL-yVqQPZ8OOtnKnlzi1_igRd1-zg6Ne0SxHMCKYmQ5g9I_Ba-sRV/pub` → new base URL from Step 1
- The 6 gids (1113250734, 38565451, 1202517721, 1290975261, 529056657, 2033732112) → 6 new gids from Step 1

**`README.md` and `README.docx`** — update references:
- Sheet ID `1UHKrpeS56Bgt5ZQ2si6i9LunogM88V4VDKZ93PoqTeg` → new Sheet ID
- Service account email `nuclear-scraper@rugged-abacus-405804.iam.gserviceaccount.com` → new service account email
- Maintainer name "Edgar Aguilar" → new successor name (in Credits section)

Commit and push.

### Step 7 — Configure GitHub Pages on the new repo

Settings → Pages → Source: Deploy from a branch → Branch: main / /docs → Save.

GitHub Pages provisions the new site at `https://<efi-org>.github.io/<repo>/`. Wait ~2 minutes, visit the URL, verify dashboard loads.

If EFI wants a custom domain, configure it in this same panel. Requires a DNS CNAME record from EFI IT.

### Step 8 — Manual scraper test run on new infrastructure

Don't wait for the scheduled cron — test now.

1. **Successor**, in the new repo: Actions tab → "Daily Scraper" workflow → Run workflow → main branch → Run.
2. Watch logs. Expected: ~20-30 minutes, identical output structure to local runs.
3. Verify new rows appear in the EFI Sheet (Announcements, possibly Deals/Review, Seen).

### Step 9 — Verify the dashboard pulls from the new Sheet

Refresh the new dashboard URL. Confirm:
- KPIs reflect current data (Announcements count matches the new Sheet)
- Activity Feed loads recent items
- Entity Explorer works for at least one Site, one Project, one Deal, one Context item
- No 404 errors in browser DevTools → Network for CSV fetches

If the dashboard shows old data or broken images, Step 6's URL/gid replacements were incomplete. Re-check.

### Step 10 — Disable the personal-account scheduled run

Only AFTER the EFI version is verified working.

In the old repo (`eaguilar-git/nuclear-deal-tracker-v2`):
- Settings → Actions → General → Disable Actions for this repository.

Old Sheet stays as backup for 30 days, then archived.

### Step 11 — Knowledge transfer call

Before Edgar's last day, run a recorded walkthrough call with the successor (and ideally a backup person). Cover:

- Live demo of the dashboard and what each KPI means
- Walkthrough of the v0.4 schema (the 6 tables and how they link)
- Live look at the Google Sheet — how the Activity Feed maps to Announcements rows, what the Review tab is for, how Proposed deals show up
- Walkthrough of the scraper's daily cron: where it lives, how to read the run logs, what failure looks like
- The 3 documents: README, PROMPTS, this MIGRATION
- The "what to review weekly" workflow:
  - Open the Review tab — eyeball flagged extractions, accept/reject
  - Open Deals tab, filter to `confirmation_status = Proposed (scraper)` — review proposals, confirm/edit/delete
  - Scan Announcements for `new_entity_flags` — decide which new entities are worth adding to reference data
- Where credentials live, and the procedure to rotate them
- How to escalate API costs if billing surprises happen
- Open issues that haven't been addressed yet (see "Known issues" section below)

Record the call. Save it in EFI's standard location.

### Step 12 — Edgar's personal credentials get revoked (post-departure)

**Do this only after the EFI version has run successfully for at least 5 consecutive days.**

1. **Anthropic API key** (in `~/Documents/credentials_deal_tracker/anthropic_key_v2.txt`):
   - Anthropic Console → API Keys → find the personal key → Delete.
   - Delete the local credentials file.
2. **Personal GCP service account**:
   - Cloud Console (`rugged-abacus-405804`) → IAM & Admin → Service Accounts → `nuclear-scraper` → Delete.
   - Delete the local credentials file.
3. **(Optional) Shut down the personal GCP project** if it has no other uses.
4. **Personal Anthropic account**: leave open if Edgar uses it for other purposes; close if not.

### Step 13 — Announce the new dashboard URL

Email the team:
- New dashboard URL
- New Sheet location (if anyone outside the scraper uses it)
- Who the new maintainer is (the contact for any issues)
- Old URLs will auto-redirect for ~90 days, then 404

---

## Verification — what success looks like 5 days post-cutover

- [ ] Scheduled scraper runs successfully every day at 6am EST (visible in EFI repo Actions tab)
- [ ] New rows appear in the EFI Sheet's Announcements tab daily
- [ ] Dashboard at new URL reflects current data
- [ ] Anthropic billing dashboard shows ~$0.30-1.50/day in API spend on EFI org
- [ ] No errors in last 5 Actions runs
- [ ] Old personal Sheet not being written to
- [ ] Successor knows how to read the daily run output and spot issues

If any of these are off after 5 days, the migration is not complete. The successor should debug or escalate.

---

## Known issues being inherited

The successor should know about these. Edgar should walk through each in the knowledge transfer call.

1. **Some RSS feeds skip every run** with HTTP 403/timeout (NEI, NucNet, NRC, IAEA, TVA, DOE, Brookfield). This is normal — Google News queries and trade press feeds cover the same content. Not urgent to fix.
2. **The scraper logs failed-API-call articles to the Seen tab anyway.** When the Anthropic credit balance runs out mid-run, every article afterward gets marked "seen" without being processed, meaning they'll never be retried. To recover lost articles, the successor needs to manually delete relevant rows from the Seen tab.
3. **Google News URLs may not resolve perfectly** — the scraper attempts to follow redirects to the real publisher URL, but sometimes Google News blocks the HEAD request, leaving a `news.google.com` URL in the announcement row. Cosmetic but worth noting.
4. **Deal IDs use two conventions**: the original 35 seed deals use human-readable IDs (e.g. `holtec_palisades_doe_lpo_loan`), and scraper-proposed deals use `deal_NNNN` sequential IDs. This is intentional — `deal_NNNN` IDs flag scraper-proposed rows at a glance — but when the successor confirms a proposed deal, they can rename the ID to human-readable form for consistency.
5. **"What's NOT yet built" items in the README** (manual data entry form, prompt tuning, PowerPoint export) — defer or pick up as time allows.

---

## Rollback plan

**Before Step 8 (scraper test run on new infrastructure):** Everything is parallel. Personal system still live. Pause the migration, continue using personal setup until issues resolved.

**After Step 8 but before Step 10 (personal cron disabled):** Both systems write to their respective Sheets. Personal Sheet still fed by old cron. If EFI version breaks, the successor can use the personal Sheet for a few days while debugging.

**After Step 10 (personal cron off, only EFI running):** If EFI scraper breaks, Edgar can re-enable Actions on the personal repo as temporary fallback — both systems write to their respective Sheets.

**After Step 12 (personal credentials revoked):** No rollback. This is why Step 12 must wait at least 5 days after Step 10.

---

## Time estimate

| Step | Time | Who |
|------|------|-----|
| Step 1: Stand up the EFI Sheet | 30 min | Both |
| Step 2: GCP project & service account | 20 min | Successor (with Edgar) |
| Step 3: EFI Anthropic API key | 10 min | Successor |
| Step 4: GitHub repo transfer | 10 min | Edgar |
| Step 5: Re-set GitHub Actions secrets | 5 min | Successor |
| Step 6: Update hardcoded values in code | 15 min | Edgar |
| Step 7: GitHub Pages settings | 5 min | Successor |
| Step 8: Manual scraper test run | 30 min (including the run itself) | Successor (with Edgar) |
| Step 9: Dashboard verification | 10 min | Both |
| Step 11: Knowledge transfer call | 60 min | Both |
| Step 13: Announcement email | 10 min | Successor |
| **Active migration work** | **~3 hours** | |
| **+ 5-day verification window** | (passive) | Successor monitors |

Steps 10 and 12 are short tasks that happen during the verification window after the cutover.

---

## What stays on Edgar's personal infrastructure after migration

After this migration, Edgar's personal accounts still have:
- A local copy of `~/Documents/nuclear-deal-tracker-v2/` working directory. Edgar can delete this any time.
- A backup of the original v1 Nuclear Deal Tracker (separate repo, separate Sheet, separate API key) which ran in parallel during v2 development. Independent of this migration — can be archived or kept indefinitely.
- Read-only access to the new EFI Sheet (if granted by the successor as a courtesy). Optional.

---

## Open questions to confirm in week 1

1. **Who is the named successor / new maintainer?**
2. **Does an EFI GitHub organization exist? If not, who creates it?**
3. **Does an EFI Anthropic Console organization exist? If not, who creates it and approves billing?**
4. **Where will credentials be stored?** (1Password? Shared encrypted Drive folder? Other?)
5. **Does EFI want a custom domain for the dashboard?**
6. **Who else (besides the successor) should have Editor access to the Sheet** as backup?
7. **Should the scheduled cron change** — currently 6am EST?
8. **What's the protocol if the daily run fails?** Email alert? Slack notification? Just check Actions tab manually?

The first three need answers before Day 1 of the migration window or it can't proceed.

---

## If the handoff timeline slips

If for any reason the migration cannot complete before Edgar leaves:

**Acceptable interim state:** Pause GitHub Actions on the personal repo (so the scraper stops running and nothing breaks silently). The dashboard continues to display the data through the date of pause. Edgar's personal credentials stay alive until the migration can complete — but this requires either keeping Edgar reachable for a credential rotation, or accepting that the dashboard becomes a read-only snapshot.

**Unacceptable state:** Edgar's personal credentials get revoked or expire while the daily scraper is still using them. This causes silent failure — daily runs stop writing to the Sheet, but no one notices for days or weeks until someone looks at the Sheet and sees stale data.

The single most important thing the successor needs to take ownership of, even if everything else slips: **at minimum**, get the GitHub Actions scheduled run disabled before Edgar's personal Anthropic key gets revoked. Better to have a frozen-in-time dashboard than a silently-broken one.
