# googletrends_selenium_profile.py

import json, csv, urllib.parse, time
from datetime import date
from dateutil.relativedelta import relativedelta
import requests

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.chrome.options import Options

# ◼ 키워드·기간 세팅
KEYWORD = "galaxy fold 7"
today = date.today()
two_years_ago = today - relativedelta(years=2)
TIMEFRAME = f"{two_years_ago.isoformat()} {today.isoformat()}"
LANG = "ko"
TZ   = "540"
explore_url = (
    "https://trends.google.com/trends/explore"
    f"?q={urllib.parse.quote(KEYWORD)}"
    f"&hl={LANG}&tz={TZ}"
    f"&date={urllib.parse.quote(TIMEFRAME)}"
)

# ◼ Chrome 옵션: 내 사용자 프로필 그대로 쓰기
options = Options()
# 반드시 Chrome을 완전히 종료한 뒤에 실행하세요!
options.add_argument("--user-data-dir=/Users/yeji/Library/Application Support/Google/Chrome")
options.add_argument("--profile-directory=Default")
# 헤드리스는 켜두어도 좋지만, 디버깅용으로 일단 켜 두겠습니다.
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument(f"--lang={LANG}")

# ◼ DevTools 네트워크 로그 활성화
caps = DesiredCapabilities.CHROME
caps["goog:loggingPrefs"] = {"performance": "ALL"}

# ◼ 드라이버 실행
driver = webdriver.Chrome(service=Service(), options=options, desired_capabilities=caps)
# 네트워크 캡쳐 켜기 (CDP)
driver.execute_cdp_cmd("Network.enable", {})

# ◼ 페이지 로드
driver.get(explore_url)
time.sleep(8)

# ◼ multiline 요청 가로채기
widget_req = token = None
for entry in driver.get_log("performance"):
    msg = json.loads(entry["message"])["message"]
    if msg.get("method")=="Network.responseReceived":
        url = msg["params"]["response"]["url"]
        if "widgetdata/multiline" in url:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            widget_req = qs["req"][0]
            token       = qs["token"][0]
            break

driver.quit()
if not widget_req or not token:
    raise RuntimeError("아직 multiline 요청을 찾지 못했습니다.")

# ◼ 실제 데이터 API 호출
data_url = (
  "https://trends.google.com/trends/api/widgetdata/multiline"
  f"?hl={LANG}&tz={TZ}"
  f"&req={urllib.parse.quote(widget_req)}"
  f"&token={urllib.parse.quote(token)}"
)
resp = requests.get(data_url, headers={
    "User-Agent":"Mozilla/5.0",
    "Accept-Language":"ko-KR,ko;q=0.9",
    "Referer": explore_url
}, timeout=10)

# ◼ prefix 제거 + JSON 파싱
text = resp.text
for pre in [")]}',", ")]}',\n", ")]}'"]:
    if text.startswith(pre):
        text = text[len(pre):]
        break
js = json.loads(text)
timeseries = js["default"]["timelineData"]

# ◼ CSV로 저장
with open("trend_2y_profile.csv","w",newline="",encoding="utf8") as f:
    w = csv.writer(f)
    w.writerow(["date","interest"])
    for p in timeseries:
        w.writerow([p["formattedTime"], p["value"][0]])

print("✅ trend_2y_profile.csv saved")
