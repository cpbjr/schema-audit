"""Schema Audit Lead Generator - CLI entry point.

Usage:
    python main.py discover "Plumbers in Eagle, ID"
    python main.py audit <place_id_or_url>
    python main.py audit-all
    python main.py report <business_id>
    python main.py status
    python main.py hot-leads [--limit 10]
"""

import sys
from datetime import datetime

import click

from analyzer import SchemaAnalyzer
from config import DB_PATH, GOOGLE_PLACES_API_KEY, ensure_directories
from db import Audit, Database, Report
from discovery import PlacesDiscovery
from extractor import SchemaExtractor
from reporter import ReportGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_label(score: int) -> str:
    """Return a colored lead-quality label for the given score."""
    if score <= 2:
        return click.style("HOT LEAD", fg="red", bold=True)
    if score <= 4:
        return click.style("WARM LEAD", fg="yellow", bold=True)
    return click.style("COLD LEAD", fg="green", bold=True)


def _pass_fail(passed: bool) -> str:
    """Return a colored PASS/FAIL indicator."""
    if passed:
        return click.style("PASS", fg="green", bold=True)
    return click.style("FAIL", fg="red", bold=True)


def _run_single_audit(
    business_id: str,
    db: Database,
    extractor: SchemaExtractor,
    analyzer: SchemaAnalyzer,
    verbose: bool = True,
) -> Audit | None:
    """Run audit for a single business and store in DB.

    Returns the Audit object on success, None on failure.
    """
    biz = db.get_business(business_id)
    if biz is None:
        if verbose:
            click.echo(click.style(f"  Business {business_id} not found in DB.", fg="red"))
        return None

    if not biz.website_url:
        if verbose:
            click.echo(click.style(f"  {biz.name}: no website URL, skipping.", fg="yellow"))
        return None

    # Extract schema from website
    schemas = extractor.extract_schema_from_url(biz.website_url)
    if schemas is None:
        schemas = []  # site unreachable, treat as no schema

    # Build GBP data dict for analyzer
    gbp_data = {
        "name": biz.name,
        "address": biz.address,
        "phone": biz.phone,
        "types": biz.gbp_categories,
    }

    # Run the 5-point audit
    result = analyzer.run_full_audit(biz.website_url, schemas, gbp_data)

    # Create Audit dataclass and store
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

    if verbose:
        click.echo()
        click.echo(click.style(f"  Audit for: {biz.name}", bold=True))
        click.echo(f"  URL: {biz.website_url}")
        click.echo()
        click.echo(f"  1. Schema Exists:       {_pass_fail(audit.has_schema)}")
        click.echo(f"  2. sameAs Connection:   {_pass_fail(audit.has_sameas)}")
        click.echo(f"  3. Category Alignment:  {_pass_fail(audit.category_aligned)}")
        click.echo(f"  4. NAP Consistency:     {_pass_fail(audit.nap_consistent)}")
        speed_ok = (
            audit.mobile_speed_score is not None
            and audit.mobile_speed_score >= 80
            and audit.mobile_lcp is not None
            and audit.mobile_lcp <= 2.5
        )
        click.echo(f"  5. Mobile Speed:        {_pass_fail(speed_ok)}")
        if audit.mobile_speed_score is not None:
            lcp_str = f"{audit.mobile_lcp}s" if audit.mobile_lcp is not None else "N/A"
            click.echo(f"     Score: {audit.mobile_speed_score}/100 | LCP: {lcp_str}")
        click.echo()
        click.echo(f"  Overall Score: {audit.score}/5  {_score_label(audit.score)}")

        if audit.issues:
            click.echo()
            click.echo(click.style("  Issues:", fg="red"))
            for issue in audit.issues:
                click.echo(f"    - {issue}")

    return audit


