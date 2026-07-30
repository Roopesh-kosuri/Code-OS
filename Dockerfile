# ── Stage 1: Build Frontend Assets ─────────────────────────────────────────────
FROM node:20-bookworm-slim AS frontend-builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ── Stage 2: Production Backend & Runtime ─────────────────────────────────────
FROM python:3.11-slim-bookworm AS runner

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    CODE_OS_DATA_DIR=/workspace-data/.code-os \
    CODE_OS_HOME=/workspace-data/.code-os

# Create Python virtual environment
RUN python3 -m venv /opt/venv

WORKDIR /app

# Copy & install Python backend dependencies into virtual environment
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source code & built frontend static assets
COPY backend/app ./backend/app
COPY --from=frontend-builder /app/dist ./dist

# Create workspace and data storage mount points
RUN mkdir -p /workspace-data /project-workspace
VOLUME ["/workspace-data", "/project-workspace"]

EXPOSE 8000

# Run production Uvicorn server
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
