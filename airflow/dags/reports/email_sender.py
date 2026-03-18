"""
이메일 발송기
- SMTP 또는 SendGrid를 사용한 이메일 발송
- HTML 이메일 지원
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.header import Header
from email.utils import formataddr
from email.policy import SMTP
import base64
from typing import List, Dict, Optional


def get_smtp_config():
    """SMTP 설정 로드 (함수 호출 시점에 환경변수 읽기)"""
    smtp_user = os.getenv("SMTP_USER", "").replace("\xa0", "")
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": smtp_user,
        "password": os.getenv("SMTP_PASSWORD", "").replace("\xa0", ""),
        "from_email": os.getenv("FROM_EMAIL", smtp_user).replace("\xa0", ""),
        "from_name": os.getenv("FROM_NAME", "BIP 모닝 브리핑"),
    }


def send_email(
    to_emails: List[str],
    subject: str,
    html_content: str,
    images: Optional[Dict[str, str]] = None,
) -> bool:
    """
    HTML 이메일 발송 (개별 발송으로 수신자 간 이메일 주소 비공개)

    Args:
        to_emails: 수신자 이메일 목록
        subject: 이메일 제목
        html_content: HTML 본문
        images: {"cid_name": "base64_image_data"} 형태의 인라인 이미지

    Returns:
        성공 여부
    """
    config = get_smtp_config()

    if not config["user"] or not config["password"]:
        print("⚠️ SMTP 설정이 없습니다. SMTP_USER, SMTP_PASSWORD 환경변수를 설정하세요.")
        return False

    # 특수 문자 정리 (non-breaking space 등)
    html_content = html_content.replace('\xa0', ' ')
    subject = subject.replace('\xa0', ' ')

    # 인라인 이미지 준비
    image_parts = []
    if images:
        for cid, img_base64 in images.items():
            img_data = base64.b64decode(img_base64)
            img_part = MIMEImage(img_data)
            img_part.add_header("Content-ID", f"<{cid}>")
            img_part.add_header(
                "Content-Disposition", "inline", filename=f"{cid}.png"
            )
            image_parts.append(img_part)

    success_count = 0
    fail_count = 0

    try:
        # SMTP 연결 (한 번 연결 후 여러 명에게 개별 발송)
        with smtplib.SMTP(config["host"], config["port"]) as server:
            server.starttls()
            server.login(config["user"], config["password"])

            # 각 수신자에게 개별 발송
            for to_email in to_emails:
                try:
                    # 메시지 생성 (수신자별로 새로 생성)
                    msg = MIMEMultipart("related")
                    msg["Subject"] = subject
                    msg["From"] = f"{config['from_name']} <{config['from_email']}>"
                    msg["To"] = to_email  # 개별 수신자만 표시

                    # HTML 본문
                    html_part = MIMEText(html_content, "html", "utf-8")
                    msg.attach(html_part)

                    # 인라인 이미지 첨부
                    for img_part in image_parts:
                        msg.attach(img_part)

                    server.send_message(msg, from_addr=config["from_email"], to_addrs=[to_email])
                    success_count += 1
                except Exception as e:
                    print(f"❌ 발송 실패 ({to_email}): {e}")
                    fail_count += 1

        print(f"✅ 이메일 발송 완료: {success_count}명 성공, {fail_count}명 실패")
        return fail_count == 0

    except Exception as e:
        import traceback
        print(f"❌ 이메일 발송 실패: {e}")
        traceback.print_exc()
        return False


def send_test_email(to_email: str) -> bool:
    """테스트 이메일 발송"""
    html = """
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h1 style="color: #2563eb;">📊 BIP 모닝 브리핑 테스트</h1>
        <p>이메일 발송 테스트입니다.</p>
        <p style="color: #666;">이 이메일이 정상적으로 보인다면 설정이 완료된 것입니다.</p>
    </body>
    </html>
    """
    return send_email([to_email], "[테스트] BIP 모닝 브리핑", html)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        test_email = sys.argv[1]
        print(f"테스트 이메일 발송: {test_email}")
        send_test_email(test_email)
    else:
        print("사용법: python email_sender.py your@email.com")
        print("\n환경변수 설정 필요:")
        print("  - SMTP_USER: Gmail 계정")
        print("  - SMTP_PASSWORD: Gmail 앱 비밀번호")
