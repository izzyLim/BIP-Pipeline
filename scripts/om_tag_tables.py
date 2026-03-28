"""
OpenMetadata 테이블 레이어/도메인 Tags 일괄 등록 스크립트

사용법:
    OM_HOST=http://localhost:8585 python scripts/om_tag_tables.py [--dry-run]

옵션:
    --dry-run       실제 API 호출 없이 적용할 태그만 출력

태그 체계:
    DataLayer.raw         — 외부에서 수집한 원천 데이터
    DataLayer.derived     — raw 데이터에서 계산/집계한 파생 데이터
    DataLayer.gold        — 분석용 pre-joined 와이드 테이블
    DataLayer.application — 서비스 앱 전용 데이터 (사용자/포트폴리오)

    Domain.market     — 주가/시세/기술지표
    Domain.financial  — 재무제표/컨센서스/기업정보
    Domain.macro      — 매크로/금리/환율/지정학
    Domain.news       — 뉴스/감성
    Domain.portfolio  — 포트폴리오/거래
    Domain.product    — 제품 가격/출시
    Domain.user       — 사용자 계정
"""

import argparse
import json
import os
import sys

import requests

# ─── 환경변수 ──────────────────────────────────────────────────────────────────

OM_HOST      = os.getenv("OM_HOST", "http://localhost:8585")
OM_BOT_TOKEN = os.getenv("OM_BOT_TOKEN", "")
OM_SERVICE_DB = os.getenv("OM_SERVICE_DB", "bip-postgres")
OM_DB_NAME   = os.getenv("OM_DB_NAME", "stockdb")
OM_DB_SCHEMA = os.getenv("OM_DB_SCHEMA", "public")

# ─── 테이블별 태그 정의 ────────────────────────────────────────────────────────
#
# 구조: { "table_name": ["TagClass.tagName", ...] }
# 각 테이블에 layer 태그 1개 + domain 태그 1개 적용

TABLE_TAGS = {
    # ── Raw / Market ──────────────────────────────────────────────────────────
    "stock_info":              ["DataLayer.raw", "Domain.market"],
    "stock_price_1d":          ["DataLayer.raw", "Domain.market"],
    "stock_price_1m":          ["DataLayer.raw", "Domain.market"],
    "sp500_sectors":           ["DataLayer.raw", "Domain.market"],

    # ── Raw / Financial ───────────────────────────────────────────────────────
    "financial_statements":    ["DataLayer.raw", "Domain.financial"],
    "company_dart_info":       ["DataLayer.raw", "Domain.financial"],
    "company_dividend":        ["DataLayer.raw", "Domain.financial"],
    "company_employees":       ["DataLayer.raw", "Domain.financial"],
    "company_executives":      ["DataLayer.raw", "Domain.financial"],
    "company_audit":           ["DataLayer.raw", "Domain.financial"],
    "company_treasury_stock":  ["DataLayer.raw", "Domain.financial"],
    "company_shareholders":    ["DataLayer.raw", "Domain.financial"],
    "company_exec_compensation": ["DataLayer.raw", "Domain.financial"],
    "consensus_estimates":     ["DataLayer.raw", "Domain.financial"],
    "consensus_history":       ["DataLayer.raw", "Domain.financial"],
    "us_financial_statements": ["DataLayer.raw", "Domain.financial"],
    "us_fundamentals":         ["DataLayer.raw", "Domain.financial"],

    # ── Raw / Macro ───────────────────────────────────────────────────────────
    "macro_indicators":        ["DataLayer.raw", "Domain.macro"],
    "risk_headlines":          ["DataLayer.raw", "Domain.macro"],

    # ── Raw / News ────────────────────────────────────────────────────────────
    "news":                    ["DataLayer.raw", "Domain.news"],
    "news_raw":                ["DataLayer.raw", "Domain.news"],
    "news_article":            ["DataLayer.raw", "Domain.news"],

    # ── Raw / Portfolio ───────────────────────────────────────────────────────
    "portfolio_snapshot":      ["DataLayer.raw", "Domain.portfolio"],

    # ── Raw / Product ─────────────────────────────────────────────────────────
    "product_price":           ["DataLayer.raw", "Domain.product"],
    "product_release":         ["DataLayer.raw", "Domain.product"],

    # ── Derived / Market ──────────────────────────────────────────────────────
    "stock_indicators":        ["DataLayer.derived", "Domain.market"],
    "market_daily_summary":    ["DataLayer.derived", "Domain.market"],

    # ── Derived / News ────────────────────────────────────────────────────────
    "news_daily_summary":      ["DataLayer.derived", "Domain.news"],

    # ── Application / User ────────────────────────────────────────────────────
    "users":                   ["DataLayer.application", "Domain.user"],
    "user_watchlist":          ["DataLayer.application", "Domain.user"],

    # ── Application / Portfolio ───────────────────────────────────────────────
    "portfolio":               ["DataLayer.application", "Domain.portfolio"],
    "holding":                 ["DataLayer.application", "Domain.portfolio"],
    "transaction":             ["DataLayer.application", "Domain.portfolio"],
    "cash_transaction":        ["DataLayer.application", "Domain.portfolio"],

    # ── Gold / Macro ──────────────────────────────────────────────────────────
    "analytics_macro_daily":   ["DataLayer.gold", "Domain.macro"],

    # ── Gold / Market ─────────────────────────────────────────────────────────
    "analytics_stock_daily":   ["DataLayer.gold", "Domain.market"],

    # ── Gold / Financial ──────────────────────────────────────────────────────
    "analytics_valuation":     ["DataLayer.gold", "Domain.financial"],
}

