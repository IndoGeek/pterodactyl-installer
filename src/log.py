"""Minimal file logging shared by the installer and the uninstaller."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from . import config

_LOGGER: logging.Logger | None = None


def setup_logging(kind: str) -> Path:
    """Configure the shared logger to append to a timestamped file in ./logs."""
    global _LOGGER
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    log_path = config.LOG_DIR / f'{kind}-{stamp}.log'
    _LOGGER = logging.getLogger('pterodactyl-installer')
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    _LOGGER.addHandler(handler)
    return log_path


def record(level: str, message: str) -> None:
    if _LOGGER is not None:
        _LOGGER.log(getattr(logging, level, logging.INFO), message)