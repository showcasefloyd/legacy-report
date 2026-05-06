"""
Main menu and all TUI flows for Legacy Report.
"""
from datetime import datetime, date
from fractions import Fraction
from typing import Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from sqlmodel import func, select, Session

from legacy_report import comicvine
from legacy_report.config import get_api_key, get_config, set_api_key
from legacy_report.db import get_engine, get_or_create_series, create_issue, update_issue
from legacy_report.db import delete_issue as _db_delete_issue
from legacy_report.publishers import filter_volumes_by_tier
from legacy_report.display import (
    console,
    print_cv_issues_table,
    print_error,
    print_header,
    print_info,
    print_issue_detail,
    print_issues_table,
    print_muted,
    print_series_table,
    print_success,
    print_volumes_table,
)
from legacy_report.models import Issue, Series


PAGE_SIZE = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session() -> Session:
    """Create a session for direct use in menu flows."""
    return Session(get_engine(), expire_on_commit=False)


def _sort_key_num(num_str: str | None) -> tuple:
    """Numeric-aware sort key for issue/legacy number strings.

    Handles integers, decimals (1.5), and fractions (1/2). Non-numeric
    strings (e.g. 'Infinity') sort after all numeric values, lexicographically.
    """
    stripped_num = (num_str or "").strip()
    try:
        return (0, float(Fraction(stripped_num)))
    except (ValueError, ZeroDivisionError):
        return (1, stripped_num)


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

    rating_raw = inquirer.text(
        message="Personal rating (1–5, blank for none):",
        default=str(defaults.get("rating") or ""),
    ).execute()

    pub_date: Optional[date] = None
    if pub_date_raw:
        try:
            pub_date = date.fromisoformat(pub_date_raw[:10])
        except ValueError:
            print_error(f"Invalid date '{pub_date_raw}' — leaving blank.")

    rating: Optional[int] = None
    if rating_raw.strip():
        try:
            r = int(rating_raw.strip())
            if 1 <= r <= 5:
                rating = r
            else:
                print_error("Rating must be 1–5 — leaving blank.")
        except ValueError:
            print_error(f"Invalid rating '{rating_raw}' — leaving blank.")

    return {
        "issue_number": issue_number or defaults.get("issue_number", ""),
        "legacy_number": legacy_number or None,
        "publication_date": pub_date,
        "story_title": story_title or None,
        "writer": writer or None,
        "artist": artist or None,
        "rating": rating,
    }


def _paginated_volume_select(volumes: list):
    """Display volumes in pages and return the selected volume dict, or None to cancel."""
    total = len(volumes)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = 0

    while True:
        start = page * PAGE_SIZE
        page_vols = volumes[start : start + PAGE_SIZE]

        console.clear()
        if total_pages > 1:
            print_muted(f"Page {page + 1} of {total_pages}  ({total} results total)")
        print_volumes_table(page_vols)

        nav_hints = []
        if page > 0:
            nav_hints.append("[p]rev")
        if page < total_pages - 1:
            nav_hints.append("[n]ext")
        nav_hints.append("blank to cancel")
        prompt = f"Enter number (1–{len(page_vols)}){', ' + ', '.join(nav_hints) if nav_hints else ''}:"

        raw = inquirer.text(message=prompt).execute().strip()

        if not raw:
            return None
        if raw.lower() == "n" and page < total_pages - 1:
            page += 1
        elif raw.lower() == "p" and page > 0:
            page -= 1
        else:
            try:
                idx = int(raw) - 1
                if idx < 0 or idx >= len(page_vols):
                    raise ValueError
                return page_vols[idx]
            except ValueError:
                print_error(f"Invalid input '{raw}'. Enter a number between 1 and {len(page_vols)}.")


def _paginated_issue_select(issues: list, series_map: dict) -> Optional[int]:
    """Display issues in pages and return the selected issue's ID, or None to cancel."""
    total = len(issues)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = 0

    while True:
        start = page * PAGE_SIZE
        page_issues = issues[start : start + PAGE_SIZE]

        console.clear()
        if total_pages > 1:
            print_muted(f"Page {page + 1} of {total_pages}  ({total} issues total)")
        print_issues_table(page_issues, series_map)

        nav_hints = []
        if page > 0:
            nav_hints.append("[p]rev")
        if page < total_pages - 1:
            nav_hints.append("[n]ext")
        nav_hints.append("blank to cancel")
        prompt = f"Enter number (1–{len(page_issues)}){', ' + ', '.join(nav_hints) if nav_hints else ''}:"

        raw = inquirer.text(message=prompt).execute().strip()

        if not raw:
            return None
        if raw.lower() == "n" and page < total_pages - 1:
            page += 1
        elif raw.lower() == "p" and page > 0:
            page -= 1
        else:
            try:
                idx = int(raw) - 1
                if idx < 0 or idx >= len(page_issues):
                    raise ValueError
                return page_issues[idx].id
            except ValueError:
                print_error(f"Invalid input '{raw}'. Enter a number between 1 and {len(page_issues)}.")


