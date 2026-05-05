"""Textual full-screen TUI for Legacy Report.

Two-pane layout:
  Left  — Series sidebar (all series + per-series filter)
  Right — Issues DataTable (responsive, fills terminal)

Footer shows hotkeys. Enter opens an issue detail modal.
Add / Edit / Delete / Search suspend the TUI and run the
existing InquirerPy flows, then resume.
"""
from __future__ import annotations

import gc
from datetime import date
from typing import Optional

from sqlmodel import select, Session
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Label, ListItem, ListView, Static

from legacy_report import __version__
from legacy_report.db import get_engine
from legacy_report.models import Issue, Series

_ALL_SERIES_ID = -1


# ── Detail modal ─────────────────────────────────────────────────────────────

class IssueDetailScreen(ModalScreen):
    """Full-detail overlay for a single issue."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close", show=False),
    ]

    DEFAULT_CSS = """
    IssueDetailScreen {
        align: center middle;
    }
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
            # Escape any Rich markup present in arbitrary text
            desc = i.description[:400].replace("[", r"\[")
            lines.append(f"\n  [dim]{desc}[/dim]")
        lines.append("\n  [dim]Esc · close[/dim]")

        yield Static("\n".join(lines), id="detail-box", markup=True)


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

    Horizontal {
        height: 1fr;
    }

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

    #main-pane {
        background: #0d0d0d;
    }

    #main-title {
        background: #002200;
        color: #00ff41;
        text-style: bold;
        height: 1;
        border-bottom: solid #1a6e1a;
        padding: 0 1;
    }

    DataTable {
        background: #0d0d0d;
    }

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

    DataTable > .datatable--hover {
        background: #002200;
    }

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
        Binding("r", "do_toggle_read", "Toggle Read"),
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
                DataTable(id="issues-table", cursor_type="row", zebra_stripes=True),
                id="main-pane",
            ),
        )
        yield Footer()

    async def on_mount(self) -> None:
        self._series_data: list[Series] = []
        self._issues_data: list[Issue] = []
        self._current_issues: list[Issue] = []
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
                ListItem(
                    Label(f" {title:<18} {count:>3}"),
                    id=f"item-{s.id}",
                )
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
        self._current_series_id = series_id

        if series_id == _ALL_SERIES_ID:
            issues = list(self._issues_data)
            series_map = {s.id: s for s in self._series_data}
            title_str = f"ALL ISSUES  ({len(issues)})"
        else:
            issues = [i for i in self._issues_data if i.series_id == series_id]
            series_map = {s.id: s for s in self._series_data if s.id == series_id}
            s = series_map.get(series_id)
            title_str = (
                f"{s.title} ({s.start_year})  \u2014  {len(issues)} issue(s)"
                if s
                else f"{len(issues)} issue(s)"
            )

        issues.sort(key=lambda i: (i.publication_date or date.min))
        self._current_issues = issues

        table = self.query_one("#issues-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Series", "Issue #", "LGY #", "Pub Date", "Story", "R")

        for issue in issues:
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

        self.query_one("#main-title", Label).update(f"  {title_str}")

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id == "item-all":
            self._load_issues(_ALL_SERIES_ID)
        elif item_id.startswith("item-"):
            try:
                series_id = int(item_id.split("-", 1)[1])
                self._load_issues(series_id)
            except (ValueError, IndexError):
                pass
        self.query_one("#issues-table", DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a DataTable row — open detail modal."""
        self._show_detail(event.cursor_row)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _show_detail(self, row: int) -> None:
        if not self._current_issues or row < 0 or row >= len(self._current_issues):
            return
        issue = self._current_issues[row]
        series = next(
            (s for s in self._series_data if s.id == issue.series_id), None
        )
        self.push_screen(IssueDetailScreen(issue, series))

    def _get_focused_issue(self) -> Optional[Issue]:
        table = self.query_one("#issues-table", DataTable)
        row = table.cursor_row
        if not self._current_issues or row < 0 or row >= len(self._current_issues):
            return None
        return self._current_issues[row]

    # ── Actions ───────────────────────────────────────────────────────────────

    async def action_do_add(self) -> None:
        from legacy_report.menu import add_issue

        with self.suspend():
            add_issue()
        gc.collect()
        await self._load_data(restore_series_id=self._current_series_id)

    async def action_do_edit(self) -> None:
        from legacy_report.menu import edit_issue

        with self.suspend():
            edit_issue()
        gc.collect()
        await self._load_data(restore_series_id=self._current_series_id)

    async def action_do_delete(self) -> None:
        from legacy_report.menu import delete_issue

        with self.suspend():
            delete_issue()
        gc.collect()
        await self._load_data(restore_series_id=self._current_series_id)

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

    async def action_do_search(self) -> None:
        from legacy_report.menu import search_collection

        with self.suspend():
            search_collection()
        gc.collect()
        await self._load_data(restore_series_id=self._current_series_id)

    def action_do_export(self) -> None:
        from legacy_report.menu import export_csv

        with self.suspend():
            export_csv()

    def action_do_config(self) -> None:
        from legacy_report.menu import setup_config

        with self.suspend():
            setup_config()

    def action_switch_focus(self) -> None:
        table = self.query_one("#issues-table", DataTable)
        lv = self.query_one("#series-list", ListView)
        if table.has_focus:
            lv.focus()
        else:
            table.focus()
