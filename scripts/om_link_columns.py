"""
OpenMetadata 컬럼 ↔ Glossary Term 연결 스크립트

사용법:
    python scripts/om_link_columns.py [--dry-run] [--table TABLE_NAME]

환경변수:
    OM_HOST, OM_BOT_TOKEN
"""

import argparse
import json
import os
import sys

import requests

OM_HOST = os.getenv("OM_HOST", "http://localhost:8585")
OM_BOT_TOKEN = os.getenv("OM_BOT_TOKEN", "")
OM_SERVICE = "bip-postgres"
OM_DB = "stockdb"
OM_SCHEMA = "public"

# ─── 컬럼 → Glossary Term 매핑 ───────────────────────────────────────────────
#
# 형식: { "table.column": ["glossary_term_fqn", ...] }
#
COLUMN_TERM_MAP = {

    # ── stock_info ────────────────────────────────────────────────────────────
    "stock_info.market_value":        ["investment-terms.price.market-cap"],
    "stock_info.per":                 ["investment-terms.valuation.per"],
    "stock_info.pbr":                 ["investment-terms.valuation.pbr"],
    "stock_info.eps":                 ["investment-terms.valuation.eps"],
    "stock_info.target_price":        ["investment-terms.consensus.target-price"],
    "stock_info.foreign_ownership_pct": ["investment-terms.price.trading-volume"],  # 외국인비중

    # ── stock_price_1d / 1m / 1wk / 1mo (OHLCV) ─────────────────────────────
    "stock_price_1d.open":            ["investment-terms.price.ohlcv"],
    "stock_price_1d.high":            ["investment-terms.price.ohlcv"],
    "stock_price_1d.low":             ["investment-terms.price.ohlcv"],
    "stock_price_1d.close":           ["investment-terms.price.close-price", "investment-terms.price.ohlcv"],
    "stock_price_1d.volume":          ["investment-terms.price.trading-volume", "investment-terms.price.ohlcv"],

    "stock_price_1m.close":           ["investment-terms.price.close-price"],
    "stock_price_1m.volume":          ["investment-terms.price.trading-volume"],
    # ── stock_indicators ──────────────────────────────────────────────────────
    "stock_indicators.open":          ["investment-terms.price.ohlcv"],
    "stock_indicators.high":          ["investment-terms.price.ohlcv"],
    "stock_indicators.low":           ["investment-terms.price.ohlcv"],
    "stock_indicators.close":         ["investment-terms.price.close-price", "investment-terms.price.ohlcv"],
    "stock_indicators.volume":        ["investment-terms.price.trading-volume", "investment-terms.price.ohlcv"],
    "stock_indicators.ma5":           ["investment-terms.technical.moving-average"],
    "stock_indicators.ma10":          ["investment-terms.technical.moving-average"],
    "stock_indicators.ma20":          ["investment-terms.technical.moving-average"],
    "stock_indicators.ma60":          ["investment-terms.technical.moving-average"],
    "stock_indicators.ma120":         ["investment-terms.technical.moving-average"],
    "stock_indicators.ma200":         ["investment-terms.technical.moving-average"],
    "stock_indicators.ema12":         ["investment-terms.technical.ema"],
    "stock_indicators.ema26":         ["investment-terms.technical.ema"],
    "stock_indicators.macd":          ["investment-terms.technical.macd", "investment-terms.technical.macd-components"],
    "stock_indicators.macd_signal":   ["investment-terms.technical.macd-components"],
    "stock_indicators.macd_hist":     ["investment-terms.technical.macd-components"],
    "stock_indicators.rsi14":         ["investment-terms.technical.rsi"],
    "stock_indicators.bb_upper":      ["investment-terms.technical.bollinger-band"],
    "stock_indicators.bb_middle":     ["investment-terms.technical.bollinger-band"],
    "stock_indicators.bb_lower":      ["investment-terms.technical.bollinger-band"],
    "stock_indicators.bb_width":      ["investment-terms.technical.bb-indicators"],
    "stock_indicators.bb_pctb":       ["investment-terms.technical.bb-indicators"],
    "stock_indicators.stoch_k":       ["investment-terms.technical.stochastic"],
    "stock_indicators.stoch_d":       ["investment-terms.technical.stochastic"],
    "stock_indicators.atr14":         ["investment-terms.technical.atr"],
    "stock_indicators.golden_cross":  ["investment-terms.technical.golden-cross"],
    "stock_indicators.death_cross":   ["investment-terms.technical.death-cross"],
    "stock_indicators.high_52w":      ["investment-terms.technical.52w-high-low"],
    "stock_indicators.low_52w":       ["investment-terms.technical.52w-high-low"],
    "stock_indicators.pct_from_52w_high": ["investment-terms.technical.52w-high-low"],
    "stock_indicators.pct_from_52w_low":  ["investment-terms.technical.52w-high-low"],

    # ── financial_statements ─────────────────────────────────────────────────
    "financial_statements.revenue":            ["investment-terms.financial.revenue"],
    "financial_statements.operating_profit":   ["investment-terms.financial.operating-profit"],
    "financial_statements.net_income":         ["investment-terms.financial.net-income"],
    "financial_statements.total_assets":       ["investment-terms.financial.total-assets"],
    "financial_statements.total_equity":       ["investment-terms.financial.total-equity"],
    "financial_statements.cash_from_operating": ["investment-terms.financial.operating-cashflow"],

    # ── us_financial_statements ───────────────────────────────────────────────
    "us_financial_statements.revenue":          ["investment-terms.financial.revenue"],
    "us_financial_statements.operating_income": ["investment-terms.financial.operating-profit"],
    "us_financial_statements.net_income":       ["investment-terms.financial.net-income"],
    "us_financial_statements.total_assets":     ["investment-terms.financial.total-assets"],
    "us_financial_statements.total_equity":     ["investment-terms.financial.total-equity"],
    "us_financial_statements.ebitda":           ["investment-terms.financial.ebitda"],
    "us_financial_statements.free_cashflow":    ["investment-terms.financial.fcf"],
    "us_financial_statements.operating_cashflow": ["investment-terms.financial.operating-cashflow"],

    # ── us_fundamentals ───────────────────────────────────────────────────────
    "us_fundamentals.trailing_pe":       ["investment-terms.valuation.trailing-forward-pe", "investment-terms.valuation.per"],
    "us_fundamentals.forward_pe":        ["investment-terms.valuation.trailing-forward-pe", "investment-terms.valuation.per"],
    "us_fundamentals.price_to_book":     ["investment-terms.valuation.pbr"],
    "us_fundamentals.ev_to_ebitda":      ["investment-terms.valuation.ev-ebitda"],
    "us_fundamentals.peg_ratio":         ["investment-terms.valuation.peg-ratio"],
    "us_fundamentals.beta":              ["investment-terms.valuation.beta"],
    "us_fundamentals.return_on_equity":  ["investment-terms.valuation.roe"],
    "us_fundamentals.market_cap":        ["investment-terms.price.market-cap"],
    "us_fundamentals.free_cashflow":     ["investment-terms.financial.fcf"],

    # ── consensus_estimates ───────────────────────────────────────────────────
    "consensus_estimates.rating":        ["investment-terms.consensus.analyst-rating"],
    "consensus_estimates.target_price":  ["investment-terms.consensus.target-price"],
    "consensus_estimates.est_eps":       ["investment-terms.valuation.eps"],
    "consensus_estimates.est_per":       ["investment-terms.valuation.per"],
    "consensus_estimates.est_pbr":       ["investment-terms.valuation.pbr"],
    "consensus_estimates.est_roe":       ["investment-terms.valuation.roe"],

    # ── consensus_history ─────────────────────────────────────────────────────
    "consensus_history.rating":          ["investment-terms.consensus.analyst-rating"],
    "consensus_history.target_price":    ["investment-terms.consensus.target-price"],
    "consensus_history.est_eps":         ["investment-terms.valuation.eps"],
    "consensus_history.est_per":         ["investment-terms.valuation.per"],

    # ── company_dividend ─────────────────────────────────────────────────────
    "company_dividend.dividend_yield":   ["investment-terms.valuation.dividend-yield"],
    "company_dividend.cash_dividend_per_share": ["investment-terms.valuation.eps"],

    # ── holding ──────────────────────────────────────────────────────────────
    "holding.market_value":              ["investment-terms.price.market-cap"],
    "holding.pnl_amount":                ["investment-terms.price.pnl"],
    "holding.pnl_percent":               ["investment-terms.price.pnl"],

    # ── portfolio_snapshot ────────────────────────────────────────────────────
    "portfolio_snapshot.daily_pnl":      ["investment-terms.price.pnl"],
    "portfolio_snapshot.daily_pnl_pct":  ["investment-terms.price.pnl"],
    "portfolio_snapshot.total_pnl":      ["investment-terms.price.pnl"],
    "portfolio_snapshot.total_pnl_pct":  ["investment-terms.price.pnl"],

    # ── macro_indicators ─────────────────────────────────────────────────────
    "macro_indicators.value":            ["investment-terms.market.vix"],  # VIX 등 포함

    # ── market_daily_summary ─────────────────────────────────────────────────
    "market_daily_summary.advancing":           ["investment-terms.market.advance-decline"],
    "market_daily_summary.declining":           ["investment-terms.market.advance-decline"],
    "market_daily_summary.advance_decline_ratio": ["investment-terms.market.advance-decline"],
    "market_daily_summary.new_high_52w":        ["investment-terms.technical.52w-high-low"],
    "market_daily_summary.new_low_52w":         ["investment-terms.technical.52w-high-low"],
    "market_daily_summary.above_ma20":          ["investment-terms.technical.moving-average"],
    "market_daily_summary.above_ma200":         ["investment-terms.technical.moving-average"],
    "market_daily_summary.avg_atr_pct":         ["investment-terms.technical.atr"],
    "market_daily_summary.rsi_oversold":        ["investment-terms.technical.rsi"],
    "market_daily_summary.rsi_overbought":      ["investment-terms.technical.rsi"],

    # ── sp500_sectors ────────────────────────────────────────────────────────
    "sp500_sectors.gics_sector":         ["investment-terms.stock-classification.gics"],
    "sp500_sectors.gics_sub_industry":   ["investment-terms.stock-classification.gics"],
}