# ---------------------------------------------------------------------------
# CLI Group
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Schema Audit Lead Generator - Find businesses with poor local SEO schema."""
    ensure_directories()


# ---------------------------------------------------------------------------
# Command: discover
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("query")
def discover(query: str):
    """Discover businesses via Google Places API.

    Example: python main.py discover "Plumbers in Eagle, ID"
    """
    if not GOOGLE_PLACES_API_KEY:
        raise click.ClickException(
            "GOOGLE_PLACES_API_KEY not set. Add it to .env or your environment."
        )

    db = Database(DB_PATH)
    discovery = PlacesDiscovery(GOOGLE_PLACES_API_KEY)

    try:
        new_count = discovery.discover_and_store(query, db)
        total = len(db.get_all_businesses())
        click.echo(f"\nDone! {new_count} new businesses added ({total} total in DB).")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Command: audit
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("business_identifier")
def audit(business_identifier: str):
    """Audit a single business by place_id or website URL.

    Examples:
        python main.py audit ChIJgfDU44ZXrlQRvMn1...
        python main.py audit https://example-plumber.com
    """
    db = Database(DB_PATH)
    extractor = SchemaExtractor()
    analyzer = SchemaAnalyzer()

    try:
        # Determine if identifier is a URL or place_id
        if business_identifier.startswith("http://") or business_identifier.startswith("https://"):
            biz = db.search_businesses_by_url(business_identifier)
            if biz is None:
                raise click.ClickException(
                    f"No business found with URL: {business_identifier}\n"
                    "Run 'discover' first to add businesses to the database."
                )
            business_id = biz.id
        else:
            business_id = business_identifier

        result = _run_single_audit(business_id, db, extractor, analyzer, verbose=True)
        if result is None:
            raise click.ClickException("Audit failed. See errors above.")

        click.echo(click.style("\nAudit saved to database.", fg="green"))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Command: audit-all
# ---------------------------------------------------------------------------

@cli.command("audit-all")
def audit_all():
    """Audit all businesses that haven't been audited yet.

    Example: python main.py audit-all
    """
    db = Database(DB_PATH)
    extractor = SchemaExtractor()
    analyzer = SchemaAnalyzer()

    try:
        unaudited = db.get_businesses_without_audit()
        if not unaudited:
            click.echo(click.style("All businesses have been audited!", fg="green"))
            return

        click.echo(f"\nAuditing {len(unaudited)} businesses...\n")
        click.echo("-" * 70)

        audited_count = 0
        hot_count = 0
        errors = 0

        for i, biz in enumerate(unaudited, start=1):
            click.echo(f"\n[{i}/{len(unaudited)}] {biz.name}")
            try:
                result = _run_single_audit(
                    biz.id, db, extractor, analyzer, verbose=False
                )
                if result is not None:
                    audited_count += 1
                    label = _score_label(result.score)
                    click.echo(f"  Score: {result.score}/5  {label}")
                    if result.score <= 2:
                        hot_count += 1
                else:
                    errors += 1
                    click.echo(click.style("  Skipped (no website or not found)", fg="yellow"))
            except Exception as exc:
                errors += 1
                click.echo(click.style(f"  Error: {exc}", fg="red"))

        click.echo("\n" + "=" * 70)
        click.echo(click.style("Audit-All Summary", bold=True))
        click.echo(f"  Total audited:   {audited_count}")
        click.echo(f"  Hot leads found: {click.style(str(hot_count), fg='red', bold=True)}")
        click.echo(f"  Errors/skipped:  {errors}")
        click.echo("=" * 70)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Command: report
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("business_id")
def report(business_id: str):
    """Generate an HTML audit report for a business.

    Example: python main.py report ChIJgfDU44ZXrlQRvMn1...
    """
    db = Database(DB_PATH)

    try:
        biz = db.get_business(business_id)
        if biz is None:
            raise click.ClickException(f"Business not found: {business_id}")

        audit_record = db.get_audit(business_id)
        if audit_record is None:
            raise click.ClickException(
                f"No audit found for {biz.name}. Run 'audit' or 'audit-all' first."
            )

        click.echo(f"\nGenerating report for: {click.style(biz.name, bold=True)}")

        reporter = ReportGenerator()

        # Generate corrected schema
        corrected_schema = reporter.generate_corrected_schema(
            biz, biz.gbp_categories
        )

        # Generate HTML report
        html_content = reporter.generate_html_report(
            biz, audit_record, corrected_schema
        )

        # Save files
        html_path, json_path = reporter.save_report(biz, html_content, corrected_schema)

        # Store report record in DB
        report_record = Report(
            business_id=biz.id,
            corrected_schema=corrected_schema,
            html_report=html_content,
            report_path=html_path,
        )
        db.insert_report(report_record)

        click.echo(click.style("\nReport generated successfully!", fg="green"))
        click.echo(f"  HTML report: {html_path}")
        click.echo(f"  JSON schema: {json_path}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Command: status
# ---------------------------------------------------------------------------

@cli.command()
def status():
    """Show pipeline statistics.

    Example: python main.py status
    """
    db = Database(DB_PATH)

    try:
        stats = db.get_pipeline_stats()

        click.echo()
        click.echo(click.style("Pipeline Status", bold=True))
        click.echo("=" * 40)

        total = stats["total_businesses"]
        audited = stats["audited_count"]
        unaudited = stats["unaudited_count"]

        click.echo(f"  Total businesses:    {total}")
        click.echo(f"  Audited:             {audited}" + (
            f"  ({audited * 100 // total}%)" if total > 0 else ""
        ))
        click.echo(f"  Unaudited:           {unaudited}" + (
            f"  ({unaudited * 100 // total}%)" if total > 0 else ""
        ))
        click.echo("-" * 40)

        hot = stats["hot_leads"]
        warm = stats["warm_leads"]
        cold = stats["cold_leads"]

        click.echo(f"  {click.style('Hot leads', fg='red', bold=True)} (0-2):    {hot}")
        click.echo(f"  {click.style('Warm leads', fg='yellow', bold=True)} (3-4):   {warm}")
        click.echo(f"  {click.style('Cold leads', fg='green', bold=True)} (5):      {cold}")
        click.echo("-" * 40)
        click.echo(f"  Reports generated:   {stats['reports_generated']}")
        click.echo("=" * 40)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Command: hot-leads
# ---------------------------------------------------------------------------

@cli.command("hot-leads")
@click.option("--limit", default=10, help="Max number of leads to show.")
def hot_leads(limit: int):
    """List hot leads (score 0-2) sorted by worst score first.

    Example: python main.py hot-leads --limit 5
    """
    db = Database(DB_PATH)

    try:
        leads = db.get_hot_leads(max_score=2)

        if not leads:
            click.echo(click.style("\nNo hot leads found.", fg="yellow"))
            click.echo("Run 'audit-all' first to audit your businesses.")
            return

        shown = leads[:limit]
        click.echo()
        click.echo(click.style(f"Hot Leads ({len(leads)} total, showing {len(shown)})", bold=True))
        click.echo("=" * 70)

        for i, (biz, aud) in enumerate(shown, start=1):
            click.echo(
                f"\n  {i}. {click.style(biz.name, bold=True)}"
                f"  [Score: {aud.score}/5]"
            )
            if biz.discovery_rank:
                 rank_str = f"#{biz.discovery_rank}"
                 if biz.rank_total_candidates:
                     rank_str += f" / {biz.rank_total_candidates}"
                 click.echo(f"     Rank:     {click.style(rank_str, fg='cyan')}")

            click.echo(f"     URL:      {biz.website_url}")
            click.echo(f"     Place ID: {biz.id}")
            if aud.issues:
                click.echo(click.style("     Issues:", fg="red"))
                for issue in aud.issues:
                    click.echo(f"       - {issue}")

        click.echo("\n" + "=" * 70)
        click.echo(
            f"Generate a report: python main.py report <place_id>"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Command: list-leads
# ---------------------------------------------------------------------------

@cli.command("list-leads")
@click.option("--limit", default=20, help="Max number of leads to show.")
@click.option("--all", is_flag=True, help="Show all businesses, not just un-audited ones.")
def list_leads(limit: int, all: bool):
    """List discovered businesses in the database.

    Example: python main.py list-leads --limit 50
    """
    db = Database(DB_PATH)
    try:
        if all:
            businesses = db.get_all_businesses()
        else:
            businesses = db.get_businesses_without_audit()

        if not businesses:
            click.echo(click.style("\nNo matching businesses found.", fg="yellow"))
            return

        shown = businesses[-limit:] if limit > 0 else businesses
        click.echo()
        click.echo(click.style(f"Businesses ({len(businesses)} total, showing {len(shown)})", bold=True))
        click.echo("=" * 70)

        for i, biz in enumerate(shown, start=1):
            audit = db.get_audit(biz.id)
            if audit:
                status = click.style(f"SCORE: {audit.score}/5", fg="green" if audit.score == 5 else "yellow" if audit.score >=3 else "red")
            else:
                status = click.style("PENDING", fg="blue")
            
            click.echo(f"  {i}. {click.style(biz.name, bold=True)} [{status}]")
            if biz.discovery_rank:
                 rank_str = f"#{biz.discovery_rank}"
                 if biz.rank_total_candidates:
                     rank_str += f" / {biz.rank_total_candidates}"
                 click.echo(f"     Rank: {click.style(rank_str, fg='cyan')}")
            click.echo(f"     URL: {biz.website_url}")

        click.echo("\n" + "=" * 70)
        click.echo("To audit these leads: python main.py audit-all")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
