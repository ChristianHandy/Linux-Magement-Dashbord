#!/usr/bin/env bash
# =============================================================================
#  FleetPilot — Password Reset Utility
#  Run as root: sudo bash reset-password.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

INSTALL_DIR="/opt/fleetpilot"
ENV_FILE="${INSTALL_DIR}/.env"
DB_FILE="${INSTALL_DIR}/users.db"
VENV_PYTHON="${INSTALL_DIR}/venv/bin/python3"

# ── Root check ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root. Use: sudo bash reset-password.sh"
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║         FleetPilot — Password Reset Utility          ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""

# ── Detect installation ───────────────────────────────────────────────────────
if [[ ! -d "${INSTALL_DIR}" ]]; then
    error "FleetPilot installation not found at ${INSTALL_DIR}"
fi

# ── Choose reset method ───────────────────────────────────────────────────────
echo -e "  ${BOLD}Choose reset method:${RESET}"
echo -e "  ${CYAN}1)${RESET} Reset via .env file  (affects the built-in admin account)"
echo -e "  ${CYAN}2)${RESET} Reset via database   (affects any user account)"
echo -e "  ${CYAN}3)${RESET} List all users       (show usernames in database)"
echo ""
read -rp "  Enter choice [1/2/3]: " CHOICE

case "${CHOICE}" in

