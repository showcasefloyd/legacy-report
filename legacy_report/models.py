from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Series(SQLModel, table=True):
    __tablename__ = "series"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    start_year: int
    publisher: Optional[str] = None
    comicvine_id: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Issue(SQLModel, table=True):
    __tablename__ = "issue"

    id: Optional[int] = Field(default=None, primary_key=True)
    series_id: int = Field(foreign_key="series.id", index=True)
    # TEXT — handles 0, 1.5, 1/2, -1, non-sequential modern numbering
    issue_number: str
    # LGY — the canonical legacy number, the spine of the collection
    legacy_number: Optional[str] = None
    # Most important field — the chronological anchor
    publication_date: Optional[date] = None
    story_title: Optional[str] = None
    description: Optional[str] = None
    cover_image_url: Optional[str] = None
    writer: Optional[str] = None
    artist: Optional[str] = None
    comicvine_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ComicVineCache(SQLModel, table=True):
    __tablename__ = "comicvine_cache"

    id: Optional[int] = Field(default=None, primary_key=True)
    cache_key: str = Field(unique=True, index=True)
    response_json: str
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    ttl_hours: int = 24