# ─── API ──────────────────────────────────────────────────────────────────────

def get_headers():
    if not OM_BOT_TOKEN:
        print("❌ OM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    return {"Authorization": f"Bearer {OM_BOT_TOKEN}"}


def get_table_info(table_name: str, headers: dict) -> tuple[str, dict] | tuple[None, None]:
    """테이블 ID와 컬럼 인덱스 맵 반환."""
    fqn = f"{OM_SERVICE}.{OM_DB}.{OM_SCHEMA}.{table_name}"
    resp = requests.get(
        f"{OM_HOST}/api/v1/tables/name/{fqn}",
        params={"fields": "columns"},
        headers=headers,
        timeout=10,
    )
    if resp.status_code != 200:
        return None, None
    data = resp.json()
    table_id = data["id"]
    col_index = {col["name"]: idx for idx, col in enumerate(data.get("columns", []))}
    col_tags = {col["name"]: col.get("tags", []) for col in data.get("columns", [])}
    return table_id, {"index": col_index, "tags": col_tags}


def add_column_tags(table_id: str, col_idx: int, col_name: str,
                    term_fqns: list[str], existing_tags: list,
                    headers: dict) -> bool:
    """컬럼에 Glossary Term 태그 추가 (중복 제외)."""
    existing_fqns = {t["tagFQN"] for t in existing_tags}
    new_tags = [fqn for fqn in term_fqns if fqn not in existing_fqns]
    if not new_tags:
        return None  # 이미 등록됨

    patch_headers = {**headers, "Content-Type": "application/json-patch+json"}
    ops = []
    for i, fqn in enumerate(new_tags):
        tag_idx = len(existing_tags) + i
        ops.append({
            "op": "add",
            "path": f"/columns/{col_idx}/tags/{tag_idx}",
            "value": {
                "tagFQN": fqn,
                "source": "Glossary",
                "labelType": "Manual",
                "state": "Confirmed",
            },
        })

    resp = requests.patch(
        f"{OM_HOST}/api/v1/tables/{table_id}",
        headers=patch_headers,
        data=json.dumps(ops),
        timeout=10,
    )
    return resp.status_code in (200, 201)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--table", help="특정 테이블만 처리")
    args = parser.parse_args()

    headers = get_headers()

    # 테이블별로 매핑 그룹화
    table_columns: dict[str, dict[str, list[str]]] = {}
    for key, fqns in COLUMN_TERM_MAP.items():
        table, col = key.split(".", 1)
        if args.table and table != args.table:
            continue
        table_columns.setdefault(table, {})[col] = fqns

    mode = "[dry-run]" if args.dry_run else "[LIVE]"
    print("=" * 60)
    print(f"컬럼 ↔ Glossary Term 연결 {mode}")
    print(f"처리 테이블: {len(table_columns)}개")
    print("=" * 60)

    total_ok = total_skip = total_fail = 0

    for table_name, col_map in sorted(table_columns.items()):
        print(f"\n▶ {table_name}")

        if args.dry_run:
            for col, fqns in col_map.items():
                print(f"    {col} → {', '.join(fqns)}")
            total_ok += len(col_map)
            continue

        table_id, info = get_table_info(table_name, headers)
        if not table_id:
            print(f"    ⚠️  테이블을 OM에서 찾을 수 없음 (스킵)")
            continue

        col_index = info["index"]
        col_tags = info["tags"]

        for col, fqns in col_map.items():
            if col not in col_index:
                print(f"    ⚠️  컬럼 없음: {col}")
                continue

            idx = col_index[col]
            existing = col_tags.get(col, [])
            result = add_column_tags(table_id, idx, col, fqns, existing, headers)

            if result is None:
                print(f"    ⏭️  이미 등록: {col}")
                total_skip += 1
            elif result:
                terms_str = ", ".join(f.split(".")[-1] for f in fqns)
                print(f"    ✅ {col} → [{terms_str}]")
                total_ok += 1
            else:
                print(f"    ❌ 실패: {col}")
                total_fail += 1

    print("\n" + "=" * 60)
    print(f"완료: {total_ok}개 성공 / {total_skip}개 스킵(기등록) / {total_fail}개 실패")
    print("=" * 60)


if __name__ == "__main__":
    main()
