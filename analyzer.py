"""Analysis module for Schema Audit Lead Generator.

Runs a 5-point audit against a business website:
  1. Schema exists (LocalBusiness JSON-LD present)
  2. sameAs links to Google Maps / Apple Maps
  3. Category alignment between GBP types and schema @type
  4. NAP (Name, Address, Phone) consistency between GBP and schema
  5. Mobile page speed (via PageSpeed Insights API)
"""

import os
import re
import sys
from dataclasses import dataclass, field

import requests

sys.path.insert(0, os.path.expanduser("~/cost-logs"))
from cost_logger import log_api_call

from config import (
    GOOGLE_PLACES_API_KEY,
    MAX_LCP_SECONDS,
    PAGESPEED_API_KEY,
    PAGESPEED_API_URL,
    PASSING_MOBILE_SCORE,
)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class AuditResult:
    """Result of a 5-point schema audit."""

    has_schema: bool
    has_sameas: bool
    category_aligned: bool
    nap_consistent: bool
    mobile_speed_score: int | None
    mobile_lcp: float | None
    raw_schema: dict | None
    issues: list[str] = field(default_factory=list)
    score: int = 0  # 0-5 (number of checks PASSED)


# ---------------------------------------------------------------------------
# GBP type -> schema.org @type mapping
# ---------------------------------------------------------------------------

GBP_TO_SCHEMA_TYPES: dict[str, list[str]] = {
    # Home services / trades
    "plumber": ["Plumber", "PlumbingService"],
    "electrician": ["Electrician", "ElectricalService"],
    "hvac_contractor": ["HVACBusiness"],
    "general_contractor": ["GeneralContractor", "HomeAndConstructionBusiness"],
    "roofing_contractor": ["RoofingContractor"],
    "locksmith": ["Locksmith"],
    "moving_company": ["MovingCompany"],
    "painter": ["HousePainter"],
    "carpet_cleaning_service": ["ProfessionalService"],
    "handyman": ["HomeAndConstructionBusiness", "ProfessionalService"],
    "landscaper": ["ProfessionalService"],
    "pest_control_service": ["ProfessionalService"],
    "tree_service": ["ProfessionalService"],
    "window_cleaning_service": ["ProfessionalService"],

    # Legal / Professional
    "lawyer": ["LegalService", "Attorney"],
    "accounting": ["AccountingService"],
    "insurance_agency": ["InsuranceAgency"],
    "real_estate_agent": ["RealEstateAgent"],
    "real_estate_agency": ["RealEstateAgent"],
    "financial_planner": ["FinancialService"],
    "tax_preparation_service": ["AccountingService", "ProfessionalService"],
    "notary_public": ["Notary"],
    "employment_agency": ["EmploymentAgency"],
    "consultant": ["ProfessionalService"],

    # Medical / Health
    "dentist": ["Dentist"],
    "doctor": ["Physician", "MedicalBusiness"],
    "hospital": ["MedicalClinic", "MedicalOrganization"],
    "pharmacy": ["Pharmacy"],
    "veterinary_care": ["Veterinarian"],
    "optometrist": ["Optician"],
    "chiropractor": ["MedicalBusiness", "Physician"],
    "physiotherapist": ["MedicalBusiness"],
    "psychologist": ["MedicalBusiness", "ProfessionalService"],

    # Beauty / Wellness
    "beauty_salon": ["BeautySalon", "HealthAndBeautyBusiness"],
    "hair_salon": ["HairSalon", "HealthAndBeautyBusiness"],
    "nail_salon": ["NailSalon", "HealthAndBeautyBusiness"],
    "spa": ["DaySpa", "HealthAndBeautyBusiness"],
    "gym": ["ExerciseGym", "HealthClub"],
    "yoga_studio": ["ExerciseGym", "SportsActivityLocation"],
    "tattoo_shop": ["TattooParlor"],
    "barber_shop": ["HairSalon", "HealthAndBeautyBusiness"],

    # Automotive
    "auto_repair": ["AutoRepair"],
    "car_dealer": ["AutoDealer"],
    "car_rental": ["AutoRental"],
    "car_wash": ["AutoWash"],
    "gas_station": ["GasStation"],
    "tire_shop": ["TireShop"],
    "auto_parts_store": ["AutoPartsStore"],

    # Food / Drink
    "restaurant": ["Restaurant", "FoodEstablishment"],
    "cafe": ["CafeOrCoffeeShop"],
    "bar": ["BarOrPub"],
    "bakery": ["Bakery"],
    "fast_food_restaurant": ["FastFoodRestaurant"],
    "ice_cream_shop": ["IceCreamShop"],
    "meal_delivery": ["FoodEstablishment"],
    "meal_takeaway": ["FoodEstablishment"],

    # Retail
    "store": ["Store"],
    "clothing_store": ["ClothingStore"],
    "convenience_store": ["ConvenienceStore"],
    "electronics_store": ["ElectronicsStore"],
    "florist": ["Florist"],
    "furniture_store": ["FurnitureStore"],
    "grocery_store": ["GroceryStore", "GroceryOrSupermarket"],
    "hardware_store": ["HardwareStore"],
    "home_goods_store": ["HomeGoodsStore"],
    "jewelry_store": ["JewelryStore"],
    "liquor_store": ["LiquorStore"],
    "pet_store": ["PetStore"],
    "shoe_store": ["ShoeStore"],
    "shopping_mall": ["ShoppingCenter"],
    "sporting_goods_store": ["SportingGoodsStore"],
    "book_store": ["Store"],

    # Lodging
    "hotel": ["Hotel", "LodgingBusiness"],
    "motel": ["Motel", "LodgingBusiness"],
    "bed_and_breakfast": ["BedAndBreakfast", "LodgingBusiness"],
    "campground": ["LodgingBusiness"],
    "lodging": ["LodgingBusiness"],

    # Other services
    "child_care_agency": ["ChildCare"],
    "dry_cleaner": ["DryCleaningOrLaundry"],
    "laundry": ["DryCleaningOrLaundry"],
    "storage": ["SelfStorage"],
    "travel_agency": ["TravelAgency"],
    "funeral_home": ["LocalBusiness"],
    "church": ["LocalBusiness"],
    "cemetery": ["LocalBusiness"],
    "animal_shelter": ["AnimalShelter"],
}

