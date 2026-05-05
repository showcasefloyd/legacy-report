"""Textual full-screen TUI for Legacy Report.

Two-pane layout:
  Left  — Series sidebar (all series + per-series filter)
  Right — Issues DataTable (responsive, fills terminal)

Footer shows hotkeys. Enter opens an issue detail modal.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlmodel import select, Session
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Label, ListItem, ListView, Static

from legacy_report import __version__
from legacy_report.config import get_config
from legacy_report.db import delete_issue as db_delete_issue
from legacy_report.db import get_engine, update_issue
from legacy_report.models import Issue, Series

_ALL_SERIES_ID = -1

_FIELD_LABEL_WIDTH = 14  # left-column width in Edit modal


# ── Shared modal CSS ──────────────────────────────────────────────────────────

_MODAL_BASE_CSS = """
    align: center middle;
"""

_MODAL_BOX_CSS = """
    background: #001a00;
    border: solid #00ff41;
    padding: 1 2;
    color: #00ff41;
"""


# ── Detail modal ──────────────────────────────────────────────────────────────

class IssueDetailScreen(ModalScreen):
    """Full-detail overlay for a single issue. Read-only."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close", show=False),
    ]

    DEFAULT_CSS = """
    IssueDetailScreen { align: center middle; }
    IssueDetailScreen #detail-box {
        width: 66;
        height: auto;
        max-height: 85%;
        background: #001a00;
        border: solid #00ff41;
        padding: 1 2;
        color: #00ff41;
    }
    """

    def __init__(self, issue: Issue, series: Optional[Series]) -> None:
        super().__init__()
        self._issue = issue
        self._series = series

    def compose(self) -> ComposeResult:
        i = self._issue
        s = self._series
        series_label = f"{s.title} ({s.start_year})" if s else "Unknown"
        stars = ("★" * i.rating + "☆" * (5 - i.rating)) if i.rating else "—"
        lines = [
            f"  [bold]Series:[/bold]      {series_label}",
            f"  [bold]Issue #:[/bold]     {i.issue_number}",
            f"  [bold]LGY #:[/bold]       {i.legacy_number or '—'}",
            f"  [bold]Pub Date:[/bold]    {i.publication_date or '—'}",
            f"  [bold]Story:[/bold]       {i.story_title or '—'}",
            f"  [bold]Publisher:[/bold]   {s.publisher if s else '—'}",
            f"  [bold]Writer:[/bold]      {i.writer or '—'}",
            f"  [bold]Artist:[/bold]      {i.artist or '—'}",
            f"  [bold]Read:[/bold]        {'Yes' if i.read else 'No'}",
            f"  [bold]Rating:[/bold]      {stars}",
        ]
        if i.description:
            desc = i.description[:400].replace("[", r"\[")
            lines.append(f"\n  [dim]{desc}[/dim]")
        lines.append("\n  [dim]Esc · close[/dim]")
        yield Static("\n".join(lines), id="detail-box", markup=True)


# ── Delete confirmation modal ─────────────────────────────────────────────────

