#!/usr/bin/env bash
# =============================================================================
#  FleetPilot — Update Script
#  Pulls the latest code, backs up your data, and restarts the service.
#  Run as root: sudo bash update.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
step()    { echo -e "\n${BOLD}━━━  $*  ━━━${RESET}"; }

# ── Configuration ─────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/fleetpilot"
SERVICE_NAME="fleetpilot"
BRANCH="feat/fleetpilot-full-redesign"   # change to "main" once PR is merged
BACKUP_DIR="/opt/fleetpilot-backups"
VENV_DIR="${INSTALL_DIR}/venv"

# Files that contain user data — never overwritten by git pull
DATA_FILES=("hosts.json" "users.db" "history.json" ".env"
            "email_settings.json" "update_settings.json" "disktool.db")

# ── Root check ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Run as root: sudo bash update.sh"

# ── Locate installation ───────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/app.py" ]]; then
    INSTALL_DIR="${SCRIPT_DIR}"
elif [[ ! -f "${INSTALL_DIR}/app.py" ]]; then
    read -rp "FleetPilot install directory [/opt/fleetpilot]: " INPUT_DIR
    INSTALL_DIR="${INPUT_DIR:-/opt/fleetpilot}"
    [[ -f "${INSTALL_DIR}/app.py" ]] || error "app.py not found in ${INSTALL_DIR}"
fi

cd "${INSTALL_DIR}"

# ── Show current version ──────────────────────────────────────────────────────
CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║            FleetPilot — Update Script                ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
info "Install dir    : ${INSTALL_DIR}"
info "Current commit : ${CURRENT_COMMIT} (${CURRENT_BRANCH})"
info "Target branch  : ${BRANCH}"
echo ""

# ── Confirm ───────────────────────────────────────────────────────────────────
read -rp "  Proceed with update? [Y/n] " CONFIRM
[[ "${CONFIRM,,}" == "n" ]] && { info "Update cancelled."; exit 0; }

# ── Step 1: Backup user data ──────────────────────────────────────────────────
step "Backing up user data"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_PATH="${BACKUP_DIR}/${TIMESTAMP}"
mkdir -p "${BACKUP_PATH}"

for FILE in "${DATA_FILES[@]}"; do
    if [[ -f "${INSTALL_DIR}/${FILE}" ]]; then
        cp "${INSTALL_DIR}/${FILE}" "${BACKUP_PATH}/${FILE}"
        success "Backed up: ${FILE}"
    fi
done

# Keep only the 10 most recent backups
ls -dt "${BACKUP_DIR}"/*/  2>/dev/null | tail -n +11 | xargs rm -rf 2>/dev/null || true
info "Backups stored in: ${BACKUP_PATH}"

# ── Step 2: Stop service ──────────────────────────────────────────────────────
step "Stopping FleetPilot service"

SERVICE_WAS_RUNNING=false
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    SERVICE_WAS_RUNNING=true
    systemctl stop "${SERVICE_NAME}"
    success "Service stopped"
else
    info "Service was not running"
fi

# ── Step 3: Pull latest code ──────────────────────────────────────────────────
step "Pulling latest code from GitHub"

# Ensure we're on the right branch and it's up to date
git fetch origin 2>&1 | sed 's/^/  /'

# Stash any local modifications to tracked files (keeps data files safe)
if ! git diff --quiet HEAD 2>/dev/null; then
    warn "Local modifications detected — stashing them"
    git stash push -m "pre-update stash ${TIMESTAMP}" 2>&1 | sed 's/^/  /'
fi

# Switch to target branch if needed
if [[ "${CURRENT_BRANCH}" != "${BRANCH}" ]]; then
    info "Switching from '${CURRENT_BRANCH}' to '${BRANCH}'"
    git checkout "${BRANCH}" 2>&1 | sed 's/^/  /'
fi

git reset --hard "origin/${BRANCH}" 2>&1 | sed 's/^/  /'
NEW_COMMIT=$(git rev-parse --short HEAD)
success "Updated to commit: ${NEW_COMMIT}"

# ── Step 4: Restore user data ─────────────────────────────────────────────────
step "Restoring user data"

for FILE in "${DATA_FILES[@]}"; do
    if [[ -f "${BACKUP_PATH}/${FILE}" ]]; then
        cp "${BACKUP_PATH}/${FILE}" "${INSTALL_DIR}/${FILE}"
        success "Restored: ${FILE}"
    fi
done

# ── Step 5: Update Python dependencies ───────────────────────────────────────
step "Updating Python dependencies"

# Find the right pip
if [[ -x "${VENV_DIR}/bin/pip" ]]; then
    PIP="${VENV_DIR}/bin/pip"
elif command -v pip3 &>/dev/null; then
    PIP="pip3"
else
    PIP="pip"
fi

"${PIP}" install -q -r "${INSTALL_DIR}/requirements.txt" 2>&1 | tail -5
success "Dependencies up to date"

# ── Step 6: Fix permissions ───────────────────────────────────────────────────
step "Fixing file permissions"

SERVICE_USER="fleetpilot"
if id "${SERVICE_USER}" &>/dev/null; then
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
    # Protect sensitive files
    [[ -f "${INSTALL_DIR}/.env" ]]       && chmod 600 "${INSTALL_DIR}/.env"
    [[ -f "${INSTALL_DIR}/users.db" ]]   && chmod 600 "${INSTALL_DIR}/users.db"
    [[ -f "${INSTALL_DIR}/disktool.db" ]] && chmod 600 "${INSTALL_DIR}/disktool.db"
    success "Permissions set for user '${SERVICE_USER}'"
else
    warn "Service user '${SERVICE_USER}' not found — skipping chown"
fi

# ── Step 7: Start service ─────────────────────────────────────────────────────
step "Starting FleetPilot service"

if [[ "${SERVICE_WAS_RUNNING}" == "true" ]]; then
    systemctl start "${SERVICE_NAME}"
    sleep 3
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        success "Service started successfully"
    else
        error "Service failed to start. Check: journalctl -u ${SERVICE_NAME} -n 30"
    fi
else
    info "Service was not running before update — not starting automatically"
    info "Start manually with: systemctl start ${SERVICE_NAME}"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║              FleetPilot updated successfully!        ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}Previous version :${RESET} ${CURRENT_COMMIT}"
echo -e "  ${BOLD}New version      :${RESET} ${NEW_COMMIT}"
echo -e "  ${BOLD}Backup location  :${RESET} ${BACKUP_PATH}"
echo ""
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    SERVER_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
    SERVER_IP=${SERVER_IP:-$(hostname -I | awk '{print $1}')}
    APP_PORT=$(grep -oP '(?<=--bind\s)\S+' /etc/systemd/system/fleetpilot.service 2>/dev/null | cut -d: -f2 || echo "5000")
    echo -e "  ${BOLD}Dashboard        :${RESET} http://${SERVER_IP}:${APP_PORT}"
fi
echo ""
echo -e "  ${YELLOW}${BOLD}If something broke:${RESET}"
echo -e "  sudo bash ${INSTALL_DIR}/update.sh --rollback ${BACKUP_PATH}"
echo ""
