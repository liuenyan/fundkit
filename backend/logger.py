"""
集中日志配置
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_logged = False


def setup_logging(
    log_dir: str = "data",
    log_name: str = "fundkit.log",
    level: int = logging.WARNING,
) -> None:
    global _logged
    if _logged:
        return
    _logged = True

    log_path = Path(log_dir) / log_name
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        stderr_h = logging.StreamHandler(sys.stderr)
        stderr_h.setFormatter(fmt)
        root.addHandler(stderr_h)

    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        file_h = RotatingFileHandler(log_path, maxBytes=5_242_880, backupCount=3, encoding="utf-8")
        file_h.setFormatter(fmt)
        root.addHandler(file_h)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
