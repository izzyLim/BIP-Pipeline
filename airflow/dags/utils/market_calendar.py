"""
한국 주식시장 개장일 판단 유틸리티
- 주말, 공휴일, 증시 휴장일 체크
- 모든 DAG에서 공통 사용
"""

import logging
from datetime import date, datetime, timezone, timedelta

import holidays

KST = timezone(timedelta(hours=9))

logger = logging.getLogger(__name__)

# 한국 공휴일 + 증시 추가 휴장일
_kr_holidays = holidays.KR()

# holidays 라이브러리에 빠진 증시 휴장일 수동 추가
# 근로자의날 (매년 5/1, 공휴일은 아니지만 증시 휴장)
EXTRA_MARKET_HOLIDAYS = {
    # 근로자의날
    date(2025, 5, 1): "근로자의날",
    date(2026, 5, 1): "근로자의날",
    date(2027, 5, 1): "근로자의날",
    date(2028, 5, 1): "근로자의날",
    date(2029, 5, 1): "근로자의날",
    date(2030, 5, 1): "근로자의날",
    # 임시공휴일 등은 발표 시 추가
}


def is_market_open(check_date: date = None) -> bool:
    """
    한국 주식시장 개장일 여부 판단

    Args:
        check_date: 확인할 날짜 (None이면 오늘)

    Returns:
        True: 개장일, False: 휴장일
    """
    if check_date is None:
        check_date = datetime.now(KST).date()

    # 1. 주말
    if check_date.weekday() >= 5:
        return False

    # 2. 공휴일 (holidays 라이브러리)
    if check_date in _kr_holidays:
        logger.info(f"휴장일 (공휴일): {check_date} — {_kr_holidays.get(check_date)}")
        return False

    # 3. 증시 추가 휴장일 (근로자의날 등)
    if check_date in EXTRA_MARKET_HOLIDAYS:
        logger.info(f"휴장일 (증시): {check_date} — {EXTRA_MARKET_HOLIDAYS[check_date]}")
        return False

    return True


def is_market_closed(check_date: date = None) -> bool:
    """is_market_open의 반대"""
    return not is_market_open(check_date)
