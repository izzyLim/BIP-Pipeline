from sqlalchemy import Column, String, Float, BigInteger, TIMESTAMP, Integer
from datetime import datetime
from .base import Base



class StockPrice1m(Base):
    __tablename__ = "stock_price_1m"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False)       # UTC 기준
    timestamp_ny = Column(TIMESTAMP(timezone=True), nullable=False)    # 뉴욕 시간
    timestamp_kst = Column(TIMESTAMP(timezone=True), nullable=False)   # 서울 시간

    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)

    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
