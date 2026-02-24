#!/usr/bin/env python3
"""Run audit for a business and write results to Supabase.

Usage:
  # Audit a specific business by Place ID
  python run_audit.py --id ChIJ...

  # Audit all businesses with no audit yet
  python run_audit.py --all-pending

  # Audit all businesses (re-audit everything)
  python run_audit.py --all

Requires SUPABASE_URL and SUPABASE_SERVICE_KEY in .env or environment.
Also requires GOOGLE_PLACES_API_KEY and PAGESPEED_API_KEY in .env.
"""
import argparse
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

from analyzer import SchemaAnalyzer
from supabase_writer import SupabaseWriter


SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def fetch_businesses(filter_no_audit: bool = False) -> list[dict]:
    """Fetch businesses from Supabase."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    url = f"{SUPABASE_URL}/rest/v1/businesses?select=id,name,website_url,address,phone,gbp_categories,google_maps_uri"
    resp = httpx.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    businesses = resp.json()

    if filter_no_audit:
        audit_url = f"{SUPABASE_URL}/rest/v1/audits?select=business_id"
        audit_resp = httpx.get(audit_url, headers=headers, timeout=30)
        audit_resp.raise_for_status()
        audited_ids = {a["business_id"] for a in audit_resp.json()}
        businesses = [b for b in businesses if b["id"] not in audited_ids]

    return businesses


def fetch_business_by_id(place_id: str) -> dict | None:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    url = f"{SUPABASE_URL}/rest/v1/businesses?id=eq.{place_id}&select=id,name,website_url,address,phone,gbp_categories,google_maps_uri"
    resp = httpx.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    results = resp.json()
    return results[0] if results else None


def audit_business(business: dict, writer: SupabaseWriter) -> bool:
    """Run audit and write to Supabase. Returns True on success."""
    if not business.get("website_url"):
        print(f"  SKIP {business['name']} — no website")
        return False

    print(f"  Auditing {business['name']} ({business['website_url']})...")
    try:
        from extractor import SchemaExtractor
        extractor = SchemaExtractor()
        analyzer = SchemaAnalyzer()

        schemas = extractor.extract_schema_from_url(business["website_url"]) or []
        gbp_data = {
            "name": business.get("name", ""),
            "address": business.get("address", ""),
            "phone": business.get("phone", ""),
            "types": business.get("gbp_categories", []),
        }
        result = analyzer.run_full_audit(business["website_url"], schemas, gbp_data)
        writer.insert_audit(result, business_id=business["id"])
        print(f"    Score: {result.score}/5  Issues: {len(result.issues)}")
        return True
    except Exception as e:
        print(f"    ERROR: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit businesses and write to Supabase")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="Audit a single business by Place ID")
    group.add_argument("--all-pending", action="store_true", help="Audit businesses with no audit")
    group.add_argument("--all", action="store_true", help="Re-audit all businesses")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")
        sys.exit(1)

    writer = SupabaseWriter()

    if args.id:
        business = fetch_business_by_id(args.id)
        if not business:
            print(f"Business not found: {args.id}")
            sys.exit(1)
        audit_business(business, writer)

    elif args.all_pending:
        businesses = fetch_businesses(filter_no_audit=True)
        print(f"Found {len(businesses)} businesses without audits")
        for b in businesses:
            audit_business(b, writer)

    else:  # --all
        businesses = fetch_businesses(filter_no_audit=False)
        print(f"Auditing all {len(businesses)} businesses")
        for b in businesses:
            audit_business(b, writer)

    print("Done.")


if __name__ == "__main__":
    main()
