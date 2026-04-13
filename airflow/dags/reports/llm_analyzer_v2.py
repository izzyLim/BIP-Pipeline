"""
LLM 분석기 v2
- RAG 기반 뉴스 컨텍스트 통합
- 단계별 심층 분석
- OpenAI GPT / Claude Sonnet / Claude Haiku 지원
"""

import os
import logging
from typing import Dict, Any, Optional

from anomaly_detector import detect_all_anomalies, format_anomalies_for_prompt

logger = logging.getLogger(__name__)

# ============================================================
# LLM 모델 설정
# 환경변수 LLM_MODEL로 선택 가능:
#   - "claude-opus"   : Claude Opus 4.5 (최고 성능, 비용 높음)
#   - "claude-sonnet" : Claude Sonnet 4 (고품질, 균형)
#   - "claude-haiku"  : Claude Haiku 4.5 (빠르고 저렴)
#   - "gpt-5.4"       : OpenAI GPT-5.4
# ============================================================
DEFAULT_LLM_MODEL = "claude-sonnet"

# 모델별 설정
MODEL_CONFIG = {
    "claude-opus": {
        "provider": "anthropic",
        "model_id": "claude-opus-4-5-20251101",
        "max_tokens": 16000,  # Opus는 긴 응답 가능
    },
    "claude-sonnet": {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "max_tokens": 16000,
    },
    "claude-haiku": {
        "provider": "anthropic",
        "model_id": "claude-haiku-4-5-20251001",
        "max_tokens": 8000,
    },
    "gpt-5.4": {
        "provider": "openai",
        "model_id": "gpt-5.4",
        "max_tokens": 12000,
    },
    "gpt-5.1": {
        "provider": "openai",
        "model_id": "gpt-5.1",
        "max_tokens": 12000,
    },
}


def get_llm_model():
    """환경변수에서 LLM 모델 설정 가져오기"""
    model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
    if model not in MODEL_CONFIG:
        logger.warning(f"알 수 없는 모델 '{model}', 기본값 '{DEFAULT_LLM_MODEL}' 사용")
        model = DEFAULT_LLM_MODEL
    return model


def get_api_key(provider: str):
    """API 키 로드"""
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY")
    else:
        return os.getenv("ANTHROPIC_API_KEY")


def call_llm(prompt: str, prompt_class: str = "llm_analyzer_v2_generic",
             agent_name: str = "morning_report_llm_analyzer",
             data_sources: list = None) -> str:
    """
    설정된 LLM 모델로 API 호출 (감사 로그 포함)

    모든 호출은 `agent_audit_log`에 기록된다 (docs/security_governance.md 1-4).

    Args:
        prompt: LLM 프롬프트
        prompt_class: 감사용 프롬프트 분류 키 (예: "analyze_market", "insight_summary")
        agent_name: 호출 에이전트 이름
        data_sources: 프롬프트 생성에 사용된 데이터 소스 목록

    Returns:
        생성된 텍스트
    """
    from utils.audited_llm import audited_anthropic_call, audited_openai_call

    model_name = get_llm_model()
    config = MODEL_CONFIG[model_name]
    provider = config["provider"]
    model_id = config["model_id"]
    max_tokens = config["max_tokens"]

    api_key = get_api_key(provider)
    if not api_key:
        key_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
        return f"{key_name}가 설정되지 않았습니다."

    logger.info(f"LLM 호출: {model_name} ({provider}/{model_id})")

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = audited_openai_call(
            agent_name=agent_name,
            agent_type="report",
            prompt_class=prompt_class,
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=max_tokens,
            client=client,
            data_sources=data_sources,
        )
        # 응답 디버깅
        finish_reason = response.choices[0].finish_reason
        logger.info(f"OpenAI 응답 finish_reason: {finish_reason}")

        content = response.choices[0].message.content
        if content:
            usage = response.usage
            in_tok = usage.prompt_tokens if usage else 0
            out_tok = usage.completion_tokens if usage else 0
            logger.info(f"OpenAI 응답 길이: {len(content)} 글자")
            print(f"    💰 [{model_id}] input={in_tok:,} / output={out_tok:,} tokens")
            if finish_reason == "length":
                logger.warning("응답이 토큰 한도로 잘렸습니다. 내용은 있음.")
        else:
            logger.warning("OpenAI 응답이 비어있습니다!")
            if hasattr(response.choices[0].message, 'refusal') and response.choices[0].message.refusal:
                logger.warning(f"OpenAI refusal: {response.choices[0].message.refusal}")
                return f"분석 거부됨: {response.choices[0].message.refusal}"
        return content or "분석 생성 실패"
    else:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        response = audited_anthropic_call(
            agent_name=agent_name,
            agent_type="report",
            prompt_class=prompt_class,
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            client=client,
            data_sources=data_sources,
        )
        usage = response.usage
        print(f"    💰 [{model_id}] input={usage.input_tokens:,} / output={usage.output_tokens:,} tokens")
        return response.content[0].text


def call_haiku(prompt: str, prompt_class: str = "insight_summary") -> str:
    """
    Haiku 모델로 빠른 요약/인사이트 생성 (비용 효율적, 감사 포함)
    Anthropic API 키가 없으면 메인 LLM으로 fallback
    """
    from utils.audited_llm import audited_anthropic_call

    api_key = get_api_key("anthropic")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY 없음 → 메인 LLM으로 인사이트 요약 생성")
        return call_llm(prompt, prompt_class=prompt_class + "_fallback")

    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)

    logger.info("Haiku 호출: 인사이트 요약 생성")

    response = audited_anthropic_call(
        agent_name="morning_report_haiku",
        agent_type="report",
        prompt_class=prompt_class,
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
        client=client,
    )
    usage = response.usage
    print(f"    💰 [haiku] input={usage.input_tokens:,} / output={usage.output_tokens:,} tokens")
    return response.content[0].text


# 인사이트 요약 프롬프트
INSIGHT_SUMMARY_PROMPT = """아래는 오늘의 시장 분석 상세 내용입니다.

이 분석을 바탕으로 **오늘 장을 어떻게 볼 것인지** 전망 중심으로 작성해주세요.
직전 거래일의 시장 결과는 이미 별도로 요약됩니다. 여기서는 그 결과로 **오늘/이번 주 어떤 흐름이 예상되는지**에 집중해주세요.

다음 구성으로 작성하세요:

# 📊 오늘의 시장 전망

## 시장 흐름 예상
어제 흐름이 오늘 장에 미칠 영향을 2-3문장으로. 갭 방향, 외국인 수급 지속 여부 등.

## 주목할 변수
오늘 장에서 방향을 바꿀 수 있는 핵심 변수 2-3가지를 bullet로.

## 대응 시나리오
- **강세 시**: (조건과 대응)
- **약세 시**: (조건과 대응)

---
분석 내용:
{analysis_content}
"""


def generate_insight_summary(detailed_analysis: str) -> str:
    """
    상세 분석 내용을 읽고 핵심 요약 + 인사이트 생성 (Haiku 사용)
    """
    prompt = INSIGHT_SUMMARY_PROMPT.format(analysis_content=detailed_analysis)
    return call_haiku(prompt)


