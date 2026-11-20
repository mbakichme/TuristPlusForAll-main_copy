#!/usr/bin/env bash
# ============================================================================
# TuristPlus — AŽURIRANJE produkcije na noviju verziju
#
# Upotreba:  sudo bash 01-update.sh
#
# Radi: git pull → Python/JS zavisnosti → build frontend-a → restart servisa.
# Pretpostavlja da je 00-setup.sh već pokrenut jednom.
# ============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/TuristPlus}"
SERVICE_USER="${SERVICE_USER:-turistplus}"

[ "$(id -u)" -eq 0 ] || { echo "Pokreni kao root: sudo bash $0"; exit 1; }
[ -d "$APP_DIR/.git" ] || { echo "GREŠKA: $APP_DIR nije repo — prvo pokreni 00-setup.sh"; exit 1; }

run_as_app() { sudo -u "$SERVICE_USER" -H bash -c "cd '$APP_DIR' && $1"; }

echo "── [1/4] git pull ─────────────────────────────────────────────────────"
run_as_app "git pull --ff-only"

echo "── [2/4] Zavisnosti ───────────────────────────────────────────────────"
run_as_app "uv sync --frozen"
run_as_app "bun install --frozen-lockfile"

echo "── [3/4] Build frontend-a (tsc -b && vite build) ──────────────────────"
run_as_app "bun run build"
[ -f "$APP_DIR/dist/index.html" ] || { echo "GREŠKA: build nije uspeo — dist/index.html ne postoji, servis NE restartujem"; exit 1; }

echo "── [4/4] Restart servisa ──────────────────────────────────────────────"
systemctl restart turistplus
sleep 2
systemctl --no-pager --lines=5 status turistplus || true

echo ""
echo "NOVA VERZIJA JE LIVE."
