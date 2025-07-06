# shared/db_handler.py 예시
from .db.session import SessionLocal
from .db.models import StockPrice1m

def save_stock_prices(data_list: list[dict]):
    session = SessionLocal()
    try:
        for data in data_list:
            record = StockPrice1m(**data)
            session.add(record)
        session.commit()
    except Exception as e:
        print(f"[ERROR] DB 저장 실패: {e}")
        session.rollback()
    finally:
        session.close()
