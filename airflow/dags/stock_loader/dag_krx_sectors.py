"""
[05_kr_sectors_daily]
KRX 업종별 등락률 일일 수집
- 네이버 금융 스크래핑 기반 공식 KRX 업종 분류
- macro_indicators 테이블에 `krx_sector_{code}` 형태로 저장
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.db import get_pg_conn
from utils.config import PG_CONN_INFO
from utils.lineage import register_table_lineage_async
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def fetch_krx_sectors() -> list:
    """네이버 금융에서 KRX 업종별 등락률 스크래핑"""
    url = "https://finance.naver.com/sise/sise_group.naver?type=upjong"

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        sectors = []

        for tr in soup.select('tr'):
            tds = tr.select('td')
            if len(tds) >= 3:
                # 업종명 링크 확인
                link = tds[0].select_one('a[href*="sise_group_detail"]')
                if link:
                    name = link.text.strip()

                    # 업종 코드 추출
                    href = link.get('href', '')
                    sector_code = ''
                    if 'no=' in href:
                        sector_code = href.split('no=')[1].split('&')[0]

                    # 등락률 찾기
                    change_pct = None
                    for td in tds[1:4]:
                        text = td.text.strip()
                        if '%' in text:
                            try:
                                change_pct = float(text.replace('%', '').replace('+', ''))
                            except:
                                pass
                            break

                    if change_pct is not None:
                        sectors.append({
                            'name': name,
                            'code': sector_code,
                            'change_pct': change_pct,
                        })

        return sectors

    except Exception as e:
        logger.error(f"Failed to fetch KRX sectors: {e}")
        return []


def load_krx_sectors(**context):
    """KRX 업종별 등락률 수집 및 저장"""
    conn = get_pg_conn(PG_CONN_INFO)
    try:
        cursor = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')

        logger.info("Naver Finance에서 KRX 업종 데이터 수집 중...")
        sectors = fetch_krx_sectors()

        if not sectors:
            logger.warning("업종 데이터 없음")
            return {"inserted": 0}

        total_inserted = 0
        for sector in sectors:
            try:
                # 이름 기반 키 사용 (이름으로 직접 조회 가능)
                indicator_type = f"krx_sector_{sector['name']}"
                cursor.execute("""
                    INSERT INTO macro_indicators (indicator_date, region, indicator_type, value, change_pct, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (indicator_date, region, indicator_type)
                    DO UPDATE SET value = EXCLUDED.value, change_pct = EXCLUDED.change_pct
                """, (today, 'South Korea', indicator_type, sector['change_pct'], sector['change_pct']))
                total_inserted += cursor.rowcount
            except Exception as e:
                logger.warning(f"업종 {sector['name']} 저장 실패: {e}")
                conn.rollback()

        conn.commit()
        logger.info(f"KRX 업종 적재 완료: {total_inserted}건 (상위: {sectors[:3]}, 하위: {sectors[-3:]})")
        register_table_lineage_async("macro_indicators", source_tables=[])
        return {"inserted": total_inserted, "sectors": len(sectors)}

    finally:
        conn.close()


with DAG(
    dag_id="05_kr_sectors_daily",
    default_args=default_args,
    description="KRX 업종별 등락률 일일 수집 (네이버 금융 스크래핑)",
    schedule_interval="35 16 * * 1-5",  # 평일 16:35 KST (02_price_kr 16:00 완료 후)
    catchup=False,
    tags=["kr", "sectors", "daily"],
) as dag_daily:

    load_task = PythonOperator(
        task_id='load_krx_sectors',
        python_callable=load_krx_sectors,
    )
