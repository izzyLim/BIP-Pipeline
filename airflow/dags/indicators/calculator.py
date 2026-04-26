"""
기술 지표 계산 모듈
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


def calculate_ma(series: pd.Series, window: int) -> pd.Series:
    """단순 이동평균"""
    return series.rolling(window=window, min_periods=window).mean()


def calculate_ema(series: pd.Series, span: int) -> pd.Series:
    """지수 이동평균"""
    return series.ewm(span=span, adjust=False).mean()


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index)"""
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
    """MACD"""
    ema_fast = calculate_ema(close, fast)
    ema_slow = calculate_ema(close, slow)

    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line

    return {
        'macd': macd_line,
        'macd_signal': signal_line,
        'macd_hist': histogram
    }


def calculate_bollinger_bands(close: pd.Series, window: int = 20, std_dev: float = 2.0) -> Dict[str, pd.Series]:
    """볼린저 밴드"""
    middle = calculate_ma(close, window)
    std = close.rolling(window=window).std()

    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)

    # 밴드 폭 (%)
    width = (upper - lower) / middle * 100

    # %B (현재가가 밴드 내 어디에 위치하는지)
    pctb = (close - lower) / (upper - lower)

    return {
        'bb_upper': upper,
        'bb_middle': middle,
        'bb_lower': lower,
        'bb_width': width,
        'bb_pctb': pctb
    }


