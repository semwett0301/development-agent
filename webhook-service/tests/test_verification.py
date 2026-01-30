import hashlib
import hmac

from verification import verify_signature

SECRET = "test_secret"
PAYLOAD = b'{"action": "opened"}'


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_valid_signature():
    signature = _sign(PAYLOAD, SECRET)
    assert verify_signature(PAYLOAD, SECRET, signature)


def test_invalid_signature():
    assert not verify_signature(PAYLOAD, SECRET, "sha256=invalid")


def test_wrong_secret():
    signature = _sign(PAYLOAD, "wrong_secret")
    assert not verify_signature(PAYLOAD, SECRET, signature)


def test_tampered_payload():
    signature = _sign(PAYLOAD, SECRET)
    assert not verify_signature(b"tampered", SECRET, signature)
