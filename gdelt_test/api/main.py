"""
수요예측 설명 에이전트 API 서버
FastAPI 기반
"""

import os
import sys
from typing import Optional, List
from datetime import datetime

from dotenv import load_dotenv

# .env 파일 로드
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# agent 모듈 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))
from agent import chat
from tools import (
    search_news,
    get_news_summary,
    get_daily_trend,
    get_shap_values,
    get_macro_indicators,
    get_product_releases,
    compare_periods
)

app = FastAPI(
    title="스마트폰 수요예측 설명 에이전트 API",
    description="GDELT 뉴스 데이터 기반 수요예측 설명 서비스",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 세션별 대화 히스토리 저장
conversation_sessions = {}


# =============================================================================
# Request/Response Models
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"

class ChatResponse(BaseModel):
    response: str
    session_id: str

class NewsSummaryRequest(BaseModel):
    region: str
    factor: Optional[str] = None
    start_date: str
    end_date: str

class DailyTrendRequest(BaseModel):
    region: str
    factor: str
    start_date: str
    end_date: str

class ShapRequest(BaseModel):
    region: str
    segment: str
    period: str
    top_k: Optional[int] = 5

class MacroRequest(BaseModel):
    region: str
    indicator_type: str
    start_date: str
    end_date: str

class CompareRequest(BaseModel):
    region: str
    segment: str
    period_a: str
    period_b: str


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    """API 상태 확인"""
    return {
        "status": "running",
        "service": "Smartphone Demand Forecast Explanation Agent",
        "version": "1.0.0",
        "endpoints": {
            "chat": "/chat",
            "news_summary": "/api/news/summary",
            "daily_trend": "/api/news/trend",
            "shap_values": "/api/analysis/shap",
            "macro_indicators": "/api/macro",
            "compare_periods": "/api/analysis/compare"
        }
    }


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    에이전트와 대화

    자연어로 질문하면 에이전트가 데이터를 분석하여 응답합니다.

    예시 질문:
    - "2020년 1분기 북미 시장 상황 분석해줘"
    - "중국 지정학 리스크가 공급망에 미치는 영향은?"
    - "코로나 시기 환율 변동 분석해줘"
    """
    try:
        # 세션별 대화 히스토리 가져오기
        session_id = request.session_id
        if session_id not in conversation_sessions:
            conversation_sessions[session_id] = []

        history = conversation_sessions[session_id]

        # 에이전트 호출
        response, updated_history = chat(request.message, history)

        # 히스토리 업데이트 (최근 10개 대화만 유지)
        conversation_sessions[session_id] = updated_history[-20:]

        return ChatResponse(
            response=response,
            session_id=session_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/chat/{session_id}")
async def clear_session(session_id: str):
    """대화 세션 초기화"""
    if session_id in conversation_sessions:
        del conversation_sessions[session_id]
    return {"message": f"Session {session_id} cleared"}


@app.post("/api/news/summary")
async def news_summary(request: NewsSummaryRequest):
    """
    뉴스 요약 통계 조회

    특정 기간/권역의 뉴스 통계 (기사 수, 평균 톤, 트렌드)
    """
    try:
        result = get_news_summary(
            region=request.region,
            factor=request.factor,
            start_date=request.start_date,
            end_date=request.end_date
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/news/trend")
async def daily_trend(request: DailyTrendRequest):
    """
    일별 뉴스 트렌드 조회

    특정 요인의 일별 기사 수 및 톤 변화
    """
    try:
        result = get_daily_trend(
            region=request.region,
            factor=request.factor,
            start_date=request.start_date,
            end_date=request.end_date
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analysis/shap")
async def shap_values(request: ShapRequest):
    """
    SHAP 값 조회

    예측에 기여한 주요 요인 분석
    """
    try:
        result = get_shap_values(
            region=request.region,
            segment=request.segment,
            period=request.period,
            top_k=request.top_k
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analysis/compare")
async def compare(request: CompareRequest):
    """
    기간 비교 분석

    두 기간의 예측 요인 변화 비교
    """
    try:
        result = compare_periods(
            region=request.region,
            segment=request.segment,
            period_a=request.period_a,
            period_b=request.period_b
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/macro")
async def macro_indicators(request: MacroRequest):
    """
    거시경제 지표 조회

    환율, 금리, 주가지수 등
    """
    try:
        result = get_macro_indicators(
            region=request.region,
            indicator_type=request.indicator_type,
            start_date=request.start_date,
            end_date=request.end_date
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news/search")
async def search(
    region: Optional[str] = None,
    factor: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10
):
    """
    뉴스 검색

    조건에 맞는 뉴스 기사 목록 조회
    """
    try:
        result = search_news(
            region=region,
            factor=factor,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        return {"articles": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/regions")
async def get_regions():
    """사용 가능한 권역 목록"""
    return {
        "regions": [
            "North America",
            "Western Europe",
            "Central Europe",
            "China",
            "India",
            "Japan",
            "South Korea",
            "Southeast Asia",
            "MEA",
            "CALA",
            "Asia Pacific Others"
        ]
    }


@app.get("/api/factors")
async def get_factors():
    """사용 가능한 외부 요인 목록"""
    return {
        "factors": [
            {"id": "geopolitics", "name": "지정학", "description": "분쟁, 제재, 무역분쟁"},
            {"id": "economy", "name": "경제", "description": "인플레이션, 금리, 환율"},
            {"id": "supply_chain", "name": "공급망", "description": "반도체, 물류, 부품"},
            {"id": "regulation", "name": "규제", "description": "법률, 금지, 독점규제"},
            {"id": "disaster", "name": "재난", "description": "팬데믹, 자연재해"}
        ]
    }


@app.get("/api/segments")
async def get_segments():
    """사용 가능한 세그먼트 목록"""
    return {
        "segments": [
            {"id": "entry", "name": "보급형", "description": "저가 스마트폰"},
            {"id": "mid-range", "name": "중급형", "description": "중가 스마트폰"},
            {"id": "flagship", "name": "프리미엄", "description": "고가 스마트폰"}
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
