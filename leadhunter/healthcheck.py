#!/usr/bin/env python3
"""Проверка живости LeadHunter для Docker HEALTHCHECK и мониторинга.

Смотрит на свежесть файла-биения: процесс может быть «жив» с точки зрения
операционной системы, но при этом иметь вставший event loop — обычная
restart-политика такое не ловит, а это самый частый способ тихо умереть.

Коды возврата: 0 — здоров, 1 — завис или не запущен.
"""

from __future__ import annotations

import sys

from config import get_settings
from core.health import is_alive


def main() -> int:
    try:
        settings = get_settings()
        alive, reason = is_alive(settings.health_path, settings.health_interval)
    except Exception as exc:  # noqa: BLE001 —healthcheck не должен падать трейсбеком
        print(f"UNHEALTHY: проверка не выполнилась: {exc}")
        return 1

    if alive:
        print("OK")
        return 0
    print(f"UNHEALTHY: {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
