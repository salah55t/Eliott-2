"""
utils/logger.py
---------------
Structured, timestamped logging for the Elliott Wave bot.
Writes to both console (stdout) and a rotating log file.

Usage:
    from utils.logger import get_logger
    log = get_logger(__name__)
    log.info("Fetched 500 candles for BTC/USDT 1h")
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def get_logger(name: str, log_dir: str = "logs", log_file: str = "bot.log",
               level: str = "INFO") -> logging.Logger:
    """
    Return a logger with console + rotating-file handlers.

    Parameters
    ----------
    name     : Typically __name__ of the calling module.
    log_dir  : Directory where log files are written.
    log_file : Base filename for the rotating log.
    level    : Logging level string ("DEBUG", "INFO", "WARNING", "ERROR").
    """
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if get_logger is called multiple times
    if logger.handlers:
        return logger

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console handler ────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(numeric_level)
    logger.addHandler(console_handler)

    # ── Rotating file handler (10 MB × 5 backups) ─────────────────────────
    file_path = os.path.join(log_dir, log_file)
    file_handler = RotatingFileHandler(
        file_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(numeric_level)
    logger.addHandler(file_handler)

    return logger


# ── Adaptive price formatter ───────────────────────────────────────────────────

def fmt_price(price: float) -> str:
    """
    Format a price with adaptive decimal places based on its magnitude.

    Prevents micro-priced tokens (SHIB, PEPE, etc.) from displaying as
    "0.0000" when formatted with the fixed %.4f specifier used throughout
    the codebase.

    Examples
    --------
    fmt_price(76000.50)      → "76,000.50"
    fmt_price(3456.789)      → "3,456.7890"
    fmt_price(0.003456)      → "0.003456"
    fmt_price(0.0000043456)  → "0.00000435"
    fmt_price(0.0000000012)  → "1.2400e-09"
    """
    if price == 0:
        return "0.0"
    abs_p = abs(price)
    if abs_p >= 1_000:
        return f"{price:,.2f}"
    elif abs_p >= 1:
        return f"{price:.4f}"
    elif abs_p >= 0.001:
        return f"{price:.6f}"
    elif abs_p >= 0.000_001:
        return f"{price:.8f}"
    else:
        return f"{price:.4e}"
