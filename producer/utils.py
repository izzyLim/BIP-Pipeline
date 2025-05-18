from datetime import datetime
import pytz

def get_market_status():
    # 뉴욕 시간 (미국 동부 시간)
    ny_tz = pytz.timezone("America/New_York")
    now = datetime.now(ny_tz)

    # 평일 + 시간 조건
    if now.weekday() >= 5:  # 5: 토요일, 6: 일요일
        return "마감"

    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

    if now < market_open:
        return "개장 전"
    elif market_open <= now <= market_close:
        return "장중"
    else:
        return "마감"
