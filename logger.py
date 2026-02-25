import logging
import os
import sys

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))

    return logger
