# syntax=docker/dockerfile:1

# ---- Stage 1: build the frontend -------------------------------------
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: the application ------------------------------------------
FROM python:3.12-slim AS app
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./

RUN pip install --no-cache-dir -e .

# Built SPA is served by app/main.py's static-file mount (architecture.md
# §6 — the "app" container serves both the API and the UI).
COPY --from=frontend-build /frontend/dist ./app/static

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# Runs the (currently: 0001 baseline + 0002 core data model) migration
# chain on every boot, per architecture.md's "normal upgrades are
# docker compose pull && up -d, no manual Postfix/DB steps" requirement.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
