# Schema Audit Lead Generator

## Overview
Automated lead generation tool for White Pine Agency. Audits local businesses for schema.org markup compliance and performance.

## Core Stack
- **Language:** Python 3.12+
- **Database:** SQLite (`leads.db`)
- **APIs:** Google Places (New), PageSpeed Insights
- **Key Libraries:** `extruct` (Schema extraction), `click` (CLI), `jinja2` (Reporting)

## Useful Commands
- `source venv/bin/activate` - Activate environment
- `python main.py discover "Query"` - Find new leads
- `python main.py audit-all` - Audit all pending leads
- `python main.py hot-leads` - List high-potential prospects
- `python main.py status` - Show pipeline status

## Directory Structure
- `analyzer.py`: Audit logic (5-point check)
- `db.py`: Database models and persistence
- `discovery.py`: Google Places API integration
- `extractor.py`: HTML metadata extraction
- `reporter.py`: HTML/JSON report generation
- `reports/`: Generated output files
