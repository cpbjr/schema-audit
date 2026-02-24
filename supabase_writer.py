"""Write audit results to Supabase.

Requires environment variables:
  SUPABASE_URL         - e.g. https://klyzdnocgrvassppripi.supabase.co
  SUPABASE_SERVICE_KEY - service_role key (not anon key)

Usage:
  from supabase_writer import SupabaseWriter
  writer = SupabaseWriter()
  writer.upsert_business(business_dict)
  writer.insert_audit(audit_result)
"""
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


class SupabaseWriter:
    def __init__(self) -> None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment or .env"
            )
        self._headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }

    def _post(self, table: str, payload: dict[str, Any]) -> None:
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        resp = httpx.post(url, headers=self._headers, json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Supabase {table} insert failed: {resp.status_code} {resp.text}"
            )

    def upsert_business(self, business: dict[str, Any]) -> None:
        """Upsert a business record. business dict should match Supabase businesses columns."""
        known_columns = {
            "id", "name", "address", "phone", "website_url", "gbp_categories",
            "search_query", "discovered_at", "contact_status", "discovery_rank",
            "rank_total_candidates", "google_maps_uri", "business_status",
            "rating", "user_rating_count", "raw_data",
        }
        row: dict[str, Any] = {}
        for col in known_columns:
            if col in business:
                row[col] = business[col]

        # Ensure JSON-serializable types for JSONB columns
        for jsonb_col in ("gbp_categories", "raw_data"):
            if jsonb_col in row and isinstance(row[jsonb_col], str):
                try:
                    row[jsonb_col] = json.loads(row[jsonb_col])
                except (json.JSONDecodeError, TypeError):
                    row[jsonb_col] = [] if jsonb_col == "gbp_categories" else None

        self._post("businesses", row)

    def insert_audit(self, audit_result: Any, business_id: str | None = None) -> None:
        """Insert an audit result. audit_result is an AuditResult dataclass from analyzer.py.

        business_id must be provided since AuditResult does not carry it.
        """
        d = asdict(audit_result) if hasattr(audit_result, "__dataclass_fields__") else dict(audit_result)

        row: dict[str, Any] = {
            "business_id": business_id or d.get("business_id"),
            "has_schema": bool(d.get("has_schema", False)),
            "has_sameas": bool(d.get("has_sameas", False)),
            "category_aligned": bool(d.get("category_aligned", False)),
            "nap_consistent": bool(d.get("nap_consistent", False)),
            "mobile_speed_score": d.get("mobile_speed_score"),
            "mobile_lcp": d.get("mobile_lcp"),
            "raw_schema": d.get("raw_schema"),
            "issues": d.get("issues", []),
            "score": d.get("score"),
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "hosting_provider": d.get("hosting_provider"),
            "hosting_cost_min": d.get("hosting_cost_min"),
            "hosting_cost_max": d.get("hosting_cost_max"),
            "hosting_savings_min": d.get("hosting_savings_min"),
            "hosting_savings_max": d.get("hosting_savings_max"),
            "pitch_summary": d.get("pitch_summary"),
        }

        # Remove None values (use Supabase defaults)
        row = {k: v for k, v in row.items() if v is not None}

        # Audits are always new rows (BIGSERIAL PK) — don't merge-duplicate
        headers = {**self._headers, "Prefer": "return=minimal"}
        url = f"{SUPABASE_URL}/rest/v1/audits"
        resp = httpx.post(url, headers=headers, json=row, timeout=30)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Supabase audits insert failed: {resp.status_code} {resp.text}"
            )
