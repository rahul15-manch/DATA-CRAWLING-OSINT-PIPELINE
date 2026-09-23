#!/usr/bin/env bash
# =============================================================================
# Pillar 1 Production EC2 Deployment Script (Ubuntu 22.04 / 24.04 LTS)
# Run from repository root: bash deploy.sh
# =============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="$(whoami)"

echo "======================================================================"
echo " Starting Pillar 1 Deployment on Ubuntu Linux"
echo " App Directory: ${APP_DIR}"
echo " App User     : ${APP_USER}"
echo "======================================================================"

# 1. System packages installation
echo "[1/6] Installing Linux system dependencies..."
sudo apt-get update -y
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libssl-dev \
    libffi-dev \
    git \
    curl \
    nginx

# 2. Virtual Environment Setup
echo "[2/6] Setting up Python virtual environment (.venv)..."
if [ ! -d "${APP_DIR}/.venv" ]; then
    python3 -m venv "${APP_DIR}/.venv"
fi

source "${APP_DIR}/.venv/bin/activate"

# 3. Python dependencies
echo "[3/6] Installing Python packages from requirements.txt..."
pip install --upgrade pip setuptools wheel
pip install -r "${APP_DIR}/requirements.txt"

# 4. Playwright Chromium & System Dependencies
echo "[4/6] Installing Playwright Chromium and system libraries..."
python -m playwright install --with-deps chromium

# 5. Environment configuration & runtime directories
echo "[5/6] Verifying environment & runtime directories..."
if [ ! -f "${APP_DIR}/.env" ]; then
    echo "  -> .env not found. Copying from .env.example..."
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    echo "  [ACTION REQUIRED] Please edit ${APP_DIR}/.env to configure API keys / proxies if needed."
fi

mkdir -p "${APP_DIR}/output/raw" "${APP_DIR}/output/final" "${APP_DIR}/output/clean"
mkdir -p "${APP_DIR}/logs" "${APP_DIR}/data" "${APP_DIR}/debug_html" "${APP_DIR}/cookies"

# 6. Service configuration (optional prompt)
echo "[6/6] Verifying systemd service..."
if [ -f "${APP_DIR}/pillar1.service" ]; then
    # Generate service file with actual path and user
    sed -e "s|/home/ubuntu/pillar1|${APP_DIR}|g" \
        -e "s|User=ubuntu|User=${APP_USER}|g" \
        -e "s|Group=ubuntu|Group=${APP_USER}|g" \
        "${APP_DIR}/pillar1.service" | sudo tee /etc/systemd/system/pillar1.service > /dev/null

    sudo systemctl daemon-reload
    echo "  -> Systemd service installed to /etc/systemd/system/pillar1.service"
    echo "  -> Start with: sudo systemctl start pillar1"
    echo "  -> Enable on boot with: sudo systemctl enable pillar1"
    echo "  -> View status: sudo systemctl status pillar1"
fi

echo "======================================================================"
echo " Pillar 1 Deployment Preparation Complete!"
echo " Test with: .venv/bin/pytest tests/ -q"
echo " Run API with: .venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000"
echo "======================================================================"