def calculate_stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                         k_period: int = 14, d_period: int = 3) -> Dict[str, pd.Series]:
    """스토캐스틱"""
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    stoch_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    stoch_d = stoch_k.rolling(window=d_period).mean()

    return {
        'stoch_k': stoch_k,
        'stoch_d': stoch_d
    }


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR (Average True Range)"""
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    return atr


def calculate_price_momentum(close: pd.Series) -> Dict[str, pd.Series]:
    """
    주가 등락률 모멘텀
    - price_change_1d/1w/1m/1y: 각 기간(1/5/20/252 거래일) 전 종가 대비 등락률(%)
    - price_momentum: 네 기간 등락률의 단순 평균(%)
    """
    change_1d = close.pct_change(periods=1) * 100
    change_1w = close.pct_change(periods=5) * 100
    change_1m = close.pct_change(periods=20) * 100
    change_1y = close.pct_change(periods=252) * 100

    # 네 구간 평균 (NaN 포함 시 NaN — 데이터 부족하면 값 없음)
    momentum = (change_1d + change_1w + change_1m + change_1y) / 4

    return {
        'price_change_1d': change_1d,
        'price_change_1w': change_1w,
        'price_change_1m': change_1m,
        'price_change_1y': change_1y,
        'price_momentum': momentum,
    }


def calculate_volume_momentum(volume: pd.Series) -> Dict[str, pd.Series]:
    """
    거래량 변동성: volume_ma5 / volume_ma20 - 1 (비율, 0.2 = +20%)
    """
    vol_ma5 = calculate_ma(volume.astype(float), 5)
    vol_ma20 = calculate_ma(volume.astype(float), 20)
    momentum = (vol_ma5 / vol_ma20) - 1
    return {
        'volume_ma5': vol_ma5,
        'volume_momentum': momentum,
    }


def calculate_vcp(high: pd.Series, low: pd.Series, volume: pd.Series) -> Dict[str, pd.Series]:
    """
    VCP (Volatility Contraction Pattern) 지표
    - vcp_contraction: 변동폭 수축률 (0~1, 1에 가까울수록 수축)
      = 1 - (최근5일 고저폭 / 과거16~20일 고저폭)
    - vcp_vol_dry: 거래량 수축률 (0~1, 1에 가까울수록 매집 중)
      = 1 - (최근10일 평균거래량 / 과거11~20일 평균거래량)
    """
    contraction = pd.Series(index=high.index, dtype=float)
    vol_dry = pd.Series(index=high.index, dtype=float)

    h = high.values
    l = low.values
    v = volume.astype(float).values

    for i in range(19, len(h)):
        # 변동폭: 구간 내 최고-최저
        range_recent = max(h[i-4:i+1]) - min(l[i-4:i+1])      # 최근 5일
        range_old = max(h[i-19:i-14]) - min(l[i-19:i-14])      # 과거 16~20일

        if range_old > 0:
            contraction.iloc[i] = max(0, 1 - (range_recent / range_old))
        else:
            contraction.iloc[i] = 0

        # 거래량: 구간 평균 비교
        vol_recent = v[i-9:i+1].mean() if v[i-9:i+1].mean() > 0 else 1   # 최근 10일
        vol_old = v[i-19:i-9].mean() if v[i-19:i-9].mean() > 0 else 1    # 과거 11~20일

        vol_dry.iloc[i] = max(0, 1 - (vol_recent / vol_old))

    return {
        'vcp_contraction': contraction,
        'vcp_vol_dry': vol_dry,
    }


def calculate_52w_high_low(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """52주 고가/저가"""
    # 252 거래일 ≈ 52주
    high_52w = df['high'].rolling(window=252, min_periods=1).max()
    low_52w = df['low'].rolling(window=252, min_periods=1).min()

    pct_from_high = (df['close'] - high_52w) / high_52w * 100
    pct_from_low = (df['close'] - low_52w) / low_52w * 100

    return {
        'high_52w': high_52w,
        'low_52w': low_52w,
        'pct_from_52w_high': pct_from_high,
        'pct_from_52w_low': pct_from_low
    }


def determine_trend(df: pd.DataFrame) -> pd.Series:
    """추세 판단 (MA 기반)"""
    conditions = [
        (df['ma5'] > df['ma20']) & (df['ma20'] > df['ma60']),  # 상승 추세
        (df['ma5'] < df['ma20']) & (df['ma20'] < df['ma60']),  # 하락 추세
    ]
    choices = ['UP', 'DOWN']
    return pd.Series(np.select(conditions, choices, default='SIDEWAYS'), index=df.index)


def detect_golden_death_cross(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """골든/데드 크로스 감지"""
    ma5_prev = df['ma5'].shift(1)
    ma20_prev = df['ma20'].shift(1)

    # 골든 크로스: MA5가 MA20을 상향 돌파
    golden_cross = (ma5_prev <= ma20_prev) & (df['ma5'] > df['ma20'])

    # 데드 크로스: MA5가 MA20을 하향 돌파
    death_cross = (ma5_prev >= ma20_prev) & (df['ma5'] < df['ma20'])

    return {
        'golden_cross': golden_cross,
        'death_cross': death_cross
    }


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    모든 기술 지표 계산

    Args:
        df: ticker별 OHLCV 데이터 (timestamp 오름차순 정렬)
            columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume']

    Returns:
        지표가 추가된 DataFrame
    """
    if df.empty:
        return df

    df = df.copy()

    # 이동평균
    for window in [5, 10, 20, 60, 120, 200]:
        df[f'ma{window}'] = calculate_ma(df['close'], window)

    # EMA
    df['ema12'] = calculate_ema(df['close'], 12)
    df['ema26'] = calculate_ema(df['close'], 26)

    # MACD
    macd = calculate_macd(df['close'])
    df['macd'] = macd['macd']
    df['macd_signal'] = macd['macd_signal']
    df['macd_hist'] = macd['macd_hist']

    # RSI
    df['rsi14'] = calculate_rsi(df['close'], 14)

    # 볼린저 밴드
    bb = calculate_bollinger_bands(df['close'])
    df['bb_upper'] = bb['bb_upper']
    df['bb_middle'] = bb['bb_middle']
    df['bb_lower'] = bb['bb_lower']
    df['bb_width'] = bb['bb_width']
    df['bb_pctb'] = bb['bb_pctb']

    # 스토캐스틱
    stoch = calculate_stochastic(df['high'], df['low'], df['close'])
    df['stoch_k'] = stoch['stoch_k']
    df['stoch_d'] = stoch['stoch_d']

    # 거래량 지표
    df['volume_ma20'] = calculate_ma(df['volume'].astype(float), 20)
    df['volume_ratio'] = df['volume'] / df['volume_ma20']

    # 거래량 변동성 (vol_ma5/vol_ma20 - 1)
    vol_mom = calculate_volume_momentum(df['volume'])
    df['volume_ma5'] = vol_mom['volume_ma5']
    df['volume_momentum'] = vol_mom['volume_momentum']

    # 주가 등락률 모멘텀 (전일/주간/월간/연간 평균)
    pm = calculate_price_momentum(df['close'])
    df['price_change_1d'] = pm['price_change_1d']
    df['price_change_1w'] = pm['price_change_1w']
    df['price_change_1m'] = pm['price_change_1m']
    df['price_change_1y'] = pm['price_change_1y']
    df['price_momentum'] = pm['price_momentum']

    # ATR
    df['atr14'] = calculate_atr(df['high'], df['low'], df['close'], 14)

    # 52주 고/저
    w52 = calculate_52w_high_low(df)
    df['high_52w'] = w52['high_52w']
    df['low_52w'] = w52['low_52w']
    df['pct_from_52w_high'] = w52['pct_from_52w_high']
    df['pct_from_52w_low'] = w52['pct_from_52w_low']

    # VCP 수축률
    vcp = calculate_vcp(df['high'], df['low'], df['volume'])
    df['vcp_contraction'] = vcp['vcp_contraction']
    df['vcp_vol_dry'] = vcp['vcp_vol_dry']

    # 추세 판단 (MA 계산 후)
    df['trend_ma'] = determine_trend(df)

    # 골든/데드 크로스
    crosses = detect_golden_death_cross(df)
    df['golden_cross'] = crosses['golden_cross']
    df['death_cross'] = crosses['death_cross']

    return df


