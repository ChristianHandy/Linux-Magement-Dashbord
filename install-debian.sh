#!/usr/bin/env bash
# =============================================================================
#  FleetPilot — Installer for Debian 13 (Trixie)
#  https://github.com/ChristianHandy/Linux-Magement-Dashbord
# =============================================================================
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
step()    { echo -e "\n${BOLD}━━━  $*  ━━━${RESET}"; }

# ── Configuration (edit before running) ──────────────────────────────────────
INSTALL_DIR="/opt/fleetpilot"
SERVICE_USER="fleetpilot"
APP_PORT="5000"
REPO_URL="https://github.com/ChristianHandy/Linux-Magement-Dashbord.git"
REPO_BRANCH="main"

# Automatically detect the primary server IP (first non-loopback address)
SERVER_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
SERVER_IP=${SERVER_IP:-$(hostname -I | awk '{print $1}')}
SERVER_IP=${SERVER_IP:-"0.0.0.0"}

# ── Preflight checks ─────────────────────────────────────────────────────────
step "Preflight checks"

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root. Use: sudo bash install-debian.sh"
fi

if ! grep -qi "trixie\|debian.*13\|debian.*bookworm" /etc/os-release 2>/dev/null; then
    warn "This script targets Debian 13 (Trixie). Your system may differ."
    warn "Detected: $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')"
    read -rp "Continue anyway? [y/N] " CONT
    [[ "${CONT,,}" == "y" ]] || exit 0
fi

success "Running on: $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')"

# ── System packages ───────────────────────────────────────────────────────────
step "Installing system packages"

apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    git \
    curl \
    openssh-client \
    smartmontools \
    e2fsprogs \
    xfsprogs \
    dosfstools \
    parted \
    util-linux \
    net-tools \
    iproute2 \
    sudo \
    ca-certificates \
    gnupg \
    lsb-release

success "System packages installed"

# ── Create service user ───────────────────────────────────────────────────────
step "Creating service user: ${SERVICE_USER}"

if id "${SERVICE_USER}" &>/dev/null; then
    warn "User '${SERVICE_USER}' already exists — skipping creation"
else
    useradd --system --shell /usr/sbin/nologin \
            --home-dir "${INSTALL_DIR}" \
            --create-home \
            "${SERVICE_USER}"
    success "User '${SERVICE_USER}' created"
fi

# Allow fleetpilot to run specific disk tools with sudo (no full root)
SUDOERS_FILE="/etc/sudoers.d/fleetpilot"
cat > "${SUDOERS_FILE}" << 'SUDOERS'
# FleetPilot — scoped sudo access for disk management tools only
fleetpilot ALL=(ALL) NOPASSWD: \
    /usr/sbin/smartctl, \
    /sbin/mkfs.ext4, \
    /sbin/mkfs.xfs, \
    /sbin/mkfs.vfat, \
    /sbin/wipefs, \
    /usr/bin/dd, \
    /sbin/badblocks, \
    /sbin/parted, \
    /bin/lsblk
SUDOERS
chmod 440 "${SUDOERS_FILE}"
success "Sudoers entry written to ${SUDOERS_FILE}"

# ── Clone / update repository ─────────────────────────────────────────────────
step "Cloning repository"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
    warn "Repository already exists at ${INSTALL_DIR} — pulling latest changes"
    git -C "${INSTALL_DIR}" fetch origin
    git -C "${INSTALL_DIR}" reset --hard "origin/${REPO_BRANCH}"
else
    git clone --branch "${REPO_BRANCH}" --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
fi

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
success "Repository ready at ${INSTALL_DIR}"

# ── Python virtual environment ────────────────────────────────────────────────
step "Setting up Python virtual environment"

VENV_DIR="${INSTALL_DIR}/venv"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip wheel --quiet
"${VENV_DIR}/bin/pip" install \
    flask \
    paramiko \
    apscheduler \
    python-dotenv \
    requests \
    werkzeug \
    gunicorn \
    --quiet

success "Python dependencies installed in ${VENV_DIR}"

# ── Generate secure credentials ───────────────────────────────────────────────
step "Generating secure credentials"

ENV_FILE="${INSTALL_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
    warn ".env already exists — skipping generation (remove it to regenerate)"
