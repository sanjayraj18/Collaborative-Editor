import pytest

from app.auth.roles import Role
from app.auth.tickets import TicketError, issue, verify

SECRET = "test-secret-key-at-least-32-bytes-long!!"
NOW = 1_700_000_000


def mint(**overrides) -> tuple[str, int]:
    kwargs = dict(
        user_id="user-1",
        doc_id="doc-42",
        role=Role.WRITER,
        secret=SECRET,
        ttl_seconds=30,
        now=NOW,
    )
    kwargs.update(overrides)
    return issue(**kwargs)


def test_round_trip():
    ticket, expires_at = mint()
    claims = verify(ticket, secret=SECRET, now=NOW)

    assert claims.user_id == "user-1"
    assert claims.doc_id == "doc-42"
    assert claims.role is Role.WRITER
    assert claims.expires_at == expires_at == NOW + 30
    assert claims.nonce


def test_reader_role_survives():
    ticket, _ = mint(role=Role.READER)
    assert verify(ticket, secret=SECRET, now=NOW).role is Role.READER


def test_nonce_is_unique_per_issue():
    a, _ = mint()
    b, _ = mint()
    assert a != b
    assert verify(a, secret=SECRET, now=NOW).nonce != verify(b, secret=SECRET, now=NOW).nonce


def test_refuses_to_issue_role_none():
    with pytest.raises(ValueError, match="Role.NONE"):
        mint(role=Role.NONE)


def test_valid_one_second_before_expiry():
    ticket, _ = mint(ttl_seconds=30)
    assert verify(ticket, secret=SECRET, now=NOW + 29)


@pytest.mark.parametrize("offset", [30, 31, 10_000])
def test_expired_at_or_after_expiry(offset):
    ticket, _ = mint(ttl_seconds=30)
    with pytest.raises(TicketError, match="expired"):
        verify(ticket, secret=SECRET, now=NOW + offset)


def test_wrong_secret_rejected():
    ticket, _ = mint()
    with pytest.raises(TicketError, match="bad signature"):
        verify(ticket, secret="a-different-secret-thats-also-32-bytes", now=NOW)


def test_tampered_payload_rejected():
    ticket, _ = mint()
    version, payload, signature = ticket.split(".")
    with pytest.raises(TicketError, match="bad signature"):
        verify(f"{version}.{payload[:-4]}AAAA.{signature}", secret=SECRET, now=NOW)


def test_tampered_signature_rejected():
    ticket, _ = mint()
    version, payload, signature = ticket.split(".")
    with pytest.raises(TicketError, match="bad signature"):
        verify(f"{version}.{payload}.{signature[:-4]}AAAA", secret=SECRET, now=NOW)


def test_version_downgrade_rejected():
    ticket, _ = mint()
    _, payload, signature = ticket.split(".")
    with pytest.raises(TicketError, match="version"):
        verify(f"v0.{payload}.{signature}", secret=SECRET, now=NOW)


@pytest.mark.parametrize("ticket", ["", None, "onlyonepart", "two.parts", "a.b.c.d"])
def test_malformed_rejected(ticket):
    with pytest.raises(TicketError):
        verify(ticket, secret=SECRET, now=NOW)


def test_oversized_rejected():
    with pytest.raises(TicketError, match="oversized"):
        verify("v1." + "A" * 2000 + ".sig", secret=SECRET, now=NOW)


def test_role_escalation_by_forgery_rejected():
    """Flip reader->writer in the payload and the signature must fail."""
    import base64
    import json

    ticket, _ = mint(role=Role.READER)
    version, payload_b64, signature = ticket.split(".")

    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    payload["r"] = "writer"
    forged = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        .rstrip(b"=")
        .decode()
    )

    with pytest.raises(TicketError, match="bad signature"):
        verify(f"{version}.{forged}.{signature}", secret=SECRET, now=NOW)


def test_payload_is_readable_by_anyone():
    """Documents the threat model: signed, not encrypted."""
    import base64
    import json

    ticket, _ = mint()
    payload_b64 = ticket.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))

    assert payload["u"] == "user-1"
    assert payload["d"] == "doc-42"
