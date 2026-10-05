"""Валидация HS256 JWT, сформированного формой 1С (ТокенДоступа.Подписать).

Форма подписывает токен общим секретом (HS256); бэкенд проверяет подпись и
извлекает sub (ИмяПользователя) для per-user RLS: запросы в 1С идут под этим
пользователем, а не под сервисным agent.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time

log = logging.getLogger("agent1c.jwt")


def _b64url_decode(data: str) -> bytes:
    """Base64url decode с восстановлением padding."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _b64url_encode(data: bytes) -> str:
    """Base64url encode без padding (как в JWT)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def validate_hs256(token: str, secret: str) -> dict[str, object] | None:
    """Проверить HS256-подпись и exp. Возвращает payload или None.

    secret — строка (тот же формат, что передаётся в BSL
    ТокенДоступа.Подписать(HS256, Ключ)). 1С использует строку как есть
    (UTF-8), НЕ декодирует её из Base64 — поэтому и здесь ключ = строка.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts

        # Проверка алгоритма в заголовке.
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            log.warning("JWT: неожиданный alg=%s (ожидался HS256)", header.get("alg"))
            return None

        # Проверка подписи. 1С ТокенДоступа.Подписать(HS256, Ключ) использует
        # строку ключа как есть (UTF-8), без base64-декодирования.
        key = secret.encode("utf-8")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = _b64url_encode(hmac.new(key, signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(expected_sig, sig_b64):
            log.warning("JWT: подпись не совпадает")
            return None

        # Decode payload.
        raw_payload = json.loads(_b64url_decode(payload_b64))
        if not isinstance(raw_payload, dict):
            return None
        payload: dict[str, object] = raw_payload

        # Проверка срока действия (если exp указан).
        exp = payload.get("exp")
        if exp is not None and time.time() > float(exp):  # type: ignore[arg-type]
            log.warning("JWT: токен истёк (exp=%s)", exp)
            return None

        return payload
    except Exception as e:  # noqa: BLE001 — любой сбой = невалидный токен
        log.debug("JWT: ошибка валидации: %s", e)
        return None


def extract_bearer_token(auth_header: str | None) -> str | None:
    """Извлечь токен из заголовка Authorization: Bearer <jwt>."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer ") :].strip()
    return token or None