def calculate_market_summary(indicators_df: pd.DataFrame, trade_date: str) -> Dict[str, Any]:
    """
    시장 일일 요약 계산

    Args:
        indicators_df: 해당 날짜의 모든 종목 지표 데이터
        trade_date: 거래일

    Returns:
        시장 요약 딕셔너리
    """
    df = indicators_df.copy()

    # 전일 대비 수익률 계산 (close와 이전 close 비교 필요 - 외부에서 전달)
    # 여기서는 지표 기반으로 계산 가능한 것만

    total_stocks = len(df)

    # RSI 분포
    rsi_oversold = len(df[df['rsi14'] < 30])
    rsi_overbought = len(df[df['rsi14'] > 70])

    # 이동평균 위치
    above_ma20 = len(df[df['close'] > df['ma20']])
    above_ma200 = len(df[df['close'] > df['ma200']])

    # 52주 신고가/신저가
    new_high_52w = len(df[df['pct_from_52w_high'] >= -0.5])  # 52주 고가 대비 0.5% 이내
    new_low_52w = len(df[df['pct_from_52w_low'] <= 0.5])     # 52주 저가 대비 0.5% 이내

    # 평균 거래량 비율
    avg_volume_ratio = df['volume_ratio'].mean()

    # 평균 ATR%
    df['atr_pct'] = df['atr14'] / df['close'] * 100
    avg_atr_pct = df['atr_pct'].mean()

    return {
        'trade_date': trade_date,
        'total_stocks': total_stocks,
        'rsi_oversold': rsi_oversold,
        'rsi_overbought': rsi_overbought,
        'above_ma20': above_ma20,
        'above_ma200': above_ma200,
        'pct_above_ma20': above_ma20 / total_stocks * 100 if total_stocks > 0 else 0,
        'pct_above_ma200': above_ma200 / total_stocks * 100 if total_stocks > 0 else 0,
        'new_high_52w': new_high_52w,
        'new_low_52w': new_low_52w,
        'avg_volume_ratio': avg_volume_ratio,
        'avg_atr_pct': avg_atr_pct
    }
