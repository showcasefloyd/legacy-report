from pathlib import Path
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

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

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
