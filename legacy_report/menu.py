"""
Main menu and all TUI flows for Legacy Report.
"""
from datetime import datetime, date
from typing import Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from sqlmodel import select, Session

from legacy_report import comicvine
from legacy_report.config import get_api_key, get_config, set_api_key
from legacy_report.db import get_session
from legacy_report.publishers import filter_volumes_by_tier
from legacy_report.display import (
    console,
    print_error,
    print_header,
    print_info,
    print_issue_detail,
    print_issues_table,
    print_muted,
    print_success,
    print_volumes_table,
)
from legacy_report.models import Issue, Series


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session() -> Session:
    """Unwrap the generator-based get_session for direct use in menu flows."""
    gen = get_session()
    return next(gen)


def _build_series_map(session: Session, issues: list) -> dict:
    ids = {i.series_id for i in issues}
    if not ids:
        return {}
    series_list = session.exec(select(Series).where(Series.id.in_(ids))).all()
    return {s.id: s for s in series_list}


def _prompt_issue_fields(defaults: dict) -> dict:
    """Prompt the user to confirm or override issue fields."""
    console.print("\n[secondary]Confirm / edit the fields below (press Enter to keep):[/secondary]\n")

    issue_number = inquirer.text(
        message="Issue number:",
        default=defaults.get("issue_number") or "",
    ).execute()

    legacy_number = inquirer.text(
        message="Legacy (LGY) number:",
        default=defaults.get("legacy_number") or "",
    ).execute()

    pub_date_raw = inquirer.text(
        message="Publication date (YYYY-MM-DD):",
        default=defaults.get("publication_date") or "",
    ).execute()

    story_title = inquirer.text(
        message="Story title:",
        default=defaults.get("story_title") or "",
    ).execute()

    writer = inquirer.text(
        message="Writer:",
        default=defaults.get("writer") or "",
    ).execute()

    artist = inquirer.text(
        message="Artist:",
        default=defaults.get("artist") or "",
    ).execute()

    pub_date: Optional[date] = None
    if pub_date_raw:
        try:
            pub_date = date.fromisoformat(pub_date_raw[:10])
        except ValueError:
            print_error(f"Invalid date '{pub_date_raw}' — leaving blank.")

    return {
        "issue_number": issue_number or defaults.get("issue_number", ""),
        "legacy_number": legacy_number or None,
        "publication_date": pub_date,
        "story_title": story_title or None,
        "writer": writer or None,
        "artist": artist or None,
    }


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------

def search_collection() -> None:
    console.rule("[green]Search My Collection[/green]")
    query = inquirer.text(message="Search by title:").execute()
    if not query.strip():
        return

    session = _get_session()
    series_results = session.exec(
        select(Series).where(Series.title.ilike(f"%{query}%"))
    ).all()

    if not series_results:
        print_muted("No matching titles in your collection.")
        session.close()
        return

    series_ids = [s.id for s in series_results]
    issues = session.exec(
        select(Issue)
        .where(Issue.series_id.in_(series_ids))
        .order_by(Issue.publication_date)
    ).all()

    series_map = {s.id: s for s in series_results}
    print_issues_table(issues, series_map)

    if not issues:
        session.close()
        return

    view = inquirer.confirm(message="View detail on an issue?", default=False).execute()
    if view:
        choices = [
            Choice(
                value=issue,
                name=f"{series_map[issue.series_id].title} ({series_map[issue.series_id].start_year}) "
                     f"#{issue.issue_number} — {issue.publication_date or 'no date'}",
            )
            for issue in issues
        ]
        selected = inquirer.select(message="Select issue:", choices=choices).execute()
        print_issue_detail(selected, series_map.get(selected.series_id))

    session.close()


