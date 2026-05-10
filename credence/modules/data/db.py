import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_DB_PATH = Path(__file__).parent.parent.parent / "credence.db"
_DEFAULT_URL = f"sqlite:///{_DB_PATH}"

DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_URL)

engine = create_engine(DATABASE_URL)

Session = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass
