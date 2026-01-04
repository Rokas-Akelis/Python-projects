# models.py
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


def get_engine(db_path="sqlite:///inventory.db"):
    return create_engine(db_path, echo=False)


def get_session(db_path="sqlite:///inventory.db"):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()