# 단계별 분석 프롬프트 (v2.3 - 심층 분석 + 국제 정세 + 이벤트 + 데이터 우선)
ANALYSIS_PROMPT_V2 = """당신은 20년 경력의 글로벌 매크로 애널리스트이자 개인 투자자 멘토입니다.
아래 시장 데이터와 최신 뉴스를 분석하여, **깊이 있고 통찰력 있는** 시장 분석 리포트를 작성해주세요.

## ⚠️ 절대 규칙 (위반 금지)
**아래 제공된 수치 데이터 외의 숫자를 절대 사용하지 마세요.**
- 환율, 지수, 금리, 주가 등 모든 수치는 반드시 아래 "오늘의 시장 데이터" 섹션의 값을 그대로 인용해야 합니다.
- 학습 데이터나 추정값을 절대 사용하지 마세요. 데이터가 없으면 "데이터 없음"으로 표시하세요.
- 예: 아래 데이터에 USD/KRW가 1511원으로 명시되어 있으면 1511원을 사용해야 합니다. 다른 값(1380원 등)을 쓰는 것은 오류입니다.

## 분석 원칙
1. **실제 데이터 우선**: 아래 제공된 시장 데이터(지수, 환율, 주가 등)가 뉴스 내용과 다를 경우, **반드시 실제 데이터를 기준으로 분석**하세요. 뉴스는 참고용이며, 숫자는 아래 데이터를 정확히 인용하세요.
2. **깊이 있는 설명**: 단순 나열이 아닌, "왜 그런지", "어떤 의미인지", "앞으로 어떻게 될 수 있는지" 맥락과 배경을 충분히 설명
3. **구체적 근거 제시**: 뉴스, 데이터, 과거 사례를 인용하며 분석의 근거를 명확히
4. **실행 가능한 인사이트**: 읽고 나서 "그래서 뭘 해야 하지?"가 아닌, 구체적인 행동 지침 제공
5. **균형 잡힌 시각**: 기회와 리스크를 모두 분석
6. **이벤트 감지 필수**: 뉴스에서 테크 컨퍼런스(GTC, WWDC 등), FOMC, 지정학적 이슈, 대형 실적 발표 등 주요 이벤트가 언급되면 반드시 "특별 이벤트" 섹션에서 심층 분석하세요
7. **표 활용**: 수치 비교, 지표 요약, 수급 정리 등 데이터가 여러 개일 때는 마크다운 표를 적극 활용하세요

## 뉴스 활용 방식 (매우 중요!)
뉴스는 **분석의 재료**이지 **인용의 대상**이 아닙니다. 아래 금지/권장 사항을 반드시 지키세요:

**❌ 절대 금지 표현:**
- "뉴스에서 자주 언급된..."
- "뉴스에 따르면..."
- "여러 언론에서 보도한..."
- "기사에서 확인된..."
- 뉴스 헤드라인을 그대로 나열하는 행위

**✅ 올바른 분석 방식:**
- 뉴스에서 **팩트(사실)만 추출**하고, 그 팩트를 **데이터와 연결**하여 분석
- 당신의 **독자적인 해석과 인사이트**를 제시
- 예시:
  - ❌ "뉴스에서 HBM 수요 증가가 자주 언급되었습니다"
  - ✅ "SK하이닉스의 HBM3E 양산 확대(뉴스)와 DRAM 현물가 3주 연속 상승(+2.3%, 데이터)을 종합하면, 메모리 업황 회복이 가시화되고 있습니다. 이는 2분기 실적 개선으로 이어질 가능성이 높습니다."

**분석가의 역할:**
- 뉴스 기자가 아닌 **애널리스트**로서 분석하세요
- 뉴스는 이미 읽은 정보, 당신은 그 정보를 **해석하고 인사이트를 도출**하는 역할
- 투자자가 뉴스만 봐서는 알 수 없는 **깊은 통찰**을 제공하세요

## 🚨 오늘의 특이점 (최우선 분석 대상!)

아래는 시스템이 자동 탐지한 **평소와 다른 이상치**입니다.
일반적인 시황 설명보다 **이 특이점들을 중심으로** 깊이 있게 분석하세요.
특이점이 없다면 시장이 평온한 상태이므로 중장기 관점의 분석을 제공하세요.

{anomalies}

---

## 오늘의 시장 데이터 (⚠️ 아래 수치만 사용할 것 — 학습 데이터 사용 금지)

※ 각 데이터 옆의 타임스탬프를 참고하여 인과관계를 정확히 분석하세요.

### 주요 지수
{indices_summary}

### 한국 시장
{korea_summary}

### 미국 시장
{us_summary}

### 매크로 지표
{macro_summary}

### 투자자 동향 (일별 합계)
{investor_flow}

### 투자자별 종목 수급 상세 (순매수 금액 기준)
{investor_trading}

### 반도체 가격
{semiconductor}

### 달러 인덱스 & 반도체 지수
{dollar_semi_index}

### 글로벌 지수 (아시아/유럽)
{global_indices}

### 미국 섹터별 등락
{us_sectors}

### 한국 섹터별 등락
{kr_sectors}

### 야간선물 (CME 코스피200) - 갭 예측 핵심!
{night_futures}

### ETF 자금흐름 - 글로벌 자금 이동
{etf_flows}

### 공매도 현황
{short_selling}

## 최신 뉴스
{news_context}

## 출력 형식 (총 2500자 이상, 충분히 자세하게)

**신호등 규칙**: 아래 5개 주요 섹션의 제목 끝에 반드시 신호등을 붙여주세요.
- `[🟢]` 긍정/강세/호재
- `[🟡]` 중립/혼조/불확실
- `[🔴]` 부정/약세/악재

**수치 기반 참고 신호** (실제 데이터로 사전 계산된 값 — 뉴스/맥락을 반영해 최종 판단하세요):
{reference_signals}

신호등이 붙는 섹션 (이 5개만):
- `### 🌍 글로벌 정세 & 매크로 환경 [🟡]` ← 이런 형식
- `### 🇰🇷 한국 시장 마감 결과 ({korea_date} 15:30 KST) [🔴]`
- `### 🇺🇸 미국 시장 마감 결과 ({us_date}) [🔴]`
- `### 📈 오늘 한국 시장 예상 (09:00 개장) [🟡]`
- `### 🔬 반도체 섹터 심층 분석 [🟢]`

---

### 📌 직전 거래일 핵심 (3-5줄)
직전 거래일({korea_date}) 시장에서 실제로 일어난 일을 사실 중심으로 요약합니다.
- 주요 지수 등락과 원인 (수치 포함)
- 가장 큰 이슈가 된 뉴스나 이벤트
- 섹터/종목 중 특이 움직임
단순 나열로 작성하되, 수치와 팩트 위주로 간결하게. 전망이나 해석은 하지 마세요.

---

### 🌍 글로벌 정세 & 매크로 환경

**국제 정세**
- 현재 글로벌 시장에 영향을 미치는 주요 지정학적/경제적 이슈 분석
- (예: 중동 전쟁, 미중 갈등, 각국 통화정책 등)
- 이 이슈들이 금융 시장에 미치는 영향과 향후 전망

**글로벌 매크로 흐름**
- 달러 강세/약세 흐름과 배경
- 글로벌 금리 동향 (연준, ECB, BOJ 등)
- 원자재 시장 동향 (유가, 금 등)
- 비트코인 동향 (위험자산 선호도, 유동성 지표로서의 의미) — 반드시 포함
- 이러한 흐름이 한국 시장에 미치는 영향

---

### 🔥 특별 이벤트/사건 심층 분석

**※ 중요: 위 뉴스에서 다음과 같은 특별 이벤트가 언급되었는지 반드시 확인하고, 있다면 이 섹션을 작성하세요:**
- 테크 컨퍼런스: NVIDIA GTC, 애플 WWDC, 구글 I/O, MS Build, CES 등
- 중앙은행 이벤트: FOMC, BOJ 회의, ECB 회의, 금리 결정
- 지정학적 이슈: 전쟁, 무역 갈등, 제재, 정상회담
- 기업 이벤트: 대형 실적 발표, M&A, IPO, 파산
- 경제 이벤트: 고용지표 발표, GDP 발표, 물가지표 발표
- 기타: 자연재해, 대규모 해킹, 규제 발표 등

**뉴스에서 위 이벤트가 하나라도 언급되면 반드시 아래 형식으로 분석하세요:**

**🎯 이벤트 개요**
- 이벤트/사건명과 현재 상황 요약
- 언제 발생했고, 현재 어떤 단계인지

**📜 배경 및 맥락**
- 이 이벤트가 발생하게 된 역사적/경제적/정치적 배경
- 관련된 주요 이해관계자들과 그들의 입장
- 과거 유사 사례가 있다면 비교 분석

**💰 시장 영향 분석**
- 직접적으로 영향받는 섹터/종목/자산군
- 수혜 업종과 피해 업종 구분
- 단기적 영향 vs 중장기적 영향

**🔮 향후 시나리오**
- 시나리오 1 (낙관): 어떻게 전개될 경우 시장에 긍정적인지
- 시나리오 2 (비관): 어떻게 전개될 경우 시장에 부정적인지
- 현재 어느 시나리오에 가까운지 판단과 근거

**📌 투자자 대응 전략**
- 이 이벤트를 고려한 포트폴리오 조정 방향
- 주목해야 할 지표나 뉴스
- 관련 종목 매매 시 유의사항

---

## ⏰ 시간순 시장 분석 (반드시 이 순서대로 분석!)

아래 세 섹션은 **시간순**으로 배열되어 있습니다. 각 섹션에서 분석 범위를 반드시 지켜주세요.

---

### 🇰🇷 한국 시장 마감 결과 ({korea_date} 15:30 KST)

⚠️ **이 섹션에서는 미국 시장을 언급하지 마세요!** 한국장이 먼저 마감되었으므로, 이후 미국장 움직임은 한국장에 영향을 줄 수 없습니다.

**한국 시장 움직임 ({korea_date})**
- 코스피/코스닥 등락 원인 심층 분석
- 왜 이렇게 움직였는지 (국내 요인, 아시아 시장, 전날 미국 영향 등)
- 섹터별 등락과 그 배경

**수급 분석**
- 외국인/기관/개인 매매 동향 (일별 합계 기준)
- 투자자별 종목 수급 상세 데이터를 활용하여 분석:
  · 외국인/기관/개인이 집중 매수한 종목과 그 공통점 (섹터, 테마 등)
  · 순매도 종목에서 읽히는 리스크 신호
  · ETF 수급 동향에서 파악되는 섹터 선호도 (예: 2차전지 ETF 기관 매수 → 2차전지 섹터 관심 확대)
- 이 수급이 의미하는 바 (단순 숫자가 아닌 해석)
- 수급 특이점 종목 (거래대금 급증 + 순매수 집중 등)

**주목할 섹터/종목**
- 강세 섹터: 왜 강했는지, 지속 가능성은?
- 약세 섹터: 왜 약했는지, 반등 가능성은?
- 개별 종목 이슈 (실적, 뉴스, 수급 등)

---

### 🇺🇸 미국 시장 마감 결과 ({us_date})

이 데이터는 한국장 마감 **이후**에 발생한 것입니다.

**미국 시장 움직임**
- 주요 지수 등락과 그 원인 (단순 수치 나열 X, 왜 그랬는지 설명)
- 섹터별 차별화된 움직임과 배경
- 주요 종목 이슈 (실적 발표, 뉴스 등)

**핵심 시그널**
- 미국 시장에서 주목해야 할 포인트
- 글로벌 투자 심리 변화 (리스크온/오프)

---

### 📈 오늘 한국 시장 예상 (09:00 개장)

✅ **이 섹션에서만** 미국 시장({us_date})이 오늘 한국장에 미칠 영향을 분석하세요!

**미국 시장 영향 분석**
- 오늘 새벽 미국장 결과가 오늘 한국장에 미칠 영향
- 동조화될 섹터 vs 디커플링 예상 섹터
- 외국인 수급 방향 예상

**오늘 한국 시장 전망**
- 코스피/코스닥 예상 방향성
- 주목해야 할 섹터/종목
- 장 초반 vs 장 후반 시나리오

**갭 분석**
- 미국장 등락에 따른 갭 상승/하락 예상치
- 갭 발생 시 대응 전략

---

### 🔬 반도체 섹터 심층 분석

**메모리 현물가격 분석** (위 반도체 가격 데이터를 반드시 인용하여 작성)
- 현재 DRAM/NAND 현물가격: 위 데이터의 정확한 가격과 등락률을 명시
- 최근 가격 추이 (상승/하락/보합)와 그 원인 분석
- 향후 가격 전망과 메모리 업체 실적에 미치는 영향

**HBM/고부가 제품 동향**
- HBM3E, HBM4 등 AI용 고대역폭 메모리 수요와 공급 현황
- DDR5 전환 사이클과 가격 프리미엄 분석
- SK하이닉스, 삼성전자의 HBM 시장 점유율과 경쟁력

**글로벌 반도체 산업**
- AI/데이터센터 수요와 반도체 업황 연결
- 미국 반도체 기업(NVIDIA, AMD, Intel 등) 실적/주가와 한국 영향
- 파운드리/메모리 업황 차별화 분석

**국내 반도체 기업 분석**
- 삼성전자, SK하이닉스 주가 움직임과 원인 (위 종가 데이터 참고)
- 반도체 장비/소재 업체 동향
- 투자 관점에서의 매수/매도 타이밍 시사점

---

### 💡 투자 아이디어 & 전략

**기회 요인**
- 어떤 섹터/종목이 왜 기회인지 구체적으로
- 진입 시 고려할 조건, 목표 수준, 손절 기준
- 관련 종목 (2-3개)과 각각의 투자 포인트

**리스크 요인**
- 현재 시장의 주요 리스크는 무엇인지
- 어떤 섹터/종목을 왜 주의해야 하는지
- 리스크가 현실화될 경우 대응 방안

---

### 📅 이번 주 주요 이벤트

| 날짜 | 이벤트 | 영향 예상 |
|------|--------|-----------|
| (날짜) | (이벤트명) | (어떤 영향이 예상되는지) |
| (날짜) | (이벤트명) | (어떤 영향이 예상되는지) |
| ... | ... | ... |

※ 실적 발표, 경제지표 발표, FOMC, 옵션만기일 등 시장에 영향을 줄 이벤트 포함

---

### ✅ 오늘의 체크리스트

반드시 아래 3개 섹션으로 나눠서 작성. 섹션 제목은 정확히 "□ 장 시작 전", "□ 장 중 모니터링", "□ 주의 가격 레벨"로.

**작성 규칙 (중요)**:
- **각 섹션당 최대 4개 항목**. 가독성을 위해 꼭 필요한 것만 선별.
- **중복/유사 항목은 하나로 병합**:
  - 같은 종목의 "지지선"과 "반등 여부" → "삼성전자 204,000~210,000원 범위" 형태로 통합
  - 같은 지수의 "이탈 회피"와 "회복 신호" → "KOSPI 5,750~5,820 범위" 형태로 통합
  - 같은 원자재의 "심리선"과 "돌파" → 하나로
- **"장 중 모니터링"과 "주의 가격 레벨"은 관점이 달라야 함**:
  - 장 중 모니터링 = 수급/섹터/뉴스 동향 (가격이 아닌 것)
  - 주의 가격 레벨 = 지수·종목의 핵심 가격대 (숫자 기반)
  - 두 섹션에서 같은 종목/지수가 겹치면 안 됨
- 각 항목은 한 줄로 간결하게 (20자 이내 권장)

□ 장 시작 전
- 항목1
- 항목2

□ 장 중 모니터링
- 항목1
- 항목2

□ 주의 가격 레벨
- 항목1
- 항목2

---

참고: 위 분석은 투자 권유가 아닌 정보 제공 목적입니다. 투자 결정은 본인의 판단과 책임하에 이루어져야 합니다.
"""


