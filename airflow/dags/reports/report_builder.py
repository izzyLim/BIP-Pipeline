"""
리포트 빌더
- 데이터 수집, 히트맵 생성, LLM 분석을 조합하여 최종 리포트 생성
"""

import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader

import sys
from pathlib import Path

# Airflow 환경에서 reports 폴더를 path에 추가
_reports_dir = Path(__file__).parent
if str(_reports_dir) not in sys.path:
    sys.path.insert(0, str(_reports_dir))

from macro_collector import collect_all_macro_data, get_korea_market_data, get_us_market_data
from heatmap_generator import generate_treemap_heatmap
from llm_analyzer_v2 import analyze_market_v2
from realtime_news import fetch_realtime_news
from email_sender import send_email


# 템플릿 경로
TEMPLATE_DIR = Path(__file__).parent / "templates"


def build_morning_report(
    to_emails: List[str],
    send: bool = True,
) -> Dict[str, Any]:
    """
    모닝 리포트 생성 및 발송

    Args:
        to_emails: 수신자 이메일 목록
        send: 실제 발송 여부 (False면 리포트만 생성)

    Returns:
        {
            "success": bool,
            "html": str,
            "data": dict,
            "error": str (실패시)
        }
    """
    result = {"success": False, "html": "", "data": {}, "error": ""}

    try:
        # 1. 데이터 수집
        print("📊 데이터 수집 중...")
        macro_data = collect_all_macro_data()
        result["data"] = macro_data

        # 2. 히트맵 생성
        print("🎨 히트맵 생성 중...")
        korea_heatmap = ""
        kosdaq_heatmap = ""
        us_heatmap = ""
        nasdaq_heatmap = ""

        # 한국 섹터 영문 변환
        sector_kr_to_en = {
            "반도체와반도체장비": "Semiconductor",
            "자동차와부품": "Auto",
            "은행": "Banks",
            "소프트웨어와서비스": "Software",
            "전기장비": "Electrical",
            "기술하드웨어와장비": "Tech Hardware",
            "제약": "Pharma",
            "미디어": "Media",
            "에너지": "Energy",
            "화학": "Chemicals",
            "금속과광물": "Metals",
            "생명공학": "Biotech",
            "건설": "Construction",
            "유통": "Retail",
            "음식료": "Food",
            "보험": "Insurance",
            "운송": "Transport",
            "통신서비스": "Telecom",
            "전자부품": "Electronics",
        }

        # 한국 히트맵
        korea = macro_data.get("korea", {})
        if korea.get("stocks"):
            korea_df = pd.DataFrame(korea["stocks"])
            korea_df = korea_df.rename(columns={
                "stock_name": "stock_name",
                "sector": "sector",
                "market_value": "market_cap",
                "change_pct": "change_pct"
            })
            # 한글 종목명 사용 (stock_name 그대로 유지)
            # 상위 100개만 사용 (시각화 성능)
            korea_df = korea_df.head(100)

            try:
                korea_heatmap = generate_treemap_heatmap(
                    korea_df,
                    title="KOSPI Top 100",
                    sector_col="sector",
                    name_col="stock_name",
                    value_col="market_cap",
                    color_col="change_pct",
                )
            except Exception as e:
                print(f"⚠️ 한국 히트맵 생성 실패: {e}")

        # 미국 히트맵
        us = macro_data.get("us", {})
        if us.get("stocks"):
            us_df = pd.DataFrame(us["stocks"])
            us_df = us_df.rename(columns={
                "stock_name": "stock_name",
                "sector": "sector",
                "market_value": "market_cap",
                "change_pct": "change_pct"
            })
            # ticker를 종목명으로 사용 (영문)
            us_df["stock_name"] = us_df["ticker"]
            # 상위 100개만 사용
            us_df = us_df.head(100)

            try:
                us_heatmap = generate_treemap_heatmap(
                    us_df,
                    title="S&P 500 Top 100",
                    sector_col="sector",
                    name_col="stock_name",
                    value_col="market_cap",
                    color_col="change_pct",
                )
            except Exception as e:
                print(f"⚠️ 미국 히트맵 생성 실패: {e}")

        # 코스닥 히트맵
        kosdaq = macro_data.get("kosdaq", {})
        if kosdaq.get("stocks"):
            kosdaq_df = pd.DataFrame(kosdaq["stocks"])
            kosdaq_df = kosdaq_df.rename(columns={
                "stock_name": "stock_name",
                "sector": "sector",
                "market_value": "market_cap",
                "change_pct": "change_pct"
            })
            kosdaq_df = kosdaq_df.head(100)

            try:
                kosdaq_heatmap = generate_treemap_heatmap(
                    kosdaq_df,
                    title="KOSDAQ Top 100",
                    sector_col="sector",
                    name_col="stock_name",
                    value_col="market_cap",
                    color_col="change_pct",
                )
            except Exception as e:
                print(f"⚠️ 코스닥 히트맵 생성 실패: {e}")

        # 나스닥 히트맵
        nasdaq = macro_data.get("nasdaq", {})
        if nasdaq.get("stocks"):
            nasdaq_df = pd.DataFrame(nasdaq["stocks"])
            nasdaq_df = nasdaq_df.rename(columns={
                "stock_name": "stock_name",
                "sector": "sector",
                "market_value": "market_cap",
                "change_pct": "change_pct"
            })
            nasdaq_df["stock_name"] = nasdaq_df["ticker"]
            # sector가 None인 종목 필터링
            nasdaq_df = nasdaq_df[nasdaq_df["sector"].notna()]
            nasdaq_df = nasdaq_df.head(100)

            try:
                nasdaq_heatmap = generate_treemap_heatmap(
                    nasdaq_df,
                    title="NASDAQ Top 100",
                    sector_col="sector",
                    name_col="stock_name",
                    value_col="market_cap",
                    color_col="change_pct",
                )
            except Exception as e:
                print(f"⚠️ 나스닥 히트맵 생성 실패: {e}")

        # 3. 실시간 뉴스 수집 (충분한 컨텍스트를 위해 더 많이 수집)
        print("🔍 실시간 뉴스 수집 중...")
        news_context = ""
        try:
            news_result = fetch_realtime_news(macro_data, max_per_query=7, max_total=25)
            news_context = news_result.get("formatted", "")
            print(f"    수집된 뉴스: {len(news_result.get('news', []))}건")
            print(f"    검색 쿼리: {news_result.get('queries', [])[:5]}")
        except Exception as e:
            print(f"⚠️ 뉴스 수집 실패 (계속 진행): {e}")

        # 4. LLM 분석 (RAG 통합)
        print("🤖 AI 분석 생성 중...")
        ai_analysis = analyze_market_v2(macro_data, news_context)
        # 마크다운을 HTML로 변환
        import re
        ai_analysis_html = ai_analysis.replace("\n", "<br>")
        # **텍스트** → <strong>텍스트</strong> 변환 (정규식 사용)
        ai_analysis_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', ai_analysis_html)
        ai_analysis_html = ai_analysis_html.replace("•", "&#8226;")

        # 5. 템플릿 데이터 준비
        print("📝 리포트 생성 중...")

        # 지수 데이터
        indices_data = macro_data.get("indices", {})
        indices = [
            {"name": "KOSPI", "value": f"{indices_data.get('kospi', {}).get('value', 0):,.2f}",
             "change": round(indices_data.get('kospi', {}).get('change_pct', 0) or 0, 2)},
            {"name": "KOSDAQ", "value": f"{indices_data.get('kosdaq', {}).get('value', 0):,.2f}",
             "change": round(indices_data.get('kosdaq', {}).get('change_pct', 0) or 0, 2)},
            {"name": "S&P 500", "value": f"{indices_data.get('sp500', {}).get('value', 0):,.2f}",
             "change": round(indices_data.get('sp500', {}).get('change_pct', 0) or 0, 2)},
            {"name": "NASDAQ", "value": f"{indices_data.get('nasdaq', {}).get('value', 0):,.2f}",
             "change": round(indices_data.get('nasdaq', {}).get('change_pct', 0) or 0, 2)},
        ]

        # 투자자 동향
        investor_flow = []
        for day in macro_data.get("investor_flow", [])[:5]:
            import math
            foreign = day.get("foreign_amount", 0) or 0
            institution = day.get("institution_amount", 0) or 0
            individual = day.get("individual_amount", 0) or 0
            # NaN 체크
            foreign = 0 if (isinstance(foreign, float) and math.isnan(foreign)) else foreign
            institution = 0 if (isinstance(institution, float) and math.isnan(institution)) else institution
            individual = 0 if (isinstance(individual, float) and math.isnan(individual)) else individual
            investor_flow.append({
                "date": str(day.get("date", ""))[:10],
                "foreign": round(foreign / 100000000),
                "institution": round(institution / 100000000),
                "individual": round(individual / 100000000),
            })

        # 반도체 가격
        semiconductor = []
        for item in macro_data.get("semiconductor", []):
            product = item.get("product_type", "").replace("_", " ")
            semiconductor.append({
                "product": product,
                "price": f"{item.get('price', 0):.2f}",
                "change": item.get("price_change_pct", 0) or 0,
            })

        # 매크로 지표 (환율, 금리, VIX, 원자재)
        macro_indicators = []

        # 환율
        exchange = macro_data.get("exchange_rates", {})
        if exchange.get("usd_krw"):
            macro_indicators.append({
                "name": "USD/KRW",
                "value": f"{exchange['usd_krw']['value']:,.0f}",
                "change": round(exchange['usd_krw'].get('change_pct', 0), 2)
            })

        # 금리
        rates = macro_data.get("interest_rates", {})
        if rates.get("us_10y"):
            macro_indicators.append({
                "name": "미국 10Y",
                "value": f"{rates['us_10y']['value']:.2f}%",
                "change": round(rates['us_10y'].get('change_pct', 0), 2)
            })
        if rates.get("kr_3y"):
            macro_indicators.append({
                "name": "한국 3Y",
                "value": f"{rates['kr_3y']['value']:.2f}%",
                "change": round(rates['kr_3y'].get('change_pct', 0), 2)
            })

        # VIX / Fear & Greed
        fear = macro_data.get("fear_greed", {})
        if fear.get("vix"):
            macro_indicators.append({
                "name": "VIX",
                "value": f"{fear['vix']['value']:.1f}",
                "change": round(fear['vix'].get('change_pct', 0), 2)
            })
        if fear.get("fear_greed_index"):
            fg_val = fear['fear_greed_index']['value']
            fg_label = "극단적 공포" if fg_val < 25 else "공포" if fg_val < 45 else "중립" if fg_val < 55 else "탐욕" if fg_val < 75 else "극단적 탐욕"
            macro_indicators.append({
                "name": "Fear&Greed",
                "value": f"{fg_val:.0f} ({fg_label})",
            })

        # 원자재
        commodities = macro_data.get("commodities", {})
        if commodities.get("gold"):
            macro_indicators.append({
                "name": "금",
                "value": f"${commodities['gold']['value']:,.0f}",
                "change": round(commodities['gold'].get('change_pct', 0), 2)
            })
        if commodities.get("oil"):
            macro_indicators.append({
                "name": "원유",
                "value": f"${commodities['oil']['value']:.1f}",
                "change": round(commodities['oil'].get('change_pct', 0), 2)
            })

        # 템플릿 렌더링
        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        template = env.get_template("morning_report.html")

        today = datetime.now()
        weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][today.weekday()]

        html = template.render(
            date=f"{today.strftime('%Y년 %m월 %d일')} ({weekday_kr})",
            ai_analysis=ai_analysis_html,
            korea_heatmap=bool(korea_heatmap),
            kosdaq_heatmap=bool(kosdaq_heatmap),
            us_heatmap=bool(us_heatmap),
            nasdaq_heatmap=bool(nasdaq_heatmap),
            indices=indices,
            investor_flow=investor_flow,
            semiconductor=semiconductor,
            macro_indicators=macro_indicators,
            web_url="https://bip.example.com",
            unsubscribe_url="https://bip.example.com/unsubscribe",
        )

        result["html"] = html

        # 6. 이메일 발송
        if send:
            print(f"📧 이메일 발송 중... ({', '.join(to_emails)})")

            images = {}
            if korea_heatmap:
                images["korea_heatmap"] = korea_heatmap
            if kosdaq_heatmap:
                images["kosdaq_heatmap"] = kosdaq_heatmap
            if us_heatmap:
                images["us_heatmap"] = us_heatmap
            if nasdaq_heatmap:
                images["nasdaq_heatmap"] = nasdaq_heatmap

            subject = f"📊 BIP 모닝 브리핑 - {today.strftime('%m/%d')} ({weekday_kr})"

            success = send_email(
                to_emails=to_emails,
                subject=subject,
                html_content=html,
                images=images,
            )

            if success:
                print("✅ 리포트 발송 완료!")
                result["success"] = True
            else:
                result["error"] = "이메일 발송 실패"
        else:
            print("📄 리포트 생성 완료 (발송 안함)")
            result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        print(f"❌ 리포트 생성 실패: {e}")
        import traceback
        traceback.print_exc()

    return result


def save_report_to_file(html: str, filename: Optional[str] = None) -> str:
    """리포트를 파일로 저장 (디버깅/미리보기용)"""
    if filename is None:
        filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

    filepath = Path("/tmp") / filename
    filepath.write_text(html, encoding="utf-8")
    print(f"📄 리포트 저장: {filepath}")
    return str(filepath)


if __name__ == "__main__":
    # 테스트: 리포트 생성만 (발송 안함)
    result = build_morning_report(
        to_emails=["test@example.com"],
        send=False,
    )

    if result["success"]:
        filepath = save_report_to_file(result["html"])
        print(f"✅ 테스트 완료. 파일 확인: {filepath}")
    else:
        print(f"❌ 테스트 실패: {result['error']}")
