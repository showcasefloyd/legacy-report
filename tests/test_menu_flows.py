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
                issue.issue_number,      # issue_number field
                "",                      # legacy_number
                "",                      # pub date
                "New Story Title",       # story_title
                "",                      # writer
                "",                      # artist
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock(issue_id)),
        ):
            from legacy_report.menu import edit_issue
            edit_issue()

        session.expire_all()
        updated = session.get(Issue, issue_id)
        assert updated.story_title == "New Story Title"

    def test_edit_survives_gc_between_select_and_mutate(self, session, seeded):
        """
        Force gc.collect() after the select prompt and before _prompt_issue_fields.
        This replicates the GC pressure from InquirerPy's asyncio event loop.
        Without the ID-based re-fetch fix, this raises ObjectDereferencedError.
        """
        issue = seeded["issue1"]
        issue_id = issue.id

        gc_collected = []

        mock_select = MagicMock()

        def execute_select():
            gc.collect()
            gc_collected.append(True)
            return issue_id

        mock_select.return_value.execute.side_effect = execute_select

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",
                issue.issue_number,
                "",
                "",
                "GC-Proof Title",
                "",
                "",
            )),
            patch("legacy_report.menu.inquirer.select", mock_select),
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
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man")),
            patch("legacy_report.menu.inquirer.select", _single_mock(None)),
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
            patch("legacy_report.menu.inquirer.select") as mock_select,
        ):
            from legacy_report.menu import edit_issue
            edit_issue()
            mock_select.assert_not_called()

    def test_edit_updates_writer_and_artist(self, session, seeded):
        issue = seeded["issue2"]
        issue_id = issue.id

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock(
                "Amazing Spider-Man",
                issue.issue_number,
                "",
                "",
                "",
                "Chris Claremont",
                "John Byrne",
            )),
            patch("legacy_report.menu.inquirer.select", _single_mock(issue_id)),
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
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man")),
            patch("legacy_report.menu.inquirer.select", _single_mock(issue_id)),
            patch("legacy_report.menu.inquirer.confirm", _single_mock(True)),
        ):
            from legacy_report.menu import delete_issue
            delete_issue()

        assert session.get(Issue, issue_id) is None

    def test_delete_survives_gc_between_select_and_confirm(self, session, seeded):
        """
        Force gc.collect() after select, before confirm — replicates GC pressure
        from InquirerPy's event loop on the confirm prompt.
        """
        issue = seeded["issue1"]
        issue_id = issue.id

        gc_collected = []

        mock_select = MagicMock()

        def execute_select():
            gc.collect()
            gc_collected.append(True)
            return issue_id

        mock_select.return_value.execute.side_effect = execute_select

        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man")),
            patch("legacy_report.menu.inquirer.select", mock_select),
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
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man")),
            patch("legacy_report.menu.inquirer.select", _single_mock(issue_id)),
            patch("legacy_report.menu.inquirer.confirm", _single_mock(False)),
        ):
            from legacy_report.menu import delete_issue
            delete_issue()

        assert session.get(Issue, issue_id) is not None

    def test_delete_cancel_at_select_makes_no_changes(self, session, seeded):
        with (
            patch("legacy_report.menu._get_session", return_value=session),
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man")),
            patch("legacy_report.menu.inquirer.select", _single_mock(None)),
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
            patch("legacy_report.menu.inquirer.text", _text_mock("Amazing Spider-Man")),
            patch("legacy_report.menu.inquirer.select", _single_mock(issue1_id)),
            patch("legacy_report.menu.inquirer.confirm", _single_mock(True)),
        ):
            from legacy_report.menu import delete_issue
            delete_issue()

        assert session.get(Issue, issue1_id) is None
        assert session.get(Issue, issue2_id) is not None
