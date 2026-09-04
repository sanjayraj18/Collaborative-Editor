import time

from app.auth.nonce import InMemoryNonceStore


def test_first_burn_succeeds():
    store = InMemoryNonceStore()
    assert store.burn("abc") is True


def test_replay_rejected():
    store = InMemoryNonceStore()
    assert store.burn("abc") is True
    assert store.burn("abc") is False
    assert store.burn("abc") is False


def test_distinct_nonces_independent():
    store = InMemoryNonceStore()
    assert store.burn("a") is True
    assert store.burn("b") is True
    assert store.burn("a") is False


def test_empty_nonce_rejected():
    store = InMemoryNonceStore()
    assert store.burn("") is False
    assert store.burn(None) is False


def test_expired_nonce_can_be_reused():
    """A nonce only needs to block replay while its ticket could still be live."""
    store = InMemoryNonceStore()
    assert store.burn("abc", ttl_seconds=0) is True
    time.sleep(0.01)
    assert store.burn("abc", ttl_seconds=0) is True


def test_unexpired_nonce_still_blocks():
    store = InMemoryNonceStore()
    assert store.burn("abc", ttl_seconds=60) is True
    assert store.burn("abc", ttl_seconds=60) is False


def test_sweep_bounds_memory():
    store = InMemoryNonceStore()
    for i in range(1000):
        store.burn(f"expired-{i}", ttl_seconds=0)
    time.sleep(0.01)
    store.burn("trigger-a-sweep")
    assert len(store) < 1000


def test_live_entries_survive_sweep():
    store = InMemoryNonceStore()
    store.burn("keep-me", ttl_seconds=300)
    for i in range(600):
        store.burn(f"junk-{i}", ttl_seconds=0)
    assert store.burn("keep-me", ttl_seconds=300) is False
