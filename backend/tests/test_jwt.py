"""Валидация HS256 JWT (app.auth.jwt): подпись, exp, alg."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_jwt(payload: Mapping[str, object], secret: str, alg: str = "HS256") -> str:
    """Собирает HS256 JWT (как делает 1С ТокенДоступа.Подписать).

    1С использует строку ключа как есть (UTF-8), без base64-декодирования.
    """
    key = secret.encode("utf-8")
    header = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = _b64url(json.dumps(dict(payload)).encode())
    sig = _b64url(hmac.new(key, f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


SECRET = "YnSdgu3G2xglYfpT3eLee2Sz1M+VwqqxkL7XYu9fP5c="


def test_valid_token() -> None:
    from app.auth.jwt import validate_hs256

    payload = {"sub": "ivanov", "iss": "1c-ai-chat", "base": "ca2"}
    token = _make_jwt(payload, SECRET)
    result = validate_hs256(token, SECRET)
    assert result is not None
    assert result["sub"] == "ivanov"
    assert result["base"] == "ca2"


def test_bad_signature() -> None:
    from app.auth.jwt import validate_hs256

    payload = {"sub": "ivanov"}
    token = _make_jwt(payload, SECRET)
    # Подменяем подпись.
    parts = token.split(".")
    parts[2] = "invalidsignature"
    assert validate_hs256(".".join(parts), SECRET) is None


def test_wrong_secret() -> None:
    from app.auth.jwt import validate_hs256

    payload = {"sub": "ivanov"}
    token = _make_jwt(payload, SECRET)
    other_secret = base64.urlsafe_b64encode(b"other-secret-key-32-bytes-long!!!").decode().rstrip("=")
    assert validate_hs256(token, other_secret) is None


def test_expired_token() -> None:
    from app.auth.jwt import validate_hs256

    payload = {"sub": "ivanov", "exp": int(time.time()) - 100}
    token = _make_jwt(payload, SECRET)
    assert validate_hs256(token, SECRET) is None


def test_future_exp_ok() -> None:
    from app.auth.jwt import validate_hs256

    payload = {"sub": "ivanov", "exp": int(time.time()) + 3600}
    token = _make_jwt(payload, SECRET)
    result = validate_hs256(token, SECRET)
    assert result is not None
    assert result["sub"] == "ivanov"


def test_no_exp_ok() -> None:
    from app.auth.jwt import validate_hs256

    payload = {"sub": "petrov"}
    token = _make_jwt(payload, SECRET)
    result = validate_hs256(token, SECRET)
    assert result is not None
    assert result["sub"] == "petrov"


def test_wrong_alg_rejected() -> None:
    from app.auth.jwt import validate_hs256

    payload = {"sub": "ivanov"}
    token = _make_jwt(payload, SECRET, alg="HS512")
    # Подпись HS512 не пройдёт проверку HS256 (alg в заголовке другой).
    assert validate_hs256(token, SECRET) is None


def test_malformed_token() -> None:
    from app.auth.jwt import validate_hs256

    assert validate_hs256("not-a-jwt", SECRET) is None
    assert validate_hs256("", SECRET) is None
    assert validate_hs256("a.b", SECRET) is None


def test_extract_bearer() -> None:
    from app.auth.jwt import extract_bearer_token

    assert extract_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    assert extract_bearer_token("bearer abc") is None  # регистр важен
    assert extract_bearer_token("") is None
    assert extract_bearer_token(None) is None
    assert extract_bearer_token("Basic dXNlcjpwYXNz") is None
