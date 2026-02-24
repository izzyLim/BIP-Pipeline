"""
수요예측 설명 에이전트 (Forecast Explanation Agent)
Claude Tool Use 기반 구현
"""

import os
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from anthropic import Anthropic

try:
    from .tools import TOOL_DEFINITIONS, execute_tool
except ImportError:
    from tools import TOOL_DEFINITIONS, execute_tool

# Anthropic 클라이언트
client = Anthropic()

# 시스템 프롬프트
SYSTEM_PROMPT = """You are a smartphone demand forecasting explanation agent.

Your role is to explain WHY the demand forecast model made certain predictions,
using evidence from news data, product releases, and economic indicators.

## Guidelines

1. **Evidence-based explanations**: Always ground your explanations in data from the tools.
   - Use get_shap_values to understand which factors contributed most
   - Use search_news and get_news_summary to find supporting evidence
   - Use get_product_releases for product launch context
   - Use get_macro_indicators for economic context

2. **Quantify impact**: When possible, include numbers and percentages
   - "경제 뉴스 톤이 -2.5로 전분기 대비 30% 악화"
   - "관련 기사 450건 중 65%가 부정적"

3. **Cite sources**: Reference specific news sources or events when relevant

4. **Business-friendly language**: Avoid technical jargon, use clear Korean explanations

5. **Structured responses**: Organize explanations with clear sections:
   - 핵심 요약 (1-2 sentences)
   - 주요 원인 분석 (numbered list with contribution %)
   - 관련 뉴스/이벤트
   - 추가 컨텍스트 (optional)

## Taxonomy

**Regions** (Counterpoint Research standard):
- North America, Western Europe, Central Europe
- China, India, Japan, South Korea, Southeast Asia
- MEA (Middle East & Africa), CALA (Caribbean & Latin America)
- Asia Pacific Others

**Segments**:
- entry: 저가 (보급형)
- mid-range: 중가 (중급형)
- flagship: 고가 (프리미엄)

**External Factors**:
- geopolitics: 지정학적 요인 (분쟁, 제재, 무역분쟁)
- economy: 경제적 요인 (인플레이션, 금리, 환율)
- supply_chain: 공급망 (반도체, 물류, 부품)
- regulation: 규제 (법률, 금지, 독점규제)
- disaster: 재난 (팬데믹, 자연재해)

## Response Format

Always respond in Korean unless the user asks in English.
Use markdown formatting for better readability.
"""


def process_tool_calls(tool_calls: List[Dict]) -> List[Dict]:
    """Tool 호출 처리"""
    results = []
    for tool_call in tool_calls:
        tool_name = tool_call.name
        tool_input = tool_call.input

        print(f"  [Tool] {tool_name}({json.dumps(tool_input, ensure_ascii=False)[:100]}...)")

        result = execute_tool(tool_name, tool_input)
        results.append({
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": json.dumps(result, ensure_ascii=False, default=str)
        })

    return results


def chat(
    user_message: str,
    conversation_history: List[Dict] = None,
    model: str = "claude-sonnet-4-20250514"
) -> tuple[str, List[Dict]]:
    """
    사용자 메시지에 응답

    Args:
        user_message: 사용자 질문
        conversation_history: 이전 대화 내역
        model: 사용할 Claude 모델

    Returns:
        (응답 텍스트, 업데이트된 대화 내역)
    """
    if conversation_history is None:
        conversation_history = []

    # 사용자 메시지 추가
    conversation_history.append({
        "role": "user",
        "content": user_message
    })

    # Claude API 호출
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=TOOL_DEFINITIONS,
        messages=conversation_history
    )

    # Tool 호출이 있으면 처리
    while response.stop_reason == "tool_use":
        # Assistant 메시지 저장
        conversation_history.append({
            "role": "assistant",
            "content": response.content
        })

        # Tool 호출 추출 및 실행
        tool_calls = [block for block in response.content if block.type == "tool_use"]
        tool_results = process_tool_calls(tool_calls)

        # Tool 결과 추가
        conversation_history.append({
            "role": "user",
            "content": tool_results
        })

        # 다시 API 호출
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=conversation_history
        )

    # 최종 응답 추출
    final_response = ""
    for block in response.content:
        if hasattr(block, "text"):
            final_response += block.text

    # Assistant 응답 저장
    conversation_history.append({
        "role": "assistant",
        "content": response.content
    })

    return final_response, conversation_history


def interactive_chat():
    """대화형 인터페이스"""
    print("=" * 60)
    print("📱 스마트폰 수요예측 설명 에이전트")
    print("=" * 60)
    print("예시 질문:")
    print("  - 북미 flagship 수요 하락 원인은?")
    print("  - 중국 시장 지정학 리스크 영향 분석해줘")
    print("  - 2020년 1분기 인도 시장 상황 설명해줘")
    print("-" * 60)
    print("종료: 'quit' 또는 'exit' 입력")
    print("=" * 60)

    conversation_history = []

    while True:
        try:
            user_input = input("\n🧑 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 안녕히 가세요!")
            break

        if not user_input:
            continue

        if user_input.lower() in ['quit', 'exit', '종료']:
            print("👋 안녕히 가세요!")
            break

        print("\n🤖 Agent: ", end="")
        try:
            response, conversation_history = chat(user_input, conversation_history)
            print(response)
        except Exception as e:
            print(f"오류 발생: {e}")
            # 오류 발생 시 대화 초기화
            conversation_history = []


def single_query(query: str) -> str:
    """단일 질문 처리"""
    response, _ = chat(query)
    return response


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # 명령줄 인자로 질문 전달
        query = " ".join(sys.argv[1:])
        print(f"Query: {query}\n")
        print(single_query(query))
    else:
        # 대화형 모드
        interactive_chat()