def _paginated_issue_view(issues: list, series_map: dict) -> None:
    """Display issues in pages with optional detail drill-down."""
    total = len(issues)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = 0

    while True:
        start = page * PAGE_SIZE
        page_issues = issues[start : start + PAGE_SIZE]

        console.clear()
        if total_pages > 1:
            print_muted(f"Page {page + 1} of {total_pages}  ({total} issues total)")
        print_issues_table(page_issues, series_map)

        nav_hints = []
        if page > 0:
            nav_hints.append("[p]rev")
        if page < total_pages - 1:
            nav_hints.append("[n]ext")
        nav_hints.append("blank to go back")
        prompt = f"Enter number to view detail (1–{len(page_issues)}){', ' + ', '.join(nav_hints) if nav_hints else ''}:"

        raw = inquirer.text(message=prompt).execute().strip()

        if not raw:
            break
        if raw.lower() == "n" and page < total_pages - 1:
            page += 1
        elif raw.lower() == "p" and page > 0:
            page -= 1
        else:
            try:
                idx = int(raw) - 1
                if idx < 0 or idx >= len(page_issues):
                    raise ValueError
                issue = page_issues[idx]
                console.clear()
                print_issue_detail(issue, series_map.get(issue.series_id))
                inquirer.text(message="Press Enter to go back").execute()
            except ValueError:
                print_error(f"Invalid input '{raw}'. Enter a number between 1 and {len(page_issues)}.")


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
    issues = list(session.exec(
        select(Issue).where(Issue.series_id.in_(series_ids))
    ).all())

    series_map = {s.id: s for s in series_results}

    if not issues:
        print_muted("No issues found.")
        session.close()
        return

    sort_choice = inquirer.select(
        message=f"Found {len(issues)} issue(s). Sort / Filter:",
        choices=[
            Choice(value="pub_date", name="Sort: Publication Date"),
            Choice(value="issue_num", name="Sort: Issue #"),
            Choice(value="lgy_num", name="Sort: LGY #"),
            Choice(value="unread_only", name="Filter: Unread Only"),
            Choice(value="read_only", name="Filter: Read Only"),
            Choice(value="cancel", name="Cancel"),
        ],
    ).execute()

    if sort_choice == "cancel":
        session.close()
        return

    if sort_choice == "unread_only":
        issues = [i for i in issues if not i.read]
        if not issues:
            print_muted("No unread issues found.")
            session.close()
            return
        issues.sort(key=lambda i: i.publication_date or date.min)
    elif sort_choice == "read_only":
        issues = [i for i in issues if i.read]
        if not issues:
            print_muted("No read issues found.")
            session.close()
            return
        issues.sort(key=lambda i: i.publication_date or date.min)
    elif sort_choice == "issue_num":
        issues.sort(key=lambda i: _sort_key_num(i.issue_number))
    elif sort_choice == "lgy_num":
        issues.sort(key=lambda i: _sort_key_num(i.legacy_number))
    else:  # pub_date
        issues.sort(key=lambda i: i.publication_date or date.min)

    _paginated_issue_view(issues, series_map)
    session.close()


