"""
리포트 빌더 - LangGraph 멀티 에이전트 버전
- 데이터 수집, 히트맵 생성은 동일
- LLM 분석: BIP-Agents LangGraph (병렬 멀티 에이전트 + MCP)
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
from langgraph_runner import run_langgraph_analysis
from llm_analyzer_v2 import calculate_reference_signals, format_reference_signals, generate_insight_summary
from realtime_news import fetch_realtime_news
from email_sender import send_email
from pdf_generator import generate_pdf_from_html, generate_pdf_filename
from glossary import apply_glossary


# 템플릿 경로
TEMPLATE_DIR = Path(__file__).parent / "templates"


def build_morning_report_langgraph(
    to_emails: List[str],
    send: bool = True,
) -> Dict[str, Any]:
    """
    모닝 리포트 생성 및 발송 (LangGraph 멀티 에이전트 버전)

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
            us_df["stock_name"] = us_df["ticker"]
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

        # 3. 실시간 뉴스 수집
        print("🔍 실시간 뉴스 수집 중...")
        news_context = ""
        try:
            news_result = fetch_realtime_news(macro_data, max_per_query=7, max_total=25)
            news_context = news_result.get("formatted", "")
            print(f"    수집된 뉴스: {len(news_result.get('news', []))}건")
            print(f"    검색 쿼리: {news_result.get('queries', [])[:5]}")
        except Exception as e:
            print(f"⚠️ 뉴스 수집 실패 (계속 진행): {e}")

        # 4. LangGraph 멀티 에이전트 분석
        print("🤖 [LangGraph] 멀티 에이전트 분석 시작...")
        ref_signals = calculate_reference_signals(macro_data)
        ref_signals_text = format_reference_signals(ref_signals)
        print(f"    수치 기반 참고 신호: {ref_signals}")
        ai_analysis = run_langgraph_analysis(macro_data, news_context, reference_signals=ref_signals_text)
        if not ai_analysis:
            raise RuntimeError("LangGraph 분석 결과가 비어있습니다.")
        print(f"    LangGraph 분석 완료 ({len(ai_analysis)}자)")

        # 5. Haiku로 시장전망 생성
        print("🤖 [Haiku] 시장전망 생성 중...")
        insight_text = ""
        try:
            insight_text = generate_insight_summary(ai_analysis)
            print(f"    시장전망 생성 완료 ({len(insight_text)}자)")
        except Exception as e:
            print(f"⚠️ 시장전망 생성 실패 (계속 진행): {e}")

        # 6. 용어 설명 추가
        print("📚 용어 설명 추가 중...")
        ai_analysis = apply_glossary(ai_analysis)

        # 마크다운을 HTML로 변환
        import re

        def convert_markdown_table_to_html(text: str) -> str:
            """마크다운 테이블을 HTML 테이블로 변환"""
            lines = text.split('\n')
            result = []
            table_lines = []
            in_table = False

            for line in lines:
                stripped = line.strip()
                if stripped.startswith('|') and stripped.endswith('|'):
                    cells_content = stripped.strip('|')
                    if all(c in '-|: ' for c in cells_content):
                        in_table = True
                        continue
                    table_lines.append(stripped)
                    in_table = True
                else:
                    if table_lines:
                        html_table = _build_html_table(table_lines)
                        result.append(html_table)
                        table_lines = []
                    in_table = False
                    result.append(line)

            if table_lines:
                html_table = _build_html_table(table_lines)
                result.append(html_table)

            return '\n'.join(result)

        def _is_numeric_cell(text: str) -> bool:
            t = text.strip()
            if not t or t == '-':
                return False
            return bool(re.match(r'^[+\-]?[\d,]+(\.\d+)?(%p?|bp|억|조|만)?$', t) or
                        re.match(r'^[+\-]?\$[\d,]+(\.\d+)?$', t) or
                        re.match(r'^[+\-]?[\d,]+(\.\d+)?\s*(억|조|만|원|달러)?$', t))

        def _build_html_table(table_lines: list) -> str:
            if not table_lines:
                return ""

            html = ['<div style="overflow-x:auto; -webkit-overflow-scrolling:touch; margin:12px 0;">']
            html.append('<table style="width:100%; border-collapse:collapse; font-size:13px; white-space:nowrap;">')

            for i, line in enumerate(table_lines):
                cells = [c.strip() for c in line.strip('|').split('|')]

                if i == 0:
                    html.append('<thead><tr>')
                    for j, cell in enumerate(cells):
                        html.append(f'<th style="padding:8px 10px; background:#eff6ff; color:#1e40af; border-bottom:2px solid #dbeafe; text-align:left; white-space:nowrap;">{cell}</th>')
                    html.append('</tr></thead><tbody>')
                else:
                    html.append('<tr>')
                    for j, cell in enumerate(cells):
                        color = ""
                        if re.search(r'\+', cell) and re.search(r'[\d]', cell):
                            color = "color:#059669;"
                        elif re.search(r'^-', cell.strip()) and re.search(r'[\d]', cell):
                            color = "color:#dc2626;"
                        html.append(f'<td style="padding:8px 10px; border-bottom:1px solid #f3f4f6; text-align:left; white-space:nowrap; {color}">{cell}</td>')
                    html.append('</tr>')

            html.append('</tbody></table></div>')
            return ''.join(html)

        def convert_markdown_headings(text: str) -> str:
            lines = text.split('\n')
            result = []

            for line in lines:
                stripped = line.strip()
                if stripped.startswith('##### '):
                    result.append(f'<h5>{stripped[6:]}</h5>')
                elif stripped.startswith('#### '):
                    result.append(f'<h4>{stripped[5:]}</h4>')
                elif stripped.startswith('### '):
                    result.append(f'<h4>{stripped[4:]}</h4>')
                elif stripped.startswith('## '):
                    result.append(f'<h3>{stripped[3:]}</h3>')
                elif stripped.startswith('# '):
                    result.append(f'<h2>{stripped[2:]}</h2>')
                elif stripped == '---' or stripped == '***':
                    result.append('<hr>')
                else:
                    result.append(line)

            return '\n'.join(result)

        def extract_key_summary(text: str) -> tuple:
            lines = text.split('\n')
            key_summary_lines = []
            remaining_lines = []
            in_key_summary = False
            found_key_summary = False

            for line in lines:
                stripped = line.strip()
                if ('오늘의 핵심' in stripped or '어제의 핵심' in stripped) and (stripped.startswith('#') or stripped.startswith('📌')):
                    in_key_summary = True
                    found_key_summary = True
                    continue

                if in_key_summary and stripped.startswith('#') and '핵심' not in stripped:
                    in_key_summary = False

                if in_key_summary and (stripped == '---' or stripped == '***'):
                    in_key_summary = False
                    continue

                if in_key_summary:
                    if stripped:
                        key_summary_lines.append(line)
                else:
                    remaining_lines.append(line)

            key_summary = '\n'.join(key_summary_lines) if key_summary_lines else ""
            remaining = '\n'.join(remaining_lines)

            return key_summary, remaining

        def extract_signals(text: str) -> tuple:
            """섹션 헤더의 [🟢🟡🔴] 에서 신호등 추출 후 헤더에서 제거"""
            signal_map = {
                r'글로벌.*정세|글로벌.*매크로': '글로벌',
                r'한국.*과거|과거.*한국|어제 한국|한국.*마감.*결과': '한국(전일)',
                r'미국.*최신|최신.*미국|새벽.*미국|미국.*마감': '미국',
                r'한국.*전망|전망.*한국|오늘 한국': '한국(전망)',
                r'반도체.*섹터|반도체.*심층': '반도체',
            }
            signals = {}
            lines = text.split('\n')
            cleaned = []
            for line in lines:
                matched = re.search(r'\[(🟢|🟡|🔴)\]\s*$', line)
                if matched:
                    signal = matched.group(1)
                    for pattern, label in signal_map.items():
                        if re.search(pattern, line):
                            signals[label] = signal
                            break
                    # 헤더에서 신호 제거
                    line = re.sub(r'\s*\[(🟢|🟡|🔴)\]\s*$', '', line)
                cleaned.append(line)
            return signals, '\n'.join(cleaned)

        def extract_checklist(text: str) -> tuple:
            lines = text.split('\n')
            checklist_lines = []
            other_lines = []
            in_checklist = False

            for line in lines:
                stripped = line.strip()
                if '체크리스트' in stripped and stripped.startswith('#'):
                    in_checklist = True
                    continue
                if in_checklist and (stripped == '---' or stripped.startswith('참고:')):
                    in_checklist = False
                    other_lines.append(line)
                    continue
                if in_checklist:
                    checklist_lines.append(line)
                else:
                    other_lines.append(line)

            checklist = '\n'.join(checklist_lines).strip()
            remaining = '\n'.join(other_lines)
            return checklist, remaining

        # 0. 핵심 요약 추출
        key_summary_raw, ai_analysis_remaining = extract_key_summary(ai_analysis)

        # 0-1. 신호등 추출
        # LLM 출력에서 섹션 헤더의 [🟢|🟡|🔴] 마커 파싱
        llm_signals, ai_analysis_remaining = extract_signals(ai_analysis_remaining)
        # 사전 계산된 ref_signals를 fallback으로 병합 (LLM 우선)
        signals = {**(ref_signals or {}), **llm_signals}

        # 0-2. 체크리스트 추출
        checklist_raw, ai_analysis_remaining = extract_checklist(ai_analysis_remaining)
        print(f"    체크리스트 추출: {len(checklist_raw)}자 / 내용: {checklist_raw[:100] if checklist_raw else '(없음)'}")

        # 1. 마크다운 테이블 → HTML 테이블
        ai_analysis_html = convert_markdown_table_to_html(ai_analysis_remaining)

        # 2. 마크다운 제목 → HTML 헤딩
        ai_analysis_html = convert_markdown_headings(ai_analysis_html)

        # 3. 나머지 마크다운 변환
        ai_analysis_html = re.sub(r'\n{2,}(<(?:h[2-4]|hr|table)[^>]*>)', r'\n\1', ai_analysis_html)
        ai_analysis_html = re.sub(r'(</(?:h[2-4]|hr|table)>)\n{2,}', r'\1\n', ai_analysis_html)
        ai_analysis_html = re.sub(r'\n{3,}', '\n\n', ai_analysis_html)
        ai_analysis_html = ai_analysis_html.replace("\n", "<br>")
        ai_analysis_html = re.sub(r'(<br>)+(<(?:h[2-4]|hr|table)[^>]*>)', r'\2', ai_analysis_html)
        ai_analysis_html = re.sub(r'(</(?:h[2-4]|hr|table)>)(<br>)+', r'\1', ai_analysis_html)
        ai_analysis_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', ai_analysis_html)
        ai_analysis_html = ai_analysis_html.replace("•", "&#8226;")

        # 4. 핵심 요약 HTML 변환
        key_summary_html = ""
        if key_summary_raw:
            key_summary_html = key_summary_raw.replace("\n", "<br>")
            key_summary_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', key_summary_html)
            key_summary_html = key_summary_html.replace("•", "&#8226;")
            key_summary_html = key_summary_html.replace("- ", "• ")

        def _to_html(text: str) -> str:
            html = convert_markdown_table_to_html(text)
            html = convert_markdown_headings(html)
            html = re.sub(r'\n{2,}(<(?:h[2-4]|hr)[^>]*>)', r'\n\1', html)
            html = re.sub(r'(</(?:h[2-4]|hr)>)\n{2,}', r'\1\n', html)
            html = re.sub(r'\n{3,}', '\n\n', html)
            html = html.replace("\n", "<br>")
            html = re.sub(r'(<br>)+(<(?:h[2-4]|hr)[^>]*>)', r'\2', html)
            html = re.sub(r'(</(?:h[2-4]|hr)>)(<br>)+', r'\1', html)
            html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
            html = html.replace("•", "&#8226;").replace("- ", "• ")
            return html

        # 📊 오늘의 시장 전망 / 대응 시나리오 — Haiku 결과에서 파싱
        scenario_pattern = re.compile(r'(#+\s*대응 시나리오.*)', re.DOTALL)
        outlook_pattern = re.compile(r'(#+\s*📊\s*오늘의 시장 전망.*?)(?=\n#+\s*대응 시나리오|\Z)', re.DOTALL)

        insight_outlook_html = ""
        insight_scenario_html = ""

        if insight_text:
            m_outlook = outlook_pattern.search(insight_text)
            m_scenario = scenario_pattern.search(insight_text)
            if m_outlook:
                outlook_raw = m_outlook.group(0).strip()
                # HTML 박스가 이미 "🔭 오늘의 시장 전망" 제목을 표시하므로
                # LLM이 생성한 중복 최상위 제목 제거
                outlook_raw = re.sub(
                    r'^\s*#+\s*[📊🔭]?\s*오늘의?\s*시장\s*전망\s*\n+',
                    '',
                    outlook_raw,
                )
                insight_outlook_html = _to_html(outlook_raw)
            if m_scenario:
                scenario_raw = m_scenario.group(0).strip()
                # 대응 시나리오도 동일 — HTML 박스 제목이 있으므로 제거
                scenario_raw = re.sub(
                    r'^\s*#+\s*[🎯]?\s*대응\s*시나리오\s*\n+',
                    '',
                    scenario_raw,
                )
                insight_scenario_html = _to_html(scenario_raw)

        # aggregator 결과에 혹시 남은 시장전망 섹션이 있으면 제거 (단일 섹션만, DOTALL 미사용)
        ai_analysis_remaining = re.sub(r'\n#+\s*📊\s*오늘의 시장 전망[^\n]*\n', '', ai_analysis_remaining)

        # 4-2. 체크리스트 HTML 변환
        checklist_html = ""
        if checklist_raw:
            checklist_html = checklist_raw.replace("\n", "<br>")
            checklist_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', checklist_html)
            checklist_html = checklist_html.replace("□", "☐")

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
        product_names = {
            'dram_ddr5_16gb': 'DDR5 16Gb',
            'dram_ddr5_16gb_ett': 'DDR5 16Gb ETT',
            'dram_ddr4_16gb': 'DDR4 16Gb',
            'dram_ddr4_16gb_ett': 'DDR4 16Gb ETT',
            'dram_ddr4_8gb': 'DDR4 8Gb',
            'dram_ddr4_8gb_ett': 'DDR4 8Gb ETT',
            'dram_ddr3_4gb': 'DDR3 4Gb',
            'nand_tlc_512gb': 'NAND TLC 512Gb',
            'nand_tlc_256gb': 'NAND TLC 256Gb',
            'nand_tlc_128gb': 'NAND TLC 128Gb',
            'nand_mlc_64gb': 'NAND MLC 64Gb',
            'nand_mlc_32gb': 'NAND MLC 32Gb',
            'nand_slc_2gb': 'NAND SLC 2Gb',
            'nand_slc_1gb': 'NAND SLC 1Gb',
        }
        product_order = [
            'dram_ddr5_16gb', 'dram_ddr4_16gb', 'dram_ddr4_8gb', 'dram_ddr3_4gb',
            'nand_tlc_512gb', 'nand_tlc_256gb', 'nand_tlc_128gb',
            'nand_mlc_64gb', 'nand_mlc_32gb',
        ]

        semi_data = {x.get("product_type"): x for x in macro_data.get("semiconductor", [])}
        for product_key in product_order:
            item = semi_data.get(product_key)
            if not item:
                continue

            product_name = product_names.get(product_key, product_key)
            price = item.get('price', 0)
            change = item.get('price_change_pct', 0) or 0
            week_chg = item.get('week_change_pct')
            month_chg = item.get('month_change_pct')

            is_nand = product_key.startswith("nand_")
            last_change_date = item.get("last_change_date")
            last_change_pct = item.get("last_change_pct")

            if is_nand and abs(change) < 0.01 and last_change_date and last_change_pct:
                date_str = str(last_change_date)
                if len(date_str) >= 10:
                    month = date_str[5:7].lstrip('0')
                    day = date_str[8:10].lstrip('0')
                    change_display = f"{month}/{day} {last_change_pct:+.1f}%"
                else:
                    change_display = f"{last_change_pct:+.1f}%"
                change_value = last_change_pct
            else:
                change_display = f"{change:+.1f}%"
                change_value = change

            semiconductor.append({
                "product": product_name,
                "price": f"{price:.2f}",
                "change_display": change_display,
                "change_value": change_value,
                "week": f"{week_chg:+.1f}%" if week_chg is not None else "-",
                "week_value": week_chg or 0,
                "month": f"{month_chg:+.1f}%" if month_chg is not None else "-",
                "month_value": month_chg or 0,
            })

        # 투자자별 수급 상세 데이터
        investor_trading = macro_data.get("investor_trading", {})

        # 매크로 지표
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
            us10y_chg = rates['us_10y'].get('change_pct', 0)
            us10y_chg = 0 if (us10y_chg is None or (isinstance(us10y_chg, float) and math.isnan(us10y_chg))) else us10y_chg
            macro_indicators.append({
                "name": "미국 10Y",
                "value": f"{rates['us_10y']['value']:.2f}%",
                "change": round(us10y_chg, 2)
            })
        if rates.get("kr_3y"):
            kr3y_chg = rates['kr_3y'].get('change_pct', 0)
            kr3y_chg = 0 if (kr3y_chg is None or (isinstance(kr3y_chg, float) and math.isnan(kr3y_chg))) else kr3y_chg
            macro_indicators.append({
                "name": "한국 3Y",
                "value": f"{rates['kr_3y']['value']:.2f}%",
                "change": round(kr3y_chg, 2)
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
                "value": f"{fg_val:.0f}",
                "label": fg_label,
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

        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Seoul"))
        weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][today.weekday()]

        # 신호 대시보드 라벨용 날짜 (한국/미국 각각의 실제 거래일)
        korea_date_str = (macro_data.get("korea", {}) or {}).get("date") or ""
        us_date_str = (macro_data.get("us", {}) or {}).get("date") or ""

        def _fmt_date_label(date_str: str) -> str:
            """YYYY-MM-DD → MM/DD 형식"""
            if not date_str or len(date_str) < 10:
                return ""
            return f"{date_str[5:7]}/{date_str[8:10]}"

        korea_date_label = _fmt_date_label(korea_date_str)
        us_date_label = _fmt_date_label(us_date_str)

        html = template.render(
            date=f"{today.strftime('%Y년 %m월 %d일')} ({weekday_kr})",
            signals=signals,
            korea_date_label=korea_date_label,
            us_date_label=us_date_label,
            key_summary=key_summary_html,
            insight_outlook=insight_outlook_html,
            insight_scenario=insight_scenario_html,
            checklist=checklist_html,
            ai_analysis=ai_analysis_html,
            korea_heatmap=bool(korea_heatmap),
            kosdaq_heatmap=bool(kosdaq_heatmap),
            us_heatmap=bool(us_heatmap),
            nasdaq_heatmap=bool(nasdaq_heatmap),
            indices=indices,
            investor_flow=investor_flow,
            investor_trading=investor_trading,
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

            subject = f"[Morning Pulse · LangGraph] {today.strftime('%m월 %d일')} ({weekday_kr}) AI 시장 분석"

            print("📄 PDF 생성 중...")
            pdf_attachment = None
            try:
                pdf_bytes = generate_pdf_from_html(html, images)
                pdf_filename = generate_pdf_filename()
                pdf_attachment = (pdf_filename, pdf_bytes)
                print(f"    PDF 생성 완료: {pdf_filename} ({len(pdf_bytes):,} bytes)")
            except Exception as e:
                print(f"⚠️ PDF 생성 실패 (이메일은 계속 발송): {e}")

            success = send_email(
                to_emails=to_emails,
                subject=subject,
                html_content=html,
                images=images,
                pdf_attachment=pdf_attachment,
            )

            if success:
                print("✅ [LangGraph] 리포트 발송 완료!")
                result["success"] = True
            else:
                result["error"] = "이메일 발송 실패"
        else:
            print("📄 [LangGraph] 리포트 생성 완료 (발송 안함)")
            result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        print(f"❌ [LangGraph] 리포트 생성 실패: {e}")
        import traceback
        traceback.print_exc()

    return result


def save_report_to_file(html: str, filename: Optional[str] = None) -> str:
    """리포트를 파일로 저장 (디버깅/미리보기용)"""
    if filename is None:
        filename = f"report_langgraph_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

    filepath = Path("/tmp") / filename
    filepath.write_text(html, encoding="utf-8")
    print(f"📄 리포트 저장: {filepath}")
    return str(filepath)


if __name__ == "__main__":
    result = build_morning_report_langgraph(
        to_emails=["test@example.com"],
        send=False,
    )

    if result["success"]:
        filepath = save_report_to_file(result["html"])
        print(f"✅ [LangGraph] 테스트 완료. 파일 확인: {filepath}")
    else:
        print(f"❌ [LangGraph] 테스트 실패: {result['error']}")
