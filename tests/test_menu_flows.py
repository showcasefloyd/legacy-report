"""
Menu-level integration tests for edit_issue and delete_issue flows.

These tests mock InquirerPy prompts and patch _get_session to inject an
in-memory SQLite session, then call gc.collect() between the "select" step
and the "mutate" step to simulate the GC pressure that InquirerPy's asyncio
event loop creates between prompts.

This is the class of test that catches ObjectDereferencedError — the data-
layer unit tests in test_collection.py cannot, because they never involve
InquirerPy or an asyncio event loop.
"""

import gc
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

from legacy_report.db import create_issue, get_or_create_series
from legacy_report.models import Issue, Series


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="seeded")
def seeded_fixture(session):
    """One Series + two Issues ready for menu tests."""
    series, _ = get_or_create_series(
        session,
        title="Amazing Spider-Man",
        start_year=1963,
        publisher="Marvel Comics",
    )
    issue1 = create_issue(
        session,
        series_id=series.id,
        issue_number="1",
        legacy_number="1",
        publication_date=date(1963, 3, 1),
        story_title="Spider-Man!",
        writer="Stan Lee",
        artist="Steve Ditko",
    )
    issue2 = create_issue(
        session,
        series_id=series.id,
        issue_number="2",
        legacy_number="2",
        publication_date=date(1963, 5, 1),
        story_title="Duel to the Death with the Vulture!",
        writer="Stan Lee",
        artist="Steve Ditko",
    )
    return {"series": series, "issue1": issue1, "issue2": issue2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text_mock(*values):
    """
    Returns a mock suitable for patching inquirer.text when it is called
    multiple times in one flow.

    inquirer.text(message=...).execute() is the call pattern.
    Because the same mock object is returned from every call to inquirer.text(),
    we put the successive return values on execute.side_effect.
    """
    m = MagicMock()
    m.return_value.execute.side_effect = list(values)
    return m


def _single_mock(return_value):
    """
    Returns a mock for prompts called exactly once in a flow
    (inquirer.select, inquirer.confirm).
    """
    m = MagicMock()
    m.return_value.execute.return_value = return_value
    return m


# ---------------------------------------------------------------------------
# edit_issue flow
# ---------------------------------------------------------------------------

class TestEditIssueFlow:
    def test_edit_updates_story_title(self, session, seeded):
        issue = seeded["issue1"]
        issue_id = issue.id

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",   # search query
                "1",                    # issue select (issue1 is first by date)
                issue.issue_number,     # issue_number field
                "",                     # legacy_number
                "",                     # pub date
                "New Story Title",      # story_title
                "",                     # writer
                "",                     # artist
                "",                     # Press Enter to continue
            )),
        ):
            from legacy_report.menu import edit_issue
            edit_issue()

        session.expire_all()
        updated = session.get(Issue, issue_id)
        assert updated.story_title == "New Story Title"

    def test_edit_survives_gc_between_select_and_mutate(self, session, seeded):
        """
        Force gc.collect() during the number-select prompt, before session.get().
        This replicates the GC pressure from InquirerPy's asyncio event loop.
        Without the ID-based re-fetch fix, this raises ObjectDereferencedError.
        """
        issue = seeded["issue1"]
        issue_id = issue.id

        gc_collected = []
        call_count = [0]
        values = [
            "Amazing Spider-Man",   # call 0: search query
            "1",                    # call 1: issue number select (triggers GC)
            issue.issue_number,     # call 2: issue_number field
            "",                     # call 3: legacy_number
            "",                     # call 4: pub date
            "GC-Proof Title",       # call 5: story_title
            "",                     # call 6: writer
            "",                     # call 7: artist
            "",                     # call 8: Press Enter to continue
        ]

        def gc_execute():
            idx = call_count[0]
            call_count[0] += 1
            if idx == 1:  # the number-select prompt
                gc.collect()
                gc_collected.append(True)
            return values[idx]

        mock_text = MagicMock()
        mock_text.return_value.execute.side_effect = gc_execute

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", mock_text),
        ):
            from legacy_report.menu import edit_issue
            edit_issue()  # must not raise ObjectDereferencedError

        assert gc_collected, "GC was not triggered during the test"
        session.expire_all()
        updated = session.get(Issue, issue_id)
        assert updated.story_title == "GC-Proof Title"

    def test_edit_cancel_at_select_makes_no_changes(self, session, seeded):
        issue = seeded["issue1"]
        original_title = issue.story_title

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man", "")),
        ):
            from legacy_report.menu import edit_issue
            edit_issue()

        session.expire_all()
        unchanged = session.get(Issue, issue.id)
        assert unchanged.story_title == original_title

    def test_edit_no_results_returns_early(self, session, seeded):
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock("Nonexistent Title XYZ")),
            patch("legacy_report.menu.print_issues_table") as mock_table,
        ):
            from legacy_report.menu import edit_issue
            edit_issue()
            mock_table.assert_not_called()

    def test_edit_updates_writer_and_artist(self, session, seeded):
        issue = seeded["issue2"]
        issue_id = issue.id

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",
                "2",                # issue2 is second by date
                issue.issue_number,
                "",
                "",
                "",
                "Chris Claremont",
                "John Byrne",
                "",                 # Press Enter to continue
            )),
        ):
            from legacy_report.menu import edit_issue
            edit_issue()

        session.expire_all()
        updated = session.get(Issue, issue_id)
        assert updated.writer == "Chris Claremont"
        assert updated.artist == "John Byrne"


