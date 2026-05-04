from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

CRT_THEME = Theme(
    {
        "primary": "bold green",
        "secondary": "green",
        "accent": "bold yellow",
        "danger": "bold red",
        "muted": "dim green",
        "header": "bold bright_green",
        "info": "cyan",
    }
)

console = Console(theme=CRT_THEME)

APP_NAME = "LEGACY REPORT"
APP_VERSION = "v1.0"


def print_header() -> None:
    title = Text(f"  {APP_NAME}  {APP_VERSION}  ", style="bold black on green")
    console.print(Panel(title, style="green", padding=(0, 2)))


def print_success(message: str) -> None:
    console.print(f"[primary]✓ {message}[/primary]")


def print_error(message: str) -> None:
    console.print(f"[danger]✗ {message}[/danger]")


def print_info(message: str) -> None:
    console.print(f"[info]  {message}[/info]")


def print_muted(message: str) -> None:
    console.print(f"[muted]{message}[/muted]")


def print_issues_table(issues: list, series_map: dict) -> None:
    """Render a Rich table of Issue rows. series_map: {series_id: Series}"""
    if not issues:
        console.print("[muted]No issues found.[/muted]")
        return

    table = Table(
        show_header=True,
        header_style="bold green",
        border_style="green",
        style="green",
    )
    table.add_column("#", style="dim green", width=4)
    table.add_column("Series", style="green", min_width=20)
    table.add_column("Issue #", style="bold green", width=8)
    table.add_column("LGY #", style="yellow", width=7)
    table.add_column("Pub Date", style="green", width=12)
    table.add_column("Story Title", style="bright_green", min_width=20)
    table.add_column("Publisher", style="dim green", width=12)

    for idx, issue in enumerate(issues, 1):
        series = series_map.get(issue.series_id)
        series_label = f"{series.title} ({series.start_year})" if series else "—"
        table.add_row(
            str(idx),
            series_label,
            issue.issue_number,
            issue.legacy_number or "—",
            str(issue.publication_date) if issue.publication_date else "—",
            issue.story_title or "—",
            series.publisher if series else "—",
        )

    console.print(table)


def print_issue_detail(issue, series) -> None:
    """Print a single issue's full detail in a panel."""
    series_label = f"{series.title} ({series.start_year})" if series else "Unknown"
    lines = [
        f"[header]Series:[/header]      {series_label}",
        f"[header]Issue #:[/header]     {issue.issue_number}",
        f"[header]LGY #:[/header]       {issue.legacy_number or '—'}",
        f"[header]Pub Date:[/header]    {issue.publication_date or '—'}",
        f"[header]Story:[/header]       {issue.story_title or '—'}",
        f"[header]Publisher:[/header]   {series.publisher if series else '—'}",
        f"[header]Writer:[/header]      {issue.writer or '—'}",
        f"[header]Artist:[/header]      {issue.artist or '—'}",
    ]
    if issue.description:
        lines.append(f"\n[muted]{issue.description[:300]}...[/muted]")

    content = "\n".join(lines)
    console.print(Panel(content, title="[bold green]Issue Detail[/bold green]", border_style="green"))


def print_volumes_table(volumes: list) -> None:
    """Display ComicVine volume search results."""
    table = Table(
        show_header=True,
        header_style="bold green",
        border_style="green",
        style="green",
    )
    table.add_column("#", style="dim green", width=4)
    table.add_column("Title", style="bold green", min_width=25)
    table.add_column("Year", style="yellow", width=6)
    table.add_column("Publisher", style="green", width=15)
    table.add_column("Issues", style="dim green", width=7)

    for idx, vol in enumerate(volumes, 1):
        publisher = vol.get("publisher", {})
        publisher_name = publisher.get("name", "—") if publisher else "—"
        table.add_row(
            str(idx),
            vol.get("name", "—"),
            str(vol.get("start_year") or "—"),
            publisher_name,
            str(vol.get("count_of_issues", "—")),
        )

    console.print(table)
