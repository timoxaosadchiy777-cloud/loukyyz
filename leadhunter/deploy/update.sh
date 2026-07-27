#!/usr/bin/env bash
# Обновление LeadHunter до свежей версии — с бэкапом базы и откатом при сбое.
#
#   sudo bash /opt/leadhunter/deploy/update.sh

set -euo pipefail

APP_DIR="/opt/leadhunter"
BACKUP_DIR="$APP_DIR/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Запускать нужно от root"
cd "$APP_DIR" || die "Нет каталога $APP_DIR"

log "Бэкап базы"
mkdir -p "$BACKUP_DIR"
if [[ -f data/leadhunter.db ]]; then
    # sqlite3 умеет консистентную копию на живой базе; если его нет — cp.
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 data/leadhunter.db ".backup '$BACKUP_DIR/leadhunter-$STAMP.db'"
    else
        cp data/leadhunter.db "$BACKUP_DIR/leadhunter-$STAMP.db"
    fi
    echo "Бэкап: $BACKUP_DIR/leadhunter-$STAMP.db"
fi
# Держим последние 10 копий, остальное чистим — иначе бэкапы съедят диск.
ls -1t "$BACKUP_DIR"/leadhunter-*.db 2>/dev/null | tail -n +11 | xargs -r rm --

log "Забираю обновления"
PREV="$(git rev-parse HEAD)"
git pull --ff-only || die "git pull не прошёл — разберитесь вручную"

rollback() {
    log "Откатываюсь на $PREV"
    git reset --hard "$PREV"
    if command -v docker >/dev/null 2>&1 && [[ -f docker-compose.yml ]]; then
        docker compose up -d --build
    else
        systemctl restart leadhunter
    fi
    die "Обновление откачено. Смотрите логи."
}

if command -v docker >/dev/null 2>&1 && docker compose ps >/dev/null 2>&1; then
    log "Пересобираю контейнер"
    docker compose up -d --build || rollback
    sleep 20
    docker compose ps | grep -q "healthy\|running" || rollback
else
    log "Обновляю зависимости и перезапускаю сервис"
    sudo -u leadhunter .venv/bin/pip install -q -r requirements.txt || rollback
    systemctl restart leadhunter || rollback
    sleep 10
    systemctl is-active --quiet leadhunter || rollback
fi

log "Обновление завершено: $(git rev-parse --short HEAD)"
