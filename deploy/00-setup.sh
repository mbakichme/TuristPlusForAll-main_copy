#!/usr/bin/env bash
# ============================================================================
# TuristPlus — JEDNOKRATNA setup skripta za produkcijski server (Ubuntu/Debian)
#
# Upotreba:  sudo bash 00-setup.sh
# Idempotentna — može se pokrenuti više puta (nastavlja tamo gde je stala).
#
# Šta radi:
#   1) instalira git/uv/bun ako nedostaju
#   2) kreira servisnog korisnika "turistplus"
#   3) klonira repo u /opt/TuristPlus
#   4) instalira zavisnosti i gradi frontend (dist/)
#   5) kreira /etc/turistplus.env (JWT_SECRET_KEY generiše automatski;
#      EXTERNAL_NEON_DATABASE_URL MORAŠ upisati ručno!)
#   6) instalira i startuje systemd servis (port 8000)
#
# POSLE SETUP-A: popuni EXTERNAL_NEON_DATABASE_URL u /etc/turistplus.env
# pa pokreni skriptu ponovo (ako je bila prekinuta) ili: systemctl restart turistplus
# ============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/TuristPlus}"
REPO_URL="${REPO_URL:-https://github.com/ignjatovicmilisav/TuristPlus.git}"
SERVICE_USER="${SERVICE_USER:-turistplus}"
APP_PORT="${APP_PORT:-8000}"
ENV_FILE="/etc/turistplus.env"

[ "$(id -u)" -eq 0 ] || { echo "Pokreni kao root: sudo bash $0"; exit 1; }

echo "── [1/6] Sistemski paketi ─────────────────────────────────────────────"
command -v git >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq git curl ca-certificates openssl; }

echo "── [2/6] Servisni korisnik: $SERVICE_USER ─────────────────────────────"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd -r -m -U -d "/home/$SERVICE_USER" -s /usr/sbin/nologin "$SERVICE_USER"
fi

echo "── [3/6] uv + bun (sistemski, /usr/local/bin) ─────────────────────────"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    cp -f "$HOME/.local/bin/uv" /usr/local/bin/uv
    cp -f "$HOME/.local/bin/uvx" /usr/local/bin/uvx 2>/dev/null || true
fi
if ! command -v bun >/dev/null 2>&1; then
    curl -fsSL https://bun.sh/install | bash
    cp -f "$HOME/.bun/bin/bun"  /usr/local/bin/bun
    cp -f "$HOME/.bun/bin/bunx" /usr/local/bin/bunx
fi

echo "── [4/6] Repo: $APP_DIR ───────────────────────────────────────────────"
if [ ! -d "$APP_DIR/.git" ]; then
    git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

run_as_app() { sudo -u "$SERVICE_USER" -H bash -c "cd '$APP_DIR' && $1"; }

echo "── [5/6] Zavisnosti + build frontend-a ────────────────────────────────"
run_as_app "uv sync --frozen"
run_as_app "bun install --frozen-lockfile"
run_as_app "bun run build"          # tsc -b && vite build → dist/
[ -f "$APP_DIR/dist/index.html" ] || { echo "GREŠKA: dist/index.html ne postoji — build nije uspeo"; exit 1; }

echo "── [6/6] Secrets + systemd servis ─────────────────────────────────────"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<EOF
# TuristPlus production secrets — NIKAD ne commit-ovati u git!
# OBAVEZNO upiši konekcioni string Neon baze ispod (isti kao u Workshopu):
EXTERNAL_NEON_DATABASE_URL=
# Automatski generisan JWT ključ (potpisivanje tokena):
JWT_SECRET_KEY=$(openssl rand -hex 32)
EOF
    chmod 600 "$ENV_FILE"
fi

cp "$(dirname "$0")/turistplus.service" /etc/systemd/system/turistplus.service
systemctl daemon-reload

# Upozorenje ako DB URL nije upisan — servis bi bio u crash-loop
DB_URL_LINE=$(grep -E '^EXTERNAL_NEON_DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d'=' -f2-)
if [ -z "$DB_URL_LINE" ]; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║  STOP: upiši EXTERNAL_NEON_DATABASE_URL u $ENV_FILE"
    echo "║  pa pokreni:  systemctl restart turistplus"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    exit 0
fi

systemctl enable turistplus >/dev/null 2>&1 || true
systemctl restart turistplus
sleep 2
systemctl --no-pager --lines=5 status turistplus || true

echo ""
echo "GOTOVO. Aplikacija: http://127.0.0.1:$APP_PORT (static + /api zajedno)"
echo "Za domen + HTTPS vidi deploy/nginx.conf.example"
echo "Kasnije nove verzije:  sudo bash $(dirname "$0")/01-update.sh"
