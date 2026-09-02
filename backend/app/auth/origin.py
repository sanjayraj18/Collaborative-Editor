from __future__ import annotations
from collections.abc import Iterable

def normalize(origin : str) -> str:
    return origin.strip().rstrip("/").lower()

def is_allowed(origin: str | None, allowlist: Iterable[str]) -> bool:
  
    if not origin:
        return False

    allowed = {normalize(entry) for entry in allowlist if entry.strip()}
    if not allowed:
        return False

    return normalize(origin) in allowed

