import pytest

from app.auth.origin import is_allowed, normalize

ALLOWED = ["http://localhost:5173", "https://app.example.com"]


def test_exact_match_allowed():
    assert is_allowed("http://localhost:5173", ALLOWED)
    assert is_allowed("https://app.example.com", ALLOWED)


def test_trailing_slash_tolerated_on_either_side():
    assert is_allowed("http://localhost:5173/", ALLOWED)
    assert is_allowed("http://localhost:5173", ["http://localhost:5173/"])


def test_case_insensitive():
    assert is_allowed("HTTP://LOCALHOST:5173", ALLOWED)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5174",  # wrong port
        "https://localhost:5173",  # wrong scheme
        "http://evil.com",  # wrong host
        "http://sub.localhost:5173",  # subdomain is a different origin
    ],
)
def test_mismatches_rejected(origin):
    assert not is_allowed(origin, ALLOWED)


def test_prefix_attack_rejected():
    """startswith() would let this through. Exact match must not."""
    assert not is_allowed("http://localhost:5173.evil.com", ALLOWED)
    assert not is_allowed("http://localhost:51730", ALLOWED)


@pytest.mark.parametrize("origin", [None, "", "   ", "null"])
def test_missing_or_null_origin_rejected(origin):
    assert not is_allowed(origin, ALLOWED)


def test_empty_allowlist_rejects_everything():
    assert not is_allowed("http://localhost:5173", [])
    assert not is_allowed("http://localhost:5173", ["", "  "])


def test_normalize():
    assert normalize("  HTTP://Localhost:5173/  ") == "http://localhost:5173"