def format_indices_summary(indices_data: Dict, korea_date: str = None, us_date: str = None) -> str:
    """주요 지수 포맷팅 (전일/1주/1개월/3개월 추세 포함, 타임스탬프 포함)"""
    if not indices_data:
        return "데이터 없음"

    lines = []

    # 한국 지수 (한국장 마감 시점)
    kr_timestamp = f" [마감: {korea_date} 15:30 KST]" if korea_date else ""
    for key in ['kospi', 'kosdaq']:
        data = indices_data.get(key, {})
        if data:
            name = 'KOSPI' if key == 'kospi' else 'KOSDAQ'
            val = data.get('value', 0)
            chg = data.get('change_pct', 0)
            week_chg = data.get('week_change_pct')
            month_chg = data.get('month_change_pct')
            quarter_chg = data.get('quarter_change_pct')

            trend_str = f"전일 {chg:+.2f}%"
            if week_chg is not None:
                trend_str += f", 1주 {week_chg:+.2f}%"
            if month_chg is not None:
                trend_str += f", 1개월 {month_chg:+.2f}%"
            if quarter_chg is not None:
                trend_str += f", 3개월 {quarter_chg:+.2f}%"
            lines.append(f"- {name}: {val:,.2f} ({trend_str}){kr_timestamp}")

    # 미국 지수 (미국장 마감 시점 = 한국시간 다음날 새벽)
    us_timestamp = f" [마감: {us_date} 06:00 KST]" if us_date else ""
    for key in ['sp500', 'nasdaq']:
        data = indices_data.get(key, {})
        if data:
            name = 'S&P 500' if key == 'sp500' else 'NASDAQ'
            val = data.get('value', 0)
            chg = data.get('change_pct', 0)
            week_chg = data.get('week_change_pct')
            month_chg = data.get('month_change_pct')
            quarter_chg = data.get('quarter_change_pct')

            trend_str = f"전일 {chg:+.2f}%"
            if week_chg is not None:
                trend_str += f", 1주 {week_chg:+.2f}%"
            if month_chg is not None:
                trend_str += f", 1개월 {month_chg:+.2f}%"
            if quarter_chg is not None:
                trend_str += f", 3개월 {quarter_chg:+.2f}%"
            lines.append(f"- {name}: {val:,.2f} ({trend_str}){us_timestamp}")

    return "\n".join(lines) if lines else "데이터 없음"


