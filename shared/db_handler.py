# shared/db_handler.py
from .db.session import SessionLocal
from .db.models import StockPrice1m
from .logging_config import get_logger

logger = get_logger(__name__)


def save_stock_prices(data_list: list[dict]):
    session = SessionLocal()
    try:
        for data in data_list:
            record = StockPrice1m(**data)
            session.add(record)
        session.commit()
        logger.info(f"DB 저장 완료: {len(data_list)}건")
    except Exception as e:
        logger.error(f"DB 저장 실패: {e}")
        session.rollback()
    finally:
        session.close()
