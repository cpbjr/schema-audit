"""FastAPI backend for Schema Audit Lead Generator."""

import json
import sqlite3
from datetime import date
from typing import List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import (
    DB_PATH,
    GOOGLE_PLACES_API_KEY,
    WPA_AUDIT_API_KEY,
    DAILY_DISCOVERY_LIMIT,
    ensure_directories,
)
from db import Database, Business, Audit, Report
from discovery import PlacesDiscovery
from analyzer import SchemaAnalyzer
from extractor import SchemaExtractor
from reporter import ReportGenerator
from email_generator import generate_email_from_db_records

app = FastAPI(title="Schema Audit API", version="1.0.0")

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API Key Authentication Middleware
# ---------------------------------------------------------------------------

EXEMPT_PATHS = {"/api/docs", "/docs", "/openapi.json", "/api/health", "/health"}

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    """Require X-API-Key header for all endpoints except health/docs."""
    if request.url.path in EXEMPT_PATHS or request.url.path.startswith("/docs"):
        return await call_next(request)
    if WPA_AUDIT_API_KEY:
        key = request.headers.get("X-API-Key", "")
        if key != WPA_AUDIT_API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key."})
    return await call_next(request)

# ---------------------------------------------------------------------------
# Rate Limiting Helpers
# ---------------------------------------------------------------------------

def _get_discovery_count_today(db: Database) -> int:
    """Return number of discovery calls made today."""
    today = date.today().isoformat()
    row = db.conn.execute(
        "SELECT count FROM discovery_rate_limit WHERE date = ?", (today,)
    ).fetchone()
    return row[0] if row else 0

def _increment_discovery_count(db: Database) -> int:
    """Increment today's discovery counter, return new count."""
    today = date.today().isoformat()
    db.conn.execute(
        """INSERT INTO discovery_rate_limit (date, count)
           VALUES (?, 1)
           ON CONFLICT(date) DO UPDATE SET count = count + 1""",
        (today,),
    )
    db.conn.commit()
    return _get_discovery_count_today(db)

def _ensure_rate_limit_table(db: Database) -> None:
    """Create rate limit table if it doesn't exist."""
    db.conn.execute(
        """CREATE TABLE IF NOT EXISTS discovery_rate_limit (
               date TEXT PRIMARY KEY,
               count INTEGER NOT NULL DEFAULT 0
           )"""
    )
    db.conn.commit()

# Ensure directories exist on startup
ensure_directories()

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class BusinessRead(BaseModel):
    id: str
    name: str
    address: str
    phone: str
    website_url: str
    gbp_categories: List[str]
    search_query: str
    discovered_at: str
    contact_status: str
    discovery_rank: Optional[int] = None
    rank_total_candidates: Optional[int] = None
    google_maps_uri: str = ""
    business_status: str = ""
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None

class AuditRead(BaseModel):
    id: Optional[int]
    business_id: str
    has_schema: bool
    has_sameas: bool
    category_aligned: bool
    nap_consistent: bool
    mobile_speed_score: Optional[int]
    mobile_lcp: Optional[float]
    raw_schema: Optional[dict]
    issues: List[str]
    score: int
    audited_at: str

class BusinessWithAudit(BusinessRead):
    audit: Optional[AuditRead] = None

class DiscoverRequest(BaseModel):
    query: str

class DiscoverResponse(BaseModel):
    new_count: int
    total_count: int
    message: str

class UpdateStatusRequest(BaseModel):
    status: str

class EmailResponse(BaseModel):
    subject: str
    body: str
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    sameas_urls: List[str] = []

class AuditByNameRequest(BaseModel):
    business_name: str
    city: str
    state: str

class AuditByNameResponse(BaseModel):
    business: BusinessRead
    audit: Optional[AuditRead] = None
    already_existed: bool = False
    alternatives: List[str] = []
    message: str

# ---------------------------------------------------------------------------
# Dependencies / Helpers
# ---------------------------------------------------------------------------

def get_db():
    db = Database(DB_PATH)
    try:
        yield db
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
@app.get("/api/health")
def health_check():
    """Health check — no auth required."""
    return {"status": "ok", "service": "wpa-audit-api"}

@app.get("/api/status")
def get_status():
    """Pipeline statistics."""
    db = Database(DB_PATH)
    try:
        _ensure_rate_limit_table(db)
        stats = db.get_pipeline_stats()
        today_discoveries = _get_discovery_count_today(db)
        return {
            **stats,
            "discovery_calls_today": today_discoveries,
            "discovery_limit_today": DAILY_DISCOVERY_LIMIT,
        }
    finally:
        db.close()

