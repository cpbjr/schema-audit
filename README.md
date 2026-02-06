# Schema Audit Lead Generator

Automated lead generation tool that finds local businesses via Google Places API, audits their schema.org markup against a 5-point criteria, scores them 0-5, and generates corrected schema with professional HTML reports.

---

## Setup

```bash
# Navigate to the tool directory
cd /home/cpbjr/WhitePineAgency/Tools/schema-audit

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env and add your Google Places API key:
# GOOGLE_PLACES_API_KEY=your_key_here
```

---

## Commands

### `discover`
Search for local businesses and store them in the database.

```bash
python main.py discover "Plumbers in Eagle, ID"
```

**What it does:**
- Queries Google Places API (Text Search)
- Fetches up to 60 results (3 pages × 20)
- Filters for businesses with websites
- Stores: place_id, name, address, phone, website URL, GBP categories
- Skips duplicates automatically

**Example output:**
```
Searching: 'Plumbers in Eagle, ID'
  Page 1: 20 results (total: 20)
  Page 2: 18 results (total: 38)
  [1/38] Eagle Valley Plumbing -- saved (https://eaglevalleyplumbing.com)
  [2/38] Fast Plumbing LLC -- no website, skipping
  ...
Done! 32 new businesses added (32 total in DB).
```

---

### `audit`
Audit a single business by place_id or URL.

```bash
# By place_id
python main.py audit ChIJgfDU44ZXrlQRvMn1...

# By website URL
python main.py audit https://example-plumber.com
```

**What it does:**
- Fetches website HTML and extracts LocalBusiness JSON-LD schema
- Runs 5-point audit (see below)
- Displays pass/fail for each check
- Shows overall score (0-5) and lead quality (HOT/WARM/COLD)
- Stores audit results in database

**Example output:**
```
  Audit for: Eagle Valley Plumbing
  URL: https://eaglevalleyplumbing.com

  1. Schema Exists:       FAIL
  2. sameAs Connection:   FAIL
  3. Category Alignment:  FAIL
  4. NAP Consistency:     FAIL
  5. Mobile Speed:        PASS
     Score: 78/100 | LCP: 2.1s

  Overall Score: 1/5  HOT LEAD

  Issues:
    - No LocalBusiness schema found on homepage
    - Missing sameAs link to Google Maps or Apple Maps profile (no schema found)
    - Category alignment cannot be checked (no schema found)
    - NAP consistency cannot be checked (no schema found)

Audit saved to database.
```

---

### `audit-all`
Batch audit all unaudited businesses in the database.

```bash
python main.py audit-all
```

**What it does:**
- Queries database for businesses without audit records
- Runs audit for each (fetches HTML, extracts schema, checks 5 points, calls PageSpeed API)
- Displays progress with summary scores
- Skips businesses with no website

**Example output:**
```
Auditing 32 businesses...
----------------------------------------------------------------------

[1/32] Eagle Valley Plumbing
  Score: 1/5  HOT LEAD

[2/32] Fast Plumbing LLC
  Skipped (no website or not found)

[3/32] Mountain View HVAC
  Score: 3/5  WARM LEAD

...

======================================================================
Audit-All Summary
  Total audited:   30
  Hot leads found: 12
  Errors/skipped:  2
======================================================================
```

---

### `report`
Generate HTML audit report with corrected schema for a business.

```bash
python main.py report ChIJgfDU44ZXrlQRvMn1...
```

**What it does:**
- Retrieves business and audit data from database
- Generates corrected LocalBusiness JSON-LD schema using GBP data
- Renders professional HTML report with:
  - Audit results (pass/fail for each check)
  - Issues found
  - Complete corrected schema (copy-paste ready)
  - Lead quality badge
- Saves HTML and JSON files to `reports/` directory

**Output files:**
```
reports/2026-02-06_eagle-valley-plumbing_audit.html
reports/2026-02-06_eagle-valley-plumbing_schema.json
```

**Example output:**
```
Generating report for: Eagle Valley Plumbing

Report generated successfully!
  HTML report: /home/cpbjr/WhitePineAgency/Tools/schema-audit/reports/2026-02-06_eagle-valley-plumbing_audit.html
  JSON schema: /home/cpbjr/WhitePineAgency/Tools/schema-audit/reports/2026-02-06_eagle-valley-plumbing_schema.json
```

---

### `status`
View pipeline statistics.