# Lenient types: if the schema has any of these, it's a partial match
_LENIENT_TYPES = {"LocalBusiness", "ProfessionalService", "Organization"}


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class SchemaAnalyzer:
    """Runs the 5-point schema audit."""

    # ------------------------------------------------------------------ #
    # Orchestrator
    # ------------------------------------------------------------------ #

    def run_full_audit(
        self,
        website_url: str,
        schemas: list[dict],
        gbp_data: dict,
    ) -> AuditResult:
        """Run all 5 checks and return an AuditResult.

        Args:
            website_url: The homepage URL of the business.
            schemas: List of LocalBusiness schema blocks (from extractor).
            gbp_data: Dict with keys: name, address, phone, types, primary_type.

        Returns:
            AuditResult with individual check results and overall score.
        """
        issues: list[str] = []
        score = 0

        # Check 1: Schema exists
        has_schema, msg = self.check_schema_exists(schemas)
        if not has_schema and msg:
            issues.append(msg)

        # Check 2: sameAs connection (auto-fail if no schema)
        if has_schema:
            has_sameas, msg = self.check_sameas_connection(schemas)
        else:
            has_sameas = False
            msg = "Missing sameAs link to Google Maps or Apple Maps profile (no schema found)"
        if not has_sameas and msg:
            issues.append(msg)

        # Check 3: Category alignment (auto-fail if no schema)
        if has_schema:
            category_aligned, msg = self.check_category_alignment(
                schemas,
                gbp_data.get("types", []),
                gbp_data.get("primary_type", ""),
            )
        else:
            category_aligned = False
            msg = "Category alignment cannot be checked (no schema found)"
        if not category_aligned and msg:
            issues.append(msg)

        # Entity trap: multi-service businesses with category weight problems
        if has_schema and gbp_data.get("primary_type") and gbp_data.get("types"):
            trap_issues = self._check_entity_trap(
                gbp_data.get("primary_type", ""),
                gbp_data.get("types", []),
            )
            issues.extend(trap_issues)

        # Check 4: NAP consistency (auto-fail if no schema)
        if has_schema:
            nap_consistent, msg = self.check_nap_consistency(
                schemas, gbp_data.get("address", ""), gbp_data.get("phone", "")
            )
        else:
            nap_consistent = False
            msg = "NAP consistency cannot be checked (no schema found)"
        if not nap_consistent and msg:
            issues.append(msg)

        # Check 5: Mobile speed (always runs)
        speed_ok, speed_score, lcp, msg = self.check_mobile_speed(website_url)
        if not speed_ok and msg:
            issues.append(msg)

        # Calculate score = number of PASSED checks
        for passed in (has_schema, has_sameas, category_aligned, nap_consistent, speed_ok):
            if passed:
                score += 1

        # Pick first schema block as representative raw_schema
        raw_schema = schemas[0] if schemas else None

        return AuditResult(
            has_schema=has_schema,
            has_sameas=has_sameas,
            category_aligned=category_aligned,
            nap_consistent=nap_consistent,
            mobile_speed_score=speed_score,
            mobile_lcp=lcp,
            raw_schema=raw_schema,
            issues=issues,
            score=score,
        )

    # ------------------------------------------------------------------ #
    # Check 1: Schema exists
    # ------------------------------------------------------------------ #

    def check_schema_exists(self, schemas: list[dict]) -> tuple[bool, str | None]:
        """Check whether at least one LocalBusiness schema block was found."""
        if len(schemas) > 0:
            return True, None
        return False, "No LocalBusiness schema found on homepage"

    # ------------------------------------------------------------------ #
    # Check 2: sameAs links
    # ------------------------------------------------------------------ #

    def check_sameas_connection(self, schemas: list[dict]) -> tuple[bool, str | None]:
        """Check whether any schema block has a sameAs link to Maps."""
        maps_patterns = (
            "google.com/maps",
            "maps.google.com",
            "maps.apple.com",
            "goo.gl/maps",
        )

        for schema in schemas:
            same_as = schema.get("sameAs")
            if same_as is None:
                continue
            # sameAs can be a string or a list
            if isinstance(same_as, str):
                same_as = [same_as]
            if isinstance(same_as, list):
                for url in same_as:
                    if isinstance(url, str):
                        url_lower = url.lower()
                        if any(pat in url_lower for pat in maps_patterns):
                            return True, None

        return False, "Missing sameAs link to Google Maps or Apple Maps profile"

    # ------------------------------------------------------------------ #
    # Check 3: Category alignment
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Check 3: Category alignment (primaryType-first)
    # ------------------------------------------------------------------ #

    def check_category_alignment(
        self,
        schemas: list[dict],
        gbp_types: list[str],
        primary_type: str = "",
    ) -> tuple[bool, str | None]:
        """Check whether schema @type aligns with GBP entity type.

        Uses primaryType (single definitive entity) when available.
        Falls back to types-list mapping when primaryType is absent.

        Three cases:
        1. primaryType present + matches schema @type → Pass
        2. primaryType present + mismatches → Fail (Entity mismatch)
        3. primaryType missing/generic:
           a. types array only generic tags → Fail (Identity crisis / SEO Emergency)
           b. types array has specific categories → Fall back to types-based logic
        """
        # Collect all schema @type values
        schema_types: set[str] = set()
        for schema in schemas:
            raw_type = schema.get("@type")
            if isinstance(raw_type, str):
                schema_types.add(raw_type)
            elif isinstance(raw_type, list):
                schema_types.update(raw_type)

        if not schema_types:
            return False, "Schema has no @type field to compare"

        # Generic/useless primaryType values
        _GENERIC_PRIMARY_TYPES = {
            "store", "establishment", "point_of_interest", "local_business", ""
        }

        # Generic GBP type tags that add no entity signal
        _GENERIC_GBP_TYPES = {
            "establishment", "point_of_interest", "store", "local_business_or_poi",
            "food", "premise", "geocode",
        }

        effective_primary = (primary_type or "").strip().lower().replace(" ", "_")

        # --- Case 1 & 2: primaryType is present and specific ---
        if effective_primary and effective_primary not in _GENERIC_PRIMARY_TYPES:
            # Map primaryType to expected schema.org types
            expected_types = set(GBP_TO_SCHEMA_TYPES.get(effective_primary, []))

            # Direct match
            if schema_types & expected_types:
                return True, None

            # Lenient match is intentionally DISABLED when primaryType is present.
            # A business with primaryType=roofing_contractor using ProfessionalService
            # on their website IS misaligned — that's the whole point of this check.

            # No match
            schema_str = ", ".join(sorted(schema_types))
            expected_str = ", ".join(sorted(expected_types)) if expected_types else effective_primary
            return False, (
                f"Entity mismatch: GBP primaryType is '{effective_primary}' but "
                f"schema @type is [{schema_str}] — "
                f"Google AI has low confidence in your category"
            )

        # --- Case 3: primaryType missing or generic ---
        specific_gbp_types = [t for t in gbp_types if t not in _GENERIC_GBP_TYPES]

        if not specific_gbp_types:
            # Case 3a: Only generic tags — SEO Emergency
            return False, (
                "Identity crisis: GBP has no specific entity type "
                "(only generic tags like 'establishment' or 'point_of_interest') — "
                "a simple category update could double visibility"
            )

        # Case 3b: Fall back to types-based mapping logic
        expected_types: set[str] = set()
        for gbp_type in specific_gbp_types:
            mapped = GBP_TO_SCHEMA_TYPES.get(gbp_type, [])
            expected_types.update(mapped)

        # Direct match
        if schema_types & expected_types:
            return True, None

        # Lenient match: LocalBusiness / ProfessionalService / Organization
        # (only allowed in fallback mode, not when primaryType is present)
        if schema_types & _LENIENT_TYPES:
            return True, None

        # No match
        found_str = ", ".join(sorted(schema_types))
        expected_str = ", ".join(sorted(expected_types)) if expected_types else ", ".join(specific_gbp_types)
        return False, (
            f"Schema @type mismatch: found [{found_str}] "
            f"but GBP types suggest [{expected_str}]"
        )

    # ------------------------------------------------------------------ #
    # Entity trap detection (informational, no score impact)
    # ------------------------------------------------------------------ #

    def _check_entity_trap(
        self,
        primary_type: str,
        gbp_types: list[str],
    ) -> list[str]:
        """Detect multi-service businesses with category weight problems.

        Returns a list of informational issue strings (empty if no trap found).
        These are appended to the audit issues but do NOT affect the score.

        Example: primaryType=hair_salon but types includes massage_therapist.
        Google ranks them as a salon first — massage is deprioritized.
        """
        _GENERIC_TYPES = {
            "establishment", "point_of_interest", "store", "local_business_or_poi",
            "food", "premise", "geocode",
        }

        effective_primary = primary_type.strip().lower().replace(" ", "_")
        if not effective_primary or effective_primary in _GENERIC_TYPES:
            return []

        # Find secondary service types that differ from primary
        secondary_types = [
            t for t in gbp_types
            if t != effective_primary and t not in _GENERIC_TYPES
        ]

        if not secondary_types:
            return []

        # Only flag if there are meaningful secondary service types
        # (skip infrastructure tags like "health" or "service_establishment")
        _INFRASTRUCTURE_TYPES = {
            "health", "service_establishment", "beauty_salon", "store",
            "food_establishment", "home_goods_store",
        }
        meaningful_secondary = [t for t in secondary_types if t not in _INFRASTRUCTURE_TYPES]

        if not meaningful_secondary:
            return []

        secondary_str = ", ".join(meaningful_secondary[:3])  # cap at 3 for readability
        return [
            f"Category weight: Google identifies you primarily as '{effective_primary}' — "
            f"secondary services ({secondary_str}) are deprioritized in search rankings. "
            f"Dedicated service-page schema can help capture this traffic."
        ]

    # ------------------------------------------------------------------ #
    # Check 4: NAP consistency
    # ------------------------------------------------------------------ #

    def check_nap_consistency(
        self,
        schemas: list[dict],
        gbp_address: str,
        gbp_phone: str,
    ) -> tuple[bool, str | None]:
        """Check that Name/Address/Phone in schema match GBP data."""
        # Extract address and phone from schema blocks
        schema_address = ""
        schema_phone = ""

        for schema in schemas:
            # Address
            if not schema_address:
                addr = schema.get("address")
                if isinstance(addr, dict):
                    schema_address = addr.get("streetAddress", "")
                    if not schema_address:
                        # Try building from parts
                        parts = []
                        for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode"):
                            v = addr.get(key, "")
                            if v:
                                parts.append(str(v))
                        schema_address = " ".join(parts)
                elif isinstance(addr, str):
                    schema_address = addr

            # Phone
            if not schema_phone:
                phone = schema.get("telephone")
                if isinstance(phone, str):
                    schema_phone = phone
                elif isinstance(phone, list) and phone:
                    schema_phone = str(phone[0])

        # Check if we found any address or phone in schema
        has_address = bool(schema_address.strip())
        has_phone = bool(schema_phone.strip())

        if not has_address and not has_phone:
            return False, "Schema has no address or phone fields"

        mismatches: list[str] = []

        # Compare phone (digits only)
        if gbp_phone and has_phone:
            gbp_digits = re.sub(r"\D", "", gbp_phone)
            schema_digits = re.sub(r"\D", "", schema_phone)
            if gbp_digits and schema_digits and gbp_digits != schema_digits:
                mismatches.append(
                    f"Phone mismatch: GBP={gbp_phone}, Schema={schema_phone}"
                )
        elif gbp_phone and not has_phone:
            mismatches.append("Schema is missing phone number")

        # Compare address (normalized substring matching)
        if gbp_address and has_address:
            norm_gbp = self._normalize_address(gbp_address)
            norm_schema = self._normalize_address(schema_address)
            # Substring match: one contains the other
            if norm_gbp and norm_schema:
                if norm_gbp not in norm_schema and norm_schema not in norm_gbp:
                    mismatches.append(
                        f"Address mismatch: GBP='{gbp_address}', Schema='{schema_address}'"
                    )
        elif gbp_address and not has_address:
            mismatches.append("Schema is missing address")

        if mismatches:
            return False, "; ".join(mismatches)

        return True, None

    @staticmethod
    def _normalize_address(address: str) -> str:
        """Normalize address for comparison: lowercase, strip punctuation, collapse spaces."""
        addr = address.lower()
        addr = re.sub(r"[^\w\s]", "", addr)  # remove punctuation
        addr = re.sub(r"\s+", " ", addr).strip()  # collapse whitespace
        return addr

    # ------------------------------------------------------------------ #
    # Check 5: Mobile page speed
    # ------------------------------------------------------------------ #

    def check_mobile_speed(
        self,
        url: str,
    ) -> tuple[bool, int | None, float | None, str | None]:
        """Check mobile performance via Google PageSpeed Insights.

        Returns:
            (passed, score_0_100, lcp_seconds, issue_message)
        """
        try:
            params: dict[str, str] = {
                "url": url,
                "strategy": "mobile",
                "category": "performance",
            }
            # Add API key if available to increase rate limits
            if PAGESPEED_API_KEY:
                params["key"] = PAGESPEED_API_KEY
            resp = requests.get(
                PAGESPEED_API_URL,
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            log_api_call("schema-audit", "google-pagespeed", "audit", calls=1)
            data = resp.json()

            # Extract performance score (0.0 - 1.0 -> 0 - 100)
            perf_score_raw = (
                data.get("lighthouseResult", {})
                .get("categories", {})
                .get("performance", {})
                .get("score")
            )
            if perf_score_raw is None:
                return False, None, None, "Unable to extract performance score from PageSpeed"

            score = int(perf_score_raw * 100)

            # Extract LCP (milliseconds -> seconds)
            lcp_ms = (
                data.get("lighthouseResult", {})
                .get("audits", {})
                .get("largest-contentful-paint", {})
                .get("numericValue")
            )
            lcp_seconds = round(lcp_ms / 1000, 2) if lcp_ms is not None else None

            # Evaluate pass/fail
            passed = score >= PASSING_MOBILE_SCORE and (
                lcp_seconds is not None and lcp_seconds <= MAX_LCP_SECONDS
            )

            if passed:
                return True, score, lcp_seconds, None

            # Build failure message
            parts: list[str] = []
            if score < PASSING_MOBILE_SCORE:
                parts.append(f"Mobile performance score {score}/100 (needs {PASSING_MOBILE_SCORE}+)")
            if lcp_seconds is not None and lcp_seconds > MAX_LCP_SECONDS:
                parts.append(f"LCP {lcp_seconds}s exceeds {MAX_LCP_SECONDS}s threshold")
            elif lcp_seconds is None:
                parts.append("LCP data unavailable")

            return False, score, lcp_seconds, "; ".join(parts)

        except requests.RequestException as exc:
            return False, None, None, f"Unable to check mobile speed: {exc}"
        except (KeyError, TypeError, ValueError) as exc:
            return False, None, None, f"Unable to parse PageSpeed response: {exc}"
