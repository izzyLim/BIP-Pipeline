"""
텔레그램 발송 유틸리티 (Market Pulse Bot)
"""
import os
import re
import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _clean_markdown(text: str) -> str:
    """LLM 마크다운을 텔레그램 MarkdownV2에서 안전한 형태로 변환"""
    # 텔레그램에서 이스케이프 필요한 특수문자
    escape_chars = r'_[]()~`>#+=|{}.!'
    for ch in escape_chars:
        text = text.replace(ch, f'\\{ch}')
    # ** bold ** → *bold*
    text = re.sub(r'\\\*\\\*(.*?)\\\*\\\*', r'*\1*', text)
    return text


def _ai_to_telegram(ai_analysis: str, today_str: str) -> str:
    """AI 분석 텍스트를 텔레그램 메시지 형식으로 변환 (4096자 제한)"""
    lines = ai_analysis.split('\n')
    result = []
    char_count = 0
    limit = 3800  # 여유있게 설정

    header = f"📊 *Morning Pulse — {today_str}*\n\n"
    result.append(header)
    char_count += len(header)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append('\n')
            char_count += 1
            continue

        # 마크다운 헤딩 → 텔레그램 볼드
        if stripped.startswith('### ') or stripped.startswith('## '):
            text = re.sub(r'^#+\s*', '', stripped)
            formatted = f"\n*{text}*\n"
        elif stripped.startswith('□'):
            formatted = f"  {stripped}\n"
        elif stripped.startswith('- ') or stripped.startswith('• '):
            formatted = f"  {stripped}\n"
        elif stripped == '---':
            formatted = '\n'
        else:
            formatted = f"{stripped}\n"

        if char_count + len(formatted) > limit:
            result.append('\n_\\.\\.\\. 전체 내용은 이메일을 확인하세요_ 📧')
            break

        result.append(formatted)
        char_count += len(formatted)

    return ''.join(result)


def send_telegram_message(text: str, chat_id: str = None) -> bool:
    """텔레그램 메시지 발송"""
    if not BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN 미설정 — 텔레그램 발송 건너뜀")
        return False

    target_chat = chat_id or CHAT_ID
    if not target_chat:
        print("⚠️ TELEGRAM_CHAT_ID 미설정 — 텔레그램 발송 건너뜀")
        return False

    try:
        resp = httpx.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": target_chat,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            return True
        else:
            print(f"⚠️ 텔레그램 발송 실패: {data.get('description')}")
            return False
    except Exception as e:
        print(f"⚠️ 텔레그램 발송 오류: {e}")
        return False


def send_morning_report_telegram(ai_analysis: str, today_str: str, chat_id: str = None) -> bool:
    """모닝 리포트 텔레그램 발송"""
    text = _ai_to_telegram(ai_analysis, today_str)
    success = send_telegram_message(text, chat_id=chat_id)
    if success:
        print(f"✅ 텔레그램 발송 완료")
    return success
