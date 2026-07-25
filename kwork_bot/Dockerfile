# kwork_bot — production-образ (Playwright/Chromium, non-root).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Зависимости + браузер (ставятся root'ом; браузер в общий путь, доступный всем).
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium

# Исходники и вспомогательные файлы.
COPY . .
RUN chmod +x docker-entrypoint.sh

# Непривилегированный пользователь + каталоги данных/логов на томах.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data /app/logs \
    && chown -R appuser:appuser /app /ms-playwright
USER appuser

# Healthcheck реально вызывает существующую команду (utils/healthcheck.py).
HEALTHCHECK --interval=60s --timeout=10s --start-period=40s --retries=3 \
    CMD ["python", "-m", "utils.healthcheck"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
