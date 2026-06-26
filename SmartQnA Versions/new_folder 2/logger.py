"""
SmartQnA — Logger
Centralised logging config used across all services.
Logs go to both console and logs/app.log simultaneously.

Usage in any file:
    from logger import get_logger
    logger = get_logger(__name__)

    logger.info("File uploaded: samsung.pdf")
    logger.warning("Cache miss for query: S24 battery")
    logger.error("LLM call failed", exc_info=True)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR  = os.getenv("LOG_DIR",   "logs")
LOG_FILE = os.getenv("LOG_FILE",  "app.log")
LOG_LEVEL= os.getenv("LOG_LEVEL", "INFO")

os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, LOG_FILE)

# ── Format ────────────────────────────────────────────────────────────
# Example output:
# 2024-01-15 10:23:45,123 | INFO     | search_service | File uploaded: samsung.pdf
FORMATTER = logging.Formatter(
    fmt   ="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger.
    Call this at the top of every module:
        logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # ── Console handler ───────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(FORMATTER)
    logger.addHandler(console_handler)

    # ── File handler (rotating) ───────────────────────────────────────
    # Max 5MB per file, keep last 3 files
    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes   = 5 * 1024 * 1024,   # 5 MB
        backupCount= 3,
        encoding   = "utf-8"
    )
    file_handler.setFormatter(FORMATTER)
    logger.addHandler(file_handler)

    # Don't propagate to root logger to avoid duplicate logs
    logger.propagate = False

    return logger
