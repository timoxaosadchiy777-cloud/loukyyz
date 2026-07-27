#!/usr/bin/env bash
# Установка LeadHunter на чистый Ubuntu 24.04 LTS.
#
#   sudo bash deploy/install.sh            # Docker (рекомендуется)
#   sudo bash deploy/install.sh systemd    # без Docker, через systemd
#
# Скрипт идемпотентный: повторный запуск ничего не ломает.

set -euo pipefail

MODE="${1:-docker}"
APP_DIR="/opt/leadhunter"
APP_USER="leadhunter"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Запускать нужно от root: sudo bash deploy/install.sh"

log "Обновляю пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git

if ! id -u "$APP_USER" >/dev/null 2>&1; then
    log "Создаю системного пользователя $APP_USER"
    useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

log "Готовлю каталоги в $APP_DIR"
mkdir -p "$APP_DIR"/{data,logs}
# Исходники кладём рядом со скриптом, если запуск идёт не из /opt.
if [[ "$(cd "$(dirname "$0")/.." && pwd)" != "$APP_DIR" ]]; then
    cp -r "$(cd "$(dirname "$0")/.." && pwd)/." "$APP_DIR/"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

if [[ ! -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    warn "Создан $APP_DIR/.env — впишите BOT_TOKEN и OWNER_ID перед запуском."
fi

if [[ "$MODE" == "docker" ]]; then
    if ! command -v docker >/dev/null 2>&1; then
        log "Ставлю Docker"
        curl -fsSL https://get.docker.com | sh
    fi
    systemctl enable --now docker

    # Каталоги данных монтируются в контейнер, который работает не от root.
    # Без этого chown первый же запуск упадёт на «read-only database».
    log "Выставляю владельца каталогов данных (uid контейнера)"
    chown -R 10001:10001 "$APP_DIR/data" "$APP_DIR/logs"

    log "Собираю и запускаю контейнер"
    cd "$APP_DIR"
    docker compose up -d --build

    log "Готово. Проверка: docker compose ps && docker compose logs -f"
else
    log "Ставлю Python и виртуальное окружение"
    apt-get install -y -qq python3 python3-venv python3-pip
    sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
    sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
    sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

    log "Ставлю systemd-юнит"
    cp "$APP_DIR/deploy/leadhunter.service" /etc/systemd/system/
    cp "$APP_DIR/deploy/leadhunter.logrotate" /etc/logrotate.d/leadhunter
    systemctl daemon-reload
    systemctl enable --now leadhunter

    log "Готово. Проверка: systemctl status leadhunter && journalctl -u leadhunter -f"
fi
