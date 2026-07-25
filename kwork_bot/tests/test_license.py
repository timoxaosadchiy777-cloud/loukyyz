"""Тесты лицензирования: валидные/невалидные лицензии, привязка, TTL-кэш."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from schemas.license import LicensePayload
from security.license_service import LicenseVerifier, issue_license, machine_fingerprint
from security.signature import generate_ed25519_keypair


class _Settings:
    def __init__(self, license_key: str, public_key: str) -> None:
        self.license_key = license_key
        self.license_public_key = public_key
        self.license_cache_ttl = 3600

    @property
    def license_configured(self) -> bool:
        return bool(self.license_key and self.license_public_key)


_FUTURE = datetime.now(timezone.utc) + timedelta(days=30)
_PAST = datetime.now(timezone.utc) - timedelta(days=1)


def test_valid_license() -> None:
    priv, pub = generate_ed25519_keypair()
    token = issue_license(priv, LicensePayload(license_key="LIC-1", expires_at=_FUTURE))
    status = LicenseVerifier(_Settings(token, pub)).verify()
    assert status.valid and status.license_key == "LIC-1"


def test_wrong_public_key() -> None:
    priv, _ = generate_ed25519_keypair()
    _, other_pub = generate_ed25519_keypair()
    token = issue_license(priv, LicensePayload(license_key="LIC-1", expires_at=_FUTURE))
    status = LicenseVerifier(_Settings(token, other_pub)).verify()
    assert not status.valid


def test_tampered_payload() -> None:
    priv, pub = generate_ed25519_keypair()
    token = issue_license(priv, LicensePayload(license_key="LIC-1", expires_at=_FUTURE))
    _, signature = token.split(".")
    forged_payload = base64.urlsafe_b64encode(
        b'{"license_key":"HACKED","machine_fingerprint":"","issued_at":null,"expires_at":null}'
    ).rstrip(b"=").decode()
    forged = f"{forged_payload}.{signature}"
    status = LicenseVerifier(_Settings(forged, pub)).verify()
    assert not status.valid


def test_expired_license() -> None:
    priv, pub = generate_ed25519_keypair()
    token = issue_license(priv, LicensePayload(license_key="LIC-2", expires_at=_PAST))
    status = LicenseVerifier(_Settings(token, pub)).verify()
    assert not status.valid and "истёк" in status.reason.lower()


def test_machine_binding() -> None:
    priv, pub = generate_ed25519_keypair()
    bound_ok = issue_license(
        priv, LicensePayload(license_key="LIC-3", machine_fingerprint=machine_fingerprint(), expires_at=_FUTURE)
    )
    assert LicenseVerifier(_Settings(bound_ok, pub)).verify().valid

    bound_wrong = issue_license(
        priv, LicensePayload(license_key="LIC-4", machine_fingerprint="deadbeef" * 4, expires_at=_FUTURE)
    )
    status = LicenseVerifier(_Settings(bound_wrong, pub)).verify()
    assert not status.valid and "машин" in status.reason.lower()


def test_not_configured() -> None:
    assert not LicenseVerifier(_Settings("", "")).verify().valid


def test_ttl_cache_marks_offline_cached() -> None:
    priv, pub = generate_ed25519_keypair()
    token = issue_license(priv, LicensePayload(license_key="LIC-5", expires_at=_FUTURE))
    verifier = LicenseVerifier(_Settings(token, pub))
    first = verifier.verify()
    second = verifier.verify()
    assert first.valid and second.valid and second.offline_cached is True


def test_malformed_token() -> None:
    _, pub = generate_ed25519_keypair()
    assert not LicenseVerifier(_Settings("not-a-valid-token", pub)).verify().valid
