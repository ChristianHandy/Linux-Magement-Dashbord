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

# ── Root check ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root. Use: sudo bash reset-password.sh"
fi

# ── Locate installation ───────────────────────────────────────────────────────
# Try the default install path first, then fall back to the script's own directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/users.db" ]]; then
    INSTALL_DIR="${SCRIPT_DIR}"
elif [[ -f "/opt/fleetpilot/users.db" ]]; then
    INSTALL_DIR="/opt/fleetpilot"
else
    # Ask the user
    read -rp "FleetPilot install directory [/opt/fleetpilot]: " INPUT_DIR
    INSTALL_DIR="${INPUT_DIR:-/opt/fleetpilot}"
    [[ -f "${INSTALL_DIR}/users.db" ]] || error "users.db not found in ${INSTALL_DIR}"
fi

DB_FILE="${INSTALL_DIR}/users.db"
ENV_FILE="${INSTALL_DIR}/.env"

# ── Find a working Python interpreter with werkzeug ──────────────────────────
find_python() {
    for PY in \
        "${INSTALL_DIR}/venv/bin/python3" \
        "/opt/fleetpilot/venv/bin/python3" \
        "$(which python3 2>/dev/null)" \
        "$(which python 2>/dev/null)"; do
        if [[ -x "${PY}" ]] && "${PY}" -c "from werkzeug.security import generate_password_hash" 2>/dev/null; then
            echo "${PY}"
            return 0
        fi
    done
    return 1
}

PYTHON=$(find_python) || error "Could not find Python with werkzeug installed.
  Fix: pip3 install werkzeug   or   ${INSTALL_DIR}/venv/bin/pip install werkzeug"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║         FleetPilot — Password Reset Utility          ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
info "Install dir : ${INSTALL_DIR}"
info "Database    : ${DB_FILE}"
info "Python      : ${PYTHON}"
echo ""

