# Schema Audit Lead Generator - Implementation Plan

**Created**: 2026-02-05
**Status**: Planned
**Location**: `tools/schema-audit/`

---

## Overview

Python CLI tool that automates lead generation for White Pine Agency by discovering local businesses, extracting their schema.org data, scoring mismatches across 5 checks, and generating corrected JSON-LD + HTML reports.

---

## File Structure

```
tools/schema-audit/
├── main.py              # CLI entry point (click)
├── config.py            # Paths, API keys, constants
├── discovery.py         # Google Places API integration
├── extractor.py         # Website crawl + extruct schema extraction
├── analyzer.py          # 5 mismatch checks + scoring
├── reporter.py          # Corrected schema + HTML report generation
├── db.py                # SQLite database layer (3 tables)
├── templates/
│   └── audit_report.html # Jinja2 report template
├── reports/             # Generated reports (gitignored)
├── requirements.txt     # click, requests, extruct, jinja2, python-dotenv
├── .env.example         # GOOGLE_PLACES_API_KEY template
└── .gitignore           # .env, __pycache__, *.db, reports/, venv/
```

---

## Database (SQLite - `leads.db`)

- **businesses** - place_id (PK), name, address, phone, website_url, gbp_categories (JSON), search_query, discovered_at
- **audits** - id, business_id (FK), has_schema, has_sameas, category_aligned, nap_consistent, mobile_speed_score, mobile_lcp, raw_schema (JSON), issues (JSON), score (0-5), audited_at
- **reports** - id, business_id (FK), corrected_schema (JSON), html_report, report_path, generated_at

---

## 5 Audit Checks (score 0-5, lower = hotter lead)

1. **Existence** - Any LocalBusiness JSON-LD on homepage? (extruct library)
2. **sameAs** - Schema links to Google Maps/Apple Maps profile?
3. **Category Alignment** - GBP types match schema @type?
4. **NAP Consistency** - Address/phone match between schema and GBP? (normalized comparison)
5. **Mobile Speed** - PageSpeed Insights mobile score >= 80 and LCP <= 2.5s?

---

## CLI Commands

```bash
python main.py discover "Plumbers in Eagle, ID"   # Find businesses via Google Places
python main.py audit <place_id or URL>             # Audit single business
python main.py audit-all                           # Batch audit all unaudited businesses
python main.py report <place_id>                   # Generate HTML report + corrected JSON-LD
python main.py status                              # Pipeline stats
python main.py hot-leads                           # List leads with score 0-2
```

---

## Implementation Phases

### Phase 1: Foundation
- [ ] Create directory structure + setup files (requirements.txt, .env.example, .gitignore)
- [ ] `config.py` - paths, API URLs, thresholds (PASSING_MOBILE_SCORE=80, MAX_LCP=2.5s)
- [ ] `db.py` - Database class with dataclasses (Business, Audit, Report), CRUD ops, get_hot_leads(), get_pipeline_stats()
- [ ] **Verify:** Create venv, install deps, test DB create/insert/retrieve

### Phase 2: Discovery
- [ ] `discovery.py` - PlacesDiscovery class: search_businesses(), get_place_details(), discover_and_store()
- [ ] Handle pagination (next_page_token), skip businesses without websites
- [ ] **Verify:** Run discover command, check businesses in DB

### Phase 3: Extraction
- [ ] `extractor.py` - SchemaExtractor class: fetch_html(), extract_all_metadata(), find_local_business_schema()
- [ ] Match LocalBusiness + subtypes (PlumbingService, ProfessionalService, etc.)
- [ ] **Verify:** Test against 5-10 real websites

### Phase 4: Analysis
- [ ] `analyzer.py` - SchemaAnalyzer class: run_full_audit() orchestrating all 5 checks
- [ ] Checks 1-4: Schema existence, sameAs, category alignment, NAP consistency
- [ ] Check 5: PageSpeed Insights API call (free, no key needed)
- [ ] Phone/address normalization for NAP comparison
- [ ] **Verify:** Run audits, verify scoring logic

### Phase 5: Reporting
- [ ] `templates/audit_report.html` - Professional Jinja2 template with score colors, check results, corrected schema code block with copy button
- [ ] `reporter.py` - ReportGenerator: generate_corrected_schema(), generate_html_report(), save_report()
- [ ] Output: HTML report + standalone .json file in reports/ directory (no email sending)
- [ ] **Verify:** Generate reports, open in browser

### Phase 6: CLI Integration
- [ ] `main.py` - Click group with all 6 commands wired to modules
- [ ] Color-coded output, progress indicators for batch ops, clear error messages
- [ ] **Verify:** Full end-to-end: discover → audit-all → hot-leads → report

---

## Dependencies

```
click==8.1.7
requests==2.31.0
extruct==0.16.0
jinja2==3.1.3
python-dotenv==1.0.0
```

---

## Design Decisions

- **Storage:** SQLite (zero setup, file-based, easy to migrate to Supabase later)
- **Discovery API:** Google Places API (requires billing-enabled GCP project)
- **Output:** HTML report files + JSON schema files saved locally (no automatic email sending)
- **Scoring:** 0-5 scale where 0-2 = hot lead, 3 = warm, 4-5 = cold

---

## Verification Plan

1. Create venv and install dependencies
2. Run `discover` with real Google Places API key
3. Run `audit` on a single business - verify all 5 checks execute
4. Run `audit-all` on batch - verify scoring and DB storage
5. Run `report` - open HTML in browser, verify formatting
6. Run `status` and `hot-leads` - verify aggregation stats
