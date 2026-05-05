"""
Tests for the Textual TUI layer (legacy_report/tui.py).

Uses App.run_test() (headless) with an in-memory SQLite engine so no disk I/O
or real DB is touched. Each test swaps the module-level engine for an isolated
in-memory instance.
"""
import gc
from datetime import date
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlmodel import Session, SQLModel, create_engine, select

from legacy_report.models import Issue, Series
from legacy_report.tui import IssueDetailScreen, LegacyReportApp
from textual.widgets import DataTable, Label, ListView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(engine) -> tuple[Series, Issue]:
    with Session(engine) as session:
        series = Series(title="Amazing Spider-Man", start_year=1963, publisher="Marvel")
        session.add(series)
        session.flush()
        session.refresh(series)

        issue = Issue(
            series_id=series.id,
            issue_number="1",
            legacy_number="1",
            publication_date=date(1963, 3, 1),
            story_title="Spider-Man!",
            writer="Stan Lee",
            artist="Steve Ditko",
            read=False,
        )
        session.add(issue)
        session.commit()
        session.refresh(series)
        session.refresh(issue)

        # Detach before closing
        series_id = series.id
        issue_id = issue.id

    # Re-fetch as detached objects
    with Session(engine, expire_on_commit=False) as session:
        s = session.get(Series, series_id)
        i = session.get(Issue, issue_id)
        return s, i


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_engine():
    return _make_engine()


@pytest.fixture()
def seeded_engine():
    engine = _make_engine()
    _seed(engine)
    return engine


# ---------------------------------------------------------------------------
# Smoke tests — app mounts without errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_mounts_empty_db(mem_engine):
    """App starts and renders without crashing on an empty database."""
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            # Header rendered
            header = pilot.app.query_one("#app-header", Label)
            assert "LEGACY REPORT" in header.content

            # Issues table exists with its columns
            table = pilot.app.query_one("#issues-table", DataTable)
            assert len(table.columns) == 6

            # Sidebar "ALL" item present
            lv = pilot.app.query_one("#series-list", ListView)
            assert len(lv) >= 1  # at least the ALL entry


@pytest.mark.asyncio
async def test_app_mounts_with_data(seeded_engine):
    """App loads series and issues into the two panes."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            table = pilot.app.query_one("#issues-table", DataTable)
            # One issue row
            assert table.row_count == 1

            lv = pilot.app.query_one("#series-list", ListView)
            # ALL + 1 series
            assert len(lv) == 2


# ---------------------------------------------------------------------------
# Sidebar filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sidebar_series_filter(seeded_engine):
    """Selecting a series in the sidebar filters the issues table."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app

            # Start on ALL — 1 issue
            table = app.query_one("#issues-table", DataTable)
            assert table.row_count == 1

            # Add a second unrelated series (no issues)
            with Session(seeded_engine) as session:
                s2 = Series(title="X-Men", start_year=1991, publisher="Marvel")
                session.add(s2)
                session.commit()
                s2_id = s2.id

            await app._load_data()
            gc.collect()

            # The second series has 0 issues — select it
            app._load_issues(s2_id)
            gc.collect()

            assert table.row_count == 0
            assert "X-Men" in app.query_one("#main-title", Label).content


# ---------------------------------------------------------------------------
# Toggle read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_toggle_read_flips_db_value(seeded_engine):
    """action_do_toggle_read updates the issue's read flag in the database."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app

            # Confirm the issue starts as unread
            assert app._current_issues[0].read is False

            # Trigger the toggle action
            await app.action_do_toggle_read()
            gc.collect()

            # Verify DB was updated
            with Session(seeded_engine) as session:
                issue = session.exec(select(Issue)).first()
                assert issue.read is True

            # Trigger again — should flip back
            await app.action_do_toggle_read()
            gc.collect()

            with Session(seeded_engine) as session:
                issue = session.exec(select(Issue)).first()
                assert issue.read is False


# ---------------------------------------------------------------------------
# Detail modal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detail_modal_renders(seeded_engine):
    """_show_detail pushes an IssueDetailScreen onto the screen stack."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app

            app._show_detail(0)
            await pilot.pause()

            assert isinstance(app.screen, IssueDetailScreen)

            # Dismiss and confirm we're back to the main screen
            await pilot.press("escape")
            assert not isinstance(app.screen, IssueDetailScreen)
