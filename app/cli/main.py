from __future__ import annotations
from typing import Optional
import typer

from ..config import get_settings
from ..utils.logging import configure_logging
from ..utils.dates import parse_date
from ..schemas import JobApplicationCreate
from ..domain import Status
from ..scraping.fetch import fetch_url
from ..scraping.parse_common import parse_job_from_html
from ..storage.excel_storage import (
    ensure_file,
    create_or_update as xl_create_or_update,
    list_applications as xl_list,
    update_status as xl_update_status,
    remove_by_id as xl_remove_by_id,
    search as xl_search,
    export_to_excel as xl_export_excel,
    export_to_csv as xl_export_csv,
)

cli = typer.Typer(help="Application Tracker CLI")


@cli.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging")):
    settings = get_settings()
    configure_logging(debug=verbose or settings.DEBUG)
    # Ensure the Excel file exists on first run
    ensure_file(settings.EXCEL_PATH)


@cli.command("init-db")
def init_db_cmd():
    """Initialize the Excel workbook used for storage."""
    settings = get_settings()
    ensure_file(settings.EXCEL_PATH)
    typer.secho(f"Excel storage initialized at {settings.EXCEL_PATH}.", fg=typer.colors.GREEN)


@cli.command("add")
def add(
    url: str,
    status: Status = typer.Option(Status.applied, help="Application status"),
    date_applied: Optional[str] = typer.Option(None, help="Date applied (default: today)"),
    title: Optional[str] = typer.Option(None, help="Override parsed job title (use with --no-fetch if needed)"),
    employer: Optional[str] = typer.Option(None, help="Override parsed employer (use with --no-fetch if needed)"),
    no_fetch: bool = typer.Option(
        False,
        help="Skip downloading the page; rely on --title/--employer overrides.",
    ),
):
    settings = get_settings()
    parsed: dict
    if no_fetch:
        parsed = {"title": title, "employer": employer}
        if not title or not employer:
            typer.secho(
                "Note: --no-fetch supplied but --title/--employer not fully provided; saving with blanks.",
                fg=typer.colors.YELLOW,
            )
    else:
        # Fetch page HTML. Some career sites aggressively block bots; we use a browser-like UA and fallbacks.
        try:
            html = fetch_url(url)
            parsed = parse_job_from_html(html, url)
        except Exception as e:
            if title or employer:
                # Proceed with provided overrides despite fetch failure
                parsed = {"title": title, "employer": employer}
                typer.secho(
                    "Fetch failed, proceeding with provided --title/--employer overrides.",
                    fg=typer.colors.YELLOW,
                )
            else:
                typer.secho(f"Failed to fetch URL: {url}", fg=typer.colors.RED)
                typer.echo(str(e))
                typer.secho(
                    "Tips: some sites block non-browsers. Try one of:\n"
                    "  - Set APPTRACKER_USER_AGENT to your browser's User-Agent string and retry.\n"
                    "  - Set APPTRACKER_FETCH_PROXY_READER (e.g., https://r.jina.ai) to bypass strict blockers.\n"
                    "  - Run with --verbose to see more details.\n"
                    "  - Use --no-fetch with --title and --employer to add manually.",
                    fg=typer.colors.YELLOW,
                )
                raise typer.Exit(code=1)

    # Apply overrides if provided
    if title:
        parsed["title"] = title
    if employer:
        parsed["employer"] = employer

    if not parsed.get("title"):
        typer.secho("Warning: Could not confidently extract job title. You can edit later.", fg=typer.colors.YELLOW)
    if not parsed.get("employer"):
        typer.secho("Warning: Could not confidently extract employer.", fg=typer.colors.YELLOW)

    try:
        # Default to today when not provided
        date_applied_value = parse_date(date_applied)
    except Exception as e:
        typer.secho(f"Invalid date_applied: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    data = JobApplicationCreate(
        title=parsed.get("title") or "",
        employer=parsed.get("employer") or "",
        status=status,
        date_applied=date_applied_value,
        source_url=url,
    )
    row = xl_create_or_update(settings.EXCEL_PATH, data)
    obj_id = row.get("id", "-")
    title = row.get("title", "")
    employer = row.get("employer", "")
    status_val = row.get("status", status.value)
    typer.secho(f"Saved: [#{obj_id}] {title} at {employer} | status={status_val}", fg=typer.colors.GREEN)


