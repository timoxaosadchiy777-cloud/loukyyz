"""CLI для лицензий kwork_bot: генерация ключей, выпуск токена, отпечаток машины.

Примеры:
    python scripts/license_tool.py keygen
    python scripts/license_tool.py fingerprint
    python scripts/license_tool.py issue --private <PRIV_B64> --key CUST-001 --days 365 [--bind]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Делаем пакеты из src импортируемыми при запуске из корня проекта.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from schemas.license import LicensePayload  # noqa: E402
from security.license_service import issue_license, machine_fingerprint  # noqa: E402
from security.signature import generate_ed25519_keypair  # noqa: E402


def _cmd_keygen() -> None:
    private_b64, public_b64 = generate_ed25519_keypair()
    print("LICENSE_PRIVATE_KEY (храните в секрете, только у издателя):")
    print(f"  {private_b64}")
    print("LICENSE_PUBLIC_KEY (кладётся в .env клиента):")
    print(f"  {public_b64}")


def _cmd_fingerprint() -> None:
    print(machine_fingerprint())


def _cmd_issue(args: argparse.Namespace) -> None:
    payload = LicensePayload(
        license_key=args.key,
        machine_fingerprint=machine_fingerprint() if args.bind else "",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=args.days),
    )
    token = issue_license(args.private, payload)
    print("LICENSE_KEY (кладётся в .env клиента):")
    print(f"  {token}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Утилита лицензий kwork_bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("keygen", help="сгенерировать пару ключей Ed25519")
    sub.add_parser("fingerprint", help="показать отпечаток текущей машины")

    issue = sub.add_parser("issue", help="выпустить подписанную лицензию")
    issue.add_argument("--private", required=True, help="приватный ключ издателя (base64url)")
    issue.add_argument("--key", required=True, help="идентификатор лицензии (например, CUST-001)")
    issue.add_argument("--days", type=int, default=365, help="срок действия в днях (по умолчанию 365)")
    issue.add_argument("--bind", action="store_true", help="привязать к текущей машине")

    args = parser.parse_args()
    if args.command == "keygen":
        _cmd_keygen()
    elif args.command == "fingerprint":
        _cmd_fingerprint()
    elif args.command == "issue":
        _cmd_issue(args)


if __name__ == "__main__":
    main()