class DeleteConfirmScreen(ModalScreen):
    """Ask the user to confirm deletion of an issue."""

    BINDINGS = [
        Binding("d", "confirm_delete", "Delete"),
        Binding("escape", "cancel_delete", "Cancel"),
        Binding("n", "cancel_delete", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    DeleteConfirmScreen { align: center middle; }
    DeleteConfirmScreen #confirm-box {
        width: 62;
        height: auto;
        background: #1a0000;
        border: solid #ff4444;
        padding: 1 2;
        color: #00ff41;
    }
    """

    def __init__(self, issue: Issue, series: Optional[Series]) -> None:
        super().__init__()
        self._issue = issue
        self._series = series

    def compose(self) -> ComposeResult:
        s = self._series
        label = (
            f"{s.title} ({s.start_year}) #{self._issue.issue_number}"
            if s else f"Issue #{self._issue.issue_number}"
        )
        yield Static(
            f"  [bold]Delete this issue?[/bold]\n\n"
            f"  {label}\n\n"
            f"  [dim]D · confirm    Esc · cancel[/dim]",
            id="confirm-box",
            markup=True,
        )

    def action_confirm_delete(self) -> None:
        self.dismiss(True)

    def action_cancel_delete(self) -> None:
        self.dismiss(False)


# ── Edit Issue modal ──────────────────────────────────────────────────────────

class EditIssueScreen(ModalScreen):
    """Editable form for an existing issue."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel_edit", "Cancel"),
    ]

    DEFAULT_CSS = """
    EditIssueScreen { align: center middle; }
    EditIssueScreen #edit-box {
        width: 72;
        height: auto;
        max-height: 90%;
        background: #001a00;
        border: solid #00ff41;
        padding: 1 2;
        color: #00ff41;
    }
    EditIssueScreen .field-row {
        height: 3;
        margin-bottom: 0;
    }
    EditIssueScreen .field-label {
        width: 15;
        content-align: right middle;
        color: #00aa22;
        padding-right: 1;
    }
    EditIssueScreen .field-input {
        width: 1fr;
        background: #002200;
        color: #00ff41;
        border: tall #1a6e1a;
    }
    EditIssueScreen .field-input:focus {
        border: tall #00ff41;
    }
    EditIssueScreen #edit-buttons {
        height: 3;
        margin-top: 1;
        align: right middle;
    }
    EditIssueScreen Button {
        margin-left: 1;
        background: #002200;
        border: tall #1a6e1a;
        color: #00ff41;
        min-width: 14;
    }
    EditIssueScreen Button:focus,
    EditIssueScreen Button:hover {
        background: #004400;
        border: tall #00ff41;
    }
    EditIssueScreen #btn-save {
        background: #003300;
    }
    """

    def __init__(self, issue: Issue, series: Optional[Series]) -> None:
        super().__init__()
        self._issue = issue
        self._series = series

    def compose(self) -> ComposeResult:
        i = self._issue
        s = self._series
        series_label = f"{s.title} ({s.start_year})" if s else "Unknown"

        def field_row(label: str, field_id: str, value: str) -> Horizontal:
            return Horizontal(
                Label(f"{label}:", classes="field-label"),
                Input(value=value, id=field_id, classes="field-input"),
                classes="field-row",
            )

        with Vertical(id="edit-box"):
            yield Label(
                f"  [bold]Edit Issue[/bold]  [dim]{series_label}[/dim]",
                markup=True,
            )
            yield field_row("Issue #",    "ei-issue-number",  i.issue_number or "")
            yield field_row("LGY #",      "ei-legacy-number", i.legacy_number or "")
            yield field_row("Pub Date",   "ei-pub-date",      str(i.publication_date) if i.publication_date else "")
            yield field_row("Story",      "ei-story-title",   i.story_title or "")
            yield field_row("Writer",     "ei-writer",        i.writer or "")
            yield field_row("Artist",     "ei-artist",        i.artist or "")
            yield field_row("Rating 1-5", "ei-rating",        str(i.rating) if i.rating else "")
            with Horizontal(id="edit-buttons"):
                yield Button("Save  Ctrl+S", id="btn-save")
                yield Button("Cancel  Esc",  id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self._do_save()
        else:
            self.dismiss(False)

    def action_save(self) -> None:
        self._do_save()

    def action_cancel_edit(self) -> None:
        self.dismiss(False)

    def _do_save(self) -> None:
        def val(widget_id: str) -> str:
            return self.query_one(f"#{widget_id}", Input).value.strip()

        issue_number = val("ei-issue-number")
        if not issue_number:
            self.notify("Issue # is required.", severity="error")
            return

        # Parse pub date
        pub_date_raw = val("ei-pub-date")
        pub_date: Optional[date] = None
        if pub_date_raw:
            try:
                pub_date = date.fromisoformat(pub_date_raw[:10])
            except ValueError:
                self.notify("Invalid date — use YYYY-MM-DD.", severity="error")
                return

        # Parse rating
        rating_raw = val("ei-rating")
        rating: Optional[int] = None
        if rating_raw:
            try:
                r = int(rating_raw)
                if not 1 <= r <= 5:
                    raise ValueError
                rating = r
            except ValueError:
                self.notify("Rating must be 1–5 or blank.", severity="error")
                return

        with Session(get_engine()) as session:
            db_issue = session.get(Issue, self._issue.id)
            if db_issue is None:
                self.notify("Issue no longer exists.", severity="error")
                self.dismiss(False)
                return
            update_issue(
                session,
                db_issue,
                issue_number=issue_number or None,
                legacy_number=val("ei-legacy-number") or None,
                publication_date=pub_date,
                story_title=val("ei-story-title") or None,
                writer=val("ei-writer") or None,
                artist=val("ei-artist") or None,
                rating=rating,
            )

        self.dismiss(True)


# ── Main app ──────────────────────────────────────────────────────────────────

class LegacyReportApp(App):
    """Full-screen two-pane collection browser."""

    CSS = """
    Screen {
        background: #0d0d0d;
        color: #00cc33;
    }
    #app-header {
        background: #003300;
        color: #00ff41;
        content-align: center middle;
        text-style: bold;
        height: 1;
    }
    Horizontal { height: 1fr; }
    #sidebar {
        width: 28;
        border-right: solid #1a6e1a;
        background: #0d0d0d;
    }
    #sidebar-title {
        background: #002200;
        color: #00ff41;
        text-style: bold;
        content-align: center middle;
        height: 1;
        border-bottom: solid #1a6e1a;
    }
    ListView {
        background: #0d0d0d;
        border: none;
        padding: 0;
    }
    ListView > ListItem {
        background: #0d0d0d;
        color: #00aa22;
        padding: 0 0;
        height: 1;
    }
    ListView > ListItem:hover {
        background: #002200;
        color: #00ff41;
    }
    ListView > ListItem.--highlight {
        background: #004400;
        color: #00ff41;
        text-style: bold;
    }
    #main-pane { background: #0d0d0d; }
    #main-title {
        background: #002200;
        color: #00ff41;
        text-style: bold;
        height: 1;
        border-bottom: solid #1a6e1a;
        padding: 0 1;
    }
    #search-input {
        display: none;
        height: 3;
        background: #001a00;
        border: tall #1a6e1a;
        color: #00ff41;
        margin: 0;
        padding: 0 1;
    }
    #search-input:focus { border: tall #00ff41; }
    DataTable { background: #0d0d0d; }
    DataTable > .datatable--header {
        background: #001a00;
        color: #00ff41;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #004400;
        color: #00ff41;
        text-style: bold;
    }
    DataTable > .datatable--hover { background: #002200; }
    Footer {
        background: #001a00;
        color: #00cc33;
    }
    Footer > .footer--key {
        background: #004400;
        color: #00ff41;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("a", "do_add", "Add"),
        Binding("e", "do_edit", "Edit"),
        Binding("d", "do_delete", "Delete"),
        Binding("r", "do_toggle_read", "Read"),
        Binding("slash", "do_search", "Search", key_display="/"),
        Binding("x", "do_export", "Export"),
        Binding("c", "do_config", "Config"),
        Binding("tab", "switch_focus", "Switch Panel", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Label(f"  LEGACY REPORT {__version__}", id="app-header")
        yield Horizontal(
            Vertical(
                Label("  SERIES", id="sidebar-title"),
                ListView(id="series-list"),
                id="sidebar",
            ),
            Vertical(
                Label("  ISSUES", id="main-title"),
                Input(placeholder="Filter issues… (Esc to clear)", id="search-input"),
                DataTable(id="issues-table", cursor_type="row", zebra_stripes=True),
                id="main-pane",
            ),
        )
        yield Footer()

    async def on_mount(self) -> None:
        self._series_data: list[Series] = []
        self._issues_data: list[Issue] = []
        self._current_issues: list[Issue] = []   # full list for current series
        self._displayed_issues: list[Issue] = [] # what is actually in the DataTable
        self._filter_text: str = ""
        self._current_series_id: int = _ALL_SERIES_ID
        self._counts: dict[int, int] = {}
        await self._load_data()
        self.query_one("#issues-table", DataTable).focus()

    # ── Data loading ──────────────────────────────────────────────────────────

    async def _load_data(self, restore_series_id: Optional[int] = None) -> None:
        """Reload everything from DB and refresh both panes."""
        with Session(get_engine(), expire_on_commit=False) as session:
            self._series_data = list(
                session.exec(select(Series).order_by(Series.title)).all()
            )
            self._issues_data = list(session.exec(select(Issue)).all())

        self._counts = {}
        for issue in self._issues_data:
            self._counts[issue.series_id] = self._counts.get(issue.series_id, 0) + 1

        total_issues = len(self._issues_data)
        total_series = len(self._series_data)
        self.query_one("#app-header", Label).update(
            f"  LEGACY REPORT {__version__}  ·  "
            f"{total_issues} issue{'s' if total_issues != 1 else ''}  "
            f"across {total_series} series"
        )

        await self._refresh_sidebar()
        target_id = (
            restore_series_id
            if restore_series_id is not None
            else self._current_series_id
        )
        self._load_issues(target_id)
        self._restore_sidebar_selection(target_id)

    async def _refresh_sidebar(self) -> None:
        lv = self.query_one("#series-list", ListView)
        await lv.clear()
        total = sum(self._counts.values())
        await lv.append(ListItem(Label(f" ALL  ({total})"), id="item-all"))
        for s in self._series_data:
            count = self._counts.get(s.id, 0)
            title = s.title if len(s.title) <= 18 else s.title[:17] + "\u2026"
            await lv.append(
                ListItem(Label(f" {title:<18} {count:>3}"), id=f"item-{s.id}")
            )

    def _restore_sidebar_selection(self, series_id: int) -> None:
        lv = self.query_one("#series-list", ListView)
        if series_id == _ALL_SERIES_ID:
            lv.index = 0
            return
        for i, s in enumerate(self._series_data, 1):
            if s.id == series_id:
                lv.index = i
                return
        lv.index = 0

    def _load_issues(self, series_id: int) -> None:
        """Set _current_issues for a series and render the table."""
        self._current_series_id = series_id
        self._filter_text = ""
        si = self.query_one("#search-input", Input)
        si.value = ""
        si.display = False

        if series_id == _ALL_SERIES_ID:
            issues = list(self._issues_data)
        else:
            issues = [i for i in self._issues_data if i.series_id == series_id]

        issues.sort(key=lambda i: (i.publication_date or date.min))
        self._current_issues = issues
        self._render_table()

    def _render_table(self) -> None:
        """Render DataTable from _current_issues, applying _filter_text."""
        needle = self._filter_text.lower()
        series_map = {s.id: s for s in self._series_data}

        if needle:
            displayed = [
                i for i in self._current_issues
                if needle in (i.story_title or "").lower()
                or needle in (i.issue_number or "").lower()
                or needle in (i.legacy_number or "").lower()
                or needle in (series_map.get(i.series_id, Series(title="", start_year=0)).title).lower()
            ]
        else:
            displayed = list(self._current_issues)

        self._displayed_issues = displayed

        table = self.query_one("#issues-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Series", "Issue #", "LGY #", "Pub Date", "Story", "R")

        for issue in displayed:
            s = series_map.get(issue.series_id)
            series_label = f"{s.title} ({s.start_year})" if s else "\u2014"
            table.add_row(
                series_label,
                issue.issue_number or "\u2014",
                issue.legacy_number or "\u2014",
                str(issue.publication_date) if issue.publication_date else "\u2014",
                issue.story_title or "\u2014",
                "\u2713" if issue.read else "",
            )

        count_label = (
            f"{len(displayed)} of {len(self._current_issues)}"
            if needle else str(len(displayed))
        )
        if self._current_series_id == _ALL_SERIES_ID:
            title_str = f"ALL ISSUES  ({count_label})"
        else:
            s = series_map.get(self._current_series_id)
            title_str = (
                f"{s.title} ({s.start_year})  \u2014  {count_label} issue(s)"
                if s else f"{count_label} issue(s)"
            )
        self.query_one("#main-title", Label).update(f"  {title_str}")

    def _apply_filter(self, text: str) -> None:
        self._filter_text = text
        self._render_table()

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id == "item-all":
            self._load_issues(_ALL_SERIES_ID)
        elif item_id.startswith("item-"):
            try:
                self._load_issues(int(item_id.split("-", 1)[1]))
            except (ValueError, IndexError):
                pass
        self.query_one("#issues-table", DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._show_detail(event.cursor_row)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._apply_filter(event.value)

    def on_key(self, event: Key) -> None:
        si = self.query_one("#search-input", Input)
        if event.key == "escape" and si.display and si.has_focus:
            si.value = ""
            si.display = False
            self._apply_filter("")
            self.query_one("#issues-table", DataTable).focus()
            event.stop()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _show_detail(self, row: int) -> None:
        if not self._displayed_issues or row < 0 or row >= len(self._displayed_issues):
            return
        issue = self._displayed_issues[row]
        series = next((s for s in self._series_data if s.id == issue.series_id), None)
        self.push_screen(IssueDetailScreen(issue, series))

    def _get_focused_issue(self) -> Optional[Issue]:
        table = self.query_one("#issues-table", DataTable)
        row = table.cursor_row
        if not self._displayed_issues or row < 0 or row >= len(self._displayed_issues):
            return None
        return self._displayed_issues[row]

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_do_search(self) -> None:
        """Toggle the live-filter input bar."""
        si = self.query_one("#search-input", Input)
        if si.display:
            si.value = ""
            si.display = False
            self._apply_filter("")
            self.query_one("#issues-table", DataTable).focus()
        else:
            si.display = True
            si.focus()

    async def action_do_delete(self) -> None:
        issue = self._get_focused_issue()
        if not issue:
            return
        series = next((s for s in self._series_data if s.id == issue.series_id), None)

        async def on_confirmed(confirmed: bool) -> None:
            if confirmed:
                with Session(get_engine()) as session:
                    db_issue = session.get(Issue, issue.id)
                    if db_issue:
                        db_delete_issue(session, db_issue)
                await self._load_data(restore_series_id=self._current_series_id)

        self.push_screen(DeleteConfirmScreen(issue, series), on_confirmed)

    async def action_do_edit(self) -> None:
        issue = self._get_focused_issue()
        if not issue:
            return
        series = next((s for s in self._series_data if s.id == issue.series_id), None)

        async def on_saved(saved: bool) -> None:
            if saved:
                await self._load_data(restore_series_id=self._current_series_id)

        self.push_screen(EditIssueScreen(issue, series), on_saved)

    async def action_do_toggle_read(self) -> None:
        issue = self._get_focused_issue()
        if not issue:
            return
        with Session(get_engine()) as session:
            db_issue = session.get(Issue, issue.id)
            if db_issue:
                db_issue.read = not db_issue.read
                session.commit()
        await self._load_data(restore_series_id=self._current_series_id)

    def action_do_export(self) -> None:
        """Export collection to CSV and notify in-TUI — no suspend needed."""
        config = get_config()
        out_path = Path.home() / "legacy_report_export.csv"
        series_map = {s.id: s for s in self._series_data}
        issues = sorted(
            self._issues_data,
            key=lambda i: (i.series_id, i.publication_date or date.min),
        )
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
            self.notify(f"Exported {len(issues)} issue(s) to {out_path}")
        except OSError as e:
            self.notify(str(e), title="Export Failed", severity="error")

    async def action_do_add(self) -> None:
        # Phase 4 — AddIssueScreen not yet built; suspend for now
        import gc
        from legacy_report.menu import add_issue
        with self.suspend():
            add_issue()
        gc.collect()
        await self._load_data(restore_series_id=self._current_series_id)

    def action_do_config(self) -> None:
        # Phase 3 — ConfigScreen not yet built; suspend for now
        import gc
        from legacy_report.menu import setup_config
        with self.suspend():
            setup_config()
        gc.collect()

    def action_switch_focus(self) -> None:
        table = self.query_one("#issues-table", DataTable)
        lv = self.query_one("#series-list", ListView)
        if table.has_focus:
            lv.focus()
        else:
            table.focus()

