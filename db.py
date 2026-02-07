"""Database layer for Schema Audit Lead Generator."""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


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
    

@dataclass
class Report:
    """Generated audit report for a business."""

    business_id: str
    corrected_schema: dict = field(default_factory=dict)
    html_report: str = ""
    report_path: str = ""
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    id: int | None = None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    """SQLite wrapper for lead management."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        self._migrate_tables()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _migrate_tables(self) -> None:
        """Run necessary migrations."""
        try:
            self.conn.execute("ALTER TABLE businesses ADD COLUMN contact_status TEXT NOT NULL DEFAULT 'NEW'")
        except sqlite3.OperationalError:
            pass  # contact_status already exists

        try:
            self.conn.execute("ALTER TABLE businesses ADD COLUMN discovery_rank INTEGER")
        except sqlite3.OperationalError:
            pass  # discovery_rank already exists

        try:
            self.conn.execute("ALTER TABLE businesses ADD COLUMN rank_total_candidates INTEGER")
        except sqlite3.OperationalError:
            pass  # rank_total_candidates already exists

        try:
            self.conn.execute("ALTER TABLE businesses ADD COLUMN google_maps_uri TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # google_maps_uri already exists

        try:
            self.conn.execute("ALTER TABLE businesses ADD COLUMN business_status TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # business_status already exists

        try:
            self.conn.execute("ALTER TABLE businesses ADD COLUMN rating REAL")
        except sqlite3.OperationalError:
            pass  # rating already exists

        try:
            self.conn.execute("ALTER TABLE businesses ADD COLUMN user_rating_count INTEGER")
        except sqlite3.OperationalError:
            pass  # user_rating_count already exists

        try:
            self.conn.execute("ALTER TABLE businesses ADD COLUMN raw_data TEXT")
        except sqlite3.OperationalError:
            pass  # raw_data already exists

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS businesses (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                address         TEXT NOT NULL DEFAULT '',
                phone           TEXT NOT NULL DEFAULT '',
                website_url     TEXT NOT NULL DEFAULT '',
                gbp_categories  TEXT NOT NULL DEFAULT '[]',
                search_query    TEXT NOT NULL DEFAULT '',
                discovered_at   TEXT NOT NULL,
                contact_status  TEXT NOT NULL DEFAULT 'NEW',
                discovery_rank  INTEGER,
                discovery_rank  INTEGER,
                rank_total_candidates INTEGER,
                google_maps_uri TEXT NOT NULL DEFAULT '',
                business_status TEXT NOT NULL DEFAULT '',
                rating          REAL,
                user_rating_count INTEGER,
                raw_data        TEXT
            );

            CREATE TABLE IF NOT EXISTS audits (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id         TEXT NOT NULL REFERENCES businesses(id),
                has_schema          INTEGER NOT NULL DEFAULT 0,
                has_sameas          INTEGER NOT NULL DEFAULT 0,
                category_aligned    INTEGER NOT NULL DEFAULT 0,
                nap_consistent      INTEGER NOT NULL DEFAULT 0,
                mobile_speed_score  INTEGER,
                mobile_lcp          REAL,
                raw_schema          TEXT,
                issues              TEXT NOT NULL DEFAULT '[]',
                score               INTEGER NOT NULL DEFAULT 0,
                audited_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_audits_business_id
                ON audits(business_id);

            CREATE TABLE IF NOT EXISTS reports (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id       TEXT NOT NULL REFERENCES businesses(id),
                corrected_schema  TEXT NOT NULL DEFAULT '{}',
                html_report       TEXT NOT NULL DEFAULT '',
                report_path       TEXT NOT NULL DEFAULT '',
                generated_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reports_business_id
                ON reports(business_id);
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Business CRUD
    # ------------------------------------------------------------------

    def insert_business(self, business: Business) -> None:
        """Insert a business, ignoring duplicates (by place_id)."""
        self.conn.execute(
            """
            INSERT OR IGNORE INTO businesses
                (id, name, address, phone, website_url,
                 gbp_categories, search_query, discovered_at, contact_status,
                 discovery_rank, rank_total_candidates,
                 google_maps_uri, business_status, rating, user_rating_count, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                business.id,
                business.name,
                business.address,
                business.phone,
                business.website_url,
                json.dumps(business.gbp_categories),
                business.search_query,
                business.discovered_at,
                business.contact_status,
                business.discovery_rank,
                business.rank_total_candidates,
                business.google_maps_uri,
                business.business_status,
                business.rating,
                business.user_rating_count,
                json.dumps(business.raw_data) if business.raw_data else None,
            ),
        )
        self.conn.commit()

    def get_business(self, business_id: str) -> Business | None:
        """Retrieve a single business by place_id."""
        row = self.conn.execute(
            "SELECT * FROM businesses WHERE id = ?", (business_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_business(row)

    def get_all_businesses(self) -> list[Business]:
        """Return every business in the database."""
        rows = self.conn.execute(
            "SELECT * FROM businesses ORDER BY discovered_at DESC"
        ).fetchall()
        return [self._row_to_business(r) for r in rows]

    def get_businesses_without_audit(self) -> list[Business]:
        """Return businesses that have no audit record yet."""
        rows = self.conn.execute(
            """
            SELECT b.*
            FROM businesses b
            LEFT JOIN audits a ON b.id = a.business_id
            WHERE a.id IS NULL
            ORDER BY b.discovered_at DESC
            """
        ).fetchall()
        return [self._row_to_business(r) for r in rows]

    def search_businesses_by_url(self, url: str) -> Business | None:
        """Find a business whose website_url matches (exact)."""
        row = self.conn.execute(
            "SELECT * FROM businesses WHERE website_url = ?", (url,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_business(row)

    def update_business_status(self, business_id: str, status: str) -> bool:
        """Update the contact status of a business."""
        cur = self.conn.execute(
            "UPDATE businesses SET contact_status = ? WHERE id = ?",
            (status, business_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Audit CRUD
    # ------------------------------------------------------------------

    def insert_audit(self, audit: Audit) -> int:
        """Insert an audit and return its row id."""
        cur = self.conn.execute(
            """
            INSERT INTO audits
                (business_id, has_schema, has_sameas, category_aligned,
                 nap_consistent, mobile_speed_score, mobile_lcp,
                 raw_schema, issues, score, audited_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit.business_id,
                int(audit.has_schema),
                int(audit.has_sameas),
                int(audit.category_aligned),
                int(audit.nap_consistent),
                audit.mobile_speed_score,
                audit.mobile_lcp,
                json.dumps(audit.raw_schema) if audit.raw_schema else None,
                json.dumps(audit.issues),
                audit.score,
                audit.audited_at,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_audit(self, business_id: str) -> Audit | None:
        """Return the most recent audit for a business."""
        row = self.conn.execute(
            """
            SELECT * FROM audits
            WHERE business_id = ?
            ORDER BY audited_at DESC
            LIMIT 1
            """,
            (business_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_audit(row)

    def get_hot_leads(self, max_score: int = 2) -> list[tuple[Business, Audit]]:
        """Return businesses with audit score <= max_score (hot leads)."""
        rows = self.conn.execute(
            """
            SELECT b.*, a.id AS audit_id, a.business_id AS a_business_id,
                   a.has_schema, a.has_sameas, a.category_aligned,
                   a.nap_consistent, a.mobile_speed_score, a.mobile_lcp,
                   a.raw_schema, a.issues, a.score, a.audited_at
            FROM businesses b
            JOIN audits a ON b.id = a.business_id
            WHERE a.score <= ?
            AND a.id = (
                SELECT MAX(a2.id) FROM audits a2
                WHERE a2.business_id = b.id
            )
            ORDER BY a.score ASC, b.name ASC
            """,
            (max_score,),
        ).fetchall()
        results: list[tuple[Business, Audit]] = []
        for row in rows:
            business = self._row_to_business(row)
            audit = Audit(
                id=row["audit_id"],
                business_id=row["a_business_id"],
                has_schema=bool(row["has_schema"]),
                has_sameas=bool(row["has_sameas"]),
                category_aligned=bool(row["category_aligned"]),
                nap_consistent=bool(row["nap_consistent"]),
                mobile_speed_score=row["mobile_speed_score"],
                mobile_lcp=row["mobile_lcp"],
                raw_schema=json.loads(row["raw_schema"]) if row["raw_schema"] else None,
                issues=json.loads(row["issues"]),
                score=row["score"],
                audited_at=row["audited_at"],
            )
            results.append((business, audit))
        return results

    # ------------------------------------------------------------------
    # Report CRUD
    # ------------------------------------------------------------------

    def insert_report(self, report: Report) -> int:
        """Insert a report and return its row id."""
        cur = self.conn.execute(
            """
            INSERT INTO reports
                (business_id, corrected_schema, html_report,
                 report_path, generated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                report.business_id,
                json.dumps(report.corrected_schema),
                report.html_report,
                report.report_path,
                report.generated_at,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_report(self, business_id: str) -> Report | None:
        """Return the most recent report for a business."""
        row = self.conn.execute(
            """
            SELECT * FROM reports
            WHERE business_id = ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (business_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_report(row)

    # ------------------------------------------------------------------
    # Pipeline stats
    # ------------------------------------------------------------------

    def get_pipeline_stats(self) -> dict:
        """Return summary statistics for the lead pipeline."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM businesses"
        ).fetchone()[0]

        audited = self.conn.execute(
            """
            SELECT COUNT(DISTINCT business_id) FROM audits
            """
        ).fetchone()[0]

        unaudited = total - audited

        # Score buckets (using most recent audit per business)
        score_rows = self.conn.execute(
            """
            SELECT a.score, COUNT(*) AS cnt
            FROM audits a
            WHERE a.id = (
                SELECT MAX(a2.id) FROM audits a2
                WHERE a2.business_id = a.business_id
            )
            GROUP BY a.score
            """
        ).fetchall()

        score_counts: dict[int, int] = {row["score"]: row["cnt"] for row in score_rows}

        hot_leads = sum(v for k, v in score_counts.items() if k <= 2)
        warm_leads = sum(v for k, v in score_counts.items() if k in (3, 4))
        cold_leads = sum(v for k, v in score_counts.items() if k >= 5)

        reports_generated = self.conn.execute(
            "SELECT COUNT(DISTINCT business_id) FROM reports"
        ).fetchone()[0]

        return {
            "total_businesses": total,
            "audited_count": audited,
            "unaudited_count": unaudited,
            "hot_leads": hot_leads,
            "warm_leads": warm_leads,
            "cold_leads": cold_leads,
            "reports_generated": reports_generated,
        }

    # ------------------------------------------------------------------
    # Row converters
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_business(row: sqlite3.Row) -> Business:
        # Handle potential missing new columns during migration/lazy loading
        discovery_rank = None
        if "discovery_rank" in row.keys():
            discovery_rank = row["discovery_rank"]
            
        rank_total_candidates = None
        if "rank_total_candidates" in row.keys():
            rank_total_candidates = row["rank_total_candidates"]

        return Business(
            id=row["id"],
            name=row["name"],
            address=row["address"],
            phone=row["phone"],
            website_url=row["website_url"],
            gbp_categories=json.loads(row["gbp_categories"]),
            search_query=row["search_query"],
            discovered_at=row["discovered_at"],
            contact_status=row["contact_status"] if "contact_status" in row.keys() else "NEW",
            discovery_rank=discovery_rank,
            rank_total_candidates=rank_total_candidates,
            google_maps_uri=row["google_maps_uri"] if "google_maps_uri" in row.keys() else "",
            business_status=row["business_status"] if "business_status" in row.keys() else "",
            rating=row["rating"] if "rating" in row.keys() else None,
            user_rating_count=row["user_rating_count"] if "user_rating_count" in row.keys() else None,
            raw_data=json.loads(row["raw_data"]) if "raw_data" in row.keys() and row["raw_data"] else None,
        )

    @staticmethod
    def _row_to_audit(row: sqlite3.Row) -> Audit:
        return Audit(
            id=row["id"],
            business_id=row["business_id"],
            has_schema=bool(row["has_schema"]),
            has_sameas=bool(row["has_sameas"]),
            category_aligned=bool(row["category_aligned"]),
            nap_consistent=bool(row["nap_consistent"]),
            mobile_speed_score=row["mobile_speed_score"],
            mobile_lcp=row["mobile_lcp"],
            raw_schema=json.loads(row["raw_schema"]) if row["raw_schema"] else None,
            issues=json.loads(row["issues"]),
            score=row["score"],
            audited_at=row["audited_at"],
        )

    @staticmethod
    def _row_to_report(row: sqlite3.Row) -> Report:
        return Report(
            id=row["id"],
            business_id=row["business_id"],
            corrected_schema=json.loads(row["corrected_schema"]),
            html_report=row["html_report"],
            report_path=row["report_path"],
            generated_at=row["generated_at"],
        )

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
