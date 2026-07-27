# LeadHunter — production-образ (парсеры работают по HTTP, браузер не нужен).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

WORKDIR /app

# Сначала зависимости — слой кэшируется, пока requirements.txt не менялся.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем исходный код.
COPY . .

# Работаем не от root: если процесс скомпрометируют, он не будет хозяином
# контейнера. Каталоги данных и логов создаём заранее и отдаём этому же
# пользователю — иначе том, смонтированный поверх, окажется недоступен на запись.
# UID фиксирован намеренно: каталоги data/ и logs/ монтируются с хоста, и их
# владелец должен совпадать с пользователем внутри контейнера. Иначе на чистом
# VPS Docker создаст их от root, а контейнер не сможет писать базу.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin leadhunter \
    && mkdir -p /app/data /app/logs \
    && chown -R leadhunter:leadhunter /app

USER leadhunter

ENV DATABASE_PATH=/app/data/leadhunter.db \
    RUNTIME_CONFIG_PATH=/app/data/settings.yaml \
    HEALTH_FILE=/app/data/health

# Живость проверяем по свежести heartbeat-файла: процесс может «жить» с
# вставшим event loop, и обычная restart-политика такое не ловит.
HEALTHCHECK --interval=60s --timeout=10s --start-period=45s --retries=3 \
    CMD ["python", "healthcheck.py"]

# exec-форма: PID 1 — сам python, поэтому SIGTERM от `docker stop` доходит до
# приложения и оно успевает закрыть базу и сетевые соединения.
CMD ["python", "main.py"]