def browse_collection() -> None:
    console.rule("[green]Browse Collection[/green]")
    session = _get_session()

    series_list = session.exec(select(Series).order_by(Series.title)).all()
    if not series_list:
        print_muted("Your collection is empty. Use Add Issue to get started.")
        session.close()
        return

    all_issues = session.exec(select(Issue)).all()
    counts: dict = {}
    for issue in all_issues:
        counts[issue.series_id] = counts.get(issue.series_id, 0) + 1

    print_series_table(series_list, counts)

    raw = inquirer.text(
        message=f"Enter number to view series (1–{len(series_list)}), or blank to go back:"
    ).execute().strip()

    if not raw:
        session.close()
        return

    try:
        idx = int(raw) - 1
        if idx < 0 or idx >= len(series_list):
            raise ValueError
        selected_series = series_list[idx]
    except ValueError:
        print_error(f"Invalid input '{raw}'.")
        session.close()
        return

    series_issues = [i for i in all_issues if i.series_id == selected_series.id]
    series_issues.sort(key=lambda i: i.publication_date or date.min)
    _paginated_issue_view(series_issues, {selected_series.id: selected_series})
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

    selected_vol = _paginated_volume_select(volumes)
    if selected_vol is None:
        return

    print_info(f"Fetching issues for {selected_vol['name']}...")
    try:
        _cv_page = comicvine.get_issues_for_volume(str(selected_vol["id"]))
        cv_issues = _cv_page["results"]
    except Exception as e:
        print_error(f"Failed to fetch issues: {e}")
        return

    if not cv_issues:
        print_muted("No issues found for this series on ComicVine.")
        return

    cv_page = 0
    selected_iss = None
    cv_total = _cv_page["total"]
    cv_total_pages = max(1, (cv_total + PAGE_SIZE - 1) // PAGE_SIZE)

    while True:
        cv_start = cv_page * PAGE_SIZE
        cv_page_issues = cv_issues[cv_start : cv_start + PAGE_SIZE]

        console.clear()
        if cv_total_pages > 1:
            print_muted(f"Page {cv_page + 1} of {cv_total_pages}  ({cv_total} issues total)")
        print_cv_issues_table(cv_page_issues)

        cv_nav = []
        if cv_page > 0:
            cv_nav.append("[p]rev")
        if cv_page < cv_total_pages - 1:
            cv_nav.append("[n]ext")
        cv_nav.append("blank to cancel")
        cv_prompt = f"Enter number (1–{len(cv_page_issues)}){', ' + ', '.join(cv_nav) if cv_nav else ''}:"

        cv_raw = inquirer.text(message=cv_prompt).execute().strip()

        if not cv_raw:
            return
        if cv_raw.lower() == "n" and cv_page < cv_total_pages - 1:
            cv_page += 1
        elif cv_raw.lower() == "p" and cv_page > 0:
            cv_page -= 1
        else:
            try:
                cv_idx = int(cv_raw) - 1
                if cv_idx < 0 or cv_idx >= len(cv_page_issues):
                    raise ValueError
                selected_iss = cv_page_issues[cv_idx]
                break
            except ValueError:
                print_error(f"Invalid input '{cv_raw}'. Enter a number between 1 and {len(cv_page_issues)}.")

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

    series, _ = get_or_create_series(
        session,
        title=selected_vol["name"],
        start_year=start_year,
        publisher=publisher_name,
        comicvine_id=str(selected_vol["id"]),
        description=selected_vol.get("description"),
    )

    issue = create_issue(
        session,
        series_id=series.id,
        issue_number=fields["issue_number"],
        legacy_number=fields["legacy_number"] or None,
        publication_date=fields["publication_date"],
        story_title=fields["story_title"] or None,
        writer=fields["writer"] or None,
        artist=fields["artist"] or None,
        description=selected_iss.get("description"),
        cover_image_url=(selected_iss.get("image") or {}).get("medium_url"),
        comicvine_id=str(selected_iss["id"]),
    )
    print_success(f"Added: {series.title} ({series.start_year}) #{issue.issue_number}")
    print_issue_detail(issue, series)
    inquirer.text(message="Press Enter to continue").execute()
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

    selected_id = _paginated_issue_select(issues, series_map)

    if selected_id is None:
        session.close()
        return

    # Re-fetch by ID to get a fresh, session-bound instance not subject to GC
    selected = session.get(Issue, selected_id)
    if selected is None:
        print_error("Issue no longer exists.")
        session.close()
        return

    defaults = {
        "issue_number": selected.issue_number or "",
        "legacy_number": selected.legacy_number or "",
        "publication_date": str(selected.publication_date) if selected.publication_date else "",
        "story_title": selected.story_title or "",
        "writer": selected.writer or "",
        "artist": selected.artist or "",
        "rating": selected.rating,
    }

    fields = _prompt_issue_fields(defaults)
    updated = update_issue(
        session,
        selected,
        issue_number=fields["issue_number"] or None,
        legacy_number=fields["legacy_number"] or None,
        publication_date=fields["publication_date"],
        story_title=fields["story_title"] or None,
        writer=fields["writer"] or None,
        artist=fields["artist"] or None,
        rating=fields["rating"],
    )
    series = series_map.get(updated.series_id)
    print_success("Issue updated.")
    print_issue_detail(updated, series)
    inquirer.text(message="Press Enter to continue").execute()
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

    selected_id = _paginated_issue_select(issues, series_map)

    if selected_id is None:
        session.close()
        return

    # Re-fetch by ID to get a fresh, session-bound instance not subject to GC
    selected = session.get(Issue, selected_id)
    if selected is None:
        print_error("Issue no longer exists.")
        session.close()
        return

    series = series_map.get(selected.series_id)
    label = f"{series.title} ({series.start_year}) #{selected.issue_number}" if series else f"Issue #{selected.issue_number}"
    confirmed = inquirer.confirm(
        message=f"Delete {label}?", default=False
    ).execute()

    if confirmed:
        _db_delete_issue(session, selected)
        print_success(f"Deleted: {label}")
    else:
        print_muted("Cancelled.")

    session.close()


def mark_read_unread() -> None:
    console.rule("[green]Mark as Read / Unread[/green]")
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

    selected_id = _paginated_issue_select(issues, series_map)

    if selected_id is None:
        session.close()
        return

    selected = session.get(Issue, selected_id)
    if selected is None:
        print_error("Issue no longer exists.")
        session.close()
        return

    new_read = not selected.read
    status_label = "read" if new_read else "unread"
    series = series_map.get(selected.series_id)
    label = (
        f"{series.title} ({series.start_year}) #{selected.issue_number}"
        if series
        else f"Issue #{selected.issue_number}"
    )
    confirmed = inquirer.confirm(
        message=f"Mark '{label}' as {status_label}?", default=True
    ).execute()

    if confirmed:
        update_issue(session, selected, read=new_read)
        print_success(f"Marked as {status_label}.")
    else:
        print_muted("Cancelled.")

    session.close()


def export_csv() -> None:
    import csv
    from pathlib import Path as _Path

    console.rule("[green]Export to CSV[/green]")
    default_path = str(_Path.home() / "legacy_report_export.csv")
    path_raw = inquirer.text(
        message="Export file path:",
        default=default_path,
    ).execute().strip()

    if not path_raw:
        return

    out_path = _Path(path_raw).expanduser()

    session = _get_session()
    issues = list(session.exec(
        select(Issue).order_by(Issue.series_id, Issue.publication_date)
    ).all())
    series_map = _build_series_map(session, issues)
    session.close()

    try:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Series", "Start Year", "Publisher",
                "Issue #", "LGY #", "Pub Date",
                "Story Title", "Writer", "Artist",
                "Read", "Rating",
            ])
            for issue in issues:
                s = series_map.get(issue.series_id)
                writer.writerow([
                    s.title if s else "",
                    s.start_year if s else "",
                    s.publisher if s else "",
                    issue.issue_number,
                    issue.legacy_number or "",
                    str(issue.publication_date) if issue.publication_date else "",
                    issue.story_title or "",
                    issue.writer or "",
                    issue.artist or "",
                    "Yes" if issue.read else "No",
                    issue.rating if issue.rating is not None else "",
                ])
    except OSError as e:
        print_error(f"Could not write file: {e}")
        return

    print_success(f"Exported {len(issues)} issue(s) to {out_path}")


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
        _session = _get_session()
        _issue_count = _session.exec(select(func.count()).select_from(Issue)).one()
        _series_count = _session.exec(select(func.count()).select_from(Series)).one()
        _session.close()
        _stats = f"{_issue_count} issue{'s' if _issue_count != 1 else ''} across {_series_count} series"
        print_header(_stats)
        console.print()

        action = inquirer.rawlist(
            message="Main Menu",
            choices=[
                Choice(value="search", name="Search My Collection"),
                Choice(value="browse", name="Browse Collection"),
                Choice(value="add", name="Add Issue"),
                Choice(value="edit", name="Edit Issue"),
                Choice(value="mark_read", name="Mark as Read / Unread"),
                Choice(value="delete", name="Delete Issue"),
                Choice(value="export_csv", name="Export to CSV"),
                Choice(value="setup", name="Setup / Configuration"),
                Choice(value="quit", name="Quit"),
            ],
        ).execute()

        if action == "search":
            search_collection()
        elif action == "browse":
            browse_collection()
        elif action == "add":
            add_issue()
        elif action == "edit":
            edit_issue()
        elif action == "mark_read":
            mark_read_unread()
        elif action == "delete":
            delete_issue()
        elif action == "export_csv":
            export_csv()
        elif action == "setup":
            setup_config()
        elif action == "quit":
            print_muted("Goodbye.")
            break
