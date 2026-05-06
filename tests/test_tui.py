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
from sqlmodel import Session, SQLModel, create_engine, select

from legacy_report.models import Issue, Series
from legacy_report.tui import (
    AddIssueScreen,
    ConfigScreen,
    DeleteConfirmScreen,
    EditIssueScreen,
    IssueDetailScreen,
    LegacyReportApp,
)
from textual.widgets import DataTable, Input, Label, ListView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(engine):
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
        series_id = series.id
        issue_id = issue.id

    with Session(engine, expire_on_commit=False) as session:
        return session.get(Series, series_id), session.get(Issue, issue_id)


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
# Smoke — app mounts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_mounts_empty_db(mem_engine):
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            header = pilot.app.query_one("#app-header", Label)
            assert "LEGACY REPORT" in header.content
            table = pilot.app.query_one("#issues-table", DataTable)
            assert len(table.columns) == 6
            lv = pilot.app.query_one("#series-list", ListView)
            assert len(lv) >= 1


@pytest.mark.asyncio
async def test_app_mounts_with_data(seeded_engine):
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            assert pilot.app.query_one("#issues-table", DataTable).row_count == 1
            assert len(pilot.app.query_one("#series-list", ListView)) == 2


# ---------------------------------------------------------------------------
# Sidebar filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sidebar_series_filter(seeded_engine):
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            table = app.query_one("#issues-table", DataTable)
            assert table.row_count == 1

            with Session(seeded_engine) as session:
                s2 = Series(title="X-Men", start_year=1991, publisher="Marvel")
                session.add(s2)
                session.commit()
                s2_id = s2.id

            await app._load_data()
            app._load_issues(s2_id)

            assert table.row_count == 0
            assert "X-Men" in app.query_one("#main-title", Label).content


# ---------------------------------------------------------------------------
# Live search / filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_filter_narrows_table(seeded_engine):
    """Typing in the search input filters the DataTable."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            # Open search bar
            app.action_do_search()
            await pilot.pause()
            si = app.query_one("#search-input", Input)
            assert si.display is True

            # Type something that matches the seeded issue
            si.value = "Spider"
            app._apply_filter("Spider")
            assert app.query_one("#issues-table", DataTable).row_count == 1

            # Type something that matches nothing
            app._apply_filter("ZZZNOTHING")
            assert app.query_one("#issues-table", DataTable).row_count == 0

            # Clear filter — all issues back
            app._apply_filter("")
            assert app.query_one("#issues-table", DataTable).row_count == 1


@pytest.mark.asyncio
async def test_search_toggle_hides_on_second_press(seeded_engine):
    """Pressing / again hides the search bar and clears filter."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            app.action_do_search()
            await pilot.pause()
            si = app.query_one("#search-input", Input)
            assert si.display is True

            app._apply_filter("Spider")
            app.action_do_search()   # close
            await pilot.pause()
            assert si.display is False
            assert app._filter_text == ""
            assert app.query_one("#issues-table", DataTable).row_count == 1


# ---------------------------------------------------------------------------
# Toggle read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_toggle_read_flips_db_value(seeded_engine):
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            assert app._current_issues[0].read is False

            await app.action_do_toggle_read()
            with Session(seeded_engine) as session:
                assert session.exec(select(Issue)).first().read is True

            await app.action_do_toggle_read()
            with Session(seeded_engine) as session:
                assert session.exec(select(Issue)).first().read is False


# ---------------------------------------------------------------------------
# Detail modal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detail_modal_renders(seeded_engine):
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            app._show_detail(0)
            await pilot.pause()
            assert isinstance(app.screen, IssueDetailScreen)
            await pilot.press("escape")
            assert not isinstance(app.screen, IssueDetailScreen)


# ---------------------------------------------------------------------------
# Delete confirmation modal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_confirm_cancel_keeps_issue(seeded_engine):
    """Pressing Esc on the delete modal leaves the issue in the DB."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            await app.action_do_delete()
            await pilot.pause()
            assert isinstance(app.screen, DeleteConfirmScreen)
            await pilot.press("escape")
            await pilot.pause()
            with Session(seeded_engine) as session:
                assert session.exec(select(Issue)).first() is not None


@pytest.mark.asyncio
async def test_delete_confirm_d_removes_issue(seeded_engine):
    """Pressing D on the delete modal removes the issue from the DB."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            await app.action_do_delete()
            await pilot.pause()
            assert isinstance(app.screen, DeleteConfirmScreen)
            await pilot.press("d")
            await pilot.pause()
            with Session(seeded_engine) as session:
                assert session.exec(select(Issue)).first() is None
            assert app.query_one("#issues-table", DataTable).row_count == 0


