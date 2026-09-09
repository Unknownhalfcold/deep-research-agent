#!/usr/bin/env bash
#
# Install notion_worker.py as a systemd service on this machine.
#
# Run it from the project directory after the virtualenv and .env exist:
#
#     bash deploy/install_service.sh
#
# It detects the current user and project path itself, so there is nothing
# to edit before running.

set -euo pipefail

SERVICE_NAME="notion-agent"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_USER="$(id -un)"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"

echo "Project directory : ${PROJECT_DIR}"
echo "Run as user       : ${RUN_USER}"
echo "Python            : ${PYTHON_BIN}"
echo

# --- Preflight checks -------------------------------------------------------
# Fail loudly here rather than letting systemd restart-loop a broken service.

fail() {
    echo "ERROR: $1" >&2
    exit 1
}

if [ ! -x "${PYTHON_BIN}" ]; then
    fail "No virtualenv found at ${PROJECT_DIR}/.venv
Create it first, for example:
    uv venv --python 3.13 && uv sync"
fi

if [ ! -f "${PROJECT_DIR}/.env" ]; then
    fail "No .env found at ${PROJECT_DIR}/.env
.env is deliberately not in git, so it must be created on this machine.
Copy the template and fill in the real keys:
    cp .env.example .env && nano .env"
fi

if [ ! -f "${PROJECT_DIR}/notion_worker.py" ]; then
    fail "notion_worker.py not found in ${PROJECT_DIR}"
fi

echo "Checking that the worker can reach Notion, DeepSeek and Tavily..."

if ! "${PYTHON_BIN}" -c "
import sys
from config import DEEPSEEK_API_KEY, TAVILY_API_KEY, require_notion_api_key, require_notion_task_database_id
require_notion_api_key()
require_notion_task_database_id()
print('Configuration OK')
"; then
    fail "Configuration check failed. Fix .env before installing the service."
fi

echo

# --- Write the unit file ----------------------------------------------------

echo "Writing ${UNIT_PATH} (requires sudo)..."

sudo tee "${UNIT_PATH}" > /dev/null <<UNIT
[Unit]
Description=Notion Deep Research Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_BIN} ${PROJECT_DIR}/notion_worker.py
Restart=always
RestartSec=10

# Unbuffered so journalctl shows progress live instead of in blocks.
Environment=PYTHONUNBUFFERED=1
# The notes are Chinese; without this Python can fail on a non-UTF-8 locale.
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
UNIT

echo "Reloading systemd and starting the service..."

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

sleep 3

echo
echo "=============================================="
sudo systemctl status "${SERVICE_NAME}" --no-pager --lines=15 || true
echo "=============================================="
echo
echo "Done. Useful commands:"
echo
echo "  Live logs   : journalctl -u ${SERVICE_NAME} -f"
echo "  Restart     : sudo systemctl restart ${SERVICE_NAME}"
echo "  Stop        : sudo systemctl stop ${SERVICE_NAME}"
echo "  Disable     : sudo systemctl disable --now ${SERVICE_NAME}"
