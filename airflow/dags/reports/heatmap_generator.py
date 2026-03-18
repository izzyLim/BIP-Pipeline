"""
히트맵 생성기
- KOSPI 200 / S&P 500 섹터별 트리맵 히트맵 생성
- Plotly로 생성 후 PNG 이미지로 변환
- Chrome 없으면 matplotlib fallback 사용
"""

import io
import base64
from typing import Optional
import pandas as pd

# Plotly import (optional)
try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# Matplotlib import (fallback)
try:
    import matplotlib
    matplotlib.use('Agg')  # 헤드리스 모드
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.colors import LinearSegmentedColormap
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def generate_treemap_heatmap(
    df: pd.DataFrame,
    title: str,
    sector_col: str = "sector",
    name_col: str = "stock_name",
    value_col: str = "market_cap",
    color_col: str = "change_pct",
    width: int = 1200,
    height: int = 750,
) -> str:
    """
    섹터별 트리맵 히트맵 생성

    Args:
        df: 데이터프레임 (sector, stock_name, market_cap, change_pct 컬럼 필요)
        title: 차트 제목
        sector_col: 섹터 컬럼명
        name_col: 종목명 컬럼명
        value_col: 박스 크기 기준 컬럼 (시가총액)
        color_col: 박스 색상 기준 컬럼 (등락률)
        width: 이미지 너비
        height: 이미지 높이

    Returns:
        base64 인코딩된 PNG 이미지 문자열
    """
    if df.empty:
        return ""

    # 데이터 정제
    df = df.copy()
    df[value_col] = df[value_col].fillna(0).astype(float)
    df[color_col] = df[color_col].fillna(0).astype(float)

    # 라벨용 원본 등락률 저장
    df["original_change"] = df[color_col].copy()

    # 색상용 등락률 범위 제한 (-10% ~ +10%)
    df[color_col] = df[color_col].clip(-10, 10)

    # 종목명에 원본 등락률 표시
    df["label"] = df.apply(
        lambda row: f"{row[name_col]}<br>{row['original_change']:+.1f}%",
        axis=1
    )

    # 트리맵 생성
    fig = px.treemap(
        df,
        path=[sector_col, "label"],
        values=value_col,
        color=color_col,
        color_continuous_scale=[
            [0.0, "#d63031"],    # -10% 빨강
            [0.3, "#ff7675"],    # -4% 연한 빨강
            [0.5, "#dfe6e9"],    # 0% 회색
            [0.7, "#55efc4"],    # +4% 연한 녹색
            [1.0, "#00b894"],    # +10% 녹색
        ],
        color_continuous_midpoint=0,
        title=title,
    )

    # 레이아웃 설정
    fig.update_layout(
        font=dict(family="Pretendard, Arial, sans-serif", size=11),
        margin=dict(t=40, l=10, r=10, b=10),
        coloraxis_colorbar=dict(
            title="등락률(%)",
            tickformat="+.1f",
            ticksuffix="%",
        ),
    )

    # 트레이스 설정 (텍스트 크기 등)
    fig.update_traces(
        textfont=dict(size=10),
        hovertemplate="<b>%{label}</b><br>시총: %{value:,.0f}<extra></extra>",
    )

    # PNG로 변환
    try:
        img_bytes = fig.to_image(format="png", width=width, height=height, scale=2)
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        return img_base64
    except Exception as e:
        # Chrome 없으면 matplotlib fallback
        if MATPLOTLIB_AVAILABLE:
            return generate_treemap_matplotlib(df, title, sector_col, name_col, value_col, color_col, width, height)
        raise e


def generate_treemap_matplotlib(
    df: pd.DataFrame,
    title: str,
    sector_col: str = "sector",
    name_col: str = "stock_name",
    value_col: str = "market_cap",
    color_col: str = "change_pct",
    width: int = 800,
    height: int = 500,
) -> str:
    """matplotlib + squarify 기반 트리맵 (Chrome 불필요)"""
    if not MATPLOTLIB_AVAILABLE:
        return ""

    try:
        import squarify
    except ImportError:
        return ""

    df = df.copy()
    df[value_col] = df[value_col].fillna(0).astype(float)
    df["original_change"] = df[color_col].fillna(0)
    df[color_col] = df[color_col].fillna(0).clip(-10, 10)

    # 상위 30개 종목만
    df = df.nlargest(30, value_col)

    # 색상 맵 (빨강 → 회색 → 초록)
    colors_list = ['#d63031', '#ff7675', '#dfe6e9', '#55efc4', '#00b894']
    cmap = LinearSegmentedColormap.from_list('rg', colors_list)

    # 등락률 → 색상
    changes = df[color_col].values
    normalized = (changes + 10) / 20  # -10~10 → 0~1
    box_colors = [cmap(n) for n in normalized]

    fig, ax = plt.subplots(figsize=(width/80, height/80), dpi=100)

    # 트리맵 생성
    sizes = df[value_col].values
    labels = [f"{row[name_col]}\n{row['original_change']:+.1f}%" for _, row in df.iterrows()]

    squarify.plot(
        sizes=sizes,
        label=labels,
        color=box_colors,
        alpha=0.9,
        ax=ax,
        text_kwargs={'fontsize': 7, 'color': 'white', 'fontweight': 'bold'}
    )

    ax.set_title(title, fontsize=11, fontweight='bold', pad=10)
    ax.axis('off')

    plt.tight_layout()

    # PNG로 변환
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)

    return base64.b64encode(buf.read()).decode('utf-8')


def generate_sector_bar_chart(
    df: pd.DataFrame,
    title: str,
    sector_col: str = "sector",
    change_col: str = "change_pct",
    width: int = 800,
    height: int = 300,
) -> str:
    """
    섹터별 등락률 바 차트 생성 (대안용)

    Args:
        df: 섹터별 집계된 데이터프레임
        title: 차트 제목

    Returns:
        base64 인코딩된 PNG 이미지 문자열
    """
    if df.empty:
        return ""

    df = df.copy().sort_values(change_col, ascending=True)

    # 색상 설정
    colors = ["#d63031" if x < 0 else "#00b894" for x in df[change_col]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=df[sector_col],
        x=df[change_col],
        orientation='h',
        marker_color=colors,
        text=[f"{x:+.2f}%" for x in df[change_col]],
        textposition='outside',
    ))

    fig.update_layout(
        title=title,
        font=dict(family="Pretendard, Arial, sans-serif", size=11),
        margin=dict(t=40, l=120, r=40, b=30),
        xaxis=dict(title="등락률 (%)", zeroline=True, zerolinewidth=1),
        yaxis=dict(title=""),
        showlegend=False,
    )

    img_bytes = fig.to_image(format="png", width=width, height=height, scale=2)
    img_base64 = base64.b64encode(img_bytes).decode("utf-8")

    return img_base64


if __name__ == "__main__":
    # 테스트
    test_data = pd.DataFrame({
        "sector": ["IT", "IT", "금융", "금융", "헬스케어"],
        "stock_name": ["삼성전자", "SK하이닉스", "KB금융", "신한지주", "삼성바이오"],
        "market_cap": [400, 100, 30, 25, 50],
        "change_pct": [1.5, 2.8, -0.5, 0.3, -1.2],
    })

    img = generate_treemap_heatmap(test_data, "테스트 히트맵")
    print(f"Generated image: {len(img)} bytes (base64)")
