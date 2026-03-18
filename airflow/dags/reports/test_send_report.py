#!/usr/bin/env python3
"""
모닝 리포트 테스트 발송 스크립트
사용법: python test_send_report.py
"""

import os
import sys

print("=" * 50)
print("📧 BIP 모닝 리포트 테스트 발송")
print("=" * 50)
print()

# 환경변수에서 설정 확인, 없으면 입력 받기
SMTP_USER = os.environ.get("SMTP_USER", "").replace("\xa0", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").replace("\xa0", "")
TO_EMAIL = os.environ.get("MORNING_REPORT_EMAILS", "").split(",")[0].strip()

if not SMTP_USER or not SMTP_PASSWORD:
    print("환경변수에 SMTP 설정이 없습니다. 직접 입력하세요.\n")
    SMTP_USER = input("발신 Gmail 주소: ").strip()
    SMTP_PASSWORD = input("앱 비밀번호 (16자리): ").strip().replace(" ", "").replace("\xa0", "")
    TO_EMAIL = input("수신 이메일 [izzy253@gmail.com]: ").strip() or "izzy253@gmail.com"

    os.environ["SMTP_USER"] = SMTP_USER
    os.environ["SMTP_PASSWORD"] = SMTP_PASSWORD
    os.environ["FROM_EMAIL"] = SMTP_USER

if not TO_EMAIL:
    TO_EMAIL = "izzy253@gmail.com"

# DB 연결 설정 (없으면 기본값)
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql+psycopg2://user:pw1234@localhost:5432/stockdb"

print(f"📧 발신: {SMTP_USER}")
print(f"📬 수신: {TO_EMAIL}")

if os.environ.get("ANTHROPIC_API_KEY"):
    print("🤖 AI 분석: Claude Sonnet 사용")
else:
    print("⚠️  AI 분석: 더미 분석 사용 (ANTHROPIC_API_KEY 없음)")

print()
print("🚀 리포트 생성 및 발송 시작...")
print()

# 2. 리포트 생성 및 발송
from report_builder import build_morning_report, save_report_to_file

result = build_morning_report(
    to_emails=[TO_EMAIL],
    send=True,
)

if result["success"]:
    print()
    print("=" * 50)
    print("✅ 발송 완료!")
    print(f"   수신자: {TO_EMAIL}")
    print("=" * 50)

    # 백업 저장
    if result.get("html"):
        filepath = save_report_to_file(result["html"])
        print(f"📄 HTML 백업: {filepath}")
else:
    print()
    print("=" * 50)
    print(f"❌ 발송 실패: {result.get('error', 'Unknown error')}")
    print("=" * 50)
