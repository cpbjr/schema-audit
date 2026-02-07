"""FastAPI backend for Schema Audit Lead Generator."""

import json
from typing import List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import DB_PATH, GOOGLE_PLACES_API_KEY, ensure_directories
from db import Database, Business, Audit, Report
from discovery import PlacesDiscovery
from analyzer import SchemaAnalyzer
from extractor import SchemaExtractor
from reporter import ReportGenerator

app = FastAPI(title="Schema Audit API", version="1.0.0")

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.post("/api/discover", response_model=DiscoverResponse)
def discover_leads(request: DiscoverRequest):
    """Discover businesses via Google Places API."""
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(status_code=500, detail="Google Places API Key not set.")

    db = Database(DB_PATH)
    try:
        discovery = PlacesDiscovery(GOOGLE_PLACES_API_KEY)
        new_count = discovery.discover_and_store(request.query, db)
        total = len(db.get_all_businesses())
        return {
            "new_count": new_count,
            "total_count": total,
            "message": f"Added {new_count} new businesses."
        }
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
