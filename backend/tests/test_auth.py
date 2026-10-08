import pytest

from app.core.security import TokenError, create_access_token, decode_access_token, hash_password, verify_password


def test_hash_password_is_not_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$2b$")


def test_verify_password_round_trip():
    hashed = hash_password("s3cret")
    assert verify_password("s3cret", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_round_trip():
    token = create_access_token("admin")
    assert decode_access_token(token) == "admin"


def test_invalid_token_raises_token_error():
    with pytest.raises(TokenError):
        decode_access_token("not.a.valid.jwt")


def test_tampered_token_raises_token_error():
    token = create_access_token("admin")
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
    with pytest.raises(TokenError):
        decode_access_token(tampered)