def format_korea_summary(korea_data: Dict) -> str:
    """한국 시장 데이터 포맷팅 (타임스탬프 포함)"""
    if not korea_data.get("stocks"):
        return "데이터 없음"

    lines = []

    # 타임스탬프 추가
    date = korea_data.get("date")
    if date:
        lines.append(f"📅 데이터 시점: {date} 15:30 KST 마감 기준")
        lines.append("")

    # 상위 10개 종목 (종가 포함)
    top_stocks = korea_data["stocks"][:10]
    lines.append("시총 상위 종목:")
    for s in top_stocks:
        close = s.get('close', 0)
        if close >= 10000:
            price_str = f"{close:,.0f}원"
        else:
            price_str = f"{close:,.0f}원"
        lines.append(f"  - {s['stock_name']}: {price_str} ({s['change_pct']:+.1f}%)")

    # 섹터 요약
    sectors = korea_data.get("sector_summary", [])[:5]
    if sectors:
        lines.append("\n섹터별 등락:")
        for s in sectors:
            lines.append(f"  - {s['sector']}: {s['change_pct']:+.1f}%")

    return "\n".join(lines)


def format_us_summary(us_data: Dict) -> str:
    """미국 시장 데이터 포맷팅 (타임스탬프 포함)"""
    if not us_data.get("stocks"):
        return "데이터 없음"

    lines = []

    # 타임스탬프 추가 (미국장 마감 = 한국시간 다음날 06:00)
    date = us_data.get("date")
    if date:
        lines.append(f"📅 데이터 시점: {date} 마감 기준 (한국시간 익일 06:00 KST)")
        lines.append("")

    # 상위 10개 종목 (종가 포함)
    top_stocks = us_data["stocks"][:10]
    lines.append("시총 상위 종목:")
    for s in top_stocks:
        close = s.get('close', 0)
        lines.append(f"  - {s['stock_name']}: ${close:,.2f} ({s['change_pct']:+.1f}%)")

    # 섹터 요약
    sectors = us_data.get("sector_summary", [])[:5]
    if sectors:
        lines.append("\n섹터별 등락:")
        for s in sectors:
            lines.append(f"  - {s['sector']}: {s['change_pct']:+.1f}%")

    return "\n".join(lines)


def format_investor_flow(flow_data: list) -> str:
    """투자자 동향 포맷팅"""
    if not flow_data:
        return "데이터 없음"

    lines = []
    for day in flow_data[:5]:
        foreign = float(day.get("foreign_amount", 0) or 0) / 100000000
        institution = float(day.get("institution_amount", 0) or 0) / 100000000
        individual = float(day.get("individual_amount", 0) or 0) / 100000000

        date_str = str(day.get('date', 'N/A'))[:10]
        lines.append(
            f"- {date_str}: 외국인 {foreign:+,.0f}억, "
            f"기관 {institution:+,.0f}억, 개인 {individual:+,.0f}억"
        )

    return "\n".join(lines) if lines else "데이터 없음"


