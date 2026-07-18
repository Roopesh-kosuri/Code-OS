# Base image containing Node.js 20
FROM node:20-bookworm-slim

# Install Python 3, pip, git, and other utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set up environment variables
ENV PYTHONUNBUFFERED=1
ENV CODE_OS_DATA_DIR=/workspace-data/.code-os
ENV CODE_OS_HOME=/workspace-data/.code-os

WORKDIR /app

# Copy dependency manifests
COPY package.json package-lock.json ./
COPY backend/requirements.txt ./backend/

# Install Node and Python dependencies
RUN npm install
RUN python3 -m pip install --upgrade pip --break-system-packages
RUN python3 -m pip install -r backend/requirements.txt --break-system-packages

# Copy project source code
COPY . .

# Compile TypeScript and Vite production assets
RUN npm run build

# Expose ports: 5173 for Vite (frontend) and 8000 for FastAPI (backend)
EXPOSE 5173
EXPOSE 8000

# Create workspace and configuration storage mount points
RUN mkdir -p /workspace-data /project-workspace
VOLUME ["/workspace-data", "/project-workspace"]

# Start both services concurrently (binding to 0.0.0.0 inside container)
CMD ["npx", "concurrently", "-k", "python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000", "npm run dev:renderer -- --host 0.0.0.0"]