@app.post("/api/discover", response_model=DiscoverResponse)
def discover_leads(request: DiscoverRequest):
    """Discover businesses via Google Places API (rate limited)."""
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(status_code=500, detail="Google Places API Key not set.")

    db = Database(DB_PATH)
    try:
        _ensure_rate_limit_table(db)
        current = _get_discovery_count_today(db)
        if current >= DAILY_DISCOVERY_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Daily discovery limit reached ({current}/{DAILY_DISCOVERY_LIMIT}). Resets at midnight."
            )
        _increment_discovery_count(db)
        discovery = PlacesDiscovery(GOOGLE_PLACES_API_KEY)
        new_count = discovery.discover_and_store(request.query, db)
        total = len(db.get_all_businesses())
        return {
            "new_count": new_count,
            "total_count": total,
            "message": f"Added {new_count} new businesses."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/api/audit-by-name", response_model=AuditByNameResponse)
def audit_by_name(request: AuditByNameRequest):
    """One-shot: discover a business by name, audit it, return results.

    The live demo endpoint — give it a name and city, get a full audit back.
    """
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(status_code=500, detail="Google Places API Key not set.")

    db = Database(DB_PATH)
    try:
        _ensure_rate_limit_table(db)
        discovery = PlacesDiscovery(GOOGLE_PLACES_API_KEY)

        # --- Discover ---
        query = f"{request.business_name} in {request.city}, {request.state}"
        results = discovery.search_businesses(query)

        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"No businesses found matching '{request.business_name}' in {request.city}, {request.state}."
            )

        # Best match = first result; collect alternatives
        best = results[0]
        alternatives = []
        for r in results[1:4]:
            dn = r.get("displayName", {})
            alt_name = dn.get("text", "") if isinstance(dn, dict) else str(dn)
            if alt_name:
                alternatives.append(alt_name)

        place_id = best.get("id", "")
        display_name = best.get("displayName", {})
        biz_name = display_name.get("text", "Unknown") if isinstance(display_name, dict) else str(display_name)

        # --- Check if already in DB ---
        existing_biz = db.get_business(place_id)
        already_existed = existing_biz is not None

        if not already_existed:
            website = best.get("websiteUri", "")
            if not website:
                try:
                    details = discovery.get_place_details(place_id)
                    website = details.get("websiteUri", "")
                except Exception:
                    pass

            if not website:
                raise HTTPException(
                    status_code=422,
                    detail=f"Found '{biz_name}' but it has no website — cannot audit."
                )

            biz = Business(
                id=place_id,
                name=biz_name,
                address=best.get("formattedAddress", ""),
                phone=best.get("nationalPhoneNumber", ""),
                website_url=website,
                gbp_categories=best.get("types", []),
                search_query=query,
                discovery_rank=1,
                rank_total_candidates=len(results),
                google_maps_uri=best.get("googleMapsUri", ""),
                business_status=best.get("businessStatus", ""),
                rating=best.get("rating"),
                user_rating_count=best.get("userRatingCount"),
                raw_data=best,
            )
            db.insert_business(biz)
        else:
            biz = existing_biz

        # --- Audit ---
        existing_audit = db.get_audit(place_id)
        if existing_audit and already_existed:
            return AuditByNameResponse(
                business=BusinessRead(**biz.__dict__),
                audit=AuditRead(**existing_audit.__dict__),
                already_existed=True,
                alternatives=alternatives,
                message=f"Returning existing audit for '{biz.name}'.",
            )

        if not biz.website_url:
            raise HTTPException(status_code=422, detail=f"'{biz.name}' has no website — cannot audit.")

        extractor = SchemaExtractor()
        analyzer = SchemaAnalyzer()
        schemas = extractor.extract_schema_from_url(biz.website_url) or []
        gbp_data = {
            "name": biz.name,
            "address": biz.address,
            "phone": biz.phone,
            "types": biz.gbp_categories,
        }
        result = analyzer.run_full_audit(biz.website_url, schemas, gbp_data)

        audit = Audit(
            business_id=biz.id,
            has_schema=result.has_schema,
            has_sameas=result.has_sameas,
            category_aligned=result.category_aligned,
            nap_consistent=result.nap_consistent,
            mobile_speed_score=result.mobile_speed_score,
            mobile_lcp=result.mobile_lcp,
            raw_schema=result.raw_schema,
            issues=result.issues,
            score=result.score,
        )
        audit.id = db.insert_audit(audit)

        msg = f"Audited '{biz.name}' — score {result.score}/5"
        if alternatives:
            msg += f". Also found: {', '.join(alternatives)}"

        return AuditByNameResponse(
            business=BusinessRead(**biz.__dict__),
            audit=AuditRead(**audit.__dict__),
            already_existed=already_existed,
            alternatives=alternatives,
            message=msg,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.get("/api/leads", response_model=List[BusinessWithAudit])
def get_leads(
    status: Optional[str] = None,
    min_score: Optional[int] = None,
    max_score: Optional[int] = None,
):
    """Get all leads, optionally filtered."""
    db = Database(DB_PATH)
    try:
        all_businesses = db.get_all_businesses()
        results = []
        
        for biz in all_businesses:
            # Filter by contact status if provided
            if status and biz.contact_status != status:
                continue
                
            audit = db.get_audit(biz.id)
            
            # Filter by score if provided (only if audit exists)
            if min_score is not None:
                if not audit or audit.score < min_score:
                    continue
            if max_score is not None:
                if not audit or audit.score > max_score:
                    continue

            # Convert to response model
            biz_dict = biz.__dict__
            audit_dict = audit.__dict__ if audit else None
            
            results.append(BusinessWithAudit(**biz_dict, audit=audit_dict))
            
        return results
    finally:
        db.close()

@app.get("/api/leads/{business_id}", response_model=BusinessWithAudit)
def get_lead_detail(business_id: str):
    """Get a single lead details."""
    db = Database(DB_PATH)
    try:
        biz = db.get_business(business_id)
        if not biz:
            raise HTTPException(status_code=404, detail="Business not found")
        
        audit = db.get_audit(business_id)
        biz_dict = biz.__dict__
        audit_dict = audit.__dict__ if audit else None
        
        return BusinessWithAudit(**biz_dict, audit=audit_dict)
    finally:
        db.close()

@app.patch("/api/leads/{business_id}", response_model=BusinessRead)
def update_lead_status(business_id: str, request: UpdateStatusRequest):
    """Update contact status."""
    db = Database(DB_PATH)
    try:
        biz = db.get_business(business_id)
        if not biz:
            raise HTTPException(status_code=404, detail="Business not found")
        
        success = db.update_business_status(business_id, request.status)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update status")
            
        updated_biz = db.get_business(business_id)
        return updated_biz.__dict__
    finally:
        db.close()

@app.post("/api/audit/{business_id}", response_model=AuditRead)
def run_audit(business_id: str):
    """Run audit for a specific business."""
    db = Database(DB_PATH)
    try:
        biz = db.get_business(business_id)
        if not biz:
            raise HTTPException(status_code=404, detail="Business not found")

        if not biz.website_url:
            raise HTTPException(status_code=400, detail="Business has no website URL")

        extractor = SchemaExtractor()
        analyzer = SchemaAnalyzer()

        # Extract
        schemas = extractor.extract_schema_from_url(biz.website_url) or []

        # Analyze
        gbp_data = {
            "name": biz.name,
            "address": biz.address,
            "phone": biz.phone,
            "types": biz.gbp_categories,
        }
        result = analyzer.run_full_audit(biz.website_url, schemas, gbp_data)

        # Save
        audit = Audit(
            business_id=biz.id,
            has_schema=result.has_schema,
            has_sameas=result.has_sameas,
            category_aligned=result.category_aligned,
            nap_consistent=result.nap_consistent,
            mobile_speed_score=result.mobile_speed_score,
            mobile_lcp=result.mobile_lcp,
            raw_schema=result.raw_schema,
            issues=result.issues,
            score=result.score,
        )
        audit.id = db.insert_audit(audit)

        return audit.__dict__
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/api/generate-email/{business_id}", response_model=EmailResponse)
def generate_email(business_id: str):
    """Generate outreach email for a business."""
    db = Database(DB_PATH)
    try:
        biz = db.get_business(business_id)
        if not biz:
            raise HTTPException(status_code=404, detail="Business not found")

        audit = db.get_audit(business_id)

        # Convert to dicts for email generator
        business_data = biz.__dict__
        audit_data = audit.__dict__ if audit else None

        # Generate email
        email_content = generate_email_from_db_records(business_data, audit_data)

        return email_content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