def format_investor_trading(trading_data: Dict) -> str:
    """투자자별 수급 상세 포맷팅 (코스피/코스닥 분리 + ETF)"""
    if not trading_data or not trading_data.get("available"):
        return "데이터 없음"

    date = trading_data.get("date", "")
    lines = [f"기준: {date}"]

    def top_list(items, label):
        if not items:
            return
        parts = [f"{r['name']}({r['value']:+.0f}억)" for r in items]
        lines.append(f"  {label}: {', '.join(parts)}")

    def market_section(label, mdata):
        if not mdata:
            return
        lines.append(f"\n[{label} 개별주]")
        top_list(mdata.get("volume_top12", []), "거래량TOP12")
        top_list(mdata.get("amount_top12", []), "거래대금TOP12(억)")
        lines.append(f"  외국인 순매수: " + ", ".join(f"{r['name']}({r['value']:+.0f}억)" for r in mdata.get("foreign_buy_top5", [])))
        lines.append(f"  외국인 순매도: " + ", ".join(f"{r['name']}({r['value']:+.0f}억)" for r in mdata.get("foreign_sell_top5", [])))
        lines.append(f"  기관 순매수: " + ", ".join(f"{r['name']}({r['value']:+.0f}억)" for r in mdata.get("institution_buy_top5", [])))
        lines.append(f"  기관 순매도: " + ", ".join(f"{r['name']}({r['value']:+.0f}억)" for r in mdata.get("institution_sell_top5", [])))
        lines.append(f"  개인 순매수: " + ", ".join(f"{r['name']}({r['value']:+.0f}억)" for r in mdata.get("individual_buy_top5", [])))
        lines.append(f"  개인 순매도: " + ", ".join(f"{r['name']}({r['value']:+.0f}억)" for r in mdata.get("individual_sell_top5", [])))

    market_section("KOSPI", trading_data.get("kospi"))
    market_section("KOSDAQ", trading_data.get("kosdaq"))

    lines.append("\n[ETF/ETN 수급]")
    top_list(trading_data.get("etf_foreign_buy_top3", []), "외국인 순매수TOP3")
    top_list(trading_data.get("etf_foreign_sell_top3", []), "외국인 순매도TOP3")
    top_list(trading_data.get("etf_institution_buy_top3", []), "기관 순매수TOP3")
    top_list(trading_data.get("etf_institution_sell_top3", []), "기관 순매도TOP3")
    top_list(trading_data.get("etf_individual_buy_top3", []), "개인 순매수TOP3")
    top_list(trading_data.get("etf_individual_sell_top3", []), "개인 순매도TOP3")

    return "\n".join(lines)


def format_semiconductor(semi_data: list) -> str:
    """반도체 가격 포맷팅 (전일/1주/1개월/3개월 추세 포함)

    NAND flat 처리: 가격 변동이 없으면 "3/17 +3.54% 이후 유지 중" 형식으로 표시
    """
    if not semi_data:
        return "데이터 없음"

    # 제품명 매핑 (가독성 향상)
    product_names = {
        'dram_ddr5_16gb': 'DDR5 16Gb',
        'dram_ddr5_16gb_ett': 'DDR5 16Gb (ETT)',
        'dram_ddr4_8gb': 'DDR4 8Gb',
        'dram_ddr4_8gb_ett': 'DDR4 8Gb (ETT)',
        'dram_ddr4_16gb': 'DDR4 16Gb',
        'dram_ddr4_16gb_ett': 'DDR4 16Gb (ETT)',
        'dram_ddr3_4gb': 'DDR3 4Gb',
        'nand_tlc_512gb': 'NAND TLC 512Gb',
        'nand_tlc_256gb': 'NAND TLC 256Gb',
        'nand_tlc_128gb': 'NAND TLC 128Gb',
        'nand_mlc_64gb': 'NAND MLC 64Gb',
        'nand_mlc_32gb': 'NAND MLC 32Gb',
        'nand_slc_2gb': 'NAND SLC 2Gb',
        'nand_slc_1gb': 'NAND SLC 1Gb',
    }

    # 주요 제품만 선택 (DDR5, DDR4 8Gb, NAND TLC 512Gb 등)
    priority_products = ['dram_ddr5_16gb', 'dram_ddr4_8gb', 'nand_tlc_512gb', 'nand_tlc_256gb']

    lines = []
    shown = set()

    def format_item(item):
        product_key = item.get("product_type", "")
        product = product_names.get(product_key, product_key)
        price = item.get("price", 0)
        change = item.get("price_change_pct", 0) or 0
        week_chg = item.get("week_change_pct")
        month_chg = item.get("month_change_pct")
        quarter_chg = item.get("quarter_change_pct")

        # NAND flat 처리: 변동이 0%인 경우 마지막 유의미한 변동 표시
        is_nand = product_key.startswith("nand_")
        last_change_date = item.get("last_change_date")
        last_change_pct = item.get("last_change_pct")

        if is_nand and abs(change) < 0.01 and last_change_date and last_change_pct:
            # "3/17 +3.54% 이후 유지 중" 형식
            date_str = str(last_change_date)
            if len(date_str) >= 10:
                # "2026-03-17" -> "3/17"
                month = date_str[5:7].lstrip('0')
                day = date_str[8:10].lstrip('0')
                date_str = f"{month}/{day}"
            trend_str = f"{date_str} {last_change_pct:+.2f}% 이후 유지 중"
        else:
            trend_str = f"전일 {change:+.2f}%"

        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        return f"- {product}: ${price:.2f} ({trend_str})"

    # 우선순위 제품 먼저
    for product_key in priority_products:
        for item in semi_data:
            if item.get("product_type") == product_key and product_key not in shown:
                lines.append(format_item(item))
                shown.add(product_key)
                break

    # 나머지 제품 추가 (최대 8개)
    for item in semi_data:
        if len(lines) >= 8:
            break
        product_key = item.get("product_type", "")
        if product_key not in shown:
            lines.append(format_item(item))
            shown.add(product_key)

    return "\n".join(lines) if lines else "데이터 없음"