# ── Method 1: .env reset ──────────────────────────────────────────────────────
1)
    echo ""
    info "Resetting admin credentials in ${ENV_FILE}"

    if [[ ! -f "${ENV_FILE}" ]]; then
        error ".env file not found at ${ENV_FILE}. Was FleetPilot installed with install-debian.sh?"
    fi

    read -rp "  New admin username [leave blank to keep current]: " NEW_USER

    while true; do
        read -rsp "  New admin password (min 12 chars): " NEW_PASS
        echo ""
        if [[ ${#NEW_PASS} -ge 12 ]]; then
            read -rsp "  Confirm new password: " CONFIRM_PASS
            echo ""
            if [[ "${NEW_PASS}" == "${CONFIRM_PASS}" ]]; then
                break
            else
                warn "Passwords do not match. Try again."
            fi
        else
            warn "Password must be at least 12 characters. Try again."
        fi
    done

    # Update username if provided
    if [[ -n "${NEW_USER}" ]]; then
        if grep -q "^DASHBOARD_USERNAME=" "${ENV_FILE}"; then
            sed -i "s|^DASHBOARD_USERNAME=.*|DASHBOARD_USERNAME=${NEW_USER}|" "${ENV_FILE}"
        else
            echo "DASHBOARD_USERNAME=${NEW_USER}" >> "${ENV_FILE}"
        fi
        success "Username updated to: ${NEW_USER}"
    fi

    # Update password
    if grep -q "^DASHBOARD_PASSWORD=" "${ENV_FILE}"; then
        sed -i "s|^DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=${NEW_PASS}|" "${ENV_FILE}"
    else
        echo "DASHBOARD_PASSWORD=${NEW_PASS}" >> "${ENV_FILE}"
    fi
    success "Password updated in ${ENV_FILE}"

    # Also update the database if it exists (keeps both in sync)
    if [[ -f "${DB_FILE}" ]] && [[ -x "${VENV_PYTHON}" ]]; then
        EFFECTIVE_USER="${NEW_USER}"
        if [[ -z "${EFFECTIVE_USER}" ]]; then
            EFFECTIVE_USER=$(grep "^DASHBOARD_USERNAME=" "${ENV_FILE}" | cut -d= -f2)
        fi
        EFFECTIVE_USER="${EFFECTIVE_USER:-admin}"

        "${VENV_PYTHON}" - <<PYEOF
import sys
sys.path.insert(0, '${INSTALL_DIR}')
import os, sqlite3
os.chdir('${INSTALL_DIR}')
from werkzeug.security import generate_password_hash

db = sqlite3.connect('${DB_FILE}')
db.row_factory = sqlite3.Row

# Update by username
cur = db.execute("SELECT id FROM users WHERE username = ?", ('${EFFECTIVE_USER}',))
row = cur.fetchone()
if row:
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (generate_password_hash('${NEW_PASS}'), row['id']))
    db.commit()
    print(f"  Database record for '{EFFECTIVE_USER}' updated.")
else:
    print(f"  User '{EFFECTIVE_USER}' not found in database — only .env was updated.")
db.close()
PYEOF
    fi
    ;;

# ── Method 2: Database reset ──────────────────────────────────────────────────
2)
    echo ""

    if [[ ! -f "${DB_FILE}" ]]; then
        error "Database not found at ${DB_FILE}"
    fi

    if [[ ! -x "${VENV_PYTHON}" ]]; then
        error "Python venv not found at ${VENV_PYTHON}. Is FleetPilot installed?"
    fi

    # List users first
    info "Users in database:"
    "${VENV_PYTHON}" - <<PYEOF
import sqlite3
db = sqlite3.connect('${DB_FILE}')
db.row_factory = sqlite3.Row
rows = db.execute("SELECT id, username, active FROM users ORDER BY id").fetchall()
for r in rows:
    status = "active" if r['active'] else "inactive"
    print(f"    [{r['id']}] {r['username']}  ({status})")
db.close()
PYEOF

    echo ""
    read -rp "  Enter the username to reset: " TARGET_USER

    if [[ -z "${TARGET_USER}" ]]; then
        error "No username entered."
    fi

    while true; do
        read -rsp "  New password for '${TARGET_USER}' (min 12 chars): " NEW_PASS
        echo ""
        if [[ ${#NEW_PASS} -ge 12 ]]; then
            read -rsp "  Confirm new password: " CONFIRM_PASS
            echo ""
            if [[ "${NEW_PASS}" == "${CONFIRM_PASS}" ]]; then
                break
            else
                warn "Passwords do not match. Try again."
            fi
        else
            warn "Password must be at least 12 characters. Try again."
        fi
    done

    "${VENV_PYTHON}" - <<PYEOF
import sys
sys.path.insert(0, '${INSTALL_DIR}')
import sqlite3
from werkzeug.security import generate_password_hash

db = sqlite3.connect('${DB_FILE}')
db.row_factory = sqlite3.Row

cur = db.execute("SELECT id FROM users WHERE username = ?", ('${TARGET_USER}',))
row = cur.fetchone()
if not row:
    print(f"  ERROR: User '${TARGET_USER}' not found in database.")
    sys.exit(1)

db.execute("UPDATE users SET password_hash = ?, active = 1 WHERE id = ?",
           (generate_password_hash('${NEW_PASS}'), row['id']))
db.commit()
print(f"  Password for '${TARGET_USER}' updated successfully.")
db.close()
PYEOF
    success "Password reset for user '${TARGET_USER}'"

    # If this is the admin user, also update .env to keep them in sync
    if [[ -f "${ENV_FILE}" ]]; then
        ENV_USER=$(grep "^DASHBOARD_USERNAME=" "${ENV_FILE}" | cut -d= -f2)
        if [[ "${ENV_USER}" == "${TARGET_USER}" ]]; then
            sed -i "s|^DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=${NEW_PASS}|" "${ENV_FILE}"
            info ".env also updated to keep credentials in sync"
        fi
    fi
    ;;

# ── Method 3: List users ──────────────────────────────────────────────────────
3)
    echo ""
    if [[ ! -f "${DB_FILE}" ]]; then
        error "Database not found at ${DB_FILE}"
    fi

    info "Users in database:"
    "${VENV_PYTHON}" - <<PYEOF
import sqlite3
db = sqlite3.connect('${DB_FILE}')
db.row_factory = sqlite3.Row
rows = db.execute("""
    SELECT u.id, u.username, u.email, u.active,
           GROUP_CONCAT(r.name, ', ') as roles
    FROM users u
    LEFT JOIN user_roles ur ON u.id = ur.user_id
    LEFT JOIN roles r ON ur.role_id = r.id
    GROUP BY u.id
    ORDER BY u.id
""").fetchall()
print(f"\n  {'ID':<5} {'Username':<20} {'Email':<30} {'Roles':<20} {'Status'}")
print(f"  {'-'*4} {'-'*19} {'-'*29} {'-'*19} {'-'*8}")
for r in rows:
    status = "active" if r['active'] else "inactive"
    email  = r['email'] or '-'
    roles  = r['roles'] or '-'
    print(f"  {r['id']:<5} {r['username']:<20} {email:<30} {roles:<20} {status}")
print()
db.close()
PYEOF
    exit 0
    ;;

*)
    error "Invalid choice. Run the script again and enter 1, 2, or 3."
    ;;
esac

# ── Restart service ───────────────────────────────────────────────────────────
echo ""
if systemctl is-active --quiet fleetpilot.service 2>/dev/null; then
    read -rp "  Restart FleetPilot service to apply changes? [Y/n] " RESTART
    if [[ "${RESTART,,}" != "n" ]]; then
        systemctl restart fleetpilot.service
        sleep 2
        if systemctl is-active --quiet fleetpilot.service; then
            success "FleetPilot restarted successfully"
        else
            warn "Service restart failed. Check: journalctl -u fleetpilot -n 20"
        fi
    fi
else
    info "FleetPilot service is not running. Start it with: systemctl start fleetpilot"
fi

echo ""
success "Password reset complete. You can now log in with the new credentials."
echo ""