# ---------------------------------------------------------------------------
# delete_issue flow
# ---------------------------------------------------------------------------

class TestDeleteIssueFlow:
    def test_delete_removes_issue(self, session, seeded):
        issue = seeded["issue1"]
        issue_id = issue.id

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man", "1")),
            patch("legacy_report.menu.inquirer.confirm", _single_mock(True)),
        ):
            from legacy_report.menu import delete_issue
            delete_issue()

        assert session.get(Issue, issue_id) is None

    def test_delete_survives_gc_between_select_and_confirm(self, session, seeded):
        """
        Force gc.collect() during the number-select prompt, before confirm.
        Replicates GC pressure from InquirerPy's event loop on the confirm prompt.
        """
        issue = seeded["issue1"]
        issue_id = issue.id

        gc_collected = []
        call_count = [0]
        values = [
            "Amazing Spider-Man",  # call 0: search query
            "1",                   # call 1: issue number select (triggers GC)
        ]

        def gc_execute():
            idx = call_count[0]
            call_count[0] += 1
            if idx == 1:  # the number-select prompt
                gc.collect()
                gc_collected.append(True)
            return values[idx]

        mock_text = MagicMock()
        mock_text.return_value.execute.side_effect = gc_execute

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", mock_text),
            patch("legacy_report.menu.inquirer.confirm", _single_mock(True)),
        ):
            from legacy_report.menu import delete_issue
            delete_issue()  # must not raise ObjectDereferencedError

        assert gc_collected, "GC was not triggered during the test"
        assert session.get(Issue, issue_id) is None

    def test_delete_cancel_at_confirm_preserves_issue(self, session, seeded):
        issue = seeded["issue1"]
        issue_id = issue.id

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man", "1")),
            patch("legacy_report.menu.inquirer.confirm", _single_mock(False)),
        ):
            from legacy_report.menu import delete_issue
            delete_issue()

        assert session.get(Issue, issue_id) is not None

    def test_delete_cancel_at_select_makes_no_changes(self, session, seeded):
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man", "")),
            patch("legacy_report.menu.inquirer.confirm") as mock_confirm,
        ):
            from legacy_report.menu import delete_issue
            delete_issue()
            mock_confirm.assert_not_called()

    def test_delete_only_removes_selected_issue(self, session, seeded):
        issue1 = seeded["issue1"]
        issue2 = seeded["issue2"]
        # Capture IDs now — menu.delete_issue() closes the session, detaching objects
        issue1_id = issue1.id
        issue2_id = issue2.id

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man", "1")),
            patch("legacy_report.menu.inquirer.confirm", _single_mock(True)),
        ):
            from legacy_report.menu import delete_issue
            delete_issue()

        assert session.get(Issue, issue1_id) is None
        assert session.get(Issue, issue2_id) is not None


# ---------------------------------------------------------------------------
# add_issue display regression
# ---------------------------------------------------------------------------

