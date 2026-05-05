from datetime import date, datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from legacy_report.config import get_config

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        config = get_config()
        db_path = Path(config["db_path"]).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return _engine


def init_db() -> None:
    # Import models so SQLModel metadata is populated before create_all
    from legacy_report import models  # noqa: F401

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    # Migrate existing databases that predate these columns
    _migrations = [
        "ALTER TABLE issue ADD COLUMN read BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE issue ADD COLUMN rating INTEGER",
    ]
    with engine.connect() as conn:
        for stmt in _migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


# ---------------------------------------------------------------------------
# CRUD helpers — all DB mutations live here, not in menu flows
# ---------------------------------------------------------------------------

def get_or_create_series(
    session: Session,
    *,
    title: str,
    start_year: int,
    publisher: Optional[str] = None,
    comicvine_id: Optional[str] = None,
    description: Optional[str] = None,
) -> tuple:
    """Return (series, created). Looks up by title + start_year; creates if missing."""
    from legacy_report.models import Series

    existing = session.exec(
        select(Series).where(Series.title == title, Series.start_year == start_year)
    ).first()
    if existing:
        return existing, False

    series = Series(
        title=title,
        start_year=start_year,
        publisher=publisher,
        comicvine_id=comicvine_id,
        description=description,
    )
    session.add(series)
    session.flush()
    session.refresh(series)
    return series, True


def create_issue(
    session: Session,
    *,
    series_id: int,
    issue_number: str,
    legacy_number: Optional[str] = None,
    publication_date: Optional[date] = None,
    story_title: Optional[str] = None,
    writer: Optional[str] = None,
    artist: Optional[str] = None,
    description: Optional[str] = None,
    cover_image_url: Optional[str] = None,
    comicvine_id: Optional[str] = None,
    read: bool = False,
    rating: Optional[int] = None,
) -> object:
    """Insert a new Issue row and return a refreshed, session-tracked instance."""
    from legacy_report.models import Issue

    issue = Issue(
        series_id=series_id,
        issue_number=issue_number,
        legacy_number=legacy_number,
        publication_date=publication_date,
        story_title=story_title,
        writer=writer,
        artist=artist,
        description=description,
        cover_image_url=cover_image_url,
        comicvine_id=comicvine_id,
        read=read,
        rating=rating,
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)
    return issue


def update_issue(
    session: Session,
    issue: object,
    *,
    issue_number: Optional[str] = None,
    legacy_number: Optional[str] = None,
    publication_date: Optional[date] = None,
    story_title: Optional[str] = None,
    writer: Optional[str] = None,
    artist: Optional[str] = None,
    read: Optional[bool] = None,
    rating: Optional[int] = None,
) -> object:
    """Apply field updates to an existing Issue, commit, and return a refreshed instance."""
    if issue_number is not None:
        issue.issue_number = issue_number
    if legacy_number is not None:
        issue.legacy_number = legacy_number
    if publication_date is not None:
        issue.publication_date = publication_date
    if story_title is not None:
        issue.story_title = story_title
    if writer is not None:
        issue.writer = writer
    if artist is not None:
        issue.artist = artist
    if read is not None:
        issue.read = read
    if rating is not None:
        issue.rating = rating
    issue.updated_at = datetime.now(timezone.utc)
    session.add(issue)
    session.commit()
    session.refresh(issue)
    return issue


def delete_issue(session: Session, issue: object) -> None:
    """Delete an Issue row and commit."""
    session.delete(issue)
    session.commit()
