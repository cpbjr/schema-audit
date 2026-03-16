"""One-time migration: copy leads.db → Supabase wpa_businesses + wpa_audits."""

import json
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from supabase import create_client
import os

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
DB_PATH = Path(__file__).parent / "leads.db"

def migrate():
    if not DB_PATH.exists():
        print(f"No leads.db found at {DB_PATH}")
        return

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    schema = client.schema("wpa")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # --- Businesses ---
    rows = conn.execute("SELECT * FROM businesses").fetchall()
    print(f"Migrating {len(rows)} businesses...")
    biz_ok = biz_skip = biz_err = 0

    for row in rows:
        try:
            raw = row["raw_data"]
            if isinstance(raw, str):
                raw = json.loads(raw) if raw else None

            cats = row["gbp_categories"]
            if isinstance(cats, str):
                cats = json.loads(cats) if cats else []

            data = {
                "id": row["id"],
                "name": row["name"],
                "address": row["address"] or "",
                "phone": row["phone"] or "",
                "website_url": row["website_url"] or "",
                "gbp_categories": cats,
                "gbp_primary_type": row["gbp_primary_type"] if "gbp_primary_type" in row.keys() else "",
                "search_query": row["search_query"] or "",
                "contact_status": row["contact_status"] or "NEW",
                "discovery_rank": row["discovery_rank"],
                "rank_total_candidates": row["rank_total_candidates"],
                "google_maps_uri": row["google_maps_uri"] or "",
                "business_status": row["business_status"] or "",
                "rating": float(row["rating"]) if row["rating"] is not None else None,
                "user_rating_count": row["user_rating_count"],
                "raw_data": raw,
                "lead_source": row["lead_source"] if "lead_source" in row.keys() else None,
                "closed_date": row["closed_date"] if "closed_date" in row.keys() else None,
                "contract_value": float(row["contract_value"]) if ("contract_value" in row.keys() and row["contract_value"] is not None) else None,
            }
            # Remove None optionals cleanly
            data = {k: v for k, v in data.items() if v is not None or k in (
                "discovery_rank", "rank_total_candidates", "rating", "user_rating_count", "gbp_primary_type"
            )}

            schema.table("wpa_businesses").upsert(data, on_conflict="id").execute()
            biz_ok += 1
            if biz_ok % 10 == 0:
                print(f"  {biz_ok}/{len(rows)} businesses migrated...")
        except Exception as e:
            biz_err += 1
            print(f"  ERROR business {row['id']}: {e}")

    print(f"Businesses: {biz_ok} migrated, {biz_err} errors")

    # --- Audits ---
    try:
        audit_rows = conn.execute("SELECT * FROM audits").fetchall()
    except Exception:
        audit_rows = []
    print(f"Migrating {len(audit_rows)} audits...")
    aud_ok = aud_err = 0

    for row in audit_rows:
        try:
            raw_schema = row["raw_schema"]
            if isinstance(raw_schema, str):
                raw_schema = json.loads(raw_schema) if raw_schema else None

            issues = row["issues"]
            if isinstance(issues, str):
                issues = json.loads(issues) if issues else []

            data = {
                "id": row["id"],
                "business_id": row["business_id"],
                "has_schema": bool(row["has_schema"]),
                "has_sameas": bool(row["has_sameas"]),
                "category_aligned": bool(row["category_aligned"]),
                "nap_consistent": bool(row["nap_consistent"]),
                "mobile_speed_score": row["mobile_speed_score"],
                "mobile_lcp": float(row["mobile_lcp"]) if row["mobile_lcp"] is not None else None,
                "raw_schema": raw_schema,
                "issues": issues,
                "score": row["score"],
            }
            data = {k: v for k, v in data.items() if v is not None}
            schema.table("wpa_audits").upsert(data, on_conflict="id").execute()
            aud_ok += 1
        except Exception as e:
            aud_err += 1
            print(f"  ERROR audit {row.get('business_id', '?')}: {e}")

    print(f"Audits: {aud_ok} migrated, {aud_err} errors")
    conn.close()
    print("Done.")

if __name__ == "__main__":
    migrate()