class TestAddIssueDisplay:
    """Guard against the table+list double-render regression, and verify pagination.

    Volumes are displayed as a paginated Rich table and selected by number prompt.
    inquirer.select must never be used for volume selection.
    """

    _FAKE_VOLUMES = [
        {
            "id": str(i),
            "name": f"Amazing Spider-Man Vol {i}",
            "start_year": 1960 + i,
            "publisher": {"name": "Marvel Comics"},
            "count_of_issues": 10 * i,
            "description": "",
        }
        for i in range(1, 62)  # 61 volumes — enough for two pages at PAGE_SIZE=50
    ]

    def test_add_issue_shows_table_not_select_list(self, session):
        """Volume table must be printed; inquirer.select must NOT be called anywhere."""
        with (
            patch("legacy_report.menu.get_api_key", return_value="fake-key"),
            patch("legacy_report.menu.comicvine.search_volumes",
                  return_value=self._FAKE_VOLUMES[:5]),
            patch("legacy_report.menu.filter_volumes_by_tier",
                  return_value=self._FAKE_VOLUMES[:5]),
            patch("legacy_report.menu.print_volumes_table") as mock_table,
            patch("legacy_report.menu.inquirer.text", _text_mock("Spider-Man", "")),
            patch("legacy_report.menu.inquirer.select") as mock_select,
        ):
            from legacy_report.menu import add_issue
            add_issue()

        mock_table.assert_called()
        mock_select.assert_not_called()

    def test_add_issue_shows_cv_issues_table_not_select_list(self, session):
        """CV issues must use Rich table + number prompt, never inquirer.select."""
        vols = self._FAKE_VOLUMES[:2]
        fake_cv_issues = [
            {
                "id": "1",
                "issue_number": "1",
                "name": "First Issue",
                "cover_date": "1963-03-01",
                "description": "",
                "image": {},
                "person_credits": [],
            }
        ]
        with (
            patch("legacy_report.menu.get_api_key", return_value="fake-key"),
            patch("legacy_report.menu.comicvine.search_volumes", return_value=vols),
            patch("legacy_report.menu.filter_volumes_by_tier", return_value=vols),
            patch("legacy_report.menu.print_volumes_table"),
            patch("legacy_report.menu.comicvine.get_issues_for_volume",
                  return_value=fake_cv_issues),
            patch("legacy_report.menu.print_cv_issues_table") as mock_cv_table,
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Spider-Man",  # search query
                "1",           # volume select
                "",            # cancel at CV issue select
            )),
            patch("legacy_report.menu.inquirer.select") as mock_select,
        ):
            from legacy_report.menu import add_issue
            add_issue()

        mock_cv_table.assert_called()
        mock_select.assert_not_called()

    def test_add_issue_number_selection_picks_correct_volume(self, session):
        """Entering '1' at the number prompt selects the first volume on the page."""
        vols = self._FAKE_VOLUMES[:5]
        fake_issue = {
            "id": "999",
            "issue_number": "1",
            "name": "Spider-Man Fights Crime",
            "cover_date": "1963-03-01",
            "description": "",
            "image": {},
            "person_credits": [],
        }
        with (
            patch("legacy_report.menu.get_api_key", return_value="fake-key"),
            patch("legacy_report.menu.comicvine.search_volumes", return_value=vols),
            patch("legacy_report.menu.filter_volumes_by_tier", return_value=vols),
            patch("legacy_report.menu.print_volumes_table"),
            patch("legacy_report.menu.comicvine.get_issues_for_volume",
                  return_value=[fake_issue]),
            patch("legacy_report.menu.comicvine.calculate_lgy_number", return_value=""),
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Spider-Man",  # search query
                "1",           # volume number selection (page 1, item 1)
                "1",           # CV issue number selection
                "1",           # issue_number field
                "",            # legacy_number
                "1963-03-01",  # pub date
                "",            # story_title
                "",            # writer
                "",            # artist
                "",            # Press Enter to continue
            )),
        ):
            from legacy_report.menu import add_issue
            add_issue()

        from legacy_report.models import Series
        from sqlmodel import select as sql_select
        series = session.exec(sql_select(Series)).first()
        assert series is not None
        assert series.title == vols[0]["name"]

    def test_add_issue_invalid_number_returns_error(self, session):
        """Entering a number out of range shows an error; the loop continues so the user can retry."""
        vols = self._FAKE_VOLUMES[:5]
        with (
            patch("legacy_report.menu.get_api_key", return_value="fake-key"),
            patch("legacy_report.menu.comicvine.search_volumes", return_value=vols),
            patch("legacy_report.menu.filter_volumes_by_tier", return_value=vols),
            patch("legacy_report.menu.print_volumes_table"),
            patch("legacy_report.menu.comicvine.get_issues_for_volume") as mock_issues,
            patch("legacy_report.menu.inquirer.text",
                  _text_mock("Spider-Man", "99", "")),  # bad input, then blank to cancel
        ):
            from legacy_report.menu import add_issue
            add_issue()

        mock_issues.assert_not_called()

    def test_add_issue_pagination_next_and_select(self, session):
        """Entering 'n' advances to the next page; selecting '1' picks the first item there."""
        vols = self._FAKE_VOLUMES  # 61 volumes — 2 pages
        fake_issue = {
            "id": "999",
            "issue_number": "1",
            "name": "Issue on Page 2",
            "cover_date": "1963-03-01",
            "description": "",
            "image": {},
            "person_credits": [],
        }
        with (
            patch("legacy_report.menu.get_api_key", return_value="fake-key"),
            patch("legacy_report.menu.comicvine.search_volumes", return_value=vols),
            patch("legacy_report.menu.filter_volumes_by_tier", return_value=vols),
            patch("legacy_report.menu.print_volumes_table") as mock_table,
            patch("legacy_report.menu.comicvine.get_issues_for_volume",
                  return_value=[fake_issue]),
            patch("legacy_report.menu.comicvine.calculate_lgy_number", return_value=""),
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Spider-Man",  # search query
                "n",           # next page
                "1",           # select item 1 on page 2
                "1",           # CV issue number selection
                "1",           # issue_number field
                "",            # legacy_number
                "1963-03-01",  # pub date
                "",            # story_title
                "",            # writer
                "",            # artist
                "",            # Press Enter to continue
            )),
        ):
            from legacy_report.menu import add_issue
            add_issue()

        # Table should have been rendered twice (page 1, then page 2)
        assert mock_table.call_count == 2
        # The volume selected was from page 2 (index 50, i.e. vols[50])
        from legacy_report.models import Series
        from sqlmodel import select as sql_select
        series = session.exec(sql_select(Series)).first()
        assert series is not None
        assert series.title == vols[50]["name"]

    def test_add_issue_pagination_prev_navigates_back(self, session):
        """Entering 'p' on page 2 goes back to page 1."""
        vols = self._FAKE_VOLUMES  # 61 volumes — 2 pages
        with (
            patch("legacy_report.menu.get_api_key", return_value="fake-key"),
            patch("legacy_report.menu.comicvine.search_volumes", return_value=vols),
            patch("legacy_report.menu.filter_volumes_by_tier", return_value=vols),
            patch("legacy_report.menu.print_volumes_table") as mock_table,
            patch("legacy_report.menu.comicvine.get_issues_for_volume") as mock_issues,
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Spider-Man",  # search query
                "n",           # go to page 2
                "p",           # go back to page 1
                "",            # cancel
            )),
        ):
            from legacy_report.menu import add_issue
            add_issue()

        # Table rendered 3 times: page 1, page 2, page 1 again
        assert mock_table.call_count == 3
        mock_issues.assert_not_called()


