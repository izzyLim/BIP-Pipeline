import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
from shared.db_handler import save_stock_prices
from batch.batch_utils import fetch_historical_data


def run(ticker: str, start_date: str, end_date: str):
    print(f"[BATCH] {ticker} | 기간: {start_date} ~ {end_date} 데이터 수집 시작", flush=True)

    data = fetch_historical_data(ticker, start_date, end_date)
    print(f"[BATCH] 수집된 데이터: {len(data)}건", flush=True)

    if data:
        save_stock_prices(data)
        print("[BATCH] 데이터 저장 완료.", flush=True)
    else:
        print("[BATCH] 저장할 데이터가 없습니다.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()

    run(args.ticker, args.start, args.end)
