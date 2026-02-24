"""
로깅 설정 모듈 (BIP-Pipeline)
사용법: from shared.logging_config import get_logger
       logger = get_logger(__name__)
"""

import logging
import sys
from typing import Optional


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    표준화된 로거 반환

    Args:
        name: 로거 이름 (보통 __name__ 사용)

    Returns:
        설정된 Logger 인스턴스
    """
    logger = logging.getLogger(name or "bip-pipeline")

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger


# 기본 로거
logger = get_logger("bip-pipeline")