def add_issue() -> None:
    console.rule("[green]Add Issue[/green]")

    if not get_api_key():
        print_error("No ComicVine API key set. Go to Setup > Set ComicVine API Key first.")
        return

    query = inquirer.text(message="Search ComicVine for title:").execute()
    if not query.strip():
        return

    print_info("Searching ComicVine...")
    try:
        volumes = comicvine.search_volumes(query)
    except Exception as e:
        print_error(f"ComicVine search failed: {e}")
        return

    volumes = filter_volumes_by_tier(volumes)
    if not volumes:
        print_muted("No results found on ComicVine for US/UK/EU publishers.")
        return

    print_volumes_table(volumes)
    volume_choices = [
        Choice(
            value=vol,
            name=f"{vol.get('name')} ({vol.get('start_year') or '?'}) — "
                 f"{(vol.get('publisher') or {}).get('name', '?')} — "
                 f"{vol.get('count_of_issues', '?')} issues",
        )
        for vol in volumes
    ]
    volume_choices.append(Choice(value=None, name="Cancel"))
    selected_vol = inquirer.select(message="Select series:", choices=volume_choices).execute()

    if selected_vol is None:
        return

    print_info(f"Fetching issues for {selected_vol['name']}...")
    try:
        cv_issues = comicvine.get_issues_for_volume(str(selected_vol["id"]))
    except Exception as e:
        print_error(f"Failed to fetch issues: {e}")
        return

    if not cv_issues:
        print_muted("No issues found for this series on ComicVine.")
        return

    issue_choices = [
        Choice(
            value=iss,
            name=f"#{iss.get('issue_number', '?')} — {iss.get('name') or 'untitled'} ({iss.get('cover_date', '?')})",
        )
        for iss in cv_issues
    ]
    issue_choices.append(Choice(value=None, name="Cancel"))
    selected_iss = inquirer.select(message="Select issue:", choices=issue_choices).execute()

    if selected_iss is None:
        return

    # Build defaults from ComicVine data
    credits = selected_iss.get("person_credits") or []
    writer = next((p["name"] for p in credits if "writer" in (p.get("role") or "").lower()), None)
    artist = next((p["name"] for p in credits if "artist" in (p.get("role") or "").lower()), None)

    # Auto-calculate LGY number from prior volumes on ComicVine
    lgy_number = ""
    try:
        lgy_number = comicvine.calculate_lgy_number(
            selected_vol, selected_iss.get("issue_number", "")
        ) or ""
    except Exception:
        pass
    if lgy_number:
        print_info(f"Auto-calculated LGY #{lgy_number} — review and edit if needed.")

    defaults = {
        "issue_number": selected_iss.get("issue_number", ""),
        "legacy_number": lgy_number,
        "publication_date": selected_iss.get("cover_date", ""),
        "story_title": selected_iss.get("name", ""),
        "writer": writer or "",
        "artist": artist or "",
    }

    fields = _prompt_issue_fields(defaults)

    # Get or create the Series record
    session = _get_session()
    publisher_data = selected_vol.get("publisher") or {}
    publisher_name = publisher_data.get("name")
    start_year = selected_vol.get("start_year") or 0

    existing_series = session.exec(
        select(Series).where(
            Series.title == selected_vol["name"],
            Series.start_year == start_year,
        )
    ).first()

    if existing_series:
        series = existing_series
    else:
        series = Series(
            title=selected_vol["name"],
            start_year=start_year,
            publisher=publisher_name,
            comicvine_id=str(selected_vol["id"]),
            description=selected_vol.get("description"),
        )
        session.add(series)
        session.flush()

    issue = Issue(
        series_id=series.id,
        issue_number=fields["issue_number"],
        legacy_number=fields["legacy_number"],
        publication_date=fields["publication_date"],
        story_title=fields["story_title"],
        writer=fields["writer"],
        artist=fields["artist"],
        description=selected_iss.get("description"),
        cover_image_url=(selected_iss.get("image") or {}).get("medium_url"),
        comicvine_id=str(selected_iss["id"]),
    )
    session.add(issue)
    session.commit()
    print_success(f"Added: {series.title} ({series.start_year}) #{issue.issue_number}")
    session.close()


def edit_issue() -> None:
    console.rule("[green]Edit Issue[/green]")
    query = inquirer.text(message="Search your collection:").execute()
    if not query.strip():
        return

    session = _get_session()
    series_results = session.exec(
        select(Series).where(Series.title.ilike(f"%{query}%"))
    ).all()

    if not series_results:
        print_muted("No matching titles found.")
        session.close()
        return

    series_ids = [s.id for s in series_results]
    issues = session.exec(
        select(Issue)
        .where(Issue.series_id.in_(series_ids))
        .order_by(Issue.publication_date)
    ).all()

    series_map = {s.id: s for s in series_results}

    if not issues:
        print_muted("No issues found.")
        session.close()
        return

    choices = [
        Choice(
            value=issue,
            name=f"{series_map[issue.series_id].title} ({series_map[issue.series_id].start_year}) "
                 f"#{issue.issue_number} LGY#{issue.legacy_number or '—'} — {issue.publication_date or 'no date'}",
        )
        for issue in issues
    ]
    choices.append(Choice(value=None, name="Cancel"))
    selected = inquirer.select(message="Select issue to edit:", choices=choices).execute()

    if selected is None:
        session.close()
        return

    defaults = {
        "issue_number": selected.issue_number or "",
        "legacy_number": selected.legacy_number or "",
        "publication_date": str(selected.publication_date) if selected.publication_date else "",
        "story_title": selected.story_title or "",
        "writer": selected.writer or "",
        "artist": selected.artist or "",
    }

    fields = _prompt_issue_fields(defaults)
    selected.issue_number = fields["issue_number"]
    selected.legacy_number = fields["legacy_number"]
    selected.publication_date = fields["publication_date"]
    selected.story_title = fields["story_title"]
    selected.writer = fields["writer"]
    selected.artist = fields["artist"]
    selected.updated_at = datetime.utcnow()
    session.add(selected)
    session.commit()
    print_success("Issue updated.")
    session.close()