# ── Helper: prompt for a confirmed password ───────────────────────────────────
prompt_password() {
    local LABEL="${1:-New password}"
    local PASS=""
    while true; do
        read -rsp "  ${LABEL} (min 12 chars): " PASS
        echo ""
        if [[ ${#PASS} -lt 12 ]]; then
            warn "Password must be at least 12 characters. Try again."
            continue
        fi
        local CONFIRM=""
        read -rsp "  Confirm password: " CONFIRM
        echo ""
        if [[ "${PASS}" == "${CONFIRM}" ]]; then
            echo "${PASS}"
            return 0
        fi
        warn "Passwords do not match. Try again."
    done
}

# ── Helper: update password in SQLite ─────────────────────────────────────────
db_update_password() {
    local USERNAME="${1}"
    local NEW_PASS="${2}"
    "${PYTHON}" - "${USERNAME}" "${NEW_PASS}" <<'PYEOF'
import sys, sqlite3
from werkzeug.security import generate_password_hash

db_path = sys.argv[1] if len(sys.argv) > 3 else None
username = sys.argv[1]
new_pass = sys.argv[2]

import os
db_path = os.environ.get('FP_DB')

db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row
row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
if not row:
    print(f"  User '{username}' not found in database.")
    sys.exit(2)
db.execute("UPDATE users SET password_hash = ?, active = 1 WHERE id = ?",
           (generate_password_hash(new_pass), row['id']))
db.commit()
db.close()
print(f"  Database updated for user '{username}'.")
PYEOF
}

# ── Choose reset method ───────────────────────────────────────────────────────
echo -e "  ${BOLD}Choose an option:${RESET}"
echo -e "  ${CYAN}1)${RESET} Reset admin password  (via .env + database)"
echo -e "  ${CYAN}2)${RESET} Reset any user        (database only)"
echo -e "  ${CYAN}3)${RESET} List all users"
echo ""
read -rp "  Enter choice [1/2/3]: " CHOICE

case "${CHOICE}" in

# ── Option 1: Reset admin (env + db) ─────────────────────────────────────────
1)
    echo ""
    info "Resetting admin credentials"

    # Determine current admin username
    CURRENT_USER="admin"
    if [[ -f "${ENV_FILE}" ]]; then
        ENV_USER=$(grep "^DASHBOARD_USERNAME=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2 | tr -d '"' || true)
        [[ -n "${ENV_USER}" ]] && CURRENT_USER="${ENV_USER}"
    fi
    info "Current admin username: ${CURRENT_USER}"

    read -rp "  New username [leave blank to keep '${CURRENT_USER}']: " NEW_USER
    NEW_USER="${NEW_USER:-${CURRENT_USER}}"

    NEW_PASS=$(prompt_password "New password for '${NEW_USER}'")

    # Update .env
    if [[ -f "${ENV_FILE}" ]]; then
        # Update existing entries or append if missing
        if grep -q "^DASHBOARD_USERNAME=" "${ENV_FILE}"; then
            sed -i "s|^DASHBOARD_USERNAME=.*|DASHBOARD_USERNAME=${NEW_USER}|" "${ENV_FILE}"
        else
            echo "DASHBOARD_USERNAME=${NEW_USER}" >> "${ENV_FILE}"
        fi
        if grep -q "^DASHBOARD_PASSWORD=" "${ENV_FILE}"; then
            sed -i "s|^DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=${NEW_PASS}|" "${ENV_FILE}"
        else
            echo "DASHBOARD_PASSWORD=${NEW_PASS}" >> "${ENV_FILE}"
        fi
        success ".env updated"
    else
        warn ".env not found — skipping env file update"
    fi

    # Ensure DB schema exists and update the admin user
    "${PYTHON}" - <<PYEOF
import sys, sqlite3, os
sys.path.insert(0, '${INSTALL_DIR}')
os.chdir('${INSTALL_DIR}')
from werkzeug.security import generate_password_hash

db_path = '${DB_FILE}'
old_name = '${CURRENT_USER}'
new_name = '${NEW_USER}'
new_pass = '${NEW_PASS}'

db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row

# ── Ensure tables exist (safe to run even if already created) ──────────────
db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      email TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS roles(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      description TEXT
    );
    CREATE TABLE IF NOT EXISTS user_roles(
      user_id INTEGER,
      role_id INTEGER,
      PRIMARY KEY (user_id, role_id),
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
      FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
    );
""")
# Ensure default roles exist
for rname, rdesc in [('admin','Full access'),('operator','Operations'),('viewer','Read-only')]:
    db.execute('INSERT OR IGNORE INTO roles(name, description) VALUES (?,?)', (rname, rdesc))
db.commit()

# ── Find or create the admin user ─────────────────────────────────────────
row = db.execute('SELECT id FROM users WHERE username = ?', (old_name,)).fetchone()
if not row:
    row = db.execute('SELECT id FROM users WHERE id = 1').fetchone()
    if row:
        print(f"  User '{old_name}' not found — updating user with id=1.")

if row:
    db.execute('UPDATE users SET username=?, password_hash=?, active=1 WHERE id=?',
               (new_name, generate_password_hash(new_pass), row['id']))
    # Ensure admin role is assigned
    admin_role = db.execute('SELECT id FROM roles WHERE name="admin"').fetchone()
    if admin_role:
        db.execute('INSERT OR IGNORE INTO user_roles(user_id,role_id) VALUES (?,?)',
                   (row['id'], admin_role['id']))
    db.commit()
    print(f"  Database updated: username='{new_name}', password reset, account activated.")
else:
    # No user at all — create one from scratch
    from werkzeug.security import generate_password_hash as gph
    cur = db.execute('INSERT INTO users(username,password_hash,active) VALUES (?,?,1)',
                     (new_name, gph(new_pass)))
    uid = cur.lastrowid
    admin_role = db.execute('SELECT id FROM roles WHERE name="admin"').fetchone()
    if admin_role:
        db.execute('INSERT OR IGNORE INTO user_roles(user_id,role_id) VALUES (?,?)',
                   (uid, admin_role['id']))
    db.commit()
    print(f"  No existing user found — created new admin user '{new_name}'.")
db.close()
PYEOF
    ;;

# ── Option 2: Reset any user (db only) ───────────────────────────────────────
2)
    echo ""
    info "Users in database:"
    "${PYTHON}" - <<PYEOF
import sqlite3
db = sqlite3.connect('${DB_FILE}')
db.row_factory = sqlite3.Row
rows = db.execute("""
    SELECT u.id, u.username, u.active,
           GROUP_CONCAT(r.name, ', ') as roles
    FROM users u
    LEFT JOIN user_roles ur ON u.id = ur.user_id
    LEFT JOIN roles r ON ur.role_id = r.id
    GROUP BY u.id ORDER BY u.id
""").fetchall()
for r in rows:
    status = "active" if r['active'] else "INACTIVE"
    roles  = r['roles'] or '-'
    print(f"    [{r['id']}]  {r['username']:<20}  roles: {roles:<15}  ({status})")
db.close()
PYEOF

    echo ""
    read -rp "  Username to reset: " TARGET_USER
    [[ -z "${TARGET_USER}" ]] && error "No username entered."

    NEW_PASS=$(prompt_password "New password for '${TARGET_USER}'")

    "${PYTHON}" - <<PYEOF
import sys, sqlite3
from werkzeug.security import generate_password_hash

db = sqlite3.connect('${DB_FILE}')
db.row_factory = sqlite3.Row
row = db.execute("SELECT id FROM users WHERE username = ?", ('${TARGET_USER}',)).fetchone()
if not row:
    print("  ERROR: User '${TARGET_USER}' not found.")
    sys.exit(1)
db.execute("UPDATE users SET password_hash = ?, active = 1 WHERE id = ?",
           (generate_password_hash('${NEW_PASS}'), row['id']))
db.commit()
db.close()
print(f"  Password for '${TARGET_USER}' updated and account activated.")
PYEOF
    success "Password reset for '${TARGET_USER}'"

    # Sync .env if this is the admin user
    if [[ -f "${ENV_FILE}" ]]; then
        ENV_USER=$(grep "^DASHBOARD_USERNAME=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2 | tr -d '"' || true)
        if [[ "${ENV_USER}" == "${TARGET_USER}" ]]; then
            sed -i "s|^DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=${NEW_PASS}|" "${ENV_FILE}"
            info ".env synced for admin user '${TARGET_USER}'"
        fi
    fi
    ;;

# ── Option 3: List users ──────────────────────────────────────────────────────
3)
    echo ""
    info "Users in database (${DB_FILE}):"
    "${PYTHON}" - <<PYEOF
import sqlite3
db = sqlite3.connect('${DB_FILE}')
db.row_factory = sqlite3.Row
rows = db.execute("""
    SELECT u.id, u.username, u.email, u.active,
           GROUP_CONCAT(r.name, ', ') as roles
    FROM users u
    LEFT JOIN user_roles ur ON u.id = ur.user_id
    LEFT JOIN roles r ON ur.role_id = r.id
    GROUP BY u.id ORDER BY u.id
""").fetchall()
print(f"\n  {'ID':<5} {'Username':<20} {'Email':<28} {'Roles':<18} Status")
print(f"  {'─'*4} {'─'*19} {'─'*27} {'─'*17} {'─'*8}")
for r in rows:
    status = "active" if r['active'] else "INACTIVE"
    print(f"  {r['id']:<5} {r['username']:<20} {(r['email'] or '-'):<28} {(r['roles'] or '-'):<18} {status}")
print()
db.close()
PYEOF
    exit 0
    ;;

*)
    error "Invalid choice '${CHOICE}'. Run the script again and enter 1, 2, or 3."
    ;;
esac

# ── Offer service restart ─────────────────────────────────────────────────────
echo ""
if systemctl is-active --quiet fleetpilot.service 2>/dev/null; then
    read -rp "  Restart FleetPilot now to apply changes? [Y/n] " RESTART
    if [[ "${RESTART,,}" != "n" ]]; then
        systemctl restart fleetpilot.service
        sleep 2
        if systemctl is-active --quiet fleetpilot.service; then
            success "FleetPilot restarted"
        else
            warn "Restart failed — check: journalctl -u fleetpilot -n 30"
        fi
    fi
else
    info "FleetPilot is not running. Start it with: systemctl start fleetpilot"
fi

echo ""
success "Done. Log in with your new credentials."
echo ""