# ---------------------------------------------------------------------------
# issue view display (search_collection)
# ---------------------------------------------------------------------------

class TestIssueViewDisplay:
    """Guard that _paginated_issue_view uses Rich table + number prompt, not inquirer.select."""

    def test_issue_view_shows_table_not_select_list(self, session, seeded):
        """Issue list must use Rich table + number prompt; inquirer.select is only used for sort."""
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_issues_table") as mock_table,
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",  # search query
                "",                    # blank to exit issue view
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock("pub_date")),
        ):
            from legacy_report.menu import search_collection
            search_collection()

        mock_table.assert_called()

    def test_issue_view_blank_cancels_loop(self, session, seeded):
        """Blank input at the number prompt exits without showing any detail panel."""
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",  # search query
                "",                    # blank to exit
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock("pub_date")),
            patch("legacy_report.menu.print_issue_detail") as mock_detail,
        ):
            from legacy_report.menu import search_collection
            search_collection()

        mock_detail.assert_not_called()

    def test_issue_view_number_shows_detail(self, session, seeded):
        """Entering '1' shows the detail panel for the first issue, then loops back."""
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",  # search query
                "1",                   # view detail for issue 1
                "",                    # "Press Enter to go back" prompt
                "",                    # blank to exit issue view loop
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock("pub_date")),
            patch("legacy_report.menu.print_issue_detail") as mock_detail,
        ):
            from legacy_report.menu import search_collection
            search_collection()

        mock_detail.assert_called_once()


