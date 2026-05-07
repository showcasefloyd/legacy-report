"""Textual full-screen TUI for Legacy Report.

Two-pane layout:
  Left  — Series sidebar (all series + per-series filter)
  Right — Issues DataTable (responsive, fills terminal)

Footer shows hotkeys. Enter opens an issue detail modal.
"""
from __future__ import annotations

import asyncio
import csv
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlmodel import select, Session
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.events import Key
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Input, Label, ListItem, ListView, LoadingIndicator, Static

from legacy_report import __version__
from legacy_report.config import get_api_key, get_config, set_api_key
from legacy_report.db import create_issue as db_create_issue
from legacy_report.db import delete_issue as db_delete_issue
from legacy_report.db import get_engine, get_or_create_series, update_issue
from legacy_report.models import Issue, Series
from legacy_report.publishers import filter_volumes_by_tier

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
        border: solid #1a6e1a;
    }
    EditIssueScreen .field-input:focus {
        border: solid #00ff41;
    }
    EditIssueScreen #edit-buttons {
        height: 3;
        margin-top: 1;
        align: right middle;
    }
    EditIssueScreen Button {
        margin-left: 1;
        background: #002200;
        border: solid #1a6e1a;
        color: #00ff41;
        min-width: 14;
        content-align: center middle;
    }
    EditIssueScreen Button:focus,
    EditIssueScreen Button:hover {
        background: #004400;
        border: solid #00ff41;
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


# ── Config screen ─────────────────────────────────────────────────────────────

class ConfigScreen(Screen):
    """Full-screen configuration panel — push via 'c'."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("ctrl+s", "save_key", "Save Key"),
    ]

    DEFAULT_CSS = """
    ConfigScreen {
        background: #0d0d0d;
        color: #00ff41;
    }
    ConfigScreen #cfg-header {
        background: #003300;
        color: #00ff41;
        content-align: center middle;
        text-style: bold;
        height: 1;
    }
    ConfigScreen #cfg-body {
        padding: 1 2;
    }
    ConfigScreen .cfg-section-title {
        color: #00ff41;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
    }
    ConfigScreen .cfg-row {
        height: 3;
        margin-bottom: 0;
    }
    ConfigScreen .cfg-label {
        width: 18;
        content-align: right middle;
        color: #00aa22;
        padding-right: 1;
    }
    ConfigScreen .cfg-value {
        color: #00cc33;
        content-align: left middle;
        width: 1fr;
    }
    ConfigScreen .cfg-input {
        width: 1fr;
        background: #002200;
        color: #00ff41;
        border: solid #1a6e1a;
    }
    ConfigScreen .cfg-input:focus {
        border: solid #00ff41;
    }
    ConfigScreen #cfg-buttons {
        height: 3;
        margin-top: 1;
        align: left middle;
    }
    ConfigScreen Button {
        margin-right: 1;
        background: #002200;
        border: solid #1a6e1a;
        color: #00ff41;
        min-width: 18;
        content-align: center middle;
    }
    ConfigScreen Button:focus,
    ConfigScreen Button:hover {
        background: #004400;
        border: solid #00ff41;
    }
    ConfigScreen #cfg-status {
        margin-top: 1;
        color: #00cc33;
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        config = get_config()
        raw_key = config.get("comicvine_api_key", "")
        masked = (
            f"{raw_key[:4]}{'*' * max(0, len(raw_key) - 4)}"
            if len(raw_key) > 4 else ("(not set)" if not raw_key else raw_key)
        )
        yield Label("  LEGACY REPORT — CONFIGURATION", id="cfg-header")
        with ScrollableContainer(id="cfg-body"):
            yield Label("API Key", classes="cfg-section-title")
            yield Horizontal(
                Label("Current key:", classes="cfg-label"),
                Label(masked, id="cfg-key-display", classes="cfg-value"),
                classes="cfg-row",
            )
            yield Horizontal(
                Label("New key:", classes="cfg-label"),
                Input(password=True, placeholder="Paste new ComicVine API key…", id="cfg-key-input", classes="cfg-input"),
                classes="cfg-row",
            )
            with Horizontal(id="cfg-buttons"):
                yield Button("Validate & Save  Ctrl+S", id="btn-save-key")
                yield Button("Back  Esc", id="btn-back")
            yield Label("", id="cfg-status")

            yield Label("Database & Cache", classes="cfg-section-title")
            yield Horizontal(
                Label("DB path:", classes="cfg-label"),
                Label(config.get("db_path", ""), classes="cfg-value"),
                classes="cfg-row",
            )
            yield Horizontal(
                Label("Cache TTL:", classes="cfg-label"),
                Label(f"{config.get('cache_ttl_hours', 24)} hours", classes="cfg-value"),
                classes="cfg-row",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save-key":
            self.action_save_key()
        elif event.button.id == "btn-back":
            self.action_go_back()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_save_key(self) -> None:
        key = self.query_one("#cfg-key-input", Input).value.strip()
        if not key:
            self._set_status("Enter a key first.", error=True)
            return
        self._set_status("Validating…")
        self.run_worker(self._validate_and_save(key), exclusive=True)

    async def _validate_and_save(self, key: str) -> None:
        from legacy_report import comicvine
        valid = await asyncio.to_thread(comicvine.validate_api_key, key)
        if valid:
            set_api_key(key)
            masked = f"{key[:4]}{'*' * max(0, len(key) - 4)}" if len(key) > 4 else key
            self.query_one("#cfg-key-display", Label).update(masked)
            self.query_one("#cfg-key-input", Input).value = ""
            self._set_status("✓ API key saved.")
            self.notify("API key saved.")
        else:
            self._set_status("✗ Validation failed — check the key.", error=True)

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        label = self.query_one("#cfg-status", Label)
        label.update(msg)
        label.styles.color = "#ff4444" if error else "#00cc33"


# ── Add Issue wizard ──────────────────────────────────────────────────────────

_WIZARD_STEP_SEARCH   = "search"
_WIZARD_STEP_VOLUMES  = "volumes"
_WIZARD_STEP_ISSUES   = "issues"
_WIZARD_STEP_CONFIRM  = "confirm"

_WIZARD_STEPS = [
    (_WIZARD_STEP_SEARCH,  "Search"),
    (_WIZARD_STEP_VOLUMES, "Series"),
    (_WIZARD_STEP_ISSUES,  "Issue"),
    (_WIZARD_STEP_CONFIRM, "Confirm"),
]

_STEP_HELP = {
    _WIZARD_STEP_SEARCH:  "  Type a title and press Enter ↵  ·  Esc exits",
    _WIZARD_STEP_VOLUMES: "  ↑ ↓ navigate  ·  Enter ↵ to select a series  ·  Esc to go back",
    _WIZARD_STEP_ISSUES:  "  ↑ ↓ navigate  ·  Enter ↵ to select an issue  ·  [ ] page  ·  Esc to go back",
    _WIZARD_STEP_CONFIRM: "  Edit any field  ·  Ctrl+S to save  ·  Esc to go back",
}


def _step_indicator_markup(current: str) -> str:
    """Build a Rich-markup breadcrumb string for the wizard step indicator."""
    order = [s[0] for s in _WIZARD_STEPS]
    current_idx = order.index(current) if current in order else 0
    sep = "[#1a4e1a] ─── [/]"
    parts = []
    for i, (key, label) in enumerate(_WIZARD_STEPS):
        num = i + 1
        if i == current_idx:
            parts.append(f"[bold #00ff41]◉ {num} {label}[/]")
        elif i < current_idx:
            parts.append(f"[#00aa22]✓ {num} {label}[/]")
        else:
            parts.append(f"[#2a5e2a]○ {num} {label}[/]")
    return "  " + sep.join(parts)


class AddIssueScreen(Screen):
    """Multi-step wizard: search ComicVine → pick volume → pick issue → confirm."""

    BINDINGS = [
        Binding("escape", "go_back_or_cancel", "Back / Cancel"),
        Binding("ctrl+s", "save_issue", "Save", show=False),
        Binding("[", "prev_page", "Prev Page", show=False),
        Binding("]", "next_page", "Next Page", show=False),
    ]

    DEFAULT_CSS = """
    AddIssueScreen {
        background: #0d0d0d;
        color: #00ff41;
    }
    AddIssueScreen #wiz-header {
        background: #003300;
        color: #00ff41;
        content-align: center middle;
        text-style: bold;
        height: 1;
    }
    AddIssueScreen #wiz-step-indicator {
        background: #001a00;
        height: 1;
        padding: 0 2;
    }
    AddIssueScreen #wiz-help {
        background: #001a00;
        color: #005500;
        height: 1;
        padding: 0 2;
        border-top: solid #0a3e0a;
    }
    AddIssueScreen #wiz-body {
        padding: 1 2;
        height: 1fr;
    }
    AddIssueScreen .wiz-prompt {
        height: 3;
        margin-bottom: 1;
    }
    AddIssueScreen .wiz-input {
        width: 1fr;
        background: #002200;
        color: #00ff41;
        border: solid #1a6e1a;
    }
    AddIssueScreen .wiz-input:focus {
        border: solid #00ff41;
    }
    AddIssueScreen LoadingIndicator {
        background: #0d0d0d;
        color: #00ff41;
    }
    AddIssueScreen .field-row { height: 3; margin-bottom: 0; }
    AddIssueScreen .field-label {
        width: 15;
        content-align: right middle;
        color: #00aa22;
        padding-right: 1;
    }
    AddIssueScreen .field-input {
        width: 1fr;
        background: #002200;
        color: #00ff41;
        border: solid #1a6e1a;
    }
    AddIssueScreen .field-input:focus { border: solid #00ff41; }
    AddIssueScreen #wiz-buttons {
        height: 3;
        margin-top: 1;
        align: left middle;
    }
    AddIssueScreen Button {
        margin-right: 1;
        background: #002200;
        border: solid #1a6e1a;
        color: #00ff41;
        min-width: 16;
        content-align: center middle;
    }
    AddIssueScreen Button:focus,
    AddIssueScreen Button:hover {
        background: #004400;
        border: solid #00ff41;
    }
    AddIssueScreen #lgy-hint {
        color: #00aa22;
        height: 1;
        margin-bottom: 1;
        padding: 0 2;
    }
    AddIssueScreen #wiz-page-nav {
        height: 3;
        align: center middle;
    }
    AddIssueScreen #wiz-page-label {
        width: 1fr;
        content-align: center middle;
        color: #00aa22;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._step: str = _WIZARD_STEP_SEARCH
        self._volumes: list[dict] = []
        self._cv_issues: list[dict] = []
        self._cv_offset: int = 0
        self._cv_total: int = 0
        self._cv_limit: int = 100
        self._selected_volume: Optional[dict] = None
        self._selected_cv_issue: Optional[dict] = None

    def compose(self) -> ComposeResult:
        yield Label("  LEGACY REPORT — ADD ISSUE", id="wiz-header")
        yield Label(id="wiz-step-indicator", markup=True)
        yield Label(id="wiz-help")
        with ScrollableContainer(id="wiz-body"):
            # Step 1: search input
            yield Input(
                placeholder="Search ComicVine by title…",
                id="wiz-search-input",
                classes="wiz-input wiz-prompt",
            )
            # Step 2 & 3: results tables (hidden until needed)
            yield DataTable(id="wiz-volumes-table", cursor_type="row", zebra_stripes=True)
            yield DataTable(id="wiz-issues-table",  cursor_type="row", zebra_stripes=True)
            with Horizontal(id="wiz-page-nav"):
                yield Button("← Prev", id="btn-prev-page")
                yield Static("", id="wiz-page-label")
                yield Button("Next →", id="btn-next-page")
            yield LoadingIndicator(id="wiz-loading")
        # Step 4: confirm / edit fields (outside scrollable area to avoid layout issues)
        yield Label("", id="lgy-hint")
        yield Horizontal(
            Label("Issue #",    classes="field-label"),
            Input(id="wiz-issue-number",  classes="field-input"),
            classes="field-row",
        )
        yield Horizontal(
            Label("LGY #",      classes="field-label"),
            Input(id="wiz-legacy-number", classes="field-input"),
            classes="field-row",
        )
        yield Horizontal(
            Label("Pub Date",   classes="field-label"),
            Input(id="wiz-pub-date",      classes="field-input"),
            classes="field-row",
        )
        yield Horizontal(
            Label("Story",      classes="field-label"),
            Input(id="wiz-story-title",   classes="field-input"),
            classes="field-row",
        )
        yield Horizontal(
            Label("Writer",     classes="field-label"),
            Input(id="wiz-writer",        classes="field-input"),
            classes="field-row",
        )
        yield Horizontal(
            Label("Artist",     classes="field-label"),
            Input(id="wiz-artist",        classes="field-input"),
            classes="field-row",
        )
        yield Horizontal(
            Label("Rating 1-5", classes="field-label"),
            Input(id="wiz-rating",        classes="field-input"),
            classes="field-row",
        )
        with Horizontal(id="wiz-buttons"):
            yield Button("Save  Ctrl+S", id="btn-wiz-save")
            yield Button("Cancel  Esc",  id="btn-wiz-cancel")

    def on_mount(self) -> None:
        self._show_step(_WIZARD_STEP_SEARCH)
        self.query_one("#wiz-search-input", Input).focus()

    # ── Step visibility ───────────────────────────────────────────────────────

    def _show_step(self, step: str) -> None:
        self._step = step
        self.query_one("#wiz-step-indicator", Label).update(_step_indicator_markup(step))
        self.query_one("#wiz-help", Label).update(_STEP_HELP.get(step, ""))

        self.query_one("#wiz-search-input",  Input).display  = (step == _WIZARD_STEP_SEARCH)
        self.query_one("#wiz-volumes-table", DataTable).display = (step == _WIZARD_STEP_VOLUMES)
        self.query_one("#wiz-issues-table",  DataTable).display = (step == _WIZARD_STEP_ISSUES)
        self.query_one("#wiz-page-nav").display                 = (step == _WIZARD_STEP_ISSUES)
        self.query_one("#wiz-loading",       LoadingIndicator).display = False

        confirm = (step == _WIZARD_STEP_CONFIRM)
        for wid in ("lgy-hint", "wiz-issue-number", "wiz-legacy-number",
                    "wiz-pub-date", "wiz-story-title", "wiz-writer",
                    "wiz-artist", "wiz-rating", "wiz-buttons"):
            try:
                self.query_one(f"#{wid}").display = confirm
            except Exception:
                pass

    def _show_loading(self) -> None:
        for wid in ("wiz-search-input", "wiz-volumes-table", "wiz-issues-table", "wiz-page-nav"):
            self.query_one(f"#{wid}").display = False
        self.query_one("#wiz-loading", LoadingIndicator).display = True

    # ── Events ────────────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "wiz-search-input" and self._step == _WIZARD_STEP_SEARCH:
            query = event.value.strip()
            if query:
                if not get_api_key():
                    self.notify(
                        "No ComicVine API key set. Go to Config (c) and set your API key first.",
                        title="API Key Required",
                        severity="error",
                    )
                    return
                self._show_loading()
                self.run_worker(self._fetch_volumes(query), exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()  # prevent bubbling to LegacyReportApp._show_detail
        if self._step == _WIZARD_STEP_VOLUMES:
            idx = event.cursor_row
            if 0 <= idx < len(self._volumes):
                self._selected_volume = self._volumes[idx]
                self._cv_offset = 0
                self._show_loading()
                self.run_worker(
                    self._fetch_issues(str(self._selected_volume["id"]), offset=0),
                    exclusive=True,
                )
        elif self._step == _WIZARD_STEP_ISSUES:
            idx = event.cursor_row
            if 0 <= idx < len(self._cv_issues):
                self._selected_cv_issue = self._cv_issues[idx]
                self.run_worker(self._prepare_confirm(), exclusive=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-wiz-save":
            self.action_save_issue()
        elif event.button.id == "btn-wiz-cancel":
            self.app.pop_screen()
        elif event.button.id == "btn-prev-page":
            self.action_prev_page()
        elif event.button.id == "btn-next-page":
            self.action_next_page()

    # ── Workers ───────────────────────────────────────────────────────────────

    async def _fetch_volumes(self, query: str) -> None:
        from legacy_report import comicvine
        try:
            volumes = await asyncio.to_thread(comicvine.search_volumes, query)
            volumes = filter_volumes_by_tier(volumes)
        except Exception as e:
            self.notify(str(e), title="Search Failed", severity="error")
            self._show_step(_WIZARD_STEP_SEARCH)
            return

        if not volumes:
            self.notify("No results found.", severity="warning")
            self._show_step(_WIZARD_STEP_SEARCH)
            return

        self._volumes = volumes
        table = self.query_one("#wiz-volumes-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Title", "Year", "Publisher", "Issues")
        for v in volumes:
            pub = (v.get("publisher") or {}).get("name", "—")
            table.add_row(
                v.get("name", "—"),
                str(v.get("start_year") or "—"),
                pub,
                str(v.get("count_of_issues", "—")),
            )
        self._show_step(_WIZARD_STEP_VOLUMES)
        table.focus()

    async def _fetch_issues(self, volume_id: str, offset: int = 0) -> None:
        from legacy_report import comicvine
        try:
            page = await asyncio.to_thread(
                comicvine.get_issues_for_volume, volume_id, offset
            )
        except Exception as e:
            self.notify(str(e), title="Fetch Failed", severity="error")
            self._show_step(
                _WIZARD_STEP_ISSUES if offset > 0 else _WIZARD_STEP_VOLUMES
            )
            return

        issues = page["results"]
        if not issues and offset == 0:
            self.notify("No issues found for this series.", severity="warning")
            self._show_step(_WIZARD_STEP_VOLUMES)
            return

        self._cv_issues = issues
        self._cv_offset = offset
        self._cv_total = page["total"]

        limit = page["limit"]
        self._cv_limit = limit
        total_pages = (self._cv_total + limit - 1) // limit if self._cv_total else 1
        current_page = (offset // limit) + 1
        self.query_one("#wiz-page-label", Static).update(
            f"Page {current_page} of {total_pages} ({self._cv_total} issues)"
        )
        self.query_one("#btn-prev-page", Button).disabled = (offset == 0)
        self.query_one("#btn-next-page", Button).disabled = (offset + limit >= self._cv_total)

        table = self.query_one("#wiz-issues-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Issue #", "Story Title", "Cover Date")
        for iss in issues:
            table.add_row(
                iss.get("issue_number", "—"),
                iss.get("name") or "—",
                iss.get("cover_date", "—"),
            )
        self._show_step(_WIZARD_STEP_ISSUES)
        table.focus()

    async def _prepare_confirm(self) -> None:
        from legacy_report import comicvine
        iss = self._selected_cv_issue
        vol = self._selected_volume

        # Extract credits
        credits = iss.get("person_credits") or []
        writer = next((p["name"] for p in credits if "writer" in (p.get("role") or "").lower()), "")
        artist = next((p["name"] for p in credits if "artist" in (p.get("role") or "").lower()), "")

        # Auto-calc LGY in background thread
        lgy = ""
        try:
            lgy = await asyncio.to_thread(
                comicvine.calculate_lgy_number, vol, iss.get("issue_number", "")
            ) or ""
        except Exception:
            pass

        # Pre-fill fields
        self.query_one("#wiz-issue-number",  Input).value = iss.get("issue_number", "")
        self.query_one("#wiz-legacy-number", Input).value = lgy
        self.query_one("#wiz-pub-date",      Input).value = iss.get("cover_date", "")
        self.query_one("#wiz-story-title",   Input).value = iss.get("name") or ""
        self.query_one("#wiz-writer",        Input).value = writer
        self.query_one("#wiz-artist",        Input).value = artist
        self.query_one("#wiz-rating",        Input).value = ""

        hint = f"Auto-calculated LGY #{lgy}" if lgy else "LGY # could not be auto-calculated"
        self.query_one("#lgy-hint", Label).update(f"  {hint}")

        self._show_step(_WIZARD_STEP_CONFIRM)
        self.query_one("#wiz-issue-number", Input).focus()

    # ── Save ──────────────────────────────────────────────────────────────────

    def action_save_issue(self) -> None:
        if self._step != _WIZARD_STEP_CONFIRM:
            return

        def val(wid: str) -> str:
            return self.query_one(f"#{wid}", Input).value.strip()

        issue_number = val("wiz-issue-number")
        if not issue_number:
            self.notify("Issue # is required.", severity="error")
            return

        pub_date_raw = val("wiz-pub-date")
        pub_date: Optional[date] = None
        if pub_date_raw:
            try:
                pub_date = date.fromisoformat(pub_date_raw[:10])
            except ValueError:
                self.notify("Invalid date — use YYYY-MM-DD.", severity="error")
                return

        rating_raw = val("wiz-rating")
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

        vol = self._selected_volume
        iss = self._selected_cv_issue
        pub_data = (vol.get("publisher") or {})

        with Session(get_engine()) as session:
            series, _ = get_or_create_series(
                session,
                title=vol["name"],
                start_year=int(vol.get("start_year") or 0),
                publisher=pub_data.get("name"),
                comicvine_id=str(vol["id"]),
                description=vol.get("description"),
            )
            db_create_issue(
                session,
                series_id=series.id,
                issue_number=issue_number,
                legacy_number=val("wiz-legacy-number") or None,
                publication_date=pub_date,
                story_title=val("wiz-story-title") or None,
                writer=val("wiz-writer") or None,
                artist=val("wiz-artist") or None,
                description=iss.get("description") if iss else None,
                cover_image_url=(iss.get("image") or {}).get("medium_url") if iss else None,
                comicvine_id=str(iss["id"]) if iss else None,
                rating=rating,
            )

        self.notify(f"Added: {vol['name']} #{issue_number}")
        self.dismiss(True)

    def action_go_back_or_cancel(self) -> None:
        step_order = [s[0] for s in _WIZARD_STEPS]
        idx = step_order.index(self._step) if self._step in step_order else 0
        if idx == 0:
            self.app.pop_screen()
        else:
            self._show_step(step_order[idx - 1])
            # Re-focus the right widget
            if step_order[idx - 1] == _WIZARD_STEP_SEARCH:
                self.query_one("#wiz-search-input", Input).focus()
            elif step_order[idx - 1] == _WIZARD_STEP_VOLUMES:
                self.query_one("#wiz-volumes-table", DataTable).focus()
            elif step_order[idx - 1] == _WIZARD_STEP_ISSUES:
                self.query_one("#wiz-issues-table", DataTable).focus()

    def action_prev_page(self) -> None:
        if self._step != _WIZARD_STEP_ISSUES or self._cv_offset == 0:
            return
        new_offset = max(0, self._cv_offset - self._cv_limit)
        self._show_loading()
        self.run_worker(
            self._fetch_issues(str(self._selected_volume["id"]), offset=new_offset),
            exclusive=True,
        )

    def action_next_page(self) -> None:
        if self._step != _WIZARD_STEP_ISSUES or self._cv_offset + self._cv_limit >= self._cv_total:
            return
        new_offset = self._cv_offset + self._cv_limit
        self._show_loading()
        self.run_worker(
            self._fetch_issues(str(self._selected_volume["id"]), offset=new_offset),
            exclusive=True,
        )


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
        border: solid #1a6e1a;
        color: #00ff41;
        margin: 0;
        padding: 0 1;
    }
    #search-input:focus { border: solid #00ff41; }
    DataTable { background: #0d0d0d; border: none; }
    DataTable > .datatable--header {
        background: #001a00;
        color: #00ff41;
        text-style: bold;
    }
    DataTable > .datatable--header-cursor {
        background: #004400;
        color: #00ff41;
        text-style: bold;
    }
    DataTable > .datatable--odd-row {
        background: #0d0d0d;
        color: #00ff41;
    }
    DataTable > .datatable--even-row {
        background: #001500;
        color: #00cc33;
    }
    DataTable > .datatable--cursor {
        background: #004400;
        color: #00ff41;
        text-style: bold;
    }
    DataTable > .datatable--hover { background: #002200; color: #00ff41; }
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
        async def on_added(saved: bool) -> None:
            if saved:
                await self._load_data(restore_series_id=self._current_series_id)
        self.push_screen(AddIssueScreen(), on_added)

    def action_do_config(self) -> None:
        self.push_screen(ConfigScreen())

    def action_switch_focus(self) -> None:
        table = self.query_one("#issues-table", DataTable)
        lv = self.query_one("#series-list", ListView)
        if table.has_focus:
            lv.focus()
        else:
            table.focus()

