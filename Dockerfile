FROM node:22-bookworm-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim AS runtime

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates tmux \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    CODEX_MONITOR_DATA_DIR=/data \
    HOME=/tmp \
    TMUX_TMPDIR=/tmp \
    PORT=8765

COPY backend/requirements.txt backend/requirements.txt
RUN python -m pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY --from=frontend /app/frontend/dist frontend/dist

RUN mkdir -p /data && chmod 0777 /data

EXPOSE 8765
CMD ["sh", "-c", "cd /app/backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
