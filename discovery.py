"""Google Places API (New) discovery module for Schema Audit Lead Generator."""

import requests

from config import (
    PLACES_DETAILS_URL,
    PLACES_TEXT_SEARCH_URL,
    REQUEST_TIMEOUT,
)
from db import Business, Database


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
                    "places.nationalPhoneNumber,places.websiteUri,places.types,"
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
                "nationalPhoneNumber,websiteUri,types"
            ),
        }

        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
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

        print(f"\nProcessing {len(search_results)} places...")
        new_count = 0

        for i, place in enumerate(search_results, start=1):
            # The new API returns the id directly in the search results
            place_id = place.get("id", "")
            display_name = place.get("displayName", {})
            name = display_name.get("text", "Unknown") if isinstance(display_name, dict) else str(display_name)

            # Check if already in DB -- skip if so
            existing = db.get_business(place_id)
            if existing:
                print(f"  [{i}/{len(search_results)}] {name} -- already in DB, skipping")
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
                        print(f"  [{i}/{len(search_results)}] {name} -- no website, skipping")
                        continue
                    # Use details data for richer info
                    place = details
                    display_name = place.get("displayName", {})
                    name = display_name.get("text", name) if isinstance(display_name, dict) else name
                except Exception as exc:
                    print(f"  [{i}/{len(search_results)}] {name} -- details error: {exc}")
                    continue

            business = Business(
                id=place_id,
                name=name,
                address=place.get("formattedAddress", ""),
                phone=place.get("nationalPhoneNumber", ""),
                website_url=website,
                gbp_categories=place.get("types", []),
                search_query=query,
            )

            db.insert_business(business)
            new_count += 1
            print(f"  [{i}/{len(search_results)}] {business.name} -- saved ({business.website_url})")

        return new_count
