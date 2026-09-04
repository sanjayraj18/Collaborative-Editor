import time
from typing import Final, Protocol

DEFAULT_TTL_SECONDS: Final[int] = 120
_SWEEP_EVERY: Final[int] = 256


class NonceStore(Protocol):
    def burn(self, nonce: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool: ...


class InMemoryNonceStore:
    def __init__(self) -> None:
        self._burned: dict[str, float] = {}
        self._since_sweep = 0

    def burn(self, nonce: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
        if not nonce:
            return False

        now = time.monotonic()
        self._maybe_sweep(now)

        expires_at = self._burned.get(nonce)
        if expires_at is not None and expires_at > now:
            return False

        self._burned[nonce] = now + ttl_seconds
        return True

    def _maybe_sweep(self, now: float) -> None:

        self._since_sweep += 1
        if self._since_sweep < _SWEEP_EVERY:
            return

        self._since_sweep = 0
        self._burned = {
            nonce: expires_at for nonce, expires_at in self._burned.items() if expires_at > now
        }

    def __len__(self) -> int:
        return len(self._burned)


# Process-wide instance. ws/endpoint.py imports this; tests build their own.
nonce_store: NonceStore = InMemoryNonceStore()