# ---------------------------------------------------------------------------
# Edit Issue modal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edit_modal_opens_with_prefilled_values(seeded_engine):
    """EditIssueScreen pre-fills inputs with the issue's current field values."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            await app.action_do_edit()
            await pilot.pause()
            assert isinstance(app.screen, EditIssueScreen)
            assert app.screen.query_one("#ei-issue-number", Input).value == "1"
            assert app.screen.query_one("#ei-story-title", Input).value == "Spider-Man!"
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_edit_modal_saves_changes(seeded_engine):
    """Saving in EditIssueScreen updates the row in the DB."""
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            await app.action_do_edit()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, EditIssueScreen)
            screen.query_one("#ei-story-title", Input).value = "New Title"
            screen._do_save()
            await pilot.pause()
            with Session(seeded_engine) as session:
                issue = session.exec(select(Issue)).first()
                assert issue.story_title == "New Title"


# ---------------------------------------------------------------------------
# Export CSV
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_csv_writes_file(seeded_engine, tmp_path):
    """action_do_export creates a CSV file with the collection data."""
    import csv as csv_mod
    out = tmp_path / "legacy_report_export.csv"
    with patch("legacy_report.tui.get_engine", return_value=seeded_engine):
        with patch("legacy_report.tui.Path.home", return_value=tmp_path):
            async with LegacyReportApp().run_test(headless=True) as pilot:
                app = pilot.app
                app.action_do_export()
                await pilot.pause()
    assert out.exists()
    rows = list(csv_mod.reader(out.open()))
    assert len(rows) == 2   # header + 1 issue
    assert rows[1][0] == "Amazing Spider-Man"


# ---------------------------------------------------------------------------
# ConfigScreen
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_config_screen_opens(mem_engine):
    """Pressing c pushes ConfigScreen onto the screen stack."""
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            app.action_do_config()
            await pilot.pause()
            assert isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_config_screen_back_pops(mem_engine):
    """Pressing Esc on ConfigScreen returns to main screen."""
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            app = pilot.app
            app.action_do_config()
            await pilot.pause()
            assert isinstance(app.screen, ConfigScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_config_screen_shows_masked_key(mem_engine):
    """ConfigScreen masks an existing API key in the display label."""
    with patch("legacy_report.tui.get_config", return_value={
        "comicvine_api_key": "abcd1234efgh",
        "cache_ttl_hours": 24,
        "db_path": "~/.local/share/legacy-report/collection.db",
    }):
        with patch("legacy_report.tui.get_engine", return_value=mem_engine):
            async with LegacyReportApp().run_test(headless=True) as pilot:
                app = pilot.app
                app.action_do_config()
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, ConfigScreen)
                display = screen.query_one("#cfg-key-display", Label)
                assert display.content.startswith("abcd")
                assert "*" in display.content


# ---------------------------------------------------------------------------
# AddIssueScreen wizard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_issue_screen_opens(mem_engine):
    """Pressing a pushes AddIssueScreen."""
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            assert isinstance(pilot.app.screen, AddIssueScreen)


@pytest.mark.asyncio
async def test_add_issue_escape_cancels(mem_engine):
    """Pressing Esc on step 1 dismisses the wizard."""
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, AddIssueScreen)


@pytest.mark.asyncio
async def test_add_issue_search_requires_api_key(mem_engine):
    """Submitting a search without an API key shows an error and stays on step 1."""
    from legacy_report.tui import _WIZARD_STEP_SEARCH
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        with patch("legacy_report.tui.get_api_key", return_value=""):
            async with LegacyReportApp().run_test(headless=True) as pilot:
                await pilot.app.action_do_add()
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, AddIssueScreen)

                search_input = screen.query_one("#wiz-search-input", Input)
                search_input.value = "Batman"
                screen.on_input_submitted(Input.Submitted(search_input, "Batman"))
                await pilot.pause()

                # Wizard must remain on the search step — no API call made
                assert screen._step == _WIZARD_STEP_SEARCH


@pytest.mark.asyncio
async def test_add_issue_search_shows_volumes(mem_engine):
    """After volumes are loaded the wizard transitions to step 2 and fills the table."""
    fake_volumes = [
        {"id": 1, "name": "Amazing Spider-Man", "start_year": 1963,
         "publisher": {"name": "Marvel"}, "count_of_issues": 441}
    ]
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)

            # Directly simulate the post-fetch state transition
            from legacy_report.tui import _WIZARD_STEP_VOLUMES
            from textual.widgets import DataTable
            screen._volumes = fake_volumes
            table = screen.query_one("#wiz-volumes-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Title", "Year", "Publisher", "Issues")
            table.add_row("Amazing Spider-Man", "1963", "Marvel", "441")
            screen._show_step(_WIZARD_STEP_VOLUMES)
            await pilot.pause()

            assert screen._step == _WIZARD_STEP_VOLUMES
            assert table.row_count == 1


@pytest.mark.asyncio
async def test_add_issue_saves_to_db(mem_engine):
    """action_save_issue on step 4 writes an Issue row to the DB."""
    from legacy_report.tui import _WIZARD_STEP_CONFIRM
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)

            # Inject wizard state as if steps 1-3 were completed
            screen._selected_volume = {
                "id": 99, "name": "Daredevil", "start_year": 1964,
                "publisher": {"name": "Marvel"}, "description": None,
            }
            screen._selected_cv_issue = {
                "id": 1001, "issue_number": "1", "name": "The Man Without Fear",
                "cover_date": "1964-04-01", "person_credits": [],
                "image": {}, "description": None,
            }
            screen._step = _WIZARD_STEP_CONFIRM
            screen._show_step(_WIZARD_STEP_CONFIRM)
            await pilot.pause()

            # Fill required field
            from textual.widgets import Input
            screen.query_one("#wiz-issue-number", Input).value = "1"
            screen.action_save_issue()
            await pilot.pause()

            with Session(mem_engine) as session:
                issue = session.exec(select(Issue)).first()
                assert issue is not None
                assert issue.issue_number == "1"
                series = session.get(Series, issue.series_id)
                assert series.title == "Daredevil"


# ---------------------------------------------------------------------------
# AddIssueScreen — worker-driven step transitions (regression for run_in_thread)
# ---------------------------------------------------------------------------

_FAKE_VOLUMES = [
    {
        "id": 42,
        "name": "Batman",
        "start_year": "1940",
        "publisher": {"name": "DC Comics"},
        "count_of_issues": 5,
        "description": None,
    }
]

_FAKE_CV_ISSUES = [
    {
        "id": 1001,
        "issue_number": "1",
        "name": "The Batman Begins",
        "cover_date": "1940-04-01",
        "person_credits": [
            {"name": "Bob Kane", "role": "writer"},
            {"name": "Bill Finger", "role": "artist"},
        ],
        "image": {"medium_url": "https://example.com/img.jpg"},
        "description": "First issue.",
    }
]


@pytest.mark.asyncio
async def test_fetch_volumes_worker_advances_to_step2(mem_engine):
    """_fetch_volumes transitions to volume-select step when API returns results."""
    from legacy_report.tui import _WIZARD_STEP_VOLUMES

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        with patch("legacy_report.tui.get_api_key", return_value="fakekey"):
            with patch("legacy_report.comicvine.search_volumes", return_value=_FAKE_VOLUMES):
                async with LegacyReportApp().run_test(headless=True) as pilot:
                    await pilot.app.action_do_add()
                    await pilot.pause()
                    screen = pilot.app.screen
                    assert isinstance(screen, AddIssueScreen)

                    si = screen.query_one("#wiz-search-input", Input)
                    si.value = "Batman"
                    screen.on_input_submitted(Input.Submitted(si, "Batman"))
                    # Allow worker + thread to complete
                    for _ in range(5):
                        await pilot.pause()

                    assert screen._step == _WIZARD_STEP_VOLUMES
                    assert len(screen._volumes) == 1
                    table = screen.query_one("#wiz-volumes-table", DataTable)
                    assert table.row_count == 1


@pytest.mark.asyncio
async def test_fetch_volumes_no_results_stays_on_step1(mem_engine):
    """_fetch_volumes stays on step 1 when no volumes survive the tier filter."""
    from legacy_report.tui import _WIZARD_STEP_SEARCH

    # Return a volume from a non-US/UK publisher so filter_volumes_by_tier drops it
    other_vol = [{
        "id": 99, "name": "Manga X", "start_year": "2000",
        "publisher": {"name": "Shueisha"}, "count_of_issues": 10,
    }]
    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        with patch("legacy_report.tui.get_api_key", return_value="fakekey"):
            with patch("legacy_report.comicvine.search_volumes", return_value=other_vol):
                async with LegacyReportApp().run_test(headless=True) as pilot:
                    await pilot.app.action_do_add()
                    await pilot.pause()
                    screen = pilot.app.screen
                    assert isinstance(screen, AddIssueScreen)

                    si = screen.query_one("#wiz-search-input", Input)
                    si.value = "Manga X"
                    screen.on_input_submitted(Input.Submitted(si, "Manga X"))
                    for _ in range(5):
                        await pilot.pause()

                    assert screen._step == _WIZARD_STEP_SEARCH


@pytest.mark.asyncio
async def test_fetch_volumes_api_error_stays_on_step1(mem_engine):
    """_fetch_volumes handles an API exception and keeps the wizard on step 1."""
    from legacy_report.tui import _WIZARD_STEP_SEARCH

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        with patch("legacy_report.tui.get_api_key", return_value="fakekey"):
            with patch(
                "legacy_report.comicvine.search_volumes",
                side_effect=RuntimeError("API down"),
            ):
                async with LegacyReportApp().run_test(headless=True) as pilot:
                    await pilot.app.action_do_add()
                    await pilot.pause()
                    screen = pilot.app.screen
                    assert isinstance(screen, AddIssueScreen)

                    si = screen.query_one("#wiz-search-input", Input)
                    si.value = "Batman"
                    screen.on_input_submitted(Input.Submitted(si, "Batman"))
                    for _ in range(5):
                        await pilot.pause()

                    assert screen._step == _WIZARD_STEP_SEARCH


@pytest.mark.asyncio
async def test_fetch_issues_worker_advances_to_step3(mem_engine):
    """_fetch_issues transitions to issue-select step when volume issues are returned."""
    from legacy_report.tui import _WIZARD_STEP_ISSUES

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)

            screen._volumes = _FAKE_VOLUMES
            screen._selected_volume = _FAKE_VOLUMES[0]

            with patch(
                "legacy_report.comicvine.get_issues_for_volume",
                return_value={"results": _FAKE_CV_ISSUES, "total": 5, "offset": 0, "limit": 100},
            ):
                screen.run_worker(screen._fetch_issues("42"), exclusive=True)
                for _ in range(5):
                    await pilot.pause()

            assert screen._step == _WIZARD_STEP_ISSUES
            assert len(screen._cv_issues) == 1
            table = screen.query_one("#wiz-issues-table", DataTable)
            assert table.row_count == 1


@pytest.mark.asyncio
async def test_wizard_back_navigation(mem_engine):
    """Escape on step 2 returns to step 1 without leaving AddIssueScreen."""
    from legacy_report.tui import _WIZARD_STEP_SEARCH, _WIZARD_STEP_VOLUMES

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)

            # Jump wizard to step 2 manually
            screen._volumes = _FAKE_VOLUMES
            screen._show_step(_WIZARD_STEP_VOLUMES)
            await pilot.pause()
            assert screen._step == _WIZARD_STEP_VOLUMES

            # Press Esc — should go back to step 1, not pop the screen
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(pilot.app.screen, AddIssueScreen)
            assert screen._step == _WIZARD_STEP_SEARCH


@pytest.mark.asyncio
async def test_wizard_row_select_does_not_open_detail_modal(mem_engine):
    """Selecting a row in the wizard's DataTable must NOT open IssueDetailScreen.

    Regression: DataTable.RowSelected used to bubble up to LegacyReportApp
    which called _show_detail(), overlaying the wizard with a detail modal.
    """
    from legacy_report.tui import _WIZARD_STEP_VOLUMES

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        with patch(
            "legacy_report.comicvine.get_issues_for_volume",
            return_value={"results": _FAKE_CV_ISSUES, "total": 1, "offset": 0, "limit": 100},
        ):
            async with LegacyReportApp().run_test(headless=True) as pilot:
                await pilot.app.action_do_add()
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, AddIssueScreen)

                # Put wizard on step 2 with a row ready to select
                screen._volumes = _FAKE_VOLUMES
                table = screen.query_one("#wiz-volumes-table", DataTable)
                table.clear(columns=True)
                table.add_columns("Title", "Year", "Publisher", "Issues")
                table.add_row("Batman", "1940", "DC Comics", "5")
                screen._show_step(_WIZARD_STEP_VOLUMES)
                await pilot.pause()

                # Simulate row selection (Enter on the DataTable)
                screen.on_data_table_row_selected(
                    DataTable.RowSelected(table, cursor_row=0, row_key=table.get_row_at(0))
                )
                await pilot.pause()

                # Must still be on AddIssueScreen, not IssueDetailScreen
                assert isinstance(pilot.app.screen, AddIssueScreen)


@pytest.mark.asyncio
async def test_fetch_issues_stores_total_and_offset(mem_engine):
    """_fetch_issues stores _cv_total and _cv_offset from the API page dict."""
    from legacy_report.tui import _WIZARD_STEP_ISSUES
    fake_page = {"results": _FAKE_CV_ISSUES, "total": 342, "offset": 0, "limit": 100}

    with patch("legacy_report.tui.get_engine", return_value=mem_engine):
        async with LegacyReportApp().run_test(headless=True) as pilot:
            await pilot.app.action_do_add()
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, AddIssueScreen)
            screen._selected_volume = _FAKE_VOLUMES[0]

            with patch(
                "legacy_report.comicvine.get_issues_for_volume",
                return_value=fake_page,
            ):
                screen.run_worker(screen._fetch_issues("42", offset=0), exclusive=True)
                for _ in range(5):
                    await pilot.pause()

            assert screen._step == _WIZARD_STEP_ISSUES
            assert screen._cv_total == 342
            assert screen._cv_offset == 0
            assert screen._cv_issues == _FAKE_CV_ISSUES

