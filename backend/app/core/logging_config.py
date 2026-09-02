from datetime import datetime, timezone
from typing import Any, Dict
import logging
from core.context import get_request_id
import json
import sys

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "taskName", "thread", "threadName",
}

_NOISE={"color_message"}

class JSONFormatter(logging.Formatter):

    def __init__(self, service: str="app"):
        super().__init__()
        self.service = service

    def format(self,record : logging.LogRecord) -> str:
        payload : Dict[str,Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }

        for key,value in  record.__dict__.items():
            if key not in _RESERVED and key not in _NOISE and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(level : str = 'DEBUG', service: str= "app") -> None:

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(service=service))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    for name in "uvicorn" , "uvicorn.error":
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False