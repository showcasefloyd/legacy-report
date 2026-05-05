"""
Tests for core collection CRUD operations.

All tests use an in-memory SQLite database — no API calls, no disk I/O.
"""
from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine

from legacy_report.models import Issue, Series
from legacy_report.db import (
    create_issue,
    delete_issue,
    get_or_create_series,
    update_issue,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(name="session")
def session_fixture():
    """In-memory SQLite session, torn down after each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="series")
def series_fixture(session: Session) -> Series:
    """A persisted Series row ready for use in issue tests."""
    s = Series(title="Amazing Spider-Man", start_year=1963, publisher="Marvel Comics")
    session.add(s)
    session.flush()
    session.refresh(s)
    return s


# ---------------------------------------------------------------------------
# get_or_create_series
# ---------------------------------------------------------------------------

class TestGetOrCreateSeries:
    def test_creates_new_series(self, session):
        series, created = get_or_create_series(
            session, title="X-Men", start_year=1963, publisher="Marvel Comics"
        )
        assert created is True
        assert series.id is not None
        assert series.title == "X-Men"
        assert series.start_year == 1963

    def test_returns_existing_series(self, session, series):
        fetched, created = get_or_create_series(
            session,
            title="Amazing Spider-Man",
            start_year=1963,
            publisher="Marvel Comics",
        )
        assert created is False
        assert fetched.id == series.id

    def test_different_start_year_creates_new(self, session, series):
        series2, created = get_or_create_series(
            session, title="Amazing Spider-Man", start_year=1999, publisher="Marvel Comics"
        )
        assert created is True
        assert series2.id != series.id


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------

class TestCreateIssue:
    def test_basic_create(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        assert issue.id is not None
        assert issue.issue_number == "1"
        assert issue.series_id == series.id

    def test_create_with_all_fields(self, session, series):
        issue = create_issue(
            session,
            series_id=series.id,
            issue_number="2",
            legacy_number="2",
            publication_date=date(1963, 5, 1),
            story_title="Duel to the Death with the Vulture!",
            writer="Stan Lee",
            artist="Steve Ditko",
        )
        assert issue.story_title == "Duel to the Death with the Vulture!"
        assert issue.writer == "Stan Lee"
        assert issue.artist == "Steve Ditko"
        assert issue.publication_date == date(1963, 5, 1)
        assert issue.legacy_number == "2"

    def test_create_persists_to_db(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="3")
        fetched = session.get(Issue, issue.id)
        assert fetched is not None
        assert fetched.issue_number == "3"

    def test_create_sets_created_at(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        assert issue.created_at is not None

    def test_issue_number_stored_as_text(self, session, series):
        """Issue numbers can be non-numeric (e.g. 0.5, MU, -1)."""
        for number in ["0", "0.5", "1/2", "-1", "MU", "Annual 1"]:
            issue = create_issue(session, series_id=series.id, issue_number=number)
            assert issue.issue_number == number


# ---------------------------------------------------------------------------
# update_issue
# ---------------------------------------------------------------------------

class TestUpdateIssue:
    def test_update_issue_number(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        updated = update_issue(session, issue, issue_number="1-A")
        assert updated.issue_number == "1-A"

    def test_update_story_title(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        updated = update_issue(session, issue, story_title="Brand New Story")
        assert updated.story_title == "Brand New Story"

    def test_update_writer_and_artist(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        updated = update_issue(session, issue, writer="Chris Claremont", artist="John Byrne")
        assert updated.writer == "Chris Claremont"
        assert updated.artist == "John Byrne"

    def test_update_persists_to_db(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        update_issue(session, issue, story_title="Persisted Title")
        fetched = session.get(Issue, issue.id)
        assert fetched.story_title == "Persisted Title"

    def test_update_sets_updated_at(self, session, series):
        issue = create_issue(
            session,
            series_id=series.id,
            issue_number="1",
            publication_date=date(1963, 3, 1),
        )
        original_created = issue.created_at
        updated = update_issue(session, issue, story_title="Changed")
        assert updated.updated_at >= original_created

    def test_update_omitted_fields_unchanged(self, session, series):
        """Passing None for a field should not overwrite existing data."""
        issue = create_issue(
            session,
            series_id=series.id,
            issue_number="1",
            writer="Stan Lee",
        )
        # Only update the story title; writer should remain untouched
        updated = update_issue(session, issue, story_title="New Story")
        assert updated.writer == "Stan Lee"

    def test_update_returns_refreshed_object(self, session, series):
        """Attributes must be accessible on the returned object without a new query."""
        issue = create_issue(session, series_id=series.id, issue_number="1")
        updated = update_issue(session, issue, legacy_number="42")
        # This would raise ObjectDereferencedError if session tracking broke
        assert updated.legacy_number == "42"
        assert updated.issue_number == "1"


# ---------------------------------------------------------------------------
# delete_issue
# ---------------------------------------------------------------------------

class TestDeleteIssue:
    def test_delete_removes_issue(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        issue_id = issue.id
        delete_issue(session, issue)
        assert session.get(Issue, issue_id) is None

    def test_delete_does_not_remove_series(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        series_id = series.id
        delete_issue(session, issue)
        assert session.get(Series, series_id) is not None

    def test_delete_correct_issue_only(self, session, series):
        issue_a = create_issue(session, series_id=series.id, issue_number="1")
        issue_b = create_issue(session, series_id=series.id, issue_number="2")
        delete_issue(session, issue_a)
        assert session.get(Issue, issue_a.id) is None
        assert session.get(Issue, issue_b.id) is not None

    def test_delete_multiple_issues(self, session, series):
        issues = [
            create_issue(session, series_id=series.id, issue_number=str(n))
            for n in range(1, 6)
        ]
        for issue in issues:
            delete_issue(session, issue)
        for issue in issues:
            assert session.get(Issue, issue.id) is None


# ---------------------------------------------------------------------------
# read / rating fields
# ---------------------------------------------------------------------------

class TestReadRatingFields:
    def test_read_defaults_to_false(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        assert issue.read is False

    def test_create_with_read_true(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1", read=True)
        assert issue.read is True

    def test_rating_defaults_to_none(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        assert issue.rating is None

    def test_create_with_rating(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1", rating=4)
        assert issue.rating == 4

    def test_update_read_to_true(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        updated = update_issue(session, issue, read=True)
        assert updated.read is True

    def test_update_read_to_false(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1", read=True)
        updated = update_issue(session, issue, read=False)
        assert updated.read is False

    def test_update_rating(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        updated = update_issue(session, issue, rating=3)
        assert updated.rating == 3

    def test_update_rating_persists_to_db(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1")
        update_issue(session, issue, rating=5)
        fetched = session.get(Issue, issue.id)
        assert fetched.rating == 5

    def test_clear_rating_with_none(self, session, series):
        """Passing rating=None must clear a previously saved rating."""
        issue = create_issue(session, series_id=series.id, issue_number="1", rating=4)
        updated = update_issue(session, issue, rating=None)
        assert updated.rating is None
        fetched = session.get(Issue, issue.id)
        assert fetched.rating is None

    def test_omit_rating_leaves_value_unchanged(self, session, series):
        """Omitting the rating argument must leave the existing rating unchanged."""
        issue = create_issue(session, series_id=series.id, issue_number="1", rating=4)
        updated = update_issue(session, issue, story_title="New Title")
        assert updated.rating == 4

    def test_update_read_omitted_leaves_value_unchanged(self, session, series):
        issue = create_issue(session, series_id=series.id, issue_number="1", read=True)
        updated = update_issue(session, issue, story_title="New Title")
        assert updated.read is True

    def test_update_read_false_is_applied_not_skipped(self, session, series):
        """read=False must be treated as an explicit update, not skipped as falsy."""
        issue = create_issue(session, series_id=series.id, issue_number="1", read=True)
        updated = update_issue(session, issue, read=False)
        fetched = session.get(Issue, issue.id)
        assert fetched.read is False