```bash
python main.py status
```

**Example output:**
```
Pipeline Status
========================================
  Total businesses:    32
  Audited:             30  (93%)
  Unaudited:           2  (6%)
----------------------------------------
  Hot leads (0-2):    12
  Warm leads (3-4):   8
  Cold leads (5):      10
----------------------------------------
  Reports generated:   5
========================================
```

---

### `hot-leads`
List hot leads (score 0-2) sorted by worst score first.

```bash
# Show 10 hot leads (default)
python main.py hot-leads

# Show 5 hot leads
python main.py hot-leads --limit 5
```

**Example output:**
```
Hot Leads (12 total, showing 10)
======================================================================

  1. Eagle Valley Plumbing  [Score: 0/5]
     URL:      https://eaglevalleyplumbing.com
     Place ID: ChIJgfDU44ZXrlQRvMn1...
     Issues:
       - No LocalBusiness schema found on homepage
       - Missing sameAs link to Google Maps or Apple Maps profile
       - Schema @type mismatch: found [Organization] but GBP types suggest [Plumber, PlumbingService]
       - Phone mismatch: GBP=(208) 555-1234, Schema=208-555-1235
       - Mobile performance score 65/100 (needs 80+)

  2. Mountain View HVAC  [Score: 1/5]
     URL:      https://mountainviewhvac.com
     Place ID: ChIJqQ5w8yZXrlQRaXqB...
     Issues:
       - Missing sameAs link to Google Maps or Apple Maps profile
       - Address mismatch: GBP='123 Main St, Eagle, ID 83616', Schema='123 Main Street, Eagle, Idaho'
       ...

======================================================================
Generate a report: python main.py report <place_id>
```

---

## Typical Workflow

```bash
# 1. Discover businesses in your target market
python main.py discover "Plumbers in Eagle, ID"

# 2. Audit all discovered businesses (this takes time - PageSpeed API is slow)
python main.py audit-all

# 3. View hot leads (score 0-2 = best prospects)
python main.py hot-leads --limit 10

# 4. Generate reports for hot leads to use in outreach
python main.py report ChIJgfDU44ZXrlQRvMn1...
python main.py report ChIJqQ5w8yZXrlQRaXqB...

# 5. Check overall pipeline status
python main.py status
```

---

## The 5 Audit Checks

Each business is scored 0-5 based on how many checks they **PASS**. Lower scores = hotter leads.

### 1. Schema Exists
**Pass:** LocalBusiness (or subtype) JSON-LD found on homepage
**Fail:** No schema.org markup found

**Why it matters:** Without schema, search engines can't understand business info. This is the foundation of local SEO.

---

### 2. sameAs Connection
**Pass:** Schema includes `sameAs` link to Google Maps or Apple Maps profile
**Fail:** No Maps link found (auto-fails if no schema exists)

**Why it matters:** sameAs links verify business identity across platforms. Missing this means Google can't connect their GBP listing to the website schema, weakening local search signals.

---

### 3. Category Alignment
**Pass:** Schema `@type` matches GBP business categories
**Fail:** Mismatch between GBP types and schema (e.g., GBP says "plumber" but schema says "Restaurant")

**Why it matters:** Category misalignment confuses search engines about what the business actually does. Using generic types like "Organization" instead of specific ones like "Plumber" wastes SEO potential.

**Mapping examples:**
- GBP: `plumber` → Schema: `Plumber` or `PlumbingService`
- GBP: `lawyer` → Schema: `Attorney` or `LegalService`
- GBP: `hvac_contractor` → Schema: `HVACBusiness`

---

### 4. NAP Consistency
**Pass:** Name/Address/Phone in schema matches GBP data exactly
**Fail:** Discrepancies found (e.g., different phone format, abbreviations in address)

**Why it matters:** NAP inconsistencies across platforms (GBP, website, directories) hurt local search rankings. Even small differences like "St" vs "Street" or "(208) 555-1234" vs "208-555-1234" create trust issues for search engines.

**Common failures:**
- Phone formatting differences
- Address abbreviations (Street vs St, Suite vs Ste)
- Missing address/phone in schema entirely

---

### 5. Mobile Speed
**Pass:** Mobile PageSpeed score ≥80 AND Largest Contentful Paint (LCP) ≤2.5s
**Fail:** Score <80 or LCP >2.5s

