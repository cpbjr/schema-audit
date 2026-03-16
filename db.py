"""Database layer for Schema Audit Lead Generator."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Business:
    """A business discovered via Google Places."""

    id: str  # place_id
    name: str
    address: str
    phone: str
    website_url: str
    gbp_categories: list[str] = field(default_factory=list)
    gbp_primary_type: str = ""
    search_query: str = ""
    discovered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    contact_status: str = "NEW"  # NEW, CONTACTED, REPLIED, CLOSED
    discovery_rank: int | None = None
    rank_total_candidates: int | None = None
    google_maps_uri: str = ""
    business_status: str = ""
    rating: float | None = None
    user_rating_count: int | None = None
    raw_data: dict | None = None
    lead_source: str | None = None  # e.g. "warm intro", "cold email", "walk-in", "referral"
    closed_date: str | None = None  # ISO date when deal closed, None if not closed
    contract_value: float | None = None  # monthly recurring value in dollars, None if not closed

    def to_supabase_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "phone": self.phone,
            "website_url": self.website_url,
            "gbp_categories": self.gbp_categories,
            "gbp_primary_type": self.gbp_primary_type,
            "search_query": self.search_query,
            "discovered_at": self.discovered_at,
            "contact_status": self.contact_status,
            "discovery_rank": self.discovery_rank,
            "rank_total_candidates": self.rank_total_candidates,
            "google_maps_uri": self.google_maps_uri,
            "business_status": self.business_status,
            "rating": self.rating,
            "user_rating_count": self.user_rating_count,
            "raw_data": self.raw_data,
            "lead_source": self.lead_source,
            "closed_date": self.closed_date,
            "contract_value": self.contract_value,
        }


@dataclass
class Audit:
    """Schema / performance audit results for a business website."""

    business_id: str
    has_schema: bool
    has_sameas: bool
    category_aligned: bool
    nap_consistent: bool
    mobile_speed_score: int | None = None
    mobile_lcp: float | None = None
    raw_schema: dict | None = None
    issues: list[str] = field(default_factory=list)
    score: int = 0  # 0-5, lower = hotter lead
    audited_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    id: int | None = None

    def to_supabase_dict(self) -> dict:
        return {
            "business_id": self.business_id,
            "has_schema": self.has_schema,
            "has_sameas": self.has_sameas,
            "category_aligned": self.category_aligned,
            "nap_consistent": self.nap_consistent,
            "mobile_speed_score": self.mobile_speed_score,
            "mobile_lcp": float(self.mobile_lcp) if self.mobile_lcp is not None else None,
            "raw_schema": self.raw_schema,
            "issues": self.issues,
            "score": self.score,
            "audited_at": self.audited_at,
        }


@dataclass
class ServiceRank:
    """Per-service discovery rank for a business."""

    business_id: str
    service_query: str   # e.g. "hot water heater repair Eagle ID"
    service_label: str   # e.g. "Hot Water Repair"
    discovery_rank: int | None  # None = not found in results (invisible)
    total_results: int | None = None
    discovered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    id: int | None = None

    def to_supabase_dict(self) -> dict:
        return {
            "business_id": self.business_id,
            "service_query": self.service_query,
            "service_label": self.service_label,
            "discovery_rank": self.discovery_rank,
            "total_results": self.total_results,
            "discovered_at": self.discovered_at,
        }


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    """Supabase wrapper for lead management."""

    def __init__(self, db_path: Any = None) -> None:
        # db_path accepted but ignored — retained for call-site compatibility
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        self._schema = self.client.schema("wpa")

    # ------------------------------------------------------------------
    # Business CRUD
    # ------------------------------------------------------------------

    def insert_business(self, business: Business) -> None:
        """Insert or update a business (upsert by place_id)."""
        data: dict = {
            "id": business.id,
            "name": business.name,
            "address": business.address,
            "phone": business.phone,
            "website_url": business.website_url,
            "gbp_categories": business.gbp_categories,
            "gbp_primary_type": business.gbp_primary_type,
            "search_query": business.search_query,
            "contact_status": business.contact_status,
            "discovery_rank": business.discovery_rank,
            "rank_total_candidates": business.rank_total_candidates,
            "google_maps_uri": business.google_maps_uri,
            "business_status": business.business_status,
            "rating": business.rating,
            "user_rating_count": business.user_rating_count,
            "raw_data": business.raw_data,
            "lead_source": business.lead_source,
            "closed_date": business.closed_date,
            "contract_value": business.contract_value,
        }
        # Always include nullable numeric fields even if None; strip other Nones
        always_include = {"discovery_rank", "rank_total_candidates", "rating", "user_rating_count"}
        data = {k: v for k, v in data.items() if v is not None or k in always_include}
        self._schema.table("wpa_businesses").upsert(data, on_conflict="id").execute()

    def get_business(self, place_id: str) -> "Business | None":
        """Retrieve a single business by place_id."""
        resp = self._schema.table("wpa_businesses").select("*").eq("id", place_id).limit(1).execute()
        if resp and resp.data:
            return self._row_to_business(resp.data[0])
        return None

    def get_all_businesses(self) -> list["Business"]:
        """Return every business in the database."""
        resp = self._schema.table("wpa_businesses").select("*").order("discovered_at", desc=True).execute()
        return [self._row_to_business(row) for row in resp.data]

    def get_businesses_without_audit(self) -> list["Business"]:
        """Return businesses that have no audit record yet."""
        # Fetch all audited business IDs first, then filter
        audited_resp = self._schema.table("wpa_audits").select("business_id").execute()
        audited_ids: set[str] = {row["business_id"] for row in audited_resp.data}

        all_resp = self._schema.table("wpa_businesses").select("*").order("discovered_at", desc=True).execute()
        return [
            self._row_to_business(row)
            for row in all_resp.data
            if row["id"] not in audited_ids
        ]

    def search_businesses_by_url(self, url: str) -> "Business | None":
        """Find a business whose website_url matches (exact)."""
        resp = self._schema.table("wpa_businesses").select("*").eq("website_url", url).limit(1).execute()
        if resp and resp.data:
            return self._row_to_business(resp.data[0])
        return None

    def update_business_status(self, business_id: str, status: str) -> bool:
        """Update the contact status of a business. Returns True if a row was updated."""
        resp = self._schema.table("wpa_businesses").update({"contact_status": status}).eq("id", business_id).execute()
        return len(resp.data) > 0

    def update_contact_status(self, business_id: str, status: str) -> None:
        """Update the contact status of a business (alias for update_business_status)."""
        self._schema.table("wpa_businesses").update({"contact_status": status}).eq("id", business_id).execute()

    # ------------------------------------------------------------------
    # Audit CRUD
    # ------------------------------------------------------------------

    def insert_audit(self, audit: Audit) -> int:
        """Insert an audit and return its row id."""
        data: dict = {
            "business_id": audit.business_id,
            "has_schema": audit.has_schema,
            "has_sameas": audit.has_sameas,
            "category_aligned": audit.category_aligned,
            "nap_consistent": audit.nap_consistent,
            "mobile_speed_score": audit.mobile_speed_score,
            "mobile_lcp": float(audit.mobile_lcp) if audit.mobile_lcp is not None else None,
            "raw_schema": audit.raw_schema,
            "issues": audit.issues,
            "score": audit.score,
            "hosting_provider": getattr(audit, "hosting_provider", None),
            "hosting_cost_min": getattr(audit, "hosting_cost_min", None),
            "hosting_cost_max": getattr(audit, "hosting_cost_max", None),
            "hosting_savings_min": getattr(audit, "hosting_savings_min", None),
            "hosting_savings_max": getattr(audit, "hosting_savings_max", None),
            "pitch_summary": getattr(audit, "pitch_summary", None),
        }
        data = {k: v for k, v in data.items() if v is not None}
        resp = self._schema.table("wpa_audits").insert(data).execute()
        if resp.data:
            return resp.data[0].get("id", 0)
        return 0

    def get_audit(self, business_id: str) -> "Audit | None":
        """Return the most recent audit for a business."""
        return self.get_latest_audit(business_id)

    def get_latest_audit(self, business_id: str) -> "Audit | None":
        """Return the most recent audit for a business."""
        resp = (
            self._schema.table("wpa_audits")
            .select("*")
            .eq("business_id", business_id)
            .order("audited_at", desc=True)
            .limit(1)
            .execute()
        )
        if resp and resp.data:
            return self._row_to_audit(resp.data[0])
        return None

    def get_hot_leads(self, max_score: int = 2) -> list[tuple["Business", "Audit"]]:
        """Return businesses with audit score <= max_score (hot leads)."""
        resp = (
            self._schema.table("wpa_businesses_with_score")
            .select("*")
            .lte("latest_score", max_score)
            .order("latest_score")
            .execute()
        )
        results: list[tuple[Business, Audit]] = []
        for row in resp.data:
            biz = self._row_to_business(row)
            audit = self.get_latest_audit(biz.id)
            if audit is not None:
                results.append((biz, audit))
        return results

    # ------------------------------------------------------------------
    # Report stubs (kept for call-site compatibility)
    # ------------------------------------------------------------------

    def insert_report(self, report: Any) -> int:
        """No-op stub — reports are no longer persisted to the database."""
        return 0

    # ------------------------------------------------------------------
    # ServiceRank CRUD
    # ------------------------------------------------------------------

    def upsert_service_rank(self, rank: ServiceRank) -> None:
        """Insert or update a service rank record."""
        data: dict = {
            "business_id": rank.business_id,
            "service_query": rank.service_query,
            "service_label": rank.service_label,
            "discovery_rank": rank.discovery_rank,
            "total_results": rank.total_results,
        }
        self._schema.table("wpa_service_ranks").upsert(data, on_conflict="business_id,service_query").execute()

    def get_service_ranks(self, business_id: str) -> list[ServiceRank]:
        """Return all service ranks for a business."""
        resp = self._schema.table("wpa_service_ranks").select("*").eq("business_id", business_id).execute()
        return [self._row_to_service_rank(row) for row in resp.data]

    def get_service_gaps(self, min_rank: int = 10) -> list[dict]:
        """Return businesses with significant service visibility gaps."""
        resp = self._schema.table("wpa_service_ranks").select("*, wpa_businesses(name, website_url)").execute()
        ranks = resp.data

        by_business: dict[str, list] = defaultdict(list)
        biz_info: dict[str, dict] = {}
        for r in ranks:
            bid = r["business_id"]
            by_business[bid].append(r)
            if bid not in biz_info and r.get("wpa_businesses"):
                biz_info[bid] = r["wpa_businesses"]

        gaps = []
        for bid, service_list in by_business.items():
            if len(service_list) <= 1:
                continue

            ranked = [s for s in service_list if s["discovery_rank"] is not None]
            invisible = [s for s in service_list if s["discovery_rank"] is None]

            best_rank = min((s["discovery_rank"] for s in ranked), default=None)
            worst_rank = max((s["discovery_rank"] for s in ranked), default=None)
            gap = (worst_rank - best_rank) if (best_rank is not None and worst_rank is not None) else None

            # Skip businesses with no gaps
            if not invisible and (gap is None or gap < min_rank):
                continue

            info = biz_info.get(bid, {})

            # Build a service_breakdown string matching the SQLite format
            service_breakdown_parts = []
            for s in service_list:
                rank_str = str(s["discovery_rank"]) if s["discovery_rank"] is not None else "invisible"
                service_breakdown_parts.append(f"{s['service_label']}:{rank_str}")
            service_breakdown = " | ".join(service_breakdown_parts)

            gaps.append({
                "id": bid,
                "name": info.get("name", bid),
                "website_url": info.get("website_url", ""),
                "best_rank": best_rank,
                "worst_rank": worst_rank,
                "gap": gap,
                "service_count": len(service_list),
                "invisible_count": len(invisible),
                "service_breakdown": service_breakdown,
                "invisible_services": [s["service_label"] for s in invisible],
                "is_hot": len(invisible) > 0 or (gap is not None and gap >= 5),
                # Extended fields for callers that use the richer dict
                "services": service_list,
                "business_id": bid,
            })

        gaps.sort(key=lambda g: (not g["is_hot"], g["best_rank"] or 999))
        return gaps

    # ------------------------------------------------------------------
    # Pipeline stats
    # ------------------------------------------------------------------

    def get_pipeline_stats(self) -> dict:
        """Return summary statistics for the lead pipeline."""
        biz_resp = self._schema.table("wpa_businesses").select("id", count="exact").execute()
        total: int = biz_resp.count or len(biz_resp.data)

        audited_resp = self._schema.table("wpa_audits").select("business_id").execute()
        audited_ids: set[str] = {row["business_id"] for row in audited_resp.data}
        audited: int = len(audited_ids)
        unaudited: int = total - audited

        # Score buckets: fetch all audits, keep only latest per business
        all_audits_resp = self._schema.table("wpa_audits").select("business_id, score, audited_at").order("audited_at", desc=True).execute()
        latest_score: dict[str, int] = {}
        for row in all_audits_resp.data:
            bid = row["business_id"]
            if bid not in latest_score:
                latest_score[bid] = row["score"]

        hot_leads = sum(1 for s in latest_score.values() if s <= 2)
        warm_leads = sum(1 for s in latest_score.values() if s in (3, 4))
        cold_leads = sum(1 for s in latest_score.values() if s >= 5)

        return {
            "total_businesses": total,
            "audited_count": audited,
            "unaudited_count": unaudited,
            "hot_leads": hot_leads,
            "warm_leads": warm_leads,
            "cold_leads": cold_leads,
            "reports_generated": 0,  # reports no longer persisted
        }

    # ------------------------------------------------------------------
    # Row converters
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_business(row: dict) -> Business:
        return Business(
            id=row["id"],
            name=row["name"],
            address=row.get("address", ""),
            phone=row.get("phone", ""),
            website_url=row.get("website_url", ""),
            gbp_categories=row.get("gbp_categories") or [],
            gbp_primary_type=row.get("gbp_primary_type", ""),
            search_query=row.get("search_query", ""),
            discovered_at=row.get("discovered_at", ""),
            contact_status=row.get("contact_status", "NEW"),
            discovery_rank=row.get("discovery_rank"),
            rank_total_candidates=row.get("rank_total_candidates"),
            google_maps_uri=row.get("google_maps_uri", ""),
            business_status=row.get("business_status", ""),
            rating=row.get("rating"),
            user_rating_count=row.get("user_rating_count"),
            raw_data=row.get("raw_data"),
            lead_source=row.get("lead_source"),
            closed_date=row.get("closed_date"),
            contract_value=row.get("contract_value"),
        )

    @staticmethod
    def _row_to_audit(row: dict) -> Audit:
        return Audit(
            id=row.get("id"),
            business_id=row["business_id"],
            has_schema=bool(row["has_schema"]),
            has_sameas=bool(row["has_sameas"]),
            category_aligned=bool(row["category_aligned"]),
            nap_consistent=bool(row["nap_consistent"]),
            mobile_speed_score=row.get("mobile_speed_score"),
            mobile_lcp=float(row["mobile_lcp"]) if row.get("mobile_lcp") is not None else None,
            raw_schema=row.get("raw_schema"),
            issues=row.get("issues") or [],
            score=row.get("score", 0),
            audited_at=row.get("audited_at", ""),
        )

    @staticmethod
    def _row_to_service_rank(row: dict) -> ServiceRank:
        return ServiceRank(
            id=row.get("id"),
            business_id=row["business_id"],
            service_query=row["service_query"],
            service_label=row["service_label"],
            discovery_rank=row.get("discovery_rank"),
            total_results=row.get("total_results"),
            discovered_at=row.get("discovered_at", ""),
        )

    def close(self) -> None:
        """No-op — Supabase client does not require explicit closing."""
        pass
