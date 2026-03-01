"""Cost logging for API calls — tracks usage and estimated costs."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Pricing constants (Google Places API New, per-call after free tier)
PRICING = {
    "text-search": 0.032,    # $32/1,000 calls
    "place-details": 0.017,  # $17/1,000 calls
}

COSTS_DIR = Path.home() / ".openclaw/workspace/ops-data/costs"


def log_api_call(service: str, provider: str, operation: str, *, calls: int = 1, **kwargs):
    """Log an API call with timestamp and estimated cost.

    Appends a JSON line to YYYY-MM.jsonl and updates YYYY-MM-summary.json.
    """
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    est_cost = PRICING.get(operation, 0.0) * calls

    # Ensure directory exists
    COSTS_DIR.mkdir(parents=True, exist_ok=True)

    # Append JSONL entry
    entry = {
        "ts": now.isoformat(),
        "service": service,
        "provider": provider,
        "operation": operation,
        "calls": calls,
        "est_cost_usd": est_cost,
    }
    jsonl_path = COSTS_DIR / f"{month_key}.jsonl"
    with open(jsonl_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Update monthly summary
    summary_path = COSTS_DIR / f"{month_key}-summary.json"
    summary = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text())
        except (json.JSONDecodeError, OSError):
            summary = {}

    summary.setdefault("month", month_key)
    summary["total_calls"] = summary.get("total_calls", 0) + calls
    summary["total_est_cost_usd"] = round(summary.get("total_est_cost_usd", 0.0) + est_cost, 6)
    summary.setdefault("by_operation", {})
    op_stats = summary["by_operation"].setdefault(operation, {"calls": 0, "est_cost_usd": 0.0})
    op_stats["calls"] += calls
    op_stats["est_cost_usd"] = round(op_stats["est_cost_usd"] + est_cost, 6)
    summary["last_updated"] = now.isoformat()

    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