# ─── Tag Classification 생성 함수 ─────────────────────────────────────────────

TAG_CLASSIFICATIONS = {
    "DataLayer": {
        "description": "데이터 레이어 분류 — Medallion Architecture 기반",
        "tags": {
            "raw":         "외부 소스에서 직접 수집한 원천 데이터 (Bronze layer)",
            "derived":     "raw 데이터를 집계/계산한 파생 데이터 (Silver layer)",
            "gold":        "NL2SQL·분석용 pre-joined 와이드 테이블 (Gold layer)",
            "application": "서비스 앱 전용 데이터 (사용자/포트폴리오/거래)",
        }
    },
    "Domain": {
        "description": "비즈니스 도메인 분류",
        "tags": {
            "market":    "주가·시세·기술지표·시장 breadth",
            "financial": "재무제표·컨센서스·기업 공시 정보",
            "macro":     "매크로 경제·금리·환율·지정학 리스크",
            "news":      "뉴스·감성 분석",
            "portfolio": "포트폴리오·보유종목·거래 내역",
            "product":   "제품 가격·출시 이력",
            "user":      "사용자 계정·관심 종목",
        }
    }
}


def get_headers():
    return {
        "Authorization": f"Bearer {OM_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


def ensure_tag_classifications(dry_run: bool):
    """DataLayer, Domain classification 및 하위 태그 생성"""
    headers = get_headers()

    for cls_name, cls_info in TAG_CLASSIFICATIONS.items():
        # classification 존재 여부 확인
        resp = requests.get(
            f"{OM_HOST}/api/v1/classifications/name/{cls_name}",
            headers=headers,
        )

        if resp.status_code == 404:
            if dry_run:
                print(f"[DRY-RUN] Create classification: {cls_name}")
            else:
                r = requests.post(
                    f"{OM_HOST}/api/v1/classifications",
                    headers=headers,
                    json={
                        "name": cls_name,
                        "displayName": cls_name,
                        "description": cls_info["description"],
                    },
                )
                if r.status_code in (200, 201):
                    print(f"  ✅ Created classification: {cls_name}")
                else:
                    print(f"  ❌ Failed to create {cls_name}: {r.status_code} {r.text[:200]}")
                    return False
        elif resp.status_code == 200:
            print(f"  ℹ️  Classification already exists: {cls_name}")
        else:
            print(f"  ❌ Unexpected response for {cls_name}: {resp.status_code}")
            return False

        # 하위 태그 생성
        for tag_name, tag_desc in cls_info["tags"].items():
            tag_fqn = f"{cls_name}.{tag_name}"
            t_resp = requests.get(
                f"{OM_HOST}/api/v1/tags/name/{tag_fqn}",
                headers=headers,
            )
            if t_resp.status_code == 404:
                if dry_run:
                    print(f"  [DRY-RUN] Create tag: {tag_fqn}")
                else:
                    tr = requests.post(
                        f"{OM_HOST}/api/v1/tags",
                        headers=headers,
                        json={
                            "name": tag_name,
                            "displayName": tag_name,
                            "description": tag_desc,
                            "classification": cls_name,
                        },
                    )
                    if tr.status_code in (200, 201):
                        print(f"    ✅ Created tag: {tag_fqn}")
                    else:
                        print(f"    ❌ Failed to create {tag_fqn}: {tr.status_code} {tr.text[:200]}")
            elif t_resp.status_code == 200:
                print(f"    ℹ️  Tag already exists: {tag_fqn}")

    return True


def get_table_id(table_name: str) -> str | None:
    """테이블 FQN으로 테이블 ID 조회"""
    fqn = f"{OM_SERVICE_DB}.{OM_DB_NAME}.{OM_DB_SCHEMA}.{table_name}"
    resp = requests.get(
        f"{OM_HOST}/api/v1/tables/name/{fqn}",
        headers=get_headers(),
    )
    if resp.status_code == 200:
        return resp.json().get("id")
    return None


def apply_tags_to_table(table_name: str, tags: list[str], dry_run: bool) -> bool:
    """테이블에 태그 적용 (기존 태그 유지 + 신규 태그 추가)"""
    headers = get_headers()
    fqn = f"{OM_SERVICE_DB}.{OM_DB_NAME}.{OM_DB_SCHEMA}.{table_name}"

    # 현재 테이블 상태 조회
    resp = requests.get(
        f"{OM_HOST}/api/v1/tables/name/{fqn}",
        headers=headers,
    )
    if resp.status_code != 200:
        print(f"  ⚠️  Not found: {table_name} ({resp.status_code})")
        return False

    table_data = resp.json()
    table_id   = table_data["id"]

    # 기존 태그 수집 (tagFQN 기준)
    existing_tags = {t["tagFQN"] for t in table_data.get("tags", [])}

    # 추가할 태그 (DataLayer.* / Domain.* 만 교체 — 다른 태그는 그대로 유지)
    new_tags = [t for t in existing_tags
                if not t.startswith("DataLayer.") and not t.startswith("Domain.")]
    new_tags.extend(tags)

    tag_payload = [
        {"tagFQN": t, "source": "Classification", "labelType": "Manual", "state": "Confirmed"}
        for t in new_tags
    ]

    if dry_run:
        print(f"  [DRY-RUN] {table_name}: {tags}")
        return True

    patch = [{"op": "add", "path": "/tags", "value": tag_payload}]
    r = requests.patch(
        f"{OM_HOST}/api/v1/tables/{table_id}",
        headers={**headers, "Content-Type": "application/json-patch+json"},
        data=json.dumps(patch),
    )
    if r.status_code in (200, 201):
        print(f"  ✅ {table_name}: {' | '.join(tags)}")
        return True
    else:
        print(f"  ❌ {table_name}: {r.status_code} {r.text[:200]}")
        return False


def main():
    parser = argparse.ArgumentParser(description="OM 테이블 레이어/도메인 Tags 일괄 등록")
    parser.add_argument("--dry-run", action="store_true", help="실제 API 호출 없이 출력만")
    args = parser.parse_args()

    if not OM_BOT_TOKEN:
        print("❌ OM_BOT_TOKEN 환경변수가 필요합니다.")
        sys.exit(1)

    print(f"=== OM Tag 등록 {'(DRY-RUN)' if args.dry_run else ''} ===")
    print(f"Host: {OM_HOST}")
    print()

    # Step 1: Tag Classification 생성
    print("▶ Step 1: Tag Classification 생성")
    if not ensure_tag_classifications(args.dry_run):
        sys.exit(1)
    print()

    # Step 2: 테이블별 Tags 적용
    print("▶ Step 2: 테이블별 Tags 적용")
    success = fail = skip = 0
    for table, tags in TABLE_TAGS.items():
        result = apply_tags_to_table(table, tags, args.dry_run)
        if result:
            success += 1
        else:
            fail += 1

    print()
    print(f"=== 완료: 성공 {success} / 실패 {fail} ===")


if __name__ == "__main__":
    main()
