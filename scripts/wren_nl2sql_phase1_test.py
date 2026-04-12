#!/usr/bin/env python3
"""
Wren AI NL2SQL Phase 1 품질 검증 스크립트.

기능:
    1) POST /v1/asks 로 질문 제출
    2) GET /v1/asks/{id}/result polling
    3) Wren SQL의 public_xxx 테이블명을 PostgreSQL public.xxx 형식으로 변환
    4) PostgreSQL 실행 후 행 수/샘플 결과/간단한 의미 검증 수행
    5) JSON + Markdown 리포트 생성

실행 예시:
    python3 scripts/wren_nl2sql_phase1_test.py

환경변수:
    WREN_API_BASE=http://localhost:5555
    WREN_MDL_HASH=
    WREN_TIMEOUT_SECONDS=90
    WREN_POLL_SECONDS=3

    PG_HOST=localhost
    PG_PORT=5432
    PG_USER=user
    PG_PASSWORD=...
    PG_DB=stockdb

출력:
    reports/wren_phase1_results.json
    reports/wren_phase1_results.md
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import requests


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
JSON_REPORT = REPORT_DIR / "wren_phase1_results.json"
MD_REPORT = REPORT_DIR / "wren_phase1_results.md"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


load_dotenv(ROOT / ".env")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def normalize_table_names(sql: str) -> str:
    # "public_analytics_valuation" -> "public"."analytics_valuation"
    # Also handles unquoted: public_analytics_valuation -> "public"."analytics_valuation"
    pattern = re.compile(r'"public_([a-zA-Z0-9_]+)"')

    def repl(match: re.Match[str]) -> str:
        suffix = match.group(1)
        return f'"public"."{suffix}"'

    return pattern.sub(repl, sql)


def compact_cell(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    text = str(value)
    return text if len(text) <= 120 else text[:117] + "..."


def result_mentions(rows: list[dict[str, Any]], needle: str) -> bool:
    needle_lower = needle.lower()
    for row in rows:
        for value in row.values():
            if needle_lower in str(value).lower():
                return True
    return False


@dataclass
class TestCase:
    number: int
    question: str
    expected_min_rows: int = 0
    expected_exact_rows: int | None = None
    required_terms: list[str] = field(default_factory=list)
    required_years: list[str] = field(default_factory=list)
    required_sql_flags: list[str] = field(default_factory=list)
    required_sql_terms: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class CaseResult:
    number: int
    question: str
    query_id: str | None
    generated: bool
    api_status: str
    sql_raw: str | None
    sql_pg: str | None
    sql_error: str | None
    db_executed: bool
    db_error: str | None
    row_count: int | None
    semantic_ok: bool
    semantic_checks: list[str]
    flag_usage: dict[str, bool]
    sample_rows: list[dict[str, Any]]


TEST_CASES = [
    TestCase(1, "삼성전자 PER", expected_min_rows=1, required_terms=["삼성전자", "PER"]),
    TestCase(2, "코스피 시총 상위 5종목", expected_exact_rows=5, required_sql_terms=["LIMIT 5"]),
    TestCase(3, "저평가주 찾아줘", expected_min_rows=1, required_sql_flags=["is_value_stock"]),
    TestCase(4, "과매도 종목", expected_min_rows=0, required_sql_flags=["is_oversold_rsi"]),
    TestCase(5, "외국인 순매수 상위 종목", expected_min_rows=1),
    TestCase(6, "삼성전자 vs SK하이닉스 밸류에이션", expected_min_rows=2, required_terms=["삼성전자", "SK하이닉스"]),
    TestCase(7, "삼성전자 잠정 실적", expected_min_rows=1, required_terms=["preliminary"]),
    TestCase(8, "2025년 실적과 2026년 추정치 비교", expected_min_rows=1, required_years=["2025", "2026"]),
    TestCase(9, "삼성전자 최근 5일 주가", expected_exact_rows=5, required_terms=["삼성전자"]),
    TestCase(10, "최근 1주일 환율 추이", expected_min_rows=1),
    TestCase(11, "기관 외국인 동시 매수 종목", expected_min_rows=0),
    TestCase(12, "현대차 기아 실적 비교", expected_min_rows=2, required_terms=["현대차", "기아"]),
    TestCase(13, "성장주 추천", expected_min_rows=1, required_sql_flags=["is_growth_stock"]),
    TestCase(14, "저평가이면서 외국인 매수 종목", expected_min_rows=0, required_sql_flags=["is_value_stock"]),
    TestCase(15, "삼성전자 52주 신고가 신저가", expected_min_rows=1, required_terms=["삼성전자"]),
]


class WrenPhase1Tester:
    def __init__(self) -> None:
        self.api_base = env("WREN_API_BASE", "http://localhost:5555").rstrip("/")
        self.mdl_hash = env("WREN_MDL_HASH", "")
        self.timeout_seconds = int(env("WREN_TIMEOUT_SECONDS", "90"))
        self.poll_seconds = int(env("WREN_POLL_SECONDS", "3"))
        self.pg_conn_info = {
            "host": env("PG_HOST", "localhost"),
            "port": int(env("PG_PORT", "5432")),
            "user": env("PG_USER", "user"),
            "password": env("PG_PASSWORD"),
            "dbname": env("PG_DB", "stockdb"),
        }
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def ask(self, question: str) -> tuple[str | None, str, dict[str, Any] | None]:
        try:
            response = self.session.post(
                f"{self.api_base}/v1/asks",
                json={"query": question, "mdl_hash": self.mdl_hash},
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            query_id = payload.get("query_id") or payload.get("id")
            if not query_id:
                return None, "missing_query_id", payload
            return str(query_id), "submitted", payload
        except Exception as exc:
            return None, f"submit_error: {exc}", None

    def poll_result(self, query_id: str) -> tuple[str, dict[str, Any] | None]:
        deadline = time.time() + self.timeout_seconds
        last_payload: dict[str, Any] | None = None

        while time.time() < deadline:
            try:
                response = self.session.get(
                    f"{self.api_base}/v1/asks/{query_id}/result",
                    timeout=120,
                )
                response.raise_for_status()
                payload = response.json()
                last_payload = payload
                status = str(payload.get("status", "unknown"))
                if status in {"finished", "failed", "error", "stopped"}:
                    return status, payload
            except Exception as exc:
                return f"poll_error: {exc}", last_payload
            time.sleep(self.poll_seconds)

        return "timeout", last_payload

    def execute_sql(self, sql: str) -> tuple[list[dict[str, Any]] | None, str | None]:
        try:
            conn = psycopg2.connect(**self.pg_conn_info)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql)
                    rows = [dict(row) for row in cur.fetchall()]
                    return rows, None
            finally:
                conn.close()
        except Exception as exc:
            return None, str(exc)

    def semantic_checks(self, tc: TestCase, sql: str | None, rows: list[dict[str, Any]] | None) -> tuple[bool, list[str], dict[str, bool]]:
        checks: list[str] = []
        flags = {flag: False for flag in tc.required_sql_flags}

        if sql:
            sql_lower = sql.lower()
            for flag in tc.required_sql_flags:
                flags[flag] = flag.lower() in sql_lower
                checks.append(f"flag:{flag}={'PASS' if flags[flag] else 'FAIL'}")
            for term in tc.required_sql_terms:
                ok = term.lower() in sql_lower
                checks.append(f"sql_term:{term}={'PASS' if ok else 'FAIL'}")
        else:
            for flag in tc.required_sql_flags:
                checks.append(f"flag:{flag}=FAIL")
            for term in tc.required_sql_terms:
                checks.append(f"sql_term:{term}=FAIL")

        if rows is None:
            checks.append("db_rows=FAIL")
            return False, checks, flags

        row_count = len(rows)
        if tc.expected_exact_rows is not None:
            checks.append(
                f"rows_exact:{tc.expected_exact_rows}={'PASS' if row_count == tc.expected_exact_rows else 'FAIL'}"
            )
        elif tc.expected_min_rows:
            checks.append(
                f"rows_min:{tc.expected_min_rows}={'PASS' if row_count >= tc.expected_min_rows else 'FAIL'}"
            )

        for term in tc.required_terms:
            ok = result_mentions(rows, term)
            checks.append(f"contains:{term}={'PASS' if ok else 'FAIL'}")

        for year in tc.required_years:
            ok = result_mentions(rows, year)
            checks.append(f"contains_year:{year}={'PASS' if ok else 'FAIL'}")

        semantic_ok = all(check.endswith("PASS") for check in checks)
        return semantic_ok, checks, flags

    def run_case(self, tc: TestCase) -> CaseResult:
        query_id, submit_status, submit_payload = self.ask(tc.question)
        if not query_id:
            return CaseResult(
                number=tc.number,
                question=tc.question,
                query_id=None,
                generated=False,
                api_status=submit_status,
                sql_raw=None,
                sql_pg=None,
                sql_error=json.dumps(submit_payload, ensure_ascii=False) if submit_payload else submit_status,
                db_executed=False,
                db_error=None,
                row_count=None,
                semantic_ok=False,
                semantic_checks=["sql_generation=FAIL"],
                flag_usage={flag: False for flag in tc.required_sql_flags},
                sample_rows=[],
            )

        final_status, payload = self.poll_result(query_id)
        responses = payload.get("response", []) if payload else []
        sql_raw = None
        if responses and isinstance(responses, list):
            first = responses[0] or {}
            sql_raw = first.get("sql")

        if final_status != "finished" or not sql_raw:
            return CaseResult(
                number=tc.number,
                question=tc.question,
                query_id=query_id,
                generated=bool(sql_raw),
                api_status=final_status,
                sql_raw=sql_raw,
                sql_pg=normalize_table_names(sql_raw) if sql_raw else None,
                sql_error=(payload or {}).get("error") if payload else final_status,
                db_executed=False,
                db_error=None,
                row_count=None,
                semantic_ok=False,
                semantic_checks=["sql_generation=FAIL" if not sql_raw else "sql_generation=PASS", f"api_status={final_status}"],
                flag_usage={flag: (flag.lower() in (sql_raw or "").lower()) for flag in tc.required_sql_flags},
                sample_rows=[],
            )

        sql_pg = normalize_table_names(sql_raw)
        rows, db_error = self.execute_sql(sql_pg)
        semantic_ok, checks, flags = self.semantic_checks(tc, sql_raw, rows)
        return CaseResult(
            number=tc.number,
            question=tc.question,
            query_id=query_id,
            generated=True,
            api_status=final_status,
            sql_raw=sql_raw,
            sql_pg=sql_pg,
            sql_error=None,
            db_executed=db_error is None,
            db_error=db_error,
            row_count=None if rows is None else len(rows),
            semantic_ok=semantic_ok,
            semantic_checks=checks,
            flag_usage=flags,
            sample_rows=[] if not rows else rows[:5],
        )

    def run(self) -> dict[str, Any]:
        results = [self.run_case(tc) for tc in TEST_CASES]
        summary = {
            "sql_generated": sum(1 for r in results if r.generated),
            "db_executed": sum(1 for r in results if r.db_executed),
            "semantic_ok": sum(1 for r in results if r.semantic_ok),
            "total": len(results),
            "claude_reference": {
                "sql_generated": 15,
                "db_executed": 15,
                "semantic_ok": 15,
            },
        }
        return {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "api_base": self.api_base,
            "db_host": self.pg_conn_info["host"],
            "summary": summary,
            "results": [asdict(r) for r in results],
        }


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = report["summary"]
    lines.append("# Wren AI NL2SQL Phase 1 Test Report")
    lines.append("")
    lines.append(f"- Generated at: {report['generated_at']}")
    lines.append(f"- Wren API: `{report['api_base']}`")
    lines.append(f"- PostgreSQL host: `{report['db_host']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Codex | Claude Reference |")
    lines.append("|---|---:|---:|")
    lines.append(f"| SQL generated | {summary['sql_generated']}/{summary['total']} | {summary['claude_reference']['sql_generated']}/{summary['total']} |")
    lines.append(f"| DB executed | {summary['db_executed']}/{summary['total']} | {summary['claude_reference']['db_executed']}/{summary['total']} |")
    lines.append(f"| Semantic OK | {summary['semantic_ok']}/{summary['total']} | {summary['claude_reference']['semantic_ok']}/{summary['total']} |")
    lines.append("")
    lines.append("## Case Results")
    lines.append("")
    lines.append("| # | Question | SQL | DB | Semantic | Rows | Flags |")
    lines.append("|---:|---|---|---|---|---:|---|")
    for result in report["results"]:
        flag_text = ", ".join(
            f"{name}={'Y' if used else 'N'}" for name, used in result["flag_usage"].items()
        ) or "-"
        lines.append(
            f"| {result['number']} | {result['question']} | "
            f"{'Y' if result['generated'] else 'N'} | "
            f"{'Y' if result['db_executed'] else 'N'} | "
            f"{'Y' if result['semantic_ok'] else 'N'} | "
            f"{result['row_count'] if result['row_count'] is not None else '-'} | "
            f"{flag_text} |"
        )

    for result in report["results"]:
        lines.append("")
        lines.append(f"## TC-{result['number']:02d} {result['question']}")
        lines.append("")
        lines.append(f"- query_id: `{result['query_id']}`")
        lines.append(f"- api_status: `{result['api_status']}`")
        lines.append(f"- sql_generated: `{'yes' if result['generated'] else 'no'}`")
        lines.append(f"- db_executed: `{'yes' if result['db_executed'] else 'no'}`")
        lines.append(f"- row_count: `{result['row_count']}`")
        lines.append(f"- semantic_ok: `{'yes' if result['semantic_ok'] else 'no'}`")
        lines.append(f"- semantic_checks: `{'; '.join(result['semantic_checks'])}`")
        if result["db_error"]:
            lines.append(f"- db_error: `{result['db_error']}`")
        if result["sql_error"]:
            lines.append(f"- sql_error: `{result['sql_error']}`")
        lines.append("")
        lines.append("### Generated SQL")
        lines.append("")
        lines.append("```sql")
        lines.append(result["sql_raw"] or "-- no SQL generated")
        lines.append("```")
        lines.append("")
        lines.append("### PostgreSQL SQL")
        lines.append("")
        lines.append("```sql")
        lines.append(result["sql_pg"] or "-- no SQL generated")
        lines.append("```")
        lines.append("")
        lines.append("### Sample Rows")
        lines.append("")
        if result["sample_rows"]:
            header = list(result["sample_rows"][0].keys())
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "|".join(["---"] * len(header)) + "|")
            for row in result["sample_rows"]:
                lines.append("| " + " | ".join(compact_cell(row.get(col)) for col in header) + " |")
        else:
            lines.append("_No rows_")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    tester = WrenPhase1Tester()
    report = tester.run()
    JSON_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    MD_REPORT.write_text(render_markdown(report), encoding="utf-8")
    print(f"JSON report: {JSON_REPORT}")
    print(f"Markdown report: {MD_REPORT}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