# ---------------------------------------------------------------------------
# browse_collection display
# ---------------------------------------------------------------------------

class TestBrowseCollectionDisplay:
    """Guard that browse_collection uses Rich table + number prompt for series, not inquirer.select."""

    def test_browse_shows_series_table_not_select_list(self, session, seeded):
        """Series list must use Rich table + number prompt; inquirer.select must never be called."""
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_series_table") as mock_table,
            patch("legacy_report.menu.inquirer.text", _text_mock("")),
            patch("legacy_report.menu.inquirer.select") as mock_select,
        ):
            from legacy_report.menu import browse_collection
            browse_collection()

        mock_table.assert_called()
        mock_select.assert_not_called()

    def test_browse_number_selection_opens_issue_view(self, session, seeded):
        """Entering '1' opens the issue view (shows issues table) for the first series."""
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_issues_table") as mock_issues_table,
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "1",  # select first series
                "",   # blank to exit issue view
            )),
        ):
            from legacy_report.menu import browse_collection
            browse_collection()

        mock_issues_table.assert_called()

    def test_browse_blank_cancels_without_opening_issues(self, session, seeded):
        """Blank input at the series prompt exits without showing any issues."""
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_issues_table") as mock_issues_table,
            patch("legacy_report.menu.inquirer.text", _text_mock("")),
        ):
            from legacy_report.menu import browse_collection
            browse_collection()

        mock_issues_table.assert_not_called()


# ---------------------------------------------------------------------------
# Tier 2: search_collection sort + cancel
# ---------------------------------------------------------------------------

class TestSearchCollectionSort:
    """Verify sort choices re-order results and cancel exits before the issue view."""

    def test_sort_by_issue_number(self, session, seeded):
        """Choosing 'issue_num' sort orders issues numerically by issue_number."""
        captured = []

        def capture_table(issues, series_map):
            captured.extend(issues)

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_issues_table", side_effect=capture_table),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",  # search query
                "",                    # blank to exit issue view
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock("issue_num")),
        ):
            from legacy_report.menu import search_collection
            search_collection()

        assert len(captured) == 2
        assert captured[0].issue_number == "1"
        assert captured[1].issue_number == "2"

    def test_sort_by_lgy_number(self, session, seeded):
        """Choosing 'lgy_num' sort orders issues numerically by legacy_number."""
        captured = []

        def capture_table(issues, series_map):
            captured.extend(issues)

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_issues_table", side_effect=capture_table),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",  # search query
                "",                    # blank to exit
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock("lgy_num")),
        ):
            from legacy_report.menu import search_collection
            search_collection()

        assert len(captured) == 2
        assert captured[0].legacy_number == "1"
        assert captured[1].legacy_number == "2"

    def test_sort_cancel_exits_before_issue_view(self, session, seeded):
        """Choosing 'cancel' at the sort prompt returns without rendering the issue table."""
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_issues_table") as mock_table,
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man")),
            patch("legacy_report.menu.inquirer.select", _single_mock("cancel")),
        ):
            from legacy_report.menu import search_collection
            search_collection()

        mock_table.assert_not_called()

    def test_sort_issue_number_reorders_out_of_sequence(self, session):
        """Issue numbers '10' and '2' sort numerically (2 < 10), not lexicographically."""
        series, _ = get_or_create_series(
            session,
            title="X-Men",
            start_year=1991,
            publisher="Marvel Comics",
        )
        # Seed in reverse numeric order so pub_date order ≠ numeric order
        issue_10 = create_issue(
            session,
            series_id=series.id,
            issue_number="10",
            legacy_number="10",
            publication_date=date(1991, 3, 1),
        )
        issue_2 = create_issue(
            session,
            series_id=series.id,
            issue_number="2",
            legacy_number="2",
            publication_date=date(1991, 5, 1),
        )
        # Capture IDs before session state changes
        issue_10_id = issue_10.id
        issue_2_id = issue_2.id

        captured = []

        def capture_table(issues, series_map):
            captured.extend(issues)

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_issues_table", side_effect=capture_table),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "X-Men",  # search query
                "",        # blank to exit issue view
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock("issue_num")),
        ):
            from legacy_report.menu import search_collection
            search_collection()

        assert len(captured) == 2
        assert captured[0].id == issue_2_id   # "2" comes first numerically
        assert captured[1].id == issue_10_id  # "10" comes after "2"

    def test_sort_fractional_issue_number(self, session):
        """Issue number '1/2' sorts numerically between 0 and 1."""
        series, _ = get_or_create_series(
            session,
            title="Wolverine",
            start_year=1982,
            publisher="Marvel Comics",
        )
        issue_half = create_issue(
            session,
            series_id=series.id,
            issue_number="1/2",
            legacy_number=None,
            publication_date=date(1982, 1, 1),
        )
        issue_1 = create_issue(
            session,
            series_id=series.id,
            issue_number="1",
            legacy_number=None,
            publication_date=date(1982, 6, 1),
        )
        issue_2 = create_issue(
            session,
            series_id=series.id,
            issue_number="2",
            legacy_number=None,
            publication_date=date(1982, 9, 1),
        )
        issue_half_id = issue_half.id
        issue_1_id = issue_1.id
        issue_2_id = issue_2.id

        captured = []

        def capture_table(issues, series_map):
            captured.extend(issues)

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_issues_table", side_effect=capture_table),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Wolverine",  # search query
                "",            # blank to exit
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock("issue_num")),
        ):
            from legacy_report.menu import search_collection
            search_collection()

        assert len(captured) == 3
        assert captured[0].id == issue_half_id  # 0.5 < 1 < 2
        assert captured[1].id == issue_1_id
        assert captured[2].id == issue_2_id


