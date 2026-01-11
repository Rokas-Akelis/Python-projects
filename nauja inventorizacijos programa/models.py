# models.py
from pathlib import Path
import os
import tempfile
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    JSON,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "inventory.db"


def _is_writable_path(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(path.parent, os.W_OK)


def get_default_db_path() -> Path:
    env_path = os.getenv("INVENTORY_DB_PATH")
    if env_path:
        return Path(env_path)
    if _is_writable_path(DB_PATH):
        return DB_PATH
    return Path(tempfile.gettempdir()) / "inventory.db"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Pagrindiniai raktai
    name = Column(String, unique=True, index=True, nullable=False)  # iš CSV / WC
    sku = Column(String, unique=True, index=True, nullable=True)    # savo sukurtas
    wc_id = Column(Integer, unique=True, index=True, nullable=True) # iš WooCommerce CSV / API

    # Finansai
    cost = Column(Float, nullable=True)   # savikaina (iš žmogaus CSV)
    price = Column(Float, nullable=True)  # pardavimo kaina (iš WC ar CSV)

    # Sandėlis
    quantity = Column(Integer, default=0)
    active = Column(Boolean, default=True)


class Movement(Base):
    __tablename__ = "movements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    change = Column(Integer, nullable=False)
    source = Column(String, nullable=False)
    note = Column(String, nullable=True)


class WcProductRaw(Base):
    __tablename__ = "wc_raw_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wc_id = Column(Integer, nullable=True, index=True, unique=True)
    raw = Column(JSON, nullable=False)


def get_engine(db_path=None):
    if db_path is None:
        path = get_default_db_path()
        url = f"sqlite:///{path.as_posix()}"
    elif isinstance(db_path, Path):
        url = f"sqlite:///{db_path.as_posix()}"
    else:
        url = db_path
    return create_engine(url, echo=False)


def get_session(db_path=None):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()
