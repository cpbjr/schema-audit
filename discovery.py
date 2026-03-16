"""Google Places API (New) discovery module for Schema Audit Lead Generator."""

import os
import sys
import requests

from config import (
    PLACES_DETAILS_URL,
    PLACES_TEXT_SEARCH_URL,
    REQUEST_TIMEOUT,
)
from db import Business, Database, ServiceRank

sys.path.insert(0, os.path.expanduser("~/cost-logs"))
from cost_logger import log_api_call


class PlacesDiscovery:
    """Discover local businesses via Google Places API (New)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    # ------------------------------------------------------------------
    # API calls
    # ------------------------------------------------------------------

    def search_businesses(self, query: str) -> list[dict]:
        """Search for businesses using Google Places Text Search (New).

        Uses POST to places.googleapis.com/v1/places:searchText.
        Paginates via pageToken (up to 3 pages = 60 results).
        """
        all_results: list[dict] = []
        page_token: str | None = None

        for page in range(3):  # Max 3 pages
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": (
                    "places.id,places.displayName,places.formattedAddress,"
                    "places.nationalPhoneNumber,places.websiteUri,places.types,places.primaryType,"
                    "places.businessStatus,places.googleMapsUri,places.rating,"
                    "places.userRatingCount,places.location,places.regularOpeningHours,"
                    "places.reviews,places.photos,places.addressComponents,"
                    "places.editorialSummary,places.internationalPhoneNumber,"
                    "nextPageToken"
                ),
            }

            body: dict = {"textQuery": query, "pageSize": 20}
            if page_token:
                body["pageToken"] = page_token

            resp = requests.post(
                PLACES_TEXT_SEARCH_URL,
                headers=headers,
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            log_api_call("schema-audit", "google-places", "text-search", calls=1)
            data = resp.json()

            places = data.get("places", [])
            if not places and page == 0:
                print("  No results found for this query.")
                return []
            if not places:
                break

            all_results.extend(places)
            print(f"  Page {page + 1}: {len(places)} results (total: {len(all_results)})")

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return all_results

    def get_place_details(self, place_resource_name: str) -> dict:
        """Fetch detailed information for a single place.

        Uses GET to places.googleapis.com/v1/places/{place_id}.
        place_resource_name should be like 'places/ChIJ...' or just the id.
        """
        # Ensure we have just the ID portion (strip 'places/' prefix if present)
        place_id = place_resource_name.removeprefix("places/")

        url = f"{PLACES_DETAILS_URL}/{place_id}"
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": (
                "id,displayName,formattedAddress,"
                "nationalPhoneNumber,websiteUri,types,primaryType"
            ),
        }

        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        log_api_call("schema-audit", "google-places", "place-details", calls=1)
        return resp.json()

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def discover_and_store(self, query: str, db: Database) -> int:
        """Search for businesses, fetch details, and store those with websites.

        Returns the count of *new* businesses inserted (duplicates are skipped).
        """
        print(f"\nSearching: {query!r}")
        search_results = self.search_businesses(query)

        if not search_results:
            return 0

        total_candidates = len(search_results)
        print(f"\nProcessing {total_candidates} places...")
        new_count = 0

        for i, place in enumerate(search_results, start=1):
            # The new API returns the id directly in the search results
            place_id = place.get("id", "")
            display_name = place.get("displayName", {})
            name = display_name.get("text", "Unknown") if isinstance(display_name, dict) else str(display_name)

            # Check if already in DB -- skip if so
            existing = db.get_business(place_id)
            if existing:
                print(f"  [{i}/{total_candidates}] {name} -- already in DB, skipping")
                continue

            # The new Text Search API already returns the fields we need
            # if we specified them in the field mask, so no separate details
            # call is strictly required. But we do a details call for
            # completeness and to get any fields that might be missing.
            website = place.get("websiteUri", "")

            if not website:
                # Try a details call in case the search didn't return the website
                try:
                    details = self.get_place_details(place_id)
                    website = details.get("websiteUri", "")
                    if not website:
                        print(f"  [{i}/{total_candidates}] {name} -- no website, skipping")
                        continue
                    # Use details data for richer info
                    place = details
                    display_name = place.get("displayName", {})
                    name = display_name.get("text", name) if isinstance(display_name, dict) else name
                except Exception as exc:
                    print(f"  [{i}/{total_candidates}] {name} -- details error: {exc}")
                    continue

            business = Business(
                id=place_id,
                name=name,
                address=place.get("formattedAddress", ""),
                phone=place.get("nationalPhoneNumber", ""),
                website_url=website,
                gbp_categories=place.get("types", []),
                gbp_primary_type=place.get("primaryType", ""),
                search_query=query,
                discovery_rank=i,  # 1-based index from search results
                rank_total_candidates=total_candidates,
                google_maps_uri=place.get("googleMapsUri", ""),
                business_status=place.get("businessStatus", ""),
                rating=place.get("rating"),
                user_rating_count=place.get("userRatingCount"),
                raw_data=place,  # Store the full API response
            )

            db.insert_business(business)
            new_count += 1
            print(f"  [{i}/{total_candidates}] {business.name} -- saved ({business.website_url})")

        return new_count

    def run_multi_service_discovery(
        self,
        db: "Database",
        queries: list[str],
        labels: list[str],
    ) -> None:
        """Run multiple service queries and build a Service Visibility Matrix.

        For each query:
        - Discovers businesses and stores them in the businesses table
        - Records discovery_rank for each found business in service_ranks
        - Records discovery_rank=NULL for known businesses NOT found in this query

        Args:
            db: Database instance
            queries: List of search query strings (e.g. ["plumber Eagle ID", "drain cleaning Eagle ID"])
            labels: Human-readable labels matching queries (e.g. ["Plumbing", "Drains"])
        """
        if len(queries) != len(labels):
            raise ValueError("queries and labels must be the same length")

        for query, label in zip(queries, labels):
            print(f"\n--- Service query: {label} ({query}) ---")

            # Run the search — this returns raw place dicts
            places = self.search_businesses(query)
            if not places:
                print(f"  No results for '{query}'")
                continue

            # Build a map of place_id -> rank for found businesses
            found_ids: dict[str, int] = {}
            total = len(places)

            for i, place in enumerate(places, start=1):
                place_id = place.get("id", "")
                if not place_id:
                    continue

                display_name = place.get("displayName", {})
                name = display_name.get("text", "") if isinstance(display_name, dict) else str(display_name)
                website = place.get("websiteUri", "")

                # Skip businesses without websites
                if not website:
                    continue

                # Upsert into businesses table
                existing = db.get_business(place_id)
                if not existing:
                    from datetime import datetime
                    business = Business(
                        id=place_id,
                        name=name,
                        address=place.get("formattedAddress", ""),
                        phone=place.get("nationalPhoneNumber", ""),
                        website_url=website,
                        gbp_categories=place.get("types", []),
                        gbp_primary_type=place.get("primaryType", ""),
                        search_query=query,
                        discovery_rank=i,
                        rank_total_candidates=total,
                        google_maps_uri=place.get("googleMapsUri", ""),
                        business_status=place.get("businessStatus", ""),
                        rating=place.get("rating"),
                        user_rating_count=place.get("userRatingCount"),
                        raw_data=place,
                    )
                    db.insert_business(business)
                    print(f"  [{i}/{total}] {name} — new business saved")
                else:
                    print(f"  [{i}/{total}] {name} — already in DB")

                found_ids[place_id] = i

                # Record rank for this service query
                db.upsert_service_rank(ServiceRank(
                    business_id=place_id,
                    service_query=query,
                    service_label=label,
                    discovery_rank=i,
                    total_results=total,
                ))

            # For all known businesses NOT found in this query, record NULL rank
            all_businesses = db.get_all_businesses()
            invisible_count = 0
            for biz in all_businesses:
                if biz.id not in found_ids:
                    db.upsert_service_rank(ServiceRank(
                        business_id=biz.id,
                        service_query=query,
                        service_label=label,
                        discovery_rank=None,
                        total_results=total,
                    ))
                    invisible_count += 1

            print(f"  Found: {len(found_ids)} | Invisible (NULL rank): {invisible_count}")
