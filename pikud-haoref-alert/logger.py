"""לוגר פשוט עם timezone — stdout בלבד."""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Jerusalem"))
_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
_MIN_LEVEL = _LEVEL_ORDER.get(os.environ.get("LOG_LEVEL", "DEBUG").upper(), 0)


class _Logger:
    def __init__(self, name: str):
        self._name = name

    def _log(self, level: str, msg: str):
        if _LEVEL_ORDER.get(level, 0) >= _MIN_LEVEL:
            ts = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts} [{self._name}] {level}: {msg}", flush=True)

    def debug(self, msg: str):
        self._log("DEBUG", msg)

    def info(self, msg: str):
        self._log("INFO", msg)

    def warning(self, msg: str):
        self._log("WARNING", msg)

    def error(self, msg: str):
        self._log("ERROR", msg)


def get_logger(name: str) -> _Logger:
    return _Logger(name)
