# models.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Pagrindiniai raktai
    name = Column(String, unique=True, index=True, nullable=False)  # iš CSV / WC
    sku = Column(String, unique=True, index=True, nullable=True)    # tavo sukurtas
    wc_id = Column(Integer, unique=True, index=True, nullable=True) # iš WC

    # Finansai
    cost = Column(Float, nullable=True)   # savikaina
    price = Column(Float, nullable=True)  # pardavimo kaina

    # Sandėlis
    quantity = Column(Integer, default=0)
    active = Column(Boolean, default=True)

    # Judėjimų istorija
    movements = relationship("Movement", back_populates="product")


class Movement(Base):
    __tablename__ = "movements"

    id = Column(Integer, primary_key=True, autoincrement=True)

    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    change = Column(Integer, nullable=False)  # +10, -5 ir pan.
    source = Column(String, nullable=False)   # 'manual_ui', 'wc_order', 'stock_take'...
    note = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="movements")


def get_engine(db_path="sqlite:///inventory.db"):
    return create_engine(db_path, echo=False)


def get_session(db_path="sqlite:///inventory.db"):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()