**Why it matters:** Mobile speed is a direct ranking factor for Google. Slow sites frustrate users and get deprioritized in search results. LCP measures how quickly the main content loads - if it takes >2.5s, users bounce.

**Common causes of failure:**
- Unoptimized images
- Render-blocking JavaScript/CSS
- Slow server response times
- Third-party scripts (analytics, chatbots)

---

## Scoring System

| Score | Lead Quality | What It Means | Typical Issues |
|-------|-------------|---------------|----------------|
| **0-2** | 🔥 **HOT LEAD** | Major schema problems, easy wins | Missing schema entirely, no Maps link, NAP mismatches |
| **3-4** | ⚠️ **WARM LEAD** | Some issues, moderate opportunity | Schema exists but generic type, minor NAP issues, slow mobile |
| **5** | ❄️ **COLD LEAD** | Well-optimized, little to offer | All checks pass, already doing local SEO right |

**Sales angle by score:**

- **Score 0-1:** "Your business is invisible to Google's local search. We can fix this in 48 hours."
- **Score 2-3:** "You're leaving money on the table. Your schema exists but isn't connecting to your Google profile."
- **Score 4:** "Small optimizations could boost your rankings. Let's tighten up your mobile speed and NAP consistency."
- **Score 5:** "Great job! You're already optimized." (Not a good prospect unless you offer other services)

---

## Output Files

All reports are saved to `/home/cpbjr/WhitePineAgency/Tools/schema-audit/reports/`

### HTML Report (`YYYY-MM-DD_business-name_audit.html`)
Professional audit report containing:
- Business information (name, address, phone, website, GBP categories)
- Lead quality badge (HOT/WARM/COLD based on score)
- Audit results table (5 checks with pass/fail indicators)
- Issues list (specific problems found)
- Complete corrected JSON-LD schema (copy-paste ready)

**Use case:** Send to prospect as PDF or share link. Shows credibility and demonstrates exactly what you can fix.

### JSON Schema (`YYYY-MM-DD_business-name_schema.json`)
Standalone corrected LocalBusiness schema file containing:
- Proper `@type` based on GBP categories
- Structured PostalAddress
- Telephone, URL, and sameAs links
- Ready to paste into `<script type="application/ld+json">` tag

**Use case:** Implementation reference. Client's developer can copy-paste this directly into their site's `<head>`.

---

## Database

SQLite database: `/home/cpbjr/WhitePineAgency/Tools/schema-audit/leads.db`

**Tables:**
- `businesses` - Discovered businesses from Places API
- `audits` - Audit results (one per business, latest used)
- `reports` - Generated reports (tracks what's been sent to prospects)

**Pro tip:** Query the database directly for advanced filtering:
```bash
sqlite3 leads.db "SELECT name, website_url, score FROM businesses b JOIN audits a ON b.id = a.business_id WHERE score <= 2 ORDER BY score ASC;"
```

---

## Notes

- **PageSpeed API is slow:** Each `audit-all` run takes ~2-3 seconds per business due to PageSpeed Insights API. For 30 businesses, expect 1-2 minutes.
- **API quotas:** Google Places API has daily limits. Monitor your usage in Google Cloud Console.
- **Schema detection:** Only checks homepage (`/`). If schema exists on subpages (e.g., `/about`), it won't be detected.
- **GBP category mapping:** 100+ categories mapped to schema.org types. Unmapped categories default to `LocalBusiness`.
- **Lenient matching:** Schema types `LocalBusiness`, `Organization`, and `ProfessionalService` always pass category alignment (too generic to fail).

---

## Troubleshooting

**"GOOGLE_PLACES_API_KEY not set"**
- Add your API key to `.env` file
- Ensure `.env` is in the same directory as `main.py`

**"No results found for this query"**
- Try broader search terms (e.g., "Plumbers in Idaho" instead of "Emergency plumbers in Eagle ID 83616")
- Check that your API key has Places API (New) enabled

**"Unable to check mobile speed"**
- PageSpeed Insights API may be rate-limited or down
- This check runs last and doesn't block the audit (score will just reflect 0-4 instead of 0-5)

**"Business not found in DB"**
- Run `discover` first to populate the database
- Check place_id spelling (case-sensitive)

---

## License & Credits

Built for White Pine Agency lead generation.

**Dependencies:**
- `extruct` - Schema extraction
- `requests` - HTTP client
- `jinja2` - HTML templating
- `python-dotenv` - Environment config
