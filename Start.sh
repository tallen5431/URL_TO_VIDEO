#!/usr/bin/env bash
# Launcher for HTTP Server Manager (or run directly: ./Start.sh).
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

command -v ffmpeg >/dev/null || echo "[WARN] ffmpeg not found — install it (sudo apt install ffmpeg) or most conversions will fail" >&2

VENV_PY="$APP_DIR/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  SYS_PY="$(command -v python3 || true)"
  [[ -n "$SYS_PY" ]] || { echo "[ERROR] python3 not found"; exit 1; }
  echo "[SETUP] Creating virtualenv at .venv..."
  "$SYS_PY" -m venv "$APP_DIR/.venv"
fi

# Install requirements on first run and whenever requirements.txt changed.
REQ_STAMP="$APP_DIR/.venv/.requirements-installed"
if [[ ! -f "$REQ_STAMP" || requirements.txt -nt "$REQ_STAMP" ]]; then
  echo "[SETUP] Installing requirements..."
  "$VENV_PY" -m pip install --upgrade pip >/dev/null
  "$VENV_PY" -m pip install -r requirements.txt
  touch "$REQ_STAMP"
fi

# Sites change often and break older yt-dlp releases, so refresh it at most
# once a day. Failure (e.g. offline) is not fatal — the installed copy is used.
YTDLP_STAMP="$APP_DIR/.venv/.yt-dlp-updated"
if [[ -z "$(find "$YTDLP_STAMP" -mmin -1440 2>/dev/null)" ]]; then
  echo "[SETUP] Updating yt-dlp..."
  if "$VENV_PY" -m pip install --upgrade yt-dlp >/dev/null; then touch "$YTDLP_STAMP"
  else echo "[WARN] yt-dlp update failed; using installed version" >&2; fi
fi

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8090}"

echo "[RUN] Launching web app (HOST=$HOST PORT=$PORT)"
exec "$VENV_PY" -m web