def delete_issue() -> None:
    console.rule("[green]Delete Issue[/green]")
    query = inquirer.text(message="Search your collection:").execute()
    if not query.strip():
        return

    session = _get_session()
    series_results = session.exec(
        select(Series).where(Series.title.ilike(f"%{query}%"))
    ).all()

    if not series_results:
        print_muted("No matching titles found.")
        session.close()
        return

    series_ids = [s.id for s in series_results]
    issues = session.exec(
        select(Issue)
        .where(Issue.series_id.in_(series_ids))
        .order_by(Issue.publication_date)
    ).all()

    series_map = {s.id: s for s in series_results}

    if not issues:
        print_muted("No issues found.")
        session.close()
        return

    choices = [
        Choice(
            value=issue,
            name=f"{series_map[issue.series_id].title} ({series_map[issue.series_id].start_year}) "
                 f"#{issue.issue_number} — {issue.publication_date or 'no date'}",
        )
        for issue in issues
    ]
    choices.append(Choice(value=None, name="Cancel"))
    selected = inquirer.select(message="Select issue to delete:", choices=choices).execute()

    if selected is None:
        session.close()
        return

    series = series_map.get(selected.series_id)
    label = f"{series.title} ({series.start_year}) #{selected.issue_number}" if series else f"Issue #{selected.issue_number}"
    confirmed = inquirer.confirm(
        message=f"Delete {label}?", default=False
    ).execute()

    if confirmed:
        session.delete(selected)
        session.commit()
        print_success(f"Deleted: {label}")
    else:
        print_muted("Cancelled.")

    session.close()


def setup_config() -> None:
    console.rule("[green]Setup / Configuration[/green]")
    choice = inquirer.select(
        message="Configuration:",
        choices=[
            Choice(value="set_key", name="Set ComicVine API Key"),
            Choice(value="view", name="View current config"),
            Choice(value="back", name="Back"),
        ],
    ).execute()

    if choice == "set_key":
        key = inquirer.secret(message="Enter your ComicVine API key:").execute()
        if not key.strip():
            print_muted("No key entered.")
            return
        print_info("Validating key with ComicVine...")
        if comicvine.validate_api_key(key):
            set_api_key(key)
            print_success("API key saved.")
        else:
            print_error("Key validation failed. Check the key and try again.")

    elif choice == "view":
        config = get_config()
        key = config.get("comicvine_api_key", "")
        masked_key = f"{key[:4]}{'*' * (len(key) - 4)}" if len(key) > 4 else ("(not set)" if not key else key)
        print_info(f"API key:      {masked_key}")
        print_info(f"Cache TTL:    {config.get('cache_ttl_hours', 24)} hours")
        print_info(f"Database:     {config.get('db_path')}")


# ---------------------------------------------------------------------------
# Main menu loop
# ---------------------------------------------------------------------------

def main_menu() -> None:
    with console.screen(hide_cursor=False):
        _main_menu_loop()


def _main_menu_loop() -> None:
    while True:
        console.clear()
        console.print()
        print_header()
        console.print()

        action = inquirer.rawlist(
            message="Main Menu",
            choices=[
                Choice(value="search", name="Search My Collection"),
                Choice(value="add", name="Add Issue"),
                Choice(value="edit", name="Edit Issue"),
                Choice(value="delete", name="Delete Issue"),
                Choice(value="setup", name="Setup / Configuration"),
                Choice(value="quit", name="Quit"),
            ],
        ).execute()

        if action == "search":
            search_collection()
        elif action == "add":
            add_issue()
        elif action == "edit":
            edit_issue()
        elif action == "delete":
            delete_issue()
        elif action == "setup":
            setup_config()
        elif action == "quit":
            print_muted("Goodbye.")
            break
