#!/usr/bin/env python3
"""Winnow: Automated lead qualification engine for White Pine Agency.

Evaluates businesses in Supabase using deterministic scoring (no LLM cost).
Produces three buckets:
  - IDENTIFIED (score >= 55): clear winners, move status immediately
  - MIDDLE BAND (score 25-54): pass to Haiku Stage 2 via Claude Code skill
  - CLOSED/SKIP (score < 25): clear non-fits

Usage:
  python winnow.py --batch 50              # Process 50 businesses
  python winnow.py --batch 50 --query "landscaper Eagle"  # Filter by search_query
  python winnow.py --dry-run --batch 10    # Evaluate without writing
  python winnow.py --single ChIJ...       # Evaluate one business
  python winnow.py --status                # Show pipeline counts

Output: JSON to stdout (for skill parsing), progress to stderr.
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
CONFIG_PATH = Path(__file__).parent / "winnow_config.json"


def eprint(*args, **kwargs):
    """Print to stderr (progress/diagnostics, not captured by skill)."""
    print(*args, file=sys.stderr, **kwargs)


# ──────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────

class WinnowConfig:
    def __init__(self, path: Path = CONFIG_PATH):
        with open(path) as f:
            self._data = json.load(f)

    @property
    def thresholds(self) -> dict:
        return self._data["thresholds"]

    @property
    def scoring(self) -> dict:
        return self._data["scoring"]

    @property
    def bonuses(self) -> dict:
        return self._data["bonuses"]

    @property
    def hard_disqualifiers(self) -> list:
        return self._data["hard_disqualifiers"]

    @property
    def chain_detection(self) -> dict:
        return self._data["chain_detection"]

    @property
    def hosting_providers(self) -> dict:
        return self._data["hosting_providers"]

    @property
    def web_check(self) -> dict:
        return self._data["web_check"]

    def snapshot(self) -> dict:
        return self._data


# ──────────────────────────────────────────────────────────────────
# Web Checker
# ──────────────────────────────────────────────────────────────────

class WebChecker:
    """HTTP HEAD + <head> quality scan."""

    def __init__(self, config: WinnowConfig):
        self.cfg = config.web_check
        self.timeout = self.cfg["timeout_seconds"]
        self.max_redirects = self.cfg["max_redirects"]
        self.head_max_bytes = self.cfg["head_fetch_max_bytes"]
        self.parking_signals = [s.lower() for s in self.cfg["parking_page_signals"]]
        self.headers = {"User-Agent": "Mozilla/5.0 (compatible; WinnowBot/1.0; +https://whitepineagency.com)"}

    def normalize_url(self, url: str) -> str:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            return f"https://{url}"
        return url

    def check(self, url: str) -> dict:
        """Returns dict with: reachable, final_url, quality_score (0-3), is_parking."""
        result = {
            "reachable": False,
            "final_url": None,
            "quality_score": 0,  # 0=unreachable, 1=parking, 2=poor, 3=adequate+
            "head_html": None,
            "is_parking": False,
        }
        if not url:
            return result

        norm = self.normalize_url(url)
        try:
            with httpx.Client(
                follow_redirects=True,
                max_redirects=self.max_redirects,
                timeout=self.timeout,
            ) as client:
                resp = client.head(norm, headers=self.headers)
            result["reachable"] = resp.status_code < 400
            result["final_url"] = str(resp.url)
        except Exception as e:
            eprint(f"    HEAD check failed for {url}: {e}")
            return result

        if not result["reachable"]:
            return result

        # Fetch <head> section for quality scan
        head_html = self._fetch_head(result["final_url"])
        if head_html:
            result["head_html"] = head_html
            quality, is_parking = self._assess_quality(head_html)
            result["quality_score"] = quality
            result["is_parking"] = is_parking

        return result

    def _fetch_head(self, url: str) -> str | None:
        """Stream only the <head> section (stop early to save bandwidth)."""
        try:
            with httpx.stream("GET", url, headers=self.headers, timeout=self.timeout, follow_redirects=True) as resp:
                html_chunk = b""
                for chunk in resp.iter_bytes(chunk_size=1024):
                    html_chunk += chunk
                    if len(html_chunk) >= self.head_max_bytes:
                        break
                    # Stop once we have </head>
                    if b"</head>" in html_chunk.lower():
                        break
            return html_chunk.decode("utf-8", errors="replace")
        except Exception:
            return None

    def _assess_quality(self, html: str) -> tuple[int, bool]:
        """Returns (quality_score 1-3, is_parking)."""
        lower = html.lower()

        # Check for parking page signals
        for signal in self.parking_signals:
            if signal in lower:
                return 1, True  # parking page

        soup = BeautifulSoup(html, "html.parser")
        score = 0

        # Has <title> with real content (not default/empty)
        title = soup.find("title")
        if title and title.get_text(strip=True) and len(title.get_text(strip=True)) > 5:
            score += 1

        # Has meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content", "").strip():
            score += 1

        # quality_score 0: unreachable (set above), 1: parking, 2: poor (score 0-1), 3: adequate+ (score 2)
        if score == 0:
            return 2, False  # reachable but poor
        elif score == 1:
            return 2, False  # still poor
        else:
            return 3, False  # adequate


# ──────────────────────────────────────────────────────────────────
# Hosting Detector
# ──────────────────────────────────────────────────────────────────

class HostingDetector:
    """Detect expensive hosting providers from website HTML."""

    def __init__(self, config: WinnowConfig):
        self.providers = config.hosting_providers

    def detect(self, html: str | None, final_url: str | None) -> dict:
        """Returns dict with provider, tier, cost_range."""
        result = {"provider": None, "tier": "unknown", "cost_range": None}
        if not html and not final_url:
            return result

        content = (html or "") + " " + (final_url or "")
        content_lower = content.lower()

        for tier_key, tier_data in self.providers.items():
            if tier_key == "free_builder":
                continue  # check last
            for provider, signatures in tier_data.get("signatures", {}).items():
                for sig in signatures:
                    if sig.lower() in content_lower:
                        result["provider"] = provider
                        result["tier"] = tier_key
                        result["cost_range"] = tier_data.get("cost_range")
                        return result

        # Check free builders last
        free = self.providers.get("free_builder", {})
        for provider, signatures in free.get("signatures", {}).items():
            for sig in signatures:
                if sig.lower() in content_lower:
                    result["provider"] = provider
                    result["tier"] = "free_builder"
                    result["cost_range"] = {"min": 0, "max": 0}
                    return result

        return result


# ──────────────────────────────────────────────────────────────────
# Idaho SOS Checker
# ──────────────────────────────────────────────────────────────────

class SOSChecker:
    """Scrape Idaho SOS business registry. Best-effort — graceful failure."""

    BASE_URL = "https://sosbiz.idaho.gov/api/records/businesssearch"

    def lookup(self, business_name: str) -> dict:
        """Returns: status, registered_at, entity_type. All may be None on failure."""
        result = {"status": None, "registered_at": None, "entity_type": None}
        if not business_name:
            return result

        # Clean name for search (remove common suffixes)
        clean = re.sub(r"\b(llc|inc|corp|ltd|co\.?)\b", "", business_name, flags=re.IGNORECASE).strip()
        clean = re.sub(r"[^a-zA-Z0-9\s]", "", clean).strip()
        if not clean:
            return result

        try:
            resp = requests.get(
                self.BASE_URL,
                params={"businessName": clean, "fileNumberFrom": "", "fileNumberTo": ""},
                timeout=8,
                headers={"User-Agent": "Mozilla/5.0 (compatible; WinnowBot/1.0)"},
            )
            if resp.status_code != 200:
                return result
            data = resp.json()
            rows = data.get("rows", []) or data.get("data", []) or []
            if not rows:
                return result

            # Find best match (first active result)
            for row in rows[:5]:
                name_match = self._name_similarity(clean, row.get("businessName", ""))
                if name_match > 0.6:
                    result["status"] = row.get("statusCode") or row.get("status")
                    result["entity_type"] = row.get("entityType") or row.get("businessType")
                    filed = row.get("filedDate") or row.get("formationDate") or row.get("registrationDate")
                    if filed:
                        try:
                            result["registered_at"] = filed[:10]  # YYYY-MM-DD
                        except Exception:
                            pass
                    break
        except Exception as e:
            eprint(f"    SOS lookup failed for '{business_name}': {e}")

        return result

    def _name_similarity(self, a: str, b: str) -> float:
        """Simple token overlap similarity."""
        a_words = set(a.lower().split())
        b_words = set((b or "").lower().split())
        if not a_words or not b_words:
            return 0.0
        overlap = len(a_words & b_words)
        return overlap / max(len(a_words), len(b_words))


# ──────────────────────────────────────────────────────────────────
# Chain Detector
# ──────────────────────────────────────────────────────────────────

class ChainDetector:
    """Detect chain/franchise businesses."""

    def __init__(self, config: WinnowConfig):
        self.cfg = config.chain_detection
        self.known = [f.lower() for f in self.cfg["known_franchises"]]
        self.patterns = [re.compile(p, re.IGNORECASE) for p in self.cfg.get("franchise_name_patterns", [])]
        self.chain_categories = [c.lower() for c in self.cfg.get("franchise_gbp_categories", [])]

    def is_chain(self, name: str, gbp_categories: list) -> bool:
        if not name:
            return False
        name_lower = name.lower()

        # Check known franchise list
        for franchise in self.known:
            if franchise in name_lower:
                return True

        # Check franchise name patterns (e.g., "Subway #1234")
        for pattern in self.patterns:
            if pattern.search(name):
                return True

        # Check GBP categories
        cats = [str(c).lower() for c in (gbp_categories or [])]
        for cat in cats:
            for chain_cat in self.chain_categories:
                if chain_cat in cat:
                    return True

        return False


# ──────────────────────────────────────────────────────────────────
# Review Analyzer
# ──────────────────────────────────────────────────────────────────

class ReviewAnalyzer:
    """Extract review timestamps from raw_data JSONB."""

    def analyze(self, raw_data: dict | None) -> dict:
        result = {"velocity_90d": 0, "trend": "unknown"}
        if not raw_data:
            return result

        # Look for reviews array in raw_data (Google Places format)
        reviews = raw_data.get("reviews", [])
        if not reviews:
            return result

        now = datetime.now(timezone.utc)
        cutoff_90d = now - timedelta(days=90)
        cutoff_180d = now - timedelta(days=180)

        recent_count = 0
        older_count = 0

        for review in reviews:
            # Google Places API returns epoch seconds in 'time' field
            ts = review.get("time") or review.get("publishTime")
            if not ts:
                continue
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                elif isinstance(ts, str):
                    # ISO format
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    continue

                if dt >= cutoff_90d:
                    recent_count += 1
                elif dt >= cutoff_180d:
                    older_count += 1
            except Exception:
                continue

        result["velocity_90d"] = recent_count

        # Trend: rising if recent > older, declining if older > recent*2
        if recent_count == 0 and older_count == 0:
            result["trend"] = "unknown"
        elif recent_count >= older_count * 1.5:
            result["trend"] = "rising"
        elif older_count > recent_count * 2:
            result["trend"] = "declining"
        else:
            result["trend"] = "stable"

        return result


# ──────────────────────────────────────────────────────────────────
# Scorer
# ──────────────────────────────────────────────────────────────────

class WinnowScorer:
    """Apply scoring rubric. Returns score (0-100) + breakdown dict."""

    def __init__(self, config: WinnowConfig):
        self.cfg = config
        self.thresholds = config.thresholds

    def score(
        self,
        business: dict,
        audit: dict | None,
        web_check: dict,
        sos: dict,
        is_chain: bool,
        review_signals: dict,
        hosting: dict,
    ) -> dict:
        """Returns: {score, decision, breakdown, reasoning_summary, hard_disqualified}."""

        breakdown = {}
        total = 0
        disqualified = False
        disqualify_reason = None

        # ── Hard disqualifiers ──────────────────────────────────────
        if business.get("business_status") == "CLOSED_PERMANENTLY_CLOSED":
            disqualified = True
            disqualify_reason = "permanently_closed"
        elif sos.get("status") and "dissolv" in str(sos["status"]).lower():
            disqualified = True
            disqualify_reason = "sos_dissolved"
        elif is_chain:
            disqualified = True
            disqualify_reason = "chain_franchise"

        if disqualified:
            return {
                "score": 0,
                "decision": "CLOSED",
                "breakdown": {"hard_disqualified": disqualify_reason},
                "reasoning_summary": f"Hard disqualified: {disqualify_reason}",
                "hard_disqualified": True,
            }

        # ── Audit score (technical opportunity) ─────────────────────
        s = self.cfg.scoring
        audit_score_val = audit.get("score") if audit else None
        audit_pts = self._band(
            audit_score_val,
            s["audit_score"]["bands"],
            default_key="no_audit",
        )
        breakdown["audit_score"] = {"raw": audit_score_val, "points": audit_pts}
        total += audit_pts

        # ── Website quality ─────────────────────────────────────────
        q_score = web_check.get("quality_score", 0)
        reachable = web_check.get("reachable", False)
        if not business.get("website_url") and not reachable:
            ws_key = "no_website"
        elif web_check.get("is_parking"):
            ws_key = "parking_page"
        elif q_score == 2:
            ws_key = "poor"
        elif q_score == 3:
            ws_key = "mediocre" if audit_score_val and audit_score_val >= 3 else "adequate"
        else:
            ws_key = "poor"

        ws_pts = s["website_quality"]["bands"].get(ws_key, 0)
        breakdown["website_quality"] = {"quality_key": ws_key, "quality_score": q_score, "points": ws_pts}
        total += ws_pts

        # ── Business age (SOS) ──────────────────────────────────────
        age_pts = self._sos_age_score(sos)
        breakdown["business_age"] = {"sos_registered_at": sos.get("registered_at"), "points": age_pts}
        total += age_pts

        # ── Review count ────────────────────────────────────────────
        review_count = business.get("user_rating_count") or 0
        rc_pts = self._review_count_score(review_count)
        breakdown["review_count"] = {"count": review_count, "points": rc_pts}
        total += rc_pts

        # ── Review velocity ─────────────────────────────────────────
        vel = review_signals.get("velocity_90d", 0)
        vel_pts = self._velocity_score(vel)
        breakdown["review_velocity"] = {"velocity_90d": vel, "points": vel_pts}
        total += vel_pts

        # ── Rating ──────────────────────────────────────────────────
        rating = business.get("rating")
        rating_pts = self._rating_score(rating)
        breakdown["rating"] = {"raw": rating, "points": rating_pts}
        total += rating_pts

        # ── Business type ────────────────────────────────────────────
        cats = business.get("gbp_categories", [])
        bt_pts, bt_tier = self._business_type_score(cats, is_chain)
        breakdown["business_type"] = {"tier": bt_tier, "categories_checked": cats[:5], "points": bt_pts}
        total += bt_pts

        # ── Discovery rank ────────────────────────────────────────────
        rank = business.get("discovery_rank")
        rank_pts = self._rank_score(rank)
        breakdown["discovery_rank"] = {"rank": rank, "points": rank_pts}
        total += rank_pts

        # ── Hosting rescue ────────────────────────────────────────────
        hosting_tier = hosting.get("tier", "unknown")
        hosting_pts = s["hosting_rescue"]["bands"].get(
            hosting_tier.replace("expensive_hostile", "premium_hostile")
            .replace("expensive_friendly", "premium_friendly"),
            s["hosting_rescue"]["bands"].get("unknown", 1)
        )
        breakdown["hosting"] = {
            "provider": hosting.get("provider"),
            "tier": hosting_tier,
            "points": hosting_pts,
        }
        total += hosting_pts

        # ── Bonuses ──────────────────────────────────────────────────
        bonus_total = 0
        bonuses_applied = []

        # Website + worst audit
        if reachable and audit_score_val is not None and audit_score_val <= 1:
            bonus_total += self.cfg.bonuses["website_plus_worst_audit"]["points"]
            bonuses_applied.append("website_plus_worst_audit")

        # Expensive hosting
        if hosting_tier in ("expensive_hostile",):
            bonus_total += self.cfg.bonuses["expensive_hosting"]["points"]
            bonuses_applied.append("expensive_hosting")

        breakdown["bonuses"] = {"applied": bonuses_applied, "total_bonus_points": bonus_total}
        total += bonus_total

        # Cap at 100
        total = min(100, total)

        # ── Decision ─────────────────────────────────────────────────
        t = self.thresholds
        if total >= t["identified"]:
            decision = "IDENTIFIED"
        elif total >= t["middle_band_lower"]:
            decision = "SKIP"  # middle band — handled by skill as MIDDLE_BAND
        else:
            decision = "SKIP" if total >= t["closed"] else "CLOSED"

        # Build reasoning summary
        top_signals = sorted(
            [(k, v.get("points", 0)) for k, v in breakdown.items() if isinstance(v, dict) and "points" in v],
            key=lambda x: -x[1]
        )[:3]
        reasoning = (
            f"Score {total}/100. "
            f"Top signals: {', '.join(f'{k}={p}pts' for k, p in top_signals)}. "
            f"Decision: {decision}."
        )
        if hosting.get("provider"):
            reasoning += f" Hosting: {hosting['provider']}."

        return {
            "score": total,
            "decision": decision,
            "breakdown": breakdown,
            "reasoning_summary": reasoning,
            "hard_disqualified": False,
        }

    def is_middle_band(self, score: int) -> bool:
        t = self.thresholds
        return t["middle_band_lower"] <= score < t["identified"]

    # ── Helpers ──────────────────────────────────────────────────────

    def _band(self, value, bands: dict, default_key: str = "unknown") -> int:
        if value is None:
            return bands.get(default_key, 0)
        return bands.get(str(value), bands.get(default_key, 0))

    def _sos_age_score(self, sos: dict) -> int:
        bands = self.cfg.scoring["business_age_sos"]["bands"]
        if not sos.get("registered_at"):
            return bands.get("unknown", 5)
        try:
            reg = date.fromisoformat(str(sos["registered_at"])[:10])
            age_years = (date.today() - reg).days / 365.25
            if age_years < 2:
                return bands["under_2_years"]
            elif age_years < 5:
                return bands["2_to_5_years"]
            elif age_years < 10:
                return bands["5_to_10_years"]
            else:
                return bands["over_10_years"]
        except Exception:
            return bands.get("unknown", 5)

    def _review_count_score(self, count: int) -> int:
        bands = self.cfg.scoring["review_count"]["bands"]
        if count == 0:
            return bands["0"]
        elif count <= 9:
            return bands["1_to_9"]
        elif count <= 19:
            return bands["10_to_19"]
        elif count <= 200:
            return bands["20_to_200"]
        elif count <= 500:
            return bands["201_to_500"]
        else:
            return bands["over_500"]

    def _velocity_score(self, velocity: int) -> int:
        bands = self.cfg.scoring["review_velocity_90d"]["bands"]
        if velocity == 0:
            return bands["0"]
        elif velocity <= 2:
            return bands["1_to_2"]
        elif velocity <= 5:
            return bands["3_to_5"]
        elif velocity <= 10:
            return bands["6_to_10"]
        else:
            return bands["over_10"]

    def _rating_score(self, rating) -> int:
        bands = self.cfg.scoring["rating"]["bands"]
        if rating is None:
            return bands["no_rating"]
        r = float(rating)
        if r < 3.0:
            return bands["under_3"]
        elif r < 3.5:
            return bands["3_to_3_4"]
        elif r <= 4.4:
            return bands["3_5_to_4_4"]
        else:
            return bands["4_5_to_5"]

    def _business_type_score(self, categories: list, chain: bool) -> tuple[int, str]:
        if chain:
            return 0, "chain"
        s = self.cfg.scoring["business_type"]
        cats_lower = [str(c).lower() for c in (categories or [])]
        joined = " ".join(cats_lower)

        for keyword in s["tier_1_categories"]:
            if keyword.lower() in joined:
                return s["scores"]["tier_1"], "tier_1"

        for keyword in s["tier_2_categories"]:
            if keyword.lower() in joined:
                return s["scores"]["tier_2"], "tier_2"

        return s["scores"]["unknown"], "unknown"

    def _rank_score(self, rank) -> int:
        bands = self.cfg.scoring["discovery_rank"]["bands"]
        if rank is None:
            return bands["unknown"]
        r = int(rank)
        if r <= 5:
            return bands["1_to_5"]
        elif r <= 10:
            return bands["6_to_10"]
        elif r <= 20:
            return bands["11_to_20"]
        else:
            return bands["over_20"]


# ──────────────────────────────────────────────────────────────────
# Supabase Client
# ──────────────────────────────────────────────────────────────────

class SupabaseClient:
    """Thin httpx wrapper for Supabase REST API."""

    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        self._headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Accept-Profile": "wpa",
            "Content-Profile": "wpa",
        }

    def get(self, path: str, params: dict | None = None) -> list:
        resp = httpx.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=self._headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, data: dict | list, prefer: str = "return=minimal") -> None:
        headers = {**self._headers, "Prefer": prefer}
        resp = httpx.post(f"{SUPABASE_URL}/rest/v1/{path}", headers=headers, json=data, timeout=30)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"POST {path} failed: {resp.status_code} {resp.text}")

    def patch(self, path: str, filter_str: str, data: dict) -> None:
        headers = {**self._headers, "Prefer": "return=minimal"}
        url = f"{SUPABASE_URL}/rest/v1/{path}?{filter_str}"
        resp = httpx.patch(url, headers=headers, json=data, timeout=30)
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"PATCH {path} failed: {resp.status_code} {resp.text}")


# ──────────────────────────────────────────────────────────────────
# Main Engine
# ──────────────────────────────────────────────────────────────────

class WinnowEngine:
    """Orchestrates: fetch batch → check → score → write to Supabase."""

    def __init__(self, config: WinnowConfig, dry_run: bool = False):
        self.cfg = config
        self.dry_run = dry_run
        self.db = SupabaseClient()
        self.web = WebChecker(config)
        self.sos = SOSChecker()
        self.chains = ChainDetector(config)
        self.reviews = ReviewAnalyzer()
        self.hosting = HostingDetector(config)
        self.scorer = WinnowScorer(config)

    # ── Fetch ────────────────────────────────────────────────────────

    def fetch_batch(self, batch_size: int, search_query: str | None = None) -> list[dict]:
        """Fetch businesses not yet evaluated, highest-priority first."""
        # Base query: IDENTIFIED businesses not in winnow_decisions
        # IDENTIFIED = discovered by Bud, not yet evaluated by winnow or promoted to active pipeline
        already_evaluated = {
            row["business_id"]
            for row in self.db.get("wpa_winnow_decisions", {"select": "business_id"})
        }

        params = {
            "select": "id,name,address,phone,website_url,gbp_categories,search_query,"
                      "discovery_rank,business_status,rating,user_rating_count,raw_data,contact_status",
            "contact_status": "eq.IDENTIFIED",
            "order": "user_rating_count.desc.nullslast",
            "limit": str(batch_size * 3),  # Over-fetch since we filter already-evaluated
        }
        if search_query:
            params["search_query"] = f"ilike.*{search_query}*"

        businesses = self.db.get("wpa_businesses", params)

        # Filter already evaluated
        businesses = [b for b in businesses if b["id"] not in already_evaluated]

        # Sort: audited businesses with low scores first, then by review count
        audited_ids = self._get_audited_ids_with_scores()
        def sort_key(b):
            audit = audited_ids.get(b["id"])
            has_low_audit = audit is not None and audit <= 2
            return (0 if has_low_audit else 1, -(b.get("user_rating_count") or 0))

        businesses.sort(key=sort_key)
        return businesses[:batch_size]

    def fetch_single(self, place_id: str) -> dict | None:
        results = self.db.get("wpa_businesses", {
            "id": f"eq.{place_id}",
            "select": "id,name,address,phone,website_url,gbp_categories,search_query,"
                      "discovery_rank,business_status,rating,user_rating_count,raw_data,contact_status",
        })
        return results[0] if results else None

    def _get_audited_ids_with_scores(self) -> dict:
        """Returns {business_id: min_score} for all audited businesses."""
        rows = self.db.get("wpa_audits", {"select": "business_id,score"})
        result = {}
        for row in rows:
            bid = row["business_id"]
            s = row.get("score")
            if s is not None:
                if bid not in result or s < result[bid]:
                    result[bid] = s
        return result

    def _get_audit_for_business(self, business_id: str) -> dict | None:
        rows = self.db.get("wpa_audits", {
            "business_id": f"eq.{business_id}",
            "order": "audited_at.desc",
            "limit": "1",
            "select": "score,has_schema,has_sameas,nap_consistent,mobile_speed_score,hosting_provider",
        })
        return rows[0] if rows else None

    # ── Evaluate ─────────────────────────────────────────────────────

    def evaluate(self, business: dict) -> dict:
        """Run full evaluation for a single business. Returns decision dict."""
        eprint(f"  Evaluating: {business['name']}")

        # Fetch audit data
        audit = self._get_audit_for_business(business["id"])

        # Web check
        url = business.get("website_url") or ""
        if not url:
            # Heuristic: try slugified name
            slug = re.sub(r"[^a-z0-9]", "", business["name"].lower())
            url = f"https://{slug}.com"
            eprint(f"    No website URL — trying heuristic: {url}")
        web_result = self.web.check(url)

        # Hosting detection (use head_html if we got it)
        hosting_result = self.hosting.detect(
            web_result.get("head_html"),
            web_result.get("final_url"),
        )

        # If audit has hosting_provider, use that too (fallback)
        if not hosting_result.get("provider") and audit and audit.get("hosting_provider"):
            # Map from existing audit data
            provider = audit["hosting_provider"]
            for tier, tier_data in self.cfg.hosting_providers.items():
                if provider in tier_data.get("signatures", {}):
                    hosting_result = {
                        "provider": provider,
                        "tier": tier,
                        "cost_range": tier_data.get("cost_range"),
                    }
                    break

        # Idaho SOS
        sos_result = self.sos.lookup(business["name"])

        # Chain detection
        cats = business.get("gbp_categories") or []
        if isinstance(cats, str):
            try:
                cats = json.loads(cats)
            except Exception:
                cats = []
        chain = self.chains.is_chain(business["name"], cats)

        # Review signals
        raw = business.get("raw_data")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        review_signals = self.reviews.analyze(raw)

        # Score
        result = self.scorer.score(
            business=business,
            audit=audit,
            web_check=web_result,
            sos=sos_result,
            is_chain=chain,
            review_signals=review_signals,
            hosting=hosting_result,
        )

        # Determine if middle band (for skill to process with Haiku)
        is_middle = self.scorer.is_middle_band(result["score"])

        return {
            "business_id": business["id"],
            "business_name": business["name"],
            "winnow_score": result["score"],
            "decision": result["decision"],
            "is_middle_band": is_middle,
            "score_breakdown": result["breakdown"],
            "reasoning_summary": result["reasoning_summary"],
            "website_reachable": web_result.get("reachable"),
            "website_final_url": web_result.get("final_url"),
            "site_quality_score": web_result.get("quality_score"),
            "sos_status": sos_result.get("status"),
            "sos_registered_at": sos_result.get("registered_at"),
            "sos_entity_type": sos_result.get("entity_type"),
            "review_velocity_90d": review_signals.get("velocity_90d"),
            "review_trend": review_signals.get("trend"),
            "is_chain": chain,
            "hosting_provider": hosting_result.get("provider"),
            "hosting_tier": hosting_result.get("tier"),
            # Include raw data for Haiku (middle band)
            "_review_snippet": self._extract_review_snippet(raw),
            "_website_url": business.get("website_url") or "",
            "_is_chain": chain,
            "_website_head_snippet": (web_result.get("head_html") or "SCRAPE_FAILED")[:500],
        }

    def _extract_review_snippet(self, raw_data: dict | None) -> str:
        """Extract up to 3 recent review texts for Haiku enrichment."""
        if not raw_data:
            return ""
        reviews = raw_data.get("reviews", [])[:3]
        snippets = []
        for r in reviews:
            raw_text = r.get("text") or r.get("textOriginalLanguage") or ""
            # Google Places v1 API: text may be a dict {"text": "...", "languageCode": "..."}
            if isinstance(raw_text, dict):
                raw_text = raw_text.get("text", "")
            text = str(raw_text) if raw_text else ""
            if text:
                snippets.append(text[:200])
        return " | ".join(snippets)

    # ── Write ────────────────────────────────────────────────────────

    def write_run(self, run_id: str, counts: dict, config_snapshot: dict, filter_query: str | None) -> None:
        if self.dry_run:
            return
        data = {
            "id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "batch_size_requested": counts.get("requested"),
            "businesses_evaluated": counts.get("evaluated", 0),
            "identified_count": counts.get("identified", 0),
            "skipped_count": counts.get("skipped", 0),
            "closed_count": counts.get("closed", 0),
            "middle_band_count": counts.get("middle_band", 0),
            "errors_count": counts.get("errors", 0),
            "filter_query": filter_query,
            "config_snapshot": config_snapshot,
            "run_by": "claude-code",
        }
        self.db.post("wpa_winnow_runs", data)

    def write_decision(self, decision: dict, run_id: str) -> None:
        if self.dry_run:
            return
        row = {
            "business_id": decision["business_id"],
            "run_id": run_id,
            "winnow_score": decision["winnow_score"],
            "decision": decision["decision"],
            "website_reachable": decision.get("website_reachable"),
            "website_final_url": decision.get("website_final_url"),
            "site_quality_score": decision.get("site_quality_score"),
            "sos_status": decision.get("sos_status"),
            "sos_registered_at": decision.get("sos_registered_at"),
            "sos_entity_type": decision.get("sos_entity_type"),
            "review_velocity_90d": decision.get("review_velocity_90d"),
            "review_trend": decision.get("review_trend"),
            "is_chain": decision.get("is_chain", False),
            "score_breakdown": decision.get("score_breakdown"),
            "reasoning_summary": decision.get("reasoning_summary"),
        }
        # Remove None values
        row = {k: v for k, v in row.items() if v is not None}
        self.db.post("wpa_winnow_decisions", row)

    def update_business_status(self, business_id: str, status: str) -> None:
        if self.dry_run:
            return
        self.db.patch("wpa_businesses", f"id=eq.{business_id}", {"contact_status": status})

    def finalize_run(self, run_id: str, counts: dict | None = None) -> None:
        if self.dry_run:
            return
        update = {"finished_at": datetime.now(timezone.utc).isoformat()}
        if counts:
            update["businesses_evaluated"] = counts.get("evaluated", 0)
            update["identified_count"] = counts.get("identified", 0)
            update["skipped_count"] = counts.get("skipped", 0)
            update["closed_count"] = counts.get("closed", 0)
            update["middle_band_count"] = counts.get("middle_band", 0)
            update["errors_count"] = counts.get("errors", 0)
        self.db.patch("wpa_winnow_runs", f"id=eq.{run_id}", update)

    # ── Pipeline ──────────────────────────────────────────────────────

    def run_batch(self, batch_size: int, search_query: str | None = None) -> dict:
        """Run full batch. Returns summary dict for skill."""
        run_id = str(uuid.uuid4())
        businesses = self.fetch_batch(batch_size, search_query)
        eprint(f"\n[Winnow] Batch of {len(businesses)} businesses (run {run_id[:8]}...)")

        if self.dry_run:
            eprint("[Winnow] DRY RUN — no writes")

        counts = {"requested": batch_size, "evaluated": 0, "identified": 0, "skipped": 0, "closed": 0, "middle_band": 0, "errors": 0}
        decisions = []

        # Write run header
        self.write_run(run_id, counts, self.cfg.snapshot(), search_query)

        for biz in businesses:
            try:
                decision = self.evaluate(biz)
                decisions.append(decision)
                counts["evaluated"] += 1

                if decision["is_middle_band"]:
                    counts["middle_band"] += 1
                    eprint(f"    → MIDDLE BAND (score={decision['winnow_score']})")
                elif decision["decision"] == "IDENTIFIED":
                    counts["identified"] += 1
                    eprint(f"    → IDENTIFIED (score={decision['winnow_score']})")
                    self.write_decision(decision, run_id)
                    self.update_business_status(biz["id"], "IDENTIFIED")
                elif decision["decision"] == "CLOSED":
                    counts["closed"] += 1
                    eprint(f"    → CLOSED (score={decision['winnow_score']})")
                    self.write_decision(decision, run_id)
                else:
                    counts["skipped"] += 1
                    eprint(f"    → SKIP (score={decision['winnow_score']})")
                    self.write_decision(decision, run_id)

            except Exception as e:
                eprint(f"    ERROR evaluating {biz.get('name')}: {e}")
                counts["errors"] += 1

        self.finalize_run(run_id, counts)

        return {
            "run_id": run_id,
            "dry_run": self.dry_run,
            "counts": counts,
            "decisions": decisions,
        }

    def run_single(self, place_id: str) -> dict:
        """Evaluate a single business."""
        run_id = str(uuid.uuid4())
        biz = self.fetch_single(place_id)
        if not biz:
            return {"error": f"Business not found: {place_id}"}

        decision = self.evaluate(biz)
        if not self.dry_run:
            self.write_run(run_id, {"requested": 1, "evaluated": 1}, self.cfg.snapshot(), None)
            self.write_decision(decision, run_id)
            if decision["decision"] == "IDENTIFIED":
                self.update_business_status(place_id, "IDENTIFIED")
            self.finalize_run(run_id)

        return {
            "run_id": run_id,
            "dry_run": self.dry_run,
            "decisions": [decision],
        }

    def status(self) -> dict:
        """Show pipeline counts."""
        status_counts = {}
        for status in ("NEW", "IDENTIFIED", "CONTACTED", "REPLIED", "CLOSED", "CLOSED-WON"):
            rows = self.db.get("wpa_businesses", {"contact_status": f"eq.{status}", "select": "id"})
            status_counts[status] = len(rows)

        decision_counts = self.db.get("wpa_winnow_decisions", {"select": "decision"})
        by_decision = {}
        for row in decision_counts:
            d = row["decision"]
            by_decision[d] = by_decision.get(d, 0) + 1

        total = sum(status_counts.values())
        winnowed = sum(by_decision.values())
        new_remaining = status_counts.get("NEW", 0) - winnowed  # approximate

        return {
            "business_status_counts": status_counts,
            "winnow_decision_counts": by_decision,
            "total_businesses": total,
            "total_winnowed": winnowed,
            "new_unwinnowed_approx": max(0, new_remaining),
        }


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Winnow: WPA lead qualification engine")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--batch", type=int, metavar="N", help="Process N businesses")
    group.add_argument("--single", metavar="PLACE_ID", help="Evaluate one business by Place ID")
    group.add_argument("--status", action="store_true", help="Show pipeline counts")
    parser.add_argument("--query", metavar="SEARCH_QUERY", help="Filter by search_query (with --batch)")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without writing to DB")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print(json.dumps({"error": "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set"}))
        sys.exit(1)

    config = WinnowConfig()
    engine = WinnowEngine(config, dry_run=args.dry_run)

    if args.status:
        result = engine.status()
    elif args.single:
        result = engine.run_single(args.single)
    else:
        result = engine.run_batch(args.batch, args.query)

    # Output JSON to stdout for skill parsing
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