# ---------------------------------------------------------------------------
# Tier 2: stats in header
# ---------------------------------------------------------------------------

class TestHeaderStats:
    """Verify print_header receives a stats string reflecting collection counts."""

    def test_header_stats_string(self, session, seeded):
        """`_main_menu_loop` passes a stats string like '2 issues across 1 series'."""
        captured_stats = []

        def capture_header(stats=None):
            captured_stats.append(stats)

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_header", side_effect=capture_header),
            patch("legacy_report.menu.inquirer.rawlist", _single_mock("quit")),
        ):
            from legacy_report.menu import _main_menu_loop
            _main_menu_loop()

        assert captured_stats, "print_header was never called"
        stats = captured_stats[0]
        assert "2 issue" in stats
        assert "1 series" in stats

    def test_header_stats_singular_issue(self, session, seeded):
        """With exactly 1 issue, the string reads '1 issue' (not '1 issues')."""
        # Delete issue2 so only issue1 remains
        issue2 = seeded["issue2"]
        session.delete(issue2)
        session.commit()

        captured_stats = []

        def capture_header(stats=None):
            captured_stats.append(stats)

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.print_header", side_effect=capture_header),
            patch("legacy_report.menu.inquirer.rawlist", _single_mock("quit")),
        ):
            from legacy_report.menu import _main_menu_loop
            _main_menu_loop()

        stats = captured_stats[0]
        assert "1 issue " in stats or stats.startswith("1 issue")
        assert "issues" not in stats


# ---------------------------------------------------------------------------
# Tier 2: post-action confirmation (edit_issue shows detail panel)
# ---------------------------------------------------------------------------

class TestEditPostAction:
    """Verify print_issue_detail is called after a successful edit."""

    def test_edit_shows_detail_after_update(self, session, seeded):
        issue = seeded["issue1"]

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",
                "1",
                issue.issue_number,
                "",
                "",
                "Confirmed Title",
                "",
                "",
                "",          # Press Enter to continue
            )),
            patch("legacy_report.menu.print_issue_detail") as mock_detail,
        ):
            from legacy_report.menu import edit_issue
            edit_issue()

        mock_detail.assert_called_once()
        called_issue = mock_detail.call_args[0][0]
        assert called_issue.story_title == "Confirmed Title"

