"""Report generation module for Schema Audit Lead Generator.

Generates professional HTML audit reports and corrected JSON-LD schema
for prospect businesses.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from analyzer import GBP_TO_SCHEMA_TYPES
from config import REPORTS_DIR, TEMPLATES_DIR
from db import Audit, Business


class ReportGenerator:
    """Generate HTML audit reports and corrected JSON-LD schemas."""

    def __init__(self) -> None:
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=True,
        )
        self.template = self.jinja_env.get_template("audit_report.html")

    # ------------------------------------------------------------------
    # Corrected Schema
    # ------------------------------------------------------------------

    def generate_corrected_schema(
        self,
        business: Business,
        gbp_categories: list[str],
    ) -> dict:
        """Create an ideal LocalBusiness JSON-LD using business data from Google Places.

        Builds a complete, valid schema.org LocalBusiness block with:
        - Best-fit @type derived from GBP categories
        - Parsed postal address components
        - Telephone, URL, and sameAs (Google Maps link)
        """
        schema_type = self._determine_schema_type(gbp_categories)

        # Parse address into components by splitting on comma
        address_obj = self._parse_address(business.address)

        schema: dict = {
            "@context": "https://schema.org",
            "@type": schema_type,
            "name": business.name,
        }

        if address_obj:
            schema["address"] = address_obj

        if business.phone:
            schema["telephone"] = business.phone

        if business.website_url:
            schema["url"] = business.website_url

        # sameAs: link to Google Maps via place_id
        if business.id:
            maps_url = self._get_google_maps_url(business.id)
            schema["sameAs"] = [maps_url]

        return schema

    # ------------------------------------------------------------------
    # HTML Report
    # ------------------------------------------------------------------

    def generate_html_report(
        self,
        business: Business,
        audit: Audit,
        corrected_schema: dict,
    ) -> str:
        """Render HTML report using Jinja2 template. Returns HTML string."""
        score_color = self._get_score_color(audit.score)
        lead_quality = self._get_lead_quality(audit.score)
        quality_bg, quality_color = self._get_quality_colors(audit.score)
        corrected_schema_json = json.dumps(corrected_schema, indent=2, ensure_ascii=False)

        html = self.template.render(
            business=business,
            audit=audit,
            corrected_schema_json=corrected_schema_json,
            score_color=score_color,
            lead_quality=lead_quality,
            quality_bg=quality_bg,
            quality_color=quality_color,
        )
        return html

    # ------------------------------------------------------------------
    # File Output
    # ------------------------------------------------------------------

    def save_report(
        self,
        business: Business,
        html_content: str,
        corrected_schema: dict,
    ) -> tuple[str, str]:
        """Save HTML report and JSON schema to files in reports/ dir.

        Returns:
            (html_path, json_path) as absolute path strings.
        """
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        slug = self._slugify(business.name)
        date_stamp = datetime.utcnow().strftime("%Y-%m-%d")

        html_filename = f"{date_stamp}_{slug}_audit.html"
        json_filename = f"{date_stamp}_{slug}_schema.json"

        html_path = REPORTS_DIR / html_filename
        json_path = REPORTS_DIR / json_filename

        html_path.write_text(html_content, encoding="utf-8")
        json_path.write_text(
            json.dumps(corrected_schema, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return str(html_path), str(json_path)

    # ------------------------------------------------------------------
    # Score / quality helpers
    # ------------------------------------------------------------------

    def _get_score_color(self, score: int) -> str:
        """Return CSS color for the score badge."""
        if score <= 2:
            return "#ef4444"  # red
        if score == 3:
            return "#f59e0b"  # orange
        return "#10b981"  # green

    def _get_lead_quality(self, score: int) -> str:
        """Return human-readable quality label for the prospect."""
        if score <= 2:
            return "Needs Attention"
        if score == 3:
            return "Moderate Issues"
        return "Well Optimized"

    def _get_quality_colors(self, score: int) -> tuple[str, str]:
        """Return (background_color, text_color) for the quality badge."""
        if score <= 2:
            return ("#fef2f2", "#dc2626")  # light red bg, red text
        if score == 3:
            return ("#fffbeb", "#d97706")  # light amber bg, amber text
        return ("#f0fdf4", "#059669")  # light green bg, green text

    # ------------------------------------------------------------------
    # Schema type mapping
    # ------------------------------------------------------------------

    def _determine_schema_type(self, gbp_categories: list[str]) -> str:
        """Map GBP categories to the best schema.org @type.

        Uses the same GBP_TO_SCHEMA_TYPES mapping from the analyzer.
        Returns the first specific type found, or 'LocalBusiness' as default.
        """
        for category in gbp_categories:
            mapped_types = GBP_TO_SCHEMA_TYPES.get(category, [])
            if mapped_types:
                return mapped_types[0]  # Take the most specific type
        return "LocalBusiness"

    # ------------------------------------------------------------------
    # Address parsing
    # ------------------------------------------------------------------

    def _parse_address(self, address: str) -> dict | None:
        """Parse a comma-separated address string into a PostalAddress dict.

        Expected format: "123 Main St, City, State ZIP, Country"
        Handles varying numbers of comma-separated components.
        """
        if not address or not address.strip():
            return None

        parts = [p.strip() for p in address.split(",") if p.strip()]

        address_obj: dict = {
            "@type": "PostalAddress",
        }

        if len(parts) >= 1:
            address_obj["streetAddress"] = parts[0]

        if len(parts) >= 2:
            address_obj["addressLocality"] = parts[1]

        if len(parts) >= 3:
            # Third part often contains "State ZIP" or just "State"
            state_zip = parts[2].strip()
            # Try to split state and postal code (e.g. "CO 80521" or "Colorado 80521")
            state_zip_match = re.match(r"^(.+?)\s+(\d{5}(?:-\d{4})?)$", state_zip)
            if state_zip_match:
                address_obj["addressRegion"] = state_zip_match.group(1).strip()
                address_obj["postalCode"] = state_zip_match.group(2)
            else:
                address_obj["addressRegion"] = state_zip

        if len(parts) >= 4:
            # Fourth part is usually country or additional region info
            last_part = parts[3].strip()
            # If we didn't extract postal code yet, check if this is one
            if "postalCode" not in address_obj and re.match(r"^\d{5}(?:-\d{4})?$", last_part):
                address_obj["postalCode"] = last_part
            else:
                address_obj["addressCountry"] = last_part

        return address_obj

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _get_google_maps_url(self, place_id: str) -> str:
        """Return a Google Maps URL for the given place_id."""
        return f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    def _slugify(self, text: str) -> str:
        """Convert text to a URL/filename-safe slug."""
        slug = text.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)  # remove special chars
        slug = re.sub(r"[\s_]+", "-", slug)  # spaces/underscores to hyphens
        slug = re.sub(r"-+", "-", slug)  # collapse multiple hyphens
        slug = slug.strip("-")
        return slug
