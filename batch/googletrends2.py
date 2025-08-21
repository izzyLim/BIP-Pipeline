# googletrends_direct_with_token.py

import json
import urllib.parse
import requests
import pandas as pd
from datetime import datetime

# ——————————————————————————————————————————
KEYWORDS  = ["Galaxy Z Fold 7", "Galaxy Z Fold 6"]
TIMEFRAME = "2018-01-01 2025-07-17"
GEO       = ""
HL        = "en-US"
# ——————————————————————————————————————————

def get_explore_widgets(keywords, timeframe, geo, hl):
    """1) explore API에서 widget 리스트와 token을 가져온다."""
    items = [{"keyword": kw, "geo": geo, "time": timeframe} for kw in keywords]
    explore_req = {"comparisonItem": items, "category": 0, "property": ""}
    req_str = json.dumps(explore_req, separators=(",", ":"))
    req_enc = urllib.parse.quote(req_str, safe="")

    url = (
        f"https://trends.google.com/trends/explore"
        f"?hl={hl}&tz=0&req={req_enc}"
    )
    resp = requests.get(url, headers={"User-Agent":"Mozilla/5.0"})
    resp.raise_for_status()
    text = resp.text
    # prefix 제거
    for pre in (")]}',", ")]}'\n"):
        if text.startswith(pre):
            text = text[len(pre):]
    data = json.loads(text)
    return data["widgets"]

def fetch_multiline(data_widgets, keywords, hl):
    """2) multiline 위젯 가져와서 timelineData 파싱"""
    # id가 'TIMESERIES' 혹은 'multiline' 위젯 찾기
    widget = next(w for w in data_widgets if w["type"] in ("TIMESERIES","multiline"))
    req = widget["request"]
    token = widget["token"]

    # req는 dict → JSON → URL 인코딩
    req_str = json.dumps(req, separators=(",",":"))
    req_enc = urllib.parse.quote(req_str, safe="")

    url = (
        f"https://trends.google.com/trends/explore"
        f"?hl={hl}&tz=0"
        f"&req={req_enc}"
        f"&token={urllib.parse.quote(token, safe='')}"
    )
    print("▶ MULTILINE URL:", url)

    resp = requests.get(url, headers={"User-Agent":"Mozilla/5.0"})
    resp.raise_for_status()
    text = resp.text
    for pre in (")]}',", ")]}'\n"):
        if text.startswith(pre):
            text = text[len(pre):]
    return json.loads(text)

def to_df(raw, keywords):
    ts = raw["default"]["timelineData"]
    rows = []
    for e in ts:
        dt = datetime.fromtimestamp(int(e["time"]))
        rows.append(
            {"datetime": dt, **{kw: e["value"][i] for i, kw in enumerate(keywords)}}
        )
    df = pd.DataFrame(rows).set_index("datetime")
    return df

if __name__ == "__main__":
    widgets = get_explore_widgets(KEYWORDS, TIMEFRAME, GEO, HL)
    raw = fetch_multiline(widgets, KEYWORDS, HL)
    df  = to_df(raw, KEYWORDS)
    print(df.tail())
    df.to_csv("trends_two_step.csv", encoding="utf-8-sig")
    print("✅ Saved → trends_two_step.csv")
