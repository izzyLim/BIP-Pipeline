FROM apache/airflow:2.9.2

USER root

# Chromium + 한글 폰트 + WeasyPrint 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-nanum \
    fonts-noto-cjk \
    # WeasyPrint 의존성
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Python 패키지 설치
RUN pip install --no-cache-dir \
    yfinance>=0.2.36 \
    anthropic>=0.18.0 \
    openai>=1.0.0 \
    plotly>=5.18.0 \
    kaleido>=0.2.1 \
    jinja2>=3.1.0 \
    matplotlib>=3.8.0 \
    squarify>=0.4.0 \
    pgvector>=0.2.0 \
    weasyprint>=60.0 \
    langgraph>=1.1.3 \
    langchain-anthropic>=1.4.0 \
    langchain-mcp-adapters>=0.2.2 \
    feedparser>=6.0.10

# 로컬에 다운로드된 x86_64 Chrome 제거 (ARM64에서 호환 안됨)
RUN rm -rf /home/airflow/.local/lib/python*/site-packages/choreographer/cli/browser_exe || true
