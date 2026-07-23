# LeadHunter — образ с Playwright/Chromium и всеми зависимостями.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Сначала зависимости — чтобы слой кэшировался, пока requirements.txt не менялся.
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium

# Затем исходный код.
COPY . .

# Каталог для персистентных данных (сессия Telethon + SQLite) — монтируется томом.
RUN mkdir -p /app/data

CMD ["python", "main.py"]
