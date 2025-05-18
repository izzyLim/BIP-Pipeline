from sqlalchemy import Column, String, Float, BigInteger, TIMESTAMP, Integer
from datetime import datetime
from .base import Base

class StockPrice(Base):
    __tablename__ = "stock_price"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