def format_macro_summary(macro_data: Dict) -> str:
    """매크로 지표 포맷팅 (전일/1주/1개월/3개월 추세 포함)"""
    lines = []

    # 환율 (명확하게 현재 값 표시 + 추세)
    exchange = macro_data.get("exchange_rates", {})
    if exchange.get("usd_krw"):
        val = exchange['usd_krw']['value']
        chg = exchange['usd_krw'].get('change_pct', 0)
        week_chg = exchange['usd_krw'].get('week_change_pct')
        month_chg = exchange['usd_krw'].get('month_change_pct')
        quarter_chg = exchange['usd_krw'].get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- USD/KRW: {val:,.2f}원 ({trend_str})")

    # 금리 (절대값 변동 표시, %p)
    rates = macro_data.get("interest_rates", {})
    if rates.get("us_10y"):
        val = rates['us_10y']['value']
        chg = rates['us_10y'].get('change_pct', 0)
        week_chg = rates['us_10y'].get('week_change')
        month_chg = rates['us_10y'].get('month_change')
        quarter_chg = rates['us_10y'].get('quarter_change')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%p"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%p"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%p"
        lines.append(f"- 미국 10년물: {val:.2f}% ({trend_str})")
    if rates.get("kr_3y"):
        val = rates['kr_3y']['value']
        chg = rates['kr_3y'].get('change_pct', 0)
        week_chg = rates['kr_3y'].get('week_change')
        month_chg = rates['kr_3y'].get('month_change')
        quarter_chg = rates['kr_3y'].get('quarter_change')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%p"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%p"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%p"
        lines.append(f"- 한국 3년물: {val:.2f}% ({trend_str})")

    # VIX / Fear & Greed (절대값 변동 표시)
    fear = macro_data.get("fear_greed", {})
    if fear.get("vix"):
        val = fear['vix']['value']
        week_chg = fear['vix'].get('week_change')
        month_chg = fear['vix'].get('month_change')
        quarter_chg = fear['vix'].get('quarter_change')
        trend_str = ""
        if week_chg is not None:
            trend_str += f"1주 {week_chg:+.1f}"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.1f}"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.1f}"
        if trend_str:
            lines.append(f"- VIX: {val:.1f} ({trend_str.lstrip(', ')})")
        else:
            lines.append(f"- VIX: {val:.1f}")
    if fear.get("fear_greed_index"):
        val = fear['fear_greed_index']['value']
        label = "극단적 공포" if val < 25 else "공포" if val < 45 else "중립" if val < 55 else "탐욕" if val < 75 else "극단적 탐욕"
        week_chg = fear['fear_greed_index'].get('week_change')
        month_chg = fear['fear_greed_index'].get('month_change')
        trend_str = ""
        if week_chg is not None:
            trend_str += f"1주 {week_chg:+.0f}"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.0f}"
        if trend_str:
            lines.append(f"- Fear & Greed: {val:.0f} ({label}, {trend_str.lstrip(', ')})")
        else:
            lines.append(f"- Fear & Greed: {val:.0f} ({label})")

    # 원자재 (추세 포함)
    commodities = macro_data.get("commodities", {})
    if commodities.get("gold"):
        val = commodities['gold']['value']
        chg = commodities['gold'].get('change_pct', 0)
        week_chg = commodities['gold'].get('week_change_pct')
        month_chg = commodities['gold'].get('month_change_pct')
        quarter_chg = commodities['gold'].get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- 금: ${val:,.0f} ({trend_str})")
    if commodities.get("oil"):
        val = commodities['oil']['value']
        chg = commodities['oil'].get('change_pct', 0)
        week_chg = commodities['oil'].get('week_change_pct')
        month_chg = commodities['oil'].get('month_change_pct')
        quarter_chg = commodities['oil'].get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- 원유: ${val:.1f} ({trend_str})")

    # 비트코인 (추세 포함)
    bitcoin = macro_data.get("bitcoin", {})
    if bitcoin.get("value"):
        val = bitcoin['value']
        chg = bitcoin.get('change_pct', 0)
        week_chg = bitcoin.get('week_change_pct')
        month_chg = bitcoin.get('month_change_pct')
        quarter_chg = bitcoin.get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- 비트코인: ${val:,.0f} ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_dollar_semi_index(macro_data: Dict) -> str:
    """달러 인덱스 & 반도체 지수 포맷팅"""
    lines = []

    # 달러 인덱스
    dollar = macro_data.get("dollar_index", {})
    if dollar.get("value"):
        val = dollar['value']
        chg = dollar.get('change_pct', 0)
        week_chg = dollar.get('week_change_pct')
        month_chg = dollar.get('month_change_pct')
        quarter_chg = dollar.get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- 달러인덱스(DXY): {val:.2f} ({trend_str})")

    # 반도체 지수/ETF
    semi = macro_data.get("semiconductor_index", {})
    name_map = {'sox': 'SOX(필라델피아반도체)', 'smh': 'SMH(반도체ETF)', 'soxx': 'SOXX(반도체ETF)'}
    for key in ['sox', 'smh']:  # SOX와 SMH만 표시 (SOXX는 중복)
        if semi.get(key):
            data = semi[key]
            val = data['value']
            chg = data.get('change_pct', 0)
            week_chg = data.get('week_change_pct')
            month_chg = data.get('month_change_pct')
            quarter_chg = data.get('quarter_change_pct')
            trend_str = f"전일 {chg:+.2f}%"
            if week_chg is not None:
                trend_str += f", 1주 {week_chg:+.2f}%"
            if month_chg is not None:
                trend_str += f", 1개월 {month_chg:+.2f}%"
            if quarter_chg is not None:
                trend_str += f", 3개월 {quarter_chg:+.2f}%"
            lines.append(f"- {name_map.get(key, key)}: {val:,.2f} ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_global_indices(macro_data: Dict) -> str:
    """글로벌 지수 포맷팅 (닛케이, 상하이, 유로스톡스)"""
    lines = []
    global_idx = macro_data.get("global_indices", {})

    name_map = {
        'nikkei': '닛케이225(일본)',
        'shanghai': '상하이종합(중국)',
        'eurostoxx': '유로스톡스50(유럽)',
        'sensex': 'SENSEX(인도)'
    }

    for key in ['nikkei', 'shanghai', 'eurostoxx', 'sensex']:
        if global_idx.get(key):
            data = global_idx[key]
            val = data['value']
            chg = data.get('change_pct', 0)
            week_chg = data.get('week_change_pct')
            month_chg = data.get('month_change_pct')
            quarter_chg = data.get('quarter_change_pct')
            trend_str = f"전일 {chg:+.2f}%"
            if week_chg is not None:
                trend_str += f", 1주 {week_chg:+.2f}%"
            if month_chg is not None:
                trend_str += f", 1개월 {month_chg:+.2f}%"
            if quarter_chg is not None:
                trend_str += f", 3개월 {quarter_chg:+.2f}%"
            lines.append(f"- {name_map.get(key, key)}: {val:,.2f} ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_us_sectors(macro_data: Dict) -> str:
    """미국 섹터별 등락 포맷팅"""
    lines = []
    sectors = macro_data.get("us_sectors", {})

    name_map = {
        'technology': '기술',
        'financials': '금융',
        'healthcare': '헬스케어',
        'consumer_disc': '임의소비재',
        'communication': '커뮤니케이션',
        'industrials': '산업재',
        'consumer_staples': '필수소비재',
        'energy': '에너지',
        'materials': '소재',
        'realestate': '부동산',
        'utilities': '유틸리티'
    }

    # 변동률 기준 정렬
    sorted_sectors = sorted(
        [(k, v) for k, v in sectors.items() if v.get('change_pct') is not None],
        key=lambda x: x[1].get('change_pct', 0),
        reverse=True
    )

    for key, data in sorted_sectors:
        chg = data.get('change_pct', 0)
        week_chg = data.get('week_change_pct')
        month_chg = data.get('month_change_pct')
        quarter_chg = data.get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- {name_map.get(key, key)}: ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_kr_sectors(macro_data: Dict) -> str:
    """한국 섹터별 등락 포맷팅"""
    lines = []
    sectors = macro_data.get("kr_sectors", {})

    # 변동률 기준 정렬
    sorted_sectors = sorted(
        [(k, v) for k, v in sectors.items() if v.get('change_pct') is not None],
        key=lambda x: x[1].get('change_pct', 0),
        reverse=True
    )

    for key, data in sorted_sectors:
        chg = data.get('change_pct', 0)
        week_chg = data.get('week_change_pct')
        month_chg = data.get('month_change_pct')
        quarter_chg = data.get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- {key}: ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_night_futures(data: Dict) -> str:
    """야간 한국 시장 프록시 포맷팅 (EWY 기반 갭 예측, 애프터마켓 포함)"""
    if not data:
        return "데이터 없음"

    lines = []

    # EWY (핵심 지표)
    ewy = data.get("ewy", {})
    if ewy:
        change_pct = ewy.get("change_pct", 0)
        price_source = ewy.get("price_source", "정규장")
        direction = "상승" if change_pct > 0 else "하락" if change_pct < 0 else "보합"

        data_date = ewy.get("data_date", "")
        date_label = f", {data_date} 기준" if data_date else ""
        lines.append(f"**한국 ETF (EWY)**: ${ewy['value']:.2f} ({change_pct:+.2f}%, {direction}) [{price_source}{date_label}]")

        # 정규장 vs 애프터마켓 괴리 표시
        divergence_note = ewy.get("divergence_note")
        if divergence_note:
            lines.append(f"📊 **장외 반전**: {divergence_note}")
            divergence = ewy.get("divergence", 0)
            if divergence > 0:
                lines.append(f"   → 정규장 하락 후 애프터마켓에서 반등! 실제 갭은 상승 가능성")
            else:
                lines.append(f"   → 정규장 상승 후 애프터마켓에서 하락! 실제 갭은 하락 가능성")

        # 갭 예측 코멘트 (최종 가격 기준)
        if abs(change_pct) >= 2.0:
            gap_direction = "갭상승" if change_pct > 0 else "갭하락"
            lines.append(f"⚠️ 오늘 한국장 큰 {gap_direction} 예상 (EWY {change_pct:+.1f}% 반영)")
        elif abs(change_pct) >= 1.0:
            gap_direction = "갭상승" if change_pct > 0 else "갭하락"
            lines.append(f"오늘 한국장 {gap_direction} 가능성 ({change_pct:+.1f}% 반영)")
        else:
            lines.append(f"보합권 출발 예상")

    # 닛케이 선물 (아시아 심리 참고)
    nikkei = data.get("nikkei_futures", {})
    if nikkei:
        lines.append(f"**닛케이 선물**: {nikkei['value']:,.0f} ({nikkei['change_pct']:+.2f}%)")

    return "\n".join(lines) if lines else "데이터 없음"


def format_etf_flows(data: Dict) -> str:
    """ETF 자금흐름 포맷팅"""
    if not data:
        return "데이터 없음"

    lines = []

    # 주요 ETF 분류
    categories = {
        "지수": ["SPY", "QQQ"],
        "반도체": ["SOXX", "SMH"],
        "섹터": ["XLF", "XLE"],
        "채권/리스크": ["TLT", "HYG"],
        "한국": ["EWY"],
    }

    for category, tickers in categories.items():
        category_data = []
        for ticker in tickers:
            if ticker in data:
                etf = data[ticker]
                flow = "🟢" if etf.get("flow_direction") == "inflow" else "🔴"
                vol_ratio = etf.get("volume_ratio", 1)
                vol_signal = "📈" if vol_ratio > 1.5 else "📉" if vol_ratio < 0.5 else ""

                category_data.append(
                    f"{ticker}({etf['name']}): {etf['change_pct']:+.1f}% {flow}{vol_signal}"
                )

        if category_data:
            lines.append(f"**{category}**: {', '.join(category_data)}")

    # 시장 심리 요약
    spy = data.get("SPY", {})
    tlt = data.get("TLT", {})
    if spy and tlt:
        spy_chg = spy.get("change_pct", 0)
        tlt_chg = tlt.get("change_pct", 0)

        if spy_chg > 0 and tlt_chg < 0:
            lines.append("\n💡 위험자산 선호 (Risk-On): 주식↑ 채권↓")
        elif spy_chg < 0 and tlt_chg > 0:
            lines.append("\n💡 안전자산 선호 (Risk-Off): 주식↓ 채권↑")

    return "\n".join(lines) if lines else "데이터 없음"


def format_short_selling(data: Dict) -> str:
    """공매도 현황 포맷팅"""
    if not data.get("available"):
        return f"데이터 없음: {data.get('message', '공매도 테이블 미구축')}"

    lines = []
    lines.append(f"기준일: {data.get('date', 'N/A')}")
    lines.append("")
    lines.append("**공매도 잔고 상위 종목:**")

    for item in data.get("top_shorts", [])[:5]:
        ticker = item.get("ticker", "")
        balance = item.get("short_balance", 0)
        ratio = item.get("short_balance_ratio", 0)
        lines.append(f"- {ticker}: 잔고 {balance:,}주 (비율 {ratio:.2f}%)")

    return "\n".join(lines)


def calculate_reference_signals(macro_data: Dict) -> Dict[str, str]:
    """실제 수치 데이터 기반으로 섹션별 신호등 사전 계산"""
    import math

    def safe(val, default=0.0):
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return default
        try:
            return float(val)
        except Exception:
            return default

    indices = macro_data.get("indices", {})
    fear_greed = macro_data.get("fear_greed", {})
    investor_flow = macro_data.get("investor_flow", [])
    semiconductor = macro_data.get("semiconductor", [])

    sp500_chg  = safe(indices.get("sp500",  {}).get("change_pct"))
    nasdaq_chg = safe(indices.get("nasdaq", {}).get("change_pct"))
    kospi_chg  = safe(indices.get("kospi",  {}).get("change_pct"))
    kosdaq_chg = safe(indices.get("kosdaq", {}).get("change_pct"))
    vix        = safe(fear_greed.get("vix", {}).get("value"), 20)

    signals = {}

    # 글로벌 매크로: VIX + S&P500
    if vix < 20 and sp500_chg >= 0:
        signals["글로벌"] = "🟢"
    elif vix > 30 or sp500_chg < -1.0:
        signals["글로벌"] = "🔴"
    else:
        signals["글로벌"] = "🟡"

    # 한국 전일: KOSPI 기준
    if kospi_chg > 0.5:
        signals["한국(전일)"] = "🟢"
    elif kospi_chg < -0.5:
        signals["한국(전일)"] = "🔴"
    else:
        signals["한국(전일)"] = "🟡"

    # 미국: S&P500 + NASDAQ
    if sp500_chg > 0.3 and nasdaq_chg > 0.3:
        signals["미국"] = "🟢"
    elif sp500_chg < -0.5 or nasdaq_chg < -0.5:
        signals["미국"] = "🔴"
    else:
        signals["미국"] = "🟡"

    # 한국 전망: 미국 시장 + 외국인 최근 수급
    latest_foreign = 0
    if investor_flow:
        raw = float(investor_flow[0].get("foreign_amount", 0) or 0)
        latest_foreign = 0 if math.isnan(raw) else raw / 1e8
    if sp500_chg > 0 and latest_foreign > 0:
        signals["한국(전망)"] = "🟢"
    elif sp500_chg < -0.5 and latest_foreign < 0:
        signals["한국(전망)"] = "🔴"
    else:
        signals["한국(전망)"] = "🟡"

    # 반도체: DRAM 대표 제품 전일비
    semi_map = {s.get("product_type"): s for s in semiconductor}
    dram = (semi_map.get("dram_ddr4_16gb")
            or semi_map.get("dram_ddr5_16gb")
            or semi_map.get("dram_ddr4_8gb"))
    if dram:
        chg = safe(dram.get("change_value"))
        signals["반도체"] = "🟢" if chg > 0 else "🔴" if chg < 0 else "🟡"
    else:
        signals["반도체"] = "🟡"

    return signals


def format_reference_signals(signals: Dict[str, str]) -> str:
    label_map = [
        ("글로벌",    "글로벌 매크로  (VIX + S&P500 기준)"),
        ("한국(전일)", "한국 전일      (KOSPI ±0.5% 기준)"),
        ("미국",      "미국           (S&P+NASDAQ ±0.3%/0.5% 기준)"),
        ("한국(전망)", "한국 전망      (미국 방향 + 외국인 수급 기준)"),
        ("반도체",    "반도체         (DRAM 현물가 전일비 기준)"),
    ]
    return "\n".join(f"- {label}: {signals.get(key, '🟡')}" for key, label in label_map)


def analyze_market_v2(
    macro_data: Dict[str, Any],
    news_context: str = ""
) -> str:
    """
    시장 분석 생성 (v2 - RAG 통합, 멀티 LLM 지원)

    Args:
        macro_data: collect_all_macro_data()의 결과
        news_context: RAG로 검색한 관련 뉴스 텍스트

    Returns:
        분석 텍스트
    """
    # 날짜 정보 추출
    korea_date = macro_data.get("korea", {}).get("date")
    us_date = macro_data.get("us", {}).get("date")

    # 특이점 탐지 (최우선 분석 대상)
    anomalies = detect_all_anomalies(macro_data)
    anomalies_text = format_anomalies_for_prompt(anomalies, max_count=10)
    logger.info(f"탐지된 특이점: {len(anomalies)}건")

    # 데이터 포맷팅 (타임스탬프 포함)
    indices_summary = format_indices_summary(macro_data.get("indices", {}), korea_date, us_date)
    korea_summary = format_korea_summary(macro_data.get("korea", {}))
    us_summary = format_us_summary(macro_data.get("us", {}))
    macro_summary = format_macro_summary(macro_data)
    investor_flow = format_investor_flow(macro_data.get("investor_flow", []))
    investor_trading = format_investor_trading(macro_data.get("investor_trading", {}))
    semiconductor = format_semiconductor(macro_data.get("semiconductor", []))

    # 새로 추가된 지표들
    dollar_semi_index = format_dollar_semi_index(macro_data)
    global_indices = format_global_indices(macro_data)
    us_sectors = format_us_sectors(macro_data)
    kr_sectors = format_kr_sectors(macro_data)

    # 갭 예측 및 수급 분석용 데이터
    night_futures = format_night_futures(macro_data.get("night_futures", {}))
    etf_flows = format_etf_flows(macro_data.get("etf_flows", {}))
    short_selling = format_short_selling(macro_data.get("short_selling", {}))

    # 뉴스 컨텍스트 (없으면 기본값)
    if not news_context:
        news_context = "관련 뉴스 없음"

    # 수치 기반 참고 신호 계산
    ref_signals = calculate_reference_signals(macro_data)
    ref_signals_text = format_reference_signals(ref_signals)
    logger.info(f"수치 기반 참고 신호: {ref_signals}")

    # 오늘 날짜와 거래일 간격 계산 (월요일/연휴 후 경고)
    from datetime import datetime as _dt, date as _date
    try:
        from zoneinfo import ZoneInfo
        today = _dt.now(ZoneInfo("Asia/Seoul")).date()
    except Exception:
        today = _dt.now().date()

    today_str = today.isoformat()
    gap_days_kr = (today - _date.fromisoformat(korea_date)).days if korea_date else 0
    gap_days_us = (today - _date.fromisoformat(us_date)).days if us_date else 0

    # 미국 날짜 ET/KST 병기 생성
    us_date_display = us_date or "날짜 미확인"
    if us_date:
        us_date_display = f"{us_date} (ET) → KST {us_date} 익일 06:00"

    # 데이터 신선도 경고 (주말/연휴 후)
    freshness_warning = ""
    if gap_days_kr >= 2 or gap_days_us >= 2:
        freshness_warning = f"""
⚠️ **데이터 신선도 주의** (오늘: {today_str})
- 한국 시장 데이터: {korea_date} 기준 ({gap_days_kr}일 전)
- 미국 시장 데이터: {us_date} 기준 ({gap_days_us}일 전)
- 주말/공휴일 동안 발생한 이벤트(지정학, 유가, 긴급 정책 등)가 데이터에 반영되지 않았을 수 있음
- **뉴스 섹션을 특히 중점적으로 참고**하여 주말 동안의 변화를 반영하세요
- "어제"라는 표현 대신 정확한 날짜({korea_date}, {us_date})를 사용하세요
"""

    # 프롬프트 생성
    prompt = ANALYSIS_PROMPT_V2.format(
        anomalies=anomalies_text,
        indices_summary=indices_summary,
        korea_summary=korea_summary,
        us_summary=us_summary,
        macro_summary=macro_summary,
        investor_flow=investor_flow,
        investor_trading=investor_trading,
        semiconductor=semiconductor,
        dollar_semi_index=dollar_semi_index,
        global_indices=global_indices,
        us_sectors=us_sectors,
        kr_sectors=kr_sectors,
        night_futures=night_futures,
        etf_flows=etf_flows,
        short_selling=short_selling,
        news_context=news_context,
        reference_signals=ref_signals_text,
        korea_date=korea_date or "날짜 미확인",
        us_date=us_date_display,
    )

    # 데이터 신선도 경고를 프롬프트 상단에 삽입
    if freshness_warning:
        prompt = prompt.replace(
            "## ⏰ 시간순 시장 분석",
            f"{freshness_warning}\n## ⏰ 시간순 시장 분석",
        )

    try:
        return call_llm(prompt)
    except Exception as e:
        logger.error(f"LLM 분석 실패: {e}")
        return f"분석 생성 중 오류 발생: {str(e)}"


if __name__ == "__main__":
    # 테스트
    test_data = {
        "indices": {
            "kospi": {"value": 2500, "change_pct": -1.5},
            "kosdaq": {"value": 800, "change_pct": -2.0},
            "sp500": {"value": 5000, "change_pct": 0.5},
            "nasdaq": {"value": 15000, "change_pct": 1.2}
        },
        "korea": {
            "stocks": [
                {"stock_name": "삼성전자", "change_pct": -2.5},
                {"stock_name": "SK하이닉스", "change_pct": -3.0},
            ],
            "sector_summary": [
                {"sector": "반도체", "change_pct": -2.8},
            ]
        }
    }

    test_news = """
1. 코스피 어디까지 떨어질까…증권가 예상은
   외국인 매도세 지속, 반도체 업황 우려...

2. 삼성전자, 지금이라도 사라...특별배당 전망
   저점 매수 기회라는 분석도...
"""

    print("=== LLM 분석 테스트 ===")
    result = analyze_market_v2(test_data, test_news)
    print(result)