else
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

    echo ""
    echo -e "${YELLOW}┌─────────────────────────────────────────────────────┐${RESET}"
    echo -e "${YELLOW}│  Set your admin credentials below.                  │${RESET}"
    echo -e "${YELLOW}│  Press Enter to accept the suggested defaults.       │${RESET}"
    echo -e "${YELLOW}└─────────────────────────────────────────────────────┘${RESET}"
    echo ""

    read -rp "  Admin username  [admin]: " INPUT_USER
    ADMIN_USER="${INPUT_USER:-admin}"

    while true; do
        read -rsp "  Admin password  (min 12 chars): " INPUT_PASS
        echo ""
        if [[ ${#INPUT_PASS} -ge 12 ]]; then
            ADMIN_PASS="${INPUT_PASS}"
            break
        fi
        warn "Password must be at least 12 characters. Try again."
    done

    cat > "${ENV_FILE}" << EOF
# FleetPilot — Environment Configuration
# Generated by install-debian.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# !! Keep this file secret: chmod 600 .env !!

SECRET_KEY=${SECRET_KEY}
DASHBOARD_USERNAME=${ADMIN_USER}
DASHBOARD_PASSWORD=${ADMIN_PASS}
FLASK_DEBUG=false
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_HTTPONLY=true
SESSION_COOKIE_SAMESITE=Lax
EOF

    chmod 600 "${ENV_FILE}"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${ENV_FILE}"
    success ".env written and secured (chmod 600)"
fi

# ── systemd service ───────────────────────────────────────────────────────────
step "Installing systemd service"

cat > /etc/systemd/system/fleetpilot.service << EOF
[Unit]
Description=FleetPilot — Linux Fleet Management Dashboard
Documentation=https://github.com/ChristianHandy/Linux-Magement-Dashbord
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/gunicorn \\
    --bind ${SERVER_IP}:${APP_PORT} \\
    --workers 2 \\
    --timeout 120 \\
    --access-logfile /var/log/fleetpilot/access.log \\
    --error-logfile /var/log/fleetpilot/error.log \\
    app:app
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=fleetpilot

# Hardening
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${INSTALL_DIR} /var/log/fleetpilot

[Install]
WantedBy=multi-user.target
EOF

mkdir -p /var/log/fleetpilot
chown "${SERVICE_USER}:${SERVICE_USER}" /var/log/fleetpilot

systemctl daemon-reload
systemctl enable fleetpilot.service
success "systemd service installed and enabled"

# ── Firewall (ufw) ────────────────────────────────────────────────────────────
step "Configuring firewall (ufw)"

if command -v ufw &>/dev/null; then
    # Ensure SSH is always allowed before enabling ufw
    ufw allow OpenSSH --force > /dev/null 2>&1 || ufw allow 22/tcp --force > /dev/null 2>&1
    ufw allow "${APP_PORT}/tcp" comment "FleetPilot web interface" > /dev/null
    # Enable ufw non-interactively if not already active
    if ! ufw status | grep -q "Status: active"; then
        ufw --force enable > /dev/null
        success "ufw enabled and port ${APP_PORT} opened"
    else
        success "ufw already active — port ${APP_PORT} rule added"
    fi
    info "To restrict access to a specific IP only, run:"
    info "  ufw delete allow ${APP_PORT}/tcp"
    info "  ufw allow from <your-ip> to any port ${APP_PORT}"
else
    warn "ufw not found — skipping firewall configuration"
    warn "Make sure port ${APP_PORT} is reachable on ${SERVER_IP}"
fi

# ── SSH key for FleetPilot user ───────────────────────────────────────────────
step "Generating SSH key for managed host connections"

SSH_DIR="${INSTALL_DIR}/.ssh"
if [[ ! -f "${SSH_DIR}/id_ed25519" ]]; then
    mkdir -p "${SSH_DIR}"
    ssh-keygen -t ed25519 -f "${SSH_DIR}/id_ed25519" -N "" -C "fleetpilot@$(hostname)" -q
    chmod 700 "${SSH_DIR}"
    chmod 600 "${SSH_DIR}/id_ed25519"
    chmod 644 "${SSH_DIR}/id_ed25519.pub"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${SSH_DIR}"
    success "SSH key generated: ${SSH_DIR}/id_ed25519.pub"
else
    warn "SSH key already exists — skipping"
fi

# ── Start service ─────────────────────────────────────────────────────────────
step "Starting FleetPilot"

systemctl start fleetpilot.service
sleep 3

if systemctl is-active --quiet fleetpilot.service; then
    success "FleetPilot is running"
else
    error "Service failed to start. Check logs: journalctl -u fleetpilot -n 50"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
LOCAL_IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║         FleetPilot installed successfully!           ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}Listening on:${RESET}    http://${SERVER_IP}:${APP_PORT}"
echo -e "  ${BOLD}Local access:${RESET}    http://127.0.0.1:${APP_PORT}"
echo -e "  ${BOLD}Install dir:${RESET}     ${INSTALL_DIR}"
echo -e "  ${BOLD}Service user:${RESET}    ${SERVICE_USER}"
echo -e "  ${BOLD}Logs:${RESET}            journalctl -u fleetpilot -f"
echo ""
echo -e "  ${YELLOW}${BOLD}Next steps (recommended):${RESET}"
echo -e "  1. Restrict dashboard access to your IP only:"
echo -e "     ufw delete allow ${APP_PORT}/tcp"
echo -e "     ufw allow from <your-ip> to any port ${APP_PORT}"
echo -e "  2. Set up a reverse proxy with TLS (Caddy or Nginx)"
echo -e "     so the dashboard is accessible over HTTPS only."
echo -e "  3. Copy the SSH public key to your managed hosts:"
echo -e "     cat ${SSH_DIR}/id_ed25519.pub"
echo -e "  4. Review ${ENV_FILE} and set SESSION_COOKIE_SECURE=true"
echo -e "     once HTTPS is configured."
echo ""
echo -e "  ${BOLD}Service control:${RESET}"
echo -e "  systemctl start|stop|restart|status fleetpilot"
echo ""
