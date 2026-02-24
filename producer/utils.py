from datetime import datetime, date
import pytz
import holidays


class NYSEHolidays(holidays.UnitedStates):
    """
    NYSE 공휴일 (미국 연방 공휴일 기반 + Good Friday 추가)
    참고: https://www.nyse.com/markets/hours-calendars
    """
    def _populate(self, year):
        super()._populate(year)
        # Good Friday 추가 (부활절 2일 전 금요일)
        self._add_good_friday("Good Friday")

    def _add_good_friday(self, name):
        """부활절 기준 Good Friday 계산"""
        from dateutil.easter import easter
        for year in range(self.years.start, self.years.stop):
            easter_date = easter(year)
            good_friday = date(easter_date.year, easter_date.month, easter_date.day - 2)
            self[good_friday] = name


# NYSE 공휴일 캐시 (매번 생성 방지)
_nyse_holidays = None


def get_nyse_holidays(year: int = None) -> holidays.HolidayBase:
    """NYSE 공휴일 객체 반환 (캐싱됨)"""
    global _nyse_holidays
    if _nyse_holidays is None:
        current_year = datetime.now().year
        _nyse_holidays = NYSEHolidays(years=range(current_year - 1, current_year + 3))
    return _nyse_holidays


def is_nyse_holiday(check_date: date = None) -> bool:
    """해당 날짜가 NYSE 공휴일인지 확인"""
    if check_date is None:
        ny_tz = pytz.timezone("America/New_York")
        check_date = datetime.now(ny_tz).date()
    return check_date in get_nyse_holidays()


def get_market_status():
    """
    NYSE 시장 상태 반환
    - "마감": 주말 또는 공휴일
    - "개장 전": 평일 09:30 이전
    - "장중": 평일 09:30 ~ 16:00
    - "마감": 평일 16:00 이후
    """
    ny_tz = pytz.timezone("America/New_York")
    now = datetime.now(ny_tz)

    # 주말 체크
    if now.weekday() >= 5:
        return "마감"

    # 공휴일 체크
    if is_nyse_holiday(now.date()):
        return "마감"

    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

    if now < market_open:
        return "개장 전"
    elif market_open <= now <= market_close:
        return "장중"
    else:
        return "마감"
