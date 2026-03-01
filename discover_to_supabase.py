"""discover_to_supabase.py — Nightly discovery pipeline, writes directly to Supabase.

Reads search queries from a queries file (one per line, # lines are comments).
Runs each query through PlacesDiscovery and upserts results to Supabase.
Skips SQLite entirely.

Usage:
    python3 discover_to_supabase.py [--queries-file PATH]

Default queries file: ~/.openclaw/workspace/Knowledge/worker-inputs/discovery-queries.md
Falls back to: queries.txt in the same directory as this script.

Required env vars (in .env or environment):
    GOOGLE_PLACES_API_KEY
    SUPABASE_URL
    SUPABASE_SERVICE_KEY
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config import GOOGLE_PLACES_API_KEY
from discovery import PlacesDiscovery
from supabase_writer import SupabaseWriter


DEFAULT_QUERIES_FILE = Path.home() / ".openclaw/workspace/Knowledge/worker-inputs/discovery-queries.md"
FALLBACK_QUERIES_FILE = Path(__file__).parent / "queries.txt"


def load_queries(queries_file: Path) -> list[str]:
    """Read queries from file. Skips blank lines, comments (#), and markdown headers (-)."""
    if not queries_file.exists():
        print(f"Queries file not found: {queries_file}")
        return []

    queries = []
    divider_count = 0
    with open(queries_file) as f:
        for line in f:
            line = line.strip()
            # Stop after the second --- divider (notes section follows)
            if line.startswith("---"):
                divider_count += 1
                if divider_count >= 2:
                    break
                continue
            if not line or line.startswith("#"):
                continue
            # Strip markdown list prefix "- " if present
            if line.startswith("- "):
                line = line[2:].strip()
            elif line.startswith("-"):
                continue
            if line and line[0].isalpha():
                queries.append(line)
    return queries


def run_discovery(queries: list[str]) -> dict:
    """Run discovery for all queries, upsert to Supabase. Returns summary stats."""
    api_key = GOOGLE_PLACES_API_KEY
    if not api_key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY not set in environment or .env")

    discovery = PlacesDiscovery(api_key=api_key)
    writer = SupabaseWriter()

    stats = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "queries_run": 0,
        "total_found": 0,
        "total_upserted": 0,
        "errors": [],
    }

    for query in queries:
        print(f"\nSearching: {query!r}")
        try:
            places = discovery.search_businesses(query)
            stats["queries_run"] += 1

            if not places:
                print(f"  No results for: {query!r}")
                continue

            total = len(places)
            stats["total_found"] += total
            upserted = 0

            for i, place in enumerate(places, start=1):
                place_id = place.get("id", "")
                display_name = place.get("displayName", {})
                name = display_name.get("text", "Unknown") if isinstance(display_name, dict) else str(display_name)
                website = place.get("websiteUri", "")

                if not website:
                    print(f"  [{i}/{total}] {name} -- no website (will include)")

                business = {
                    "id": place_id,
                    "name": name,
                    "address": place.get("formattedAddress", ""),
                    "phone": place.get("nationalPhoneNumber", ""),
                    "website_url": website or "",
                    "gbp_categories": place.get("types", []),
                    "search_query": query,
                    "discovery_rank": i,
                    "rank_total_candidates": total,
                    "google_maps_uri": place.get("googleMapsUri", ""),
                    "business_status": place.get("businessStatus", ""),
                    "rating": place.get("rating"),
                    "user_rating_count": place.get("userRatingCount"),
                    "raw_data": place,
                }

                try:
                    writer.upsert_business(business)
                    upserted += 1
                    print(f"  [{i}/{total}] {name} -- upserted ({website})")
                except Exception as exc:
                    err = f"Upsert failed for {name}: {exc}"
                    print(f"  [{i}/{total}] ERROR: {err}")
                    stats["errors"].append(err)

            stats["total_upserted"] += upserted
            print(f"  Query complete: {upserted}/{total} upserted to Supabase")

        except Exception as exc:
            err = f"Query failed '{query}': {exc}"
            print(f"ERROR: {err}")
            stats["errors"].append(err)

    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Run nightly discovery and write to Supabase")
    parser.add_argument(
        "--queries-file",
        type=Path,
        default=None,
        help="Path to queries file (default: ~/.openclaw/workspace/Knowledge/worker-inputs/discovery-queries.md)",
    )
    args = parser.parse_args()

    # Resolve queries file
    if args.queries_file:
        queries_file = args.queries_file
    elif DEFAULT_QUERIES_FILE.exists():
        queries_file = DEFAULT_QUERIES_FILE
    elif FALLBACK_QUERIES_FILE.exists():
        queries_file = FALLBACK_QUERIES_FILE
    else:
        print(f"No queries file found. Tried:\n  {DEFAULT_QUERIES_FILE}\n  {FALLBACK_QUERIES_FILE}")
        sys.exit(1)

    print(f"Loading queries from: {queries_file}")
    queries = load_queries(queries_file)

    if not queries:
        print("No queries found in file. Exiting.")
        sys.exit(0)

    print(f"Running {len(queries)} queries...")
    stats = run_discovery(queries)

    print("\n" + "=" * 50)
    print("DISCOVERY COMPLETE")
    print(f"  Queries run:      {stats['queries_run']}")
    print(f"  Businesses found: {stats['total_found']}")
    print(f"  Upserted:         {stats['total_upserted']}")
    print(f"  Errors:           {len(stats['errors'])}")
    if stats["errors"]:
        print("\nErrors:")
        for err in stats["errors"]:
            print(f"  - {err}")

    # Write stats JSON for ops dashboard
    ops_dir = Path.home() / ".openclaw/workspace/ops-data/discovery"
    ops_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats_file = ops_dir / f"{date_str}.json"
    with open(stats_file, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"\nStats written to: {stats_file}")


if __name__ == "__main__":
    main()
