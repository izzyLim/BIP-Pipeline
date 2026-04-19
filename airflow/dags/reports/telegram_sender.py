"""
텔레그램 발송 유틸리티 (Market Pulse Bot)
- 채널: 운영용 (구독자 대상)
- 개인 DM: 테스트/디버깅용
"""
import os
import re
import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")  # 채널 (운영)
DM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")     # 개인 DM (테스트)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _send(text: str, chat_id: str) -> bool:
    """단일 대상 발송 (Markdown 실패 시 plain text fallback)"""
    if not BOT_TOKEN or not chat_id:
        return False
    try:
        # 1차: Markdown 시도
        resp = httpx.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            return True

        # Markdown 파싱 실패 시 plain text fallback
        if "can't parse entities" in data.get("description", ""):
            print(f"⚠️ Markdown 파싱 실패, plain text로 재시도 [{chat_id}]")
            # bold(*) 제거
            plain = text.replace("*", "").replace("_", "")
            resp2 = httpx.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": plain},
                timeout=15,
            )
            data2 = resp2.json()
            if data2.get("ok"):
                return True
            print(f"⚠️ plain text도 발송 실패 [{chat_id}]: {data2.get('description')}")
            return False

        print(f"⚠️ 텔레그램 발송 실패 [{chat_id}]: {data.get('description')}")
        return False
    except Exception as e:
        print(f"⚠️ 텔레그램 발송 오류 [{chat_id}]: {e}")
        return False


def send_telegram_message(text: str, test: bool = False) -> bool:
    """
    텔레그램 메시지 발송

    test=False (기본): 채널 + 개인 DM 둘 다 발송
    test=True: 개인 DM에만 발송 (테스트 표시 포함)
    """
    if not BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN 미설정 — 텔레그램 발송 건너뜀")
        return False

    if test:
        # 테스트: 개인 DM에만, [TEST] 표시
        if not DM_CHAT_ID:
            print("⚠️ TELEGRAM_CHAT_ID 미설정 — 테스트 발송 건너뜀")
            return False
        test_text = f"🧪 *[TEST]* {text}"
        success = _send(test_text, DM_CHAT_ID)
        if success:
            print("✅ 텔레그램 테스트 발송 완료 (DM)")
        return success
    else:
        # 운영: 채널 + 개인 DM
        results = []
        if CHANNEL_ID:
            results.append(_send(text, CHANNEL_ID))
        if DM_CHAT_ID:
            results.append(_send(text, DM_CHAT_ID))
        if not results:
            print("⚠️ 발송 대상 없음 — CHANNEL_ID, CHAT_ID 모두 미설정")
            return False
        success = any(results)
        if success:
            targets = []
            if CHANNEL_ID:
                targets.append("채널")
            if DM_CHAT_ID:
                targets.append("DM")
            print(f"✅ 텔레그램 발송 완료 ({', '.join(targets)})")
        return success
