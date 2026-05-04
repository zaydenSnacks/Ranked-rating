from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(__file__).parent.parent.parent / "credence.db"

engine = create_engine(f"sqlite:///{DB_PATH}")

Session = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass
