# Build context is the backend/ directory (see docker-compose.yml) so the shared engine can be copied in.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY packages/engine /tmp/engine
RUN pip install /tmp/engine && rm -rf /tmp/engine

COPY services/rating/requirements.txt .
RUN pip install -r requirements.txt

COPY services/rating/app ./app
COPY services/rating/alembic.ini ./alembic.ini
COPY services/rating/migrations ./migrations

RUN useradd --system --uid 10001 app && chown -R app /srv
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