@cli.command("list")
def list_cmd(status: Optional[Status] = typer.Option(None, help="Filter by status")):
    settings = get_settings()
    items = xl_list(settings.EXCEL_PATH, status=status)
    if not items:
        typer.secho("No applications found.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    for obj in items:
        date_applied = obj.get("date_applied")
        date_applied_str = str(date_applied.date() if hasattr(date_applied, "date") else date_applied) if date_applied else "-"
        typer.echo(
            f"#{obj.get('id')} | {obj.get('title')} @ {obj.get('employer')} | {obj.get('status')} | applied: {date_applied_str}"
        )


@cli.command("search")
def search_cmd(
    item_id: Optional[int] = typer.Option(None, "--id", help="Search by numeric ID"),
    title: Optional[str] = typer.Option(None, "--title", help="Search by job title (regex, case-insensitive)"),
    employer: Optional[str] = typer.Option(None, "--employer", help="Search by employer (regex, case-insensitive)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results to show"),
):
    """Search applications by id, title, or employer.

    Regex is supported for title and employer. Matching is case-insensitive.
    Results are ranked by similarity and id (desc).
    """
    if item_id is None and not title and not employer:
        typer.secho("Provide at least one of --id, --title, --employer", fg=typer.colors.YELLOW)
        raise typer.Exit(code=2)

    settings = get_settings()
    items = xl_search(
        settings.EXCEL_PATH,
        item_id=item_id,
        title=title,
        employer=employer,
        limit=limit,
    )
    if not items:
        typer.secho("No matches found.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    for obj in items:
        date_applied = obj.get("date_applied")
        date_applied_str = str(date_applied.date() if hasattr(date_applied, "date") else date_applied) if date_applied else "-"
        typer.echo(
            f"#{obj.get('id')} | {obj.get('title')} @ {obj.get('employer')} | {obj.get('status')} | applied: {date_applied_str}"
        )


@cli.command("update-status")
def update_status_cmd(selector: str, new_status: Status):
    settings = get_settings()
    obj = xl_update_status(settings.EXCEL_PATH, selector, new_status)
    if not obj:
        typer.secho("Not found.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(f"Updated #{obj.get('id')} to status={obj.get('status')}", fg=typer.colors.GREEN)


@cli.command("remove")
def remove_cmd(item_id: int):
    """Remove an entry by numeric ID."""
    settings = get_settings()
    obj = xl_remove_by_id(settings.EXCEL_PATH, item_id)
    if not obj:
        typer.secho("Not found.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(
        f"Removed #{obj.get('id')} | {obj.get('title')} @ {obj.get('employer')}",
        fg=typer.colors.GREEN,
    )


@cli.command("export")
def export_cmd(
    format: str = typer.Option("excel", help="excel or csv", case_sensitive=False),
    out: Optional[str] = typer.Option(None, help="Output file path"),
):
    format = format.lower()
    if format not in {"excel", "csv"}:
        typer.secho("Format must be 'excel' or 'csv'", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    if out is None:
        out = "Applications.xlsx" if format == "excel" else "Applications.csv"
    if format == "excel":
        settings = get_settings()
        xl_export_excel(settings.EXCEL_PATH, out)
    else:
        settings = get_settings()
        xl_export_csv(settings.EXCEL_PATH, out)

    typer.secho(f"Exported to {out}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    # Allow running via: python -m app.cli.main [COMMANDS]
    cli()
