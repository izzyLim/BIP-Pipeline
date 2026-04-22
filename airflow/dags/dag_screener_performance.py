"""
종목 추천 성과 측정 DAG
- 평일 18:00 KST (analytics DAG 17:30 완료 후)
- 미종료 추천 조회 → D+1/D+5/D+20 성과 rolling 업데이트
- 진입가: D+1 시가, 수익률: 종가 기준, 목표/손절: 장중 고가/저가
"""

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

default_args = {
    "owner": "bip",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def update_performance(**context):
    """미종료 추천의 성과 rolling 업데이트"""
    import os
    from sqlalchemy import create_engine, text

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pg_pw = os.getenv("PG_PASSWORD", "")
        database_url = f"postgresql+psycopg2://user:{pg_pw}@bip-postgres:5432/stockdb"
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # D+60 미달 추천 조회 (closed여도 daily_tracking은 D+60까지 계속)
        rows = conn.execute(text("""
            SELECT r.run_date, r.ticker, r.recommendation_type,
                   r.target_price_short, r.stop_loss, r.close_at_rec,
                   p.status, p.d1_open, p.target_hit, p.stop_hit,
                   p.target_hit_day, p.stop_hit_day
            FROM stock_recommendations r
            JOIN recommendation_performance p
                USING (run_date, ticker, recommendation_type)
            WHERE p.status NOT IN ('expired', 'tracking_done')
              AND r.run_date < CURRENT_DATE
            ORDER BY r.run_date
        """)).fetchall()

        if not rows:
            print("성과 업데이트 대상 없음")
            return {"updated": 0}

        print(f"성과 업데이트 대상: {len(rows)}건")
        updated = 0

        for row in rows:
            run_date = row.run_date
            ticker = row.ticker
            rec_type = row.recommendation_type
            target_price = float(row.target_price_short or 0)
            stop_loss = float(row.stop_loss or 0)

            # 추천일 이후 거래일 데이터 조회
            prices = conn.execute(text("""
                SELECT trade_date, open, high, low, close, volume,
                       ROW_NUMBER() OVER (ORDER BY trade_date) as day_n
                FROM analytics_stock_daily
                WHERE ticker = :ticker
                  AND trade_date > :run_date
                ORDER BY trade_date
                LIMIT 60
            """), {"ticker": ticker, "run_date": run_date}).fetchall()

            # 추천 후 30 거래일 이상 데이터 없으면 expired 처리
            if not prices:
                from datetime import date as _date
                days_since = (_date.today() - run_date).days
                if days_since >= 30:
                    conn.execute(text("""
                        UPDATE recommendation_performance
                        SET status = 'expired', last_updated_at = NOW()
                        WHERE run_date = :run_date AND ticker = :ticker
                          AND recommendation_type = :rec_type
                    """), {"run_date": run_date, "ticker": ticker, "rec_type": rec_type})
                    updated += 1
                continue

            # D+1 시가 (진입가)
            d1_open = float(prices[0].open) if prices[0].open else None
            d1_trade_date = prices[0].trade_date
            d1_close = float(prices[0].close) if prices[0].close else None

            if not d1_open or d1_open <= 0:
                continue

            # D+5, D+20 데이터
            d5_close = None
            d5_trade_date = None
            d5_high = None
            d5_low = None
            d20_close = None
            d20_trade_date = None
            d20_high = None
            d20_low = None
            d60_close = None
            d60_trade_date = None
            d60_high = None
            d60_low = None

            running_high = 0
            running_low = float('inf')

            # 목표/손절 최초 도달일 추적
            target_hit_day = row.target_hit_day
            stop_hit_day = row.stop_hit_day

            for p in prices:
                day_n = p.day_n
                p_open = float(p.open) if p.open and p.open > 0 else None
                high = float(p.high) if p.high and p.high > 0 else None
                low = float(p.low) if p.low and p.low > 0 else None
                close = float(p.close) if p.close and p.close > 0 else None
                p_volume = int(p.volume) if hasattr(p, 'volume') and p.volume else None

                # NULL 데이터는 집계에서 제외
                if high is not None:
                    running_high = max(running_high, high)
                if low is not None:
                    running_low = min(running_low, low)

                # 목표 도달 판정 (장중 고가 기준, 5% 버퍼)
                # 목표가 +5% 초과 시 확정 (목표 근처 횡보는 미판정)
                BUFFER_PCT = 0.05
                day_target_hit = False
                if target_hit_day is None and target_price > 0 and high is not None and high >= target_price * (1 + BUFFER_PCT):
                    target_hit_day = day_n
                    day_target_hit = True

                # 손절 히트 판정 (장중 저가 기준, 5% 버퍼)
                # 손절가 -5% 이탈 시 확정
                day_stop_hit = False
                if stop_hit_day is None and stop_loss > 0 and low is not None and low <= stop_loss * (1 - BUFFER_PCT):
                    stop_hit_day = day_n
                    day_stop_hit = True

                # 일별 수익률 (D+1 시가 기준)
                day_return = round((close - d1_open) / d1_open * 100, 3) if close else None
                cum_low = running_low if running_low != float('inf') else None

                # 일별 기록 INSERT
                conn.execute(text("""
                    INSERT INTO recommendation_daily_tracking (
                        run_date, ticker, recommendation_type, trade_date, day_n,
                        open, high, low, close, volume,
                        return_pct, cumulative_high, cumulative_low,
                        target_hit, stop_hit
                    ) VALUES (
                        :run_date, :ticker, :rec_type, :trade_date, :day_n,
                        :open, :high, :low, :close, :volume,
                        :return_pct, :cum_high, :cum_low,
                        :target_hit, :stop_hit
                    )
                    ON CONFLICT (run_date, ticker, recommendation_type, day_n) DO UPDATE SET
                        open = EXCLUDED.open, high = EXCLUDED.high,
                        low = EXCLUDED.low, close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        return_pct = EXCLUDED.return_pct,
                        cumulative_high = EXCLUDED.cumulative_high,
                        cumulative_low = EXCLUDED.cumulative_low,
                        target_hit = EXCLUDED.target_hit,
                        stop_hit = EXCLUDED.stop_hit
                """), {
                    "run_date": run_date, "ticker": ticker, "rec_type": rec_type,
                    "trade_date": p.trade_date, "day_n": day_n,
                    "open": p_open, "high": high, "low": low, "close": close,
                    "volume": p_volume,
                    "return_pct": day_return,
                    "cum_high": running_high if running_high > 0 else None,
                    "cum_low": cum_low,
                    "target_hit": day_target_hit or (target_hit_day is not None and target_hit_day < day_n),
                    "stop_hit": day_stop_hit or (stop_hit_day is not None and stop_hit_day < day_n),
                })

                if day_n == 5:
                    d5_close = close
                    d5_trade_date = p.trade_date
                    d5_high = running_high
                    d5_low = running_low

                if day_n == 20:
                    d20_close = close
                    d20_trade_date = p.trade_date
                    d20_high = running_high
                    d20_low = running_low

                if day_n == 60:
                    d60_close = close
                    d60_trade_date = p.trade_date
                    d60_high = running_high
                    d60_low = running_low

            # running_low가 초기값(inf)이면 None 처리
            if running_low == float('inf'):
                running_low = None
            if d5_low == float('inf'):
                d5_low = None
            if d20_low == float('inf'):
                d20_low = None

            # 수익률 계산 (D+1 시가 기준)
            d1_return = round((d1_close - d1_open) / d1_open * 100, 3) if d1_close else None
            d5_return = round((d5_close - d1_open) / d1_open * 100, 3) if d5_close else None
            d20_return = round((d20_close - d1_open) / d1_open * 100, 3) if d20_close else None
            d60_return = round((d60_close - d1_open) / d1_open * 100, 3) if d60_close else None

            # 시나리오 판정
            target_hit = target_hit_day is not None
            stop_hit = stop_hit_day is not None

            if target_hit and stop_hit:
                # 동시 터치: 손절 우선 (보수적)
                scenario = "stop_first" if stop_hit_day <= target_hit_day else "target_first"
            elif target_hit:
                scenario = "target_first"
            elif stop_hit:
                scenario = "stop_first"
            else:
                scenario = "neither"

            # 상태 결정
            # closed: 목표/손절 히트로 성과 확정 (daily_tracking은 계속)
            # tracking_done: D+60 도달, 모든 추적 완료
            num_days = len(prices)
            if num_days >= 60:
                status = "tracking_done"
            elif target_hit or stop_hit:
                status = "closed"
            elif num_days >= 20:
                status = "pending_d60"
            elif num_days >= 5:
                status = "pending_d20"
            elif num_days >= 1:
                status = "pending_d5"
            else:
                status = "pending"

            # UPSERT
            conn.execute(text("""
                UPDATE recommendation_performance SET
                    d1_open = :d1_open,
                    d1_trade_date = :d1_trade_date,
                    d1_close = :d1_close,
                    d5_close = :d5_close,
                    d5_trade_date = :d5_trade_date,
                    d20_close = :d20_close,
                    d20_trade_date = :d20_trade_date,
                    d5_high = :d5_high,
                    d5_low = :d5_low,
                    d20_high = :d20_high,
                    d20_low = :d20_low,
                    d1_return_pct = :d1_return,
                    d5_return_pct = :d5_return,
                    d20_return_pct = :d20_return,
                    d60_close = :d60_close,
                    d60_trade_date = :d60_trade_date,
                    d60_high = :d60_high,
                    d60_low = :d60_low,
                    d60_return_pct = :d60_return,
                    target_hit = :target_hit,
                    target_hit_day = :target_hit_day,
                    stop_hit = :stop_hit,
                    stop_hit_day = :stop_hit_day,
                    scenario_result = :scenario,
                    status = :status,
                    last_updated_at = NOW()
                WHERE run_date = :run_date
                  AND ticker = :ticker
                  AND recommendation_type = :rec_type
            """), {
                "run_date": run_date,
                "ticker": ticker,
                "rec_type": rec_type,
                "d1_open": d1_open,
                "d1_trade_date": d1_trade_date,
                "d1_close": d1_close,
                "d5_close": d5_close,
                "d5_trade_date": d5_trade_date,
                "d20_close": d20_close,
                "d20_trade_date": d20_trade_date,
                "d5_high": d5_high,
                "d5_low": d5_low,
                "d20_high": d20_high,
                "d20_low": d20_low,
                "d1_return": d1_return,
                "d5_return": d5_return,
                "d20_return": d20_return,
                "d60_close": d60_close,
                "d60_trade_date": d60_trade_date,
                "d60_high": d60_high,
                "d60_low": d60_low,
                "d60_return": d60_return,
                "target_hit": target_hit,
                "target_hit_day": target_hit_day,
                "stop_hit": stop_hit,
                "stop_hit_day": stop_hit_day,
                "scenario": scenario,
                "status": status,
            })
            updated += 1

    print(f"성과 업데이트 완료: {updated}건")
    return {"updated": updated}


with DAG(
    dag_id="screener_performance",
    default_args=default_args,
    description="종목 추천 성과 측정 — D+1/D+5/D+20 rolling 업데이트",
    schedule_interval="0 18 * * 1-5",  # 평일 18:00 KST (analytics 17:30 이후)
    start_date=datetime(2026, 4, 19),
    catchup=False,
    tags=["screener", "backtest"],
) as dag:

    perf_task = PythonOperator(
        task_id="update_performance",
        python_callable=update_performance,
    )
