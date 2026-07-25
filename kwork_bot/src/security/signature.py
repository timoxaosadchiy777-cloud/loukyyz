"""Криптографические примитивы для лицензий: Ed25519 (основной) и HMAC (запасной).

Ключи и подписи кодируются в base64 (urlsafe без паддинга — устойчиво к переносам).
Функции подписи/генерации ключей нужны для тулинга и тестов (не только проверка).
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def b64encode(data: bytes) -> str:
    """base64url без паддинга."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64decode(text: str) -> bytes:
    """Декодирует base64url, добавляя паддинг при необходимости."""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


# --- Ed25519 ---

def generate_ed25519_keypair() -> tuple[str, str]:
    """Возвращает пару ключей (private_b64, public_b64) в base64url."""
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes_raw()
    public_raw = private_key.public_key().public_bytes_raw()
    return b64encode(private_raw), b64encode(public_raw)


def sign_ed25519(private_key_b64: str, message: bytes) -> str:
    """Подписывает сообщение приватным ключом Ed25519 → подпись в base64url."""
    private_key = Ed25519PrivateKey.from_private_bytes(b64decode(private_key_b64))
    return b64encode(private_key.sign(message))


def verify_ed25519(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    """Проверяет подпись Ed25519. Возвращает True/False, не бросает исключений."""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(b64decode(public_key_b64))
        public_key.verify(b64decode(signature_b64), message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# --- HMAC (симметричный запасной вариант) ---

def sign_hmac(secret: str, message: bytes) -> str:
    """HMAC-SHA256 подпись в base64url."""
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return b64encode(digest)


def verify_hmac(secret: str, message: bytes, signature_b64: str) -> bool:
    """Сравнение HMAC в постоянном времени. Возвращает True/False."""
    try:
        expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
        return hmac.compare_digest(expected, b64decode(signature_b64))
    except (ValueError, TypeError):
        return False
