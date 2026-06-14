#!/usr/bin/env bash
# =============================================================================
#  FleetPilot — Remote Access Helper
#  Opens a secure SSH tunnel and prints connection data.
#  Run as root: sudo bash remote-access.sh
# =============================================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
die()     { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

# ── Root check ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "Run as root: sudo bash remote-access.sh"
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║         FleetPilot — Remote Access Helper            ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
warn "This opens a temporary SSH tunnel for remote support."
warn "Press Ctrl+C at any time to close it and remove the temp user."
echo ""
read -rp "  Continue? [Y/n] " CONFIRM
if [[ "${CONFIRM,,}" == "n" ]]; then
    info "Cancelled."
    exit 0
fi

# ── Install ngrok if missing ──────────────────────────────────────────────────
if ! command -v ngrok &>/dev/null; then
    info "Installing ngrok..."
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  NGROK_ARCH="amd64" ;;
        aarch64) NGROK_ARCH="arm64" ;;
        armv7l)  NGROK_ARCH="arm"   ;;
        *)       die "Unsupported architecture: $ARCH" ;;
    esac
    TMP=$(mktemp -d)
    curl -sSL "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${NGROK_ARCH}.tgz" \
        -o "${TMP}/ngrok.tgz" || die "Failed to download ngrok"
    tar -xzf "${TMP}/ngrok.tgz" -C "${TMP}" || die "Failed to extract ngrok"
    mv "${TMP}/ngrok" /usr/local/bin/ngrok
    chmod +x /usr/local/bin/ngrok
    rm -rf "$TMP"
    ok "ngrok installed"
else
    ok "ngrok found: $(ngrok version 2>/dev/null | head -1)"
fi

# ── Auth token ────────────────────────────────────────────────────────────────
NGROK_CFG1="${HOME}/.config/ngrok/ngrok.yml"
NGROK_CFG2="${HOME}/.ngrok2/ngrok.yml"
HAS_TOKEN=false
grep -q "authtoken" "$NGROK_CFG1" 2>/dev/null && HAS_TOKEN=true
grep -q "authtoken" "$NGROK_CFG2" 2>/dev/null && HAS_TOKEN=true

if [[ "$HAS_TOKEN" == "false" ]]; then
    echo ""
    info "Get a FREE auth token at: https://dashboard.ngrok.com/get-started/your-authtoken"
    read -rp "  Paste your ngrok auth token: " NGROK_TOKEN
    if [[ -z "$NGROK_TOKEN" ]]; then
        die "Auth token cannot be empty"
    fi
    ngrok config add-authtoken "$NGROK_TOKEN" || die "Failed to save auth token"
    ok "Auth token saved"
else
    ok "ngrok auth token already configured"
fi

# ── Ensure SSH is running ─────────────────────────────────────────────────────
echo ""
info "Checking SSH..."
if systemctl is-active --quiet ssh 2>/dev/null; then
    ok "SSH is running (ssh)"
elif systemctl is-active --quiet sshd 2>/dev/null; then
    ok "SSH is running (sshd)"
else
    info "Starting SSH..."
    systemctl start ssh 2>/dev/null || systemctl start sshd 2>/dev/null
    sleep 1
    if systemctl is-active --quiet ssh 2>/dev/null || systemctl is-active --quiet sshd 2>/dev/null; then
        ok "SSH started"
    else
        die "SSH could not be started. Run: apt install openssh-server"
    fi
fi

# ── Create temporary user ─────────────────────────────────────────────────────
echo ""
info "Creating temporary access user..."

TEMP_USER="fp-support"
TEMP_PASS=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)

# Delete stale user if exists
if id "$TEMP_USER" &>/dev/null; then
    userdel -r "$TEMP_USER" 2>/dev/null
    info "Removed old temp user"
fi

# Create fresh user
useradd -m -s /bin/bash "$TEMP_USER"
RC=$?
if [[ $RC -ne 0 ]]; then
    die "useradd failed (exit $RC). Try manually: useradd -m -s /bin/bash ${TEMP_USER}"
fi
ok "User '${TEMP_USER}' created"

# Set password using Python (most reliable across distros)
python3 -c "
import subprocess, sys
result = subprocess.run(['chpasswd'], input='${TEMP_USER}:${TEMP_PASS}',
    capture_output=True, text=True)
if result.returncode != 0:
    sys.exit(result.returncode)
" 2>/dev/null
RC=$?
if [[ $RC -ne 0 ]]; then
    # Direct fallback
    echo "${TEMP_USER}:${TEMP_PASS}" | chpasswd
    RC=$?
fi
if [[ $RC -ne 0 ]]; then
    die "Failed to set password. Try: echo '${TEMP_USER}:${TEMP_PASS}' | chpasswd"
fi
ok "Password set"

# Scoped sudo permissions
cat > "/etc/sudoers.d/${TEMP_USER}" << SUDOEOF
# FleetPilot temporary support — auto-removed on tunnel close
${TEMP_USER} ALL=(ALL) NOPASSWD: /usr/bin/journalctl, /bin/journalctl
${TEMP_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl status fleetpilot, /bin/systemctl status fleetpilot
${TEMP_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart fleetpilot, /bin/systemctl restart fleetpilot
${TEMP_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop fleetpilot, /bin/systemctl stop fleetpilot
${TEMP_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl start fleetpilot, /bin/systemctl start fleetpilot
${TEMP_USER} ALL=(ALL) NOPASSWD: /usr/bin/python3, /opt/fleetpilot/venv/bin/python3
${TEMP_USER} ALL=(ALL) NOPASSWD: /usr/bin/git
SUDOEOF
chmod 440 "/etc/sudoers.d/${TEMP_USER}"
ok "Sudo permissions configured"

# ── Start ngrok tunnel ────────────────────────────────────────────────────────
echo ""
info "Starting ngrok tunnel..."

# Kill any leftover ngrok processes
pkill -f "ngrok tcp" 2>/dev/null || true
sleep 1

ngrok tcp 22 --log=stdout > /tmp/ngrok_fp.log 2>&1 &
NGROK_PID=$!

# Wait up to 15 seconds for tunnel URL
TUNNEL_URL=""
for i in $(seq 1 15); do
    sleep 1
    TUNNEL_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
        | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tunnels = data.get('tunnels', [])
    if tunnels:
        print(tunnels[0]['public_url'])
except:
    pass
" 2>/dev/null || true)
    if [[ -n "$TUNNEL_URL" ]]; then
        break
    fi
    echo -n "."
done
echo ""

if [[ -z "$TUNNEL_URL" ]]; then
    kill "$NGROK_PID" 2>/dev/null || true
    echo ""
    info "ngrok log:"
    cat /tmp/ngrok_fp.log | head -20
    die "Tunnel failed to start. See log above."
fi

TUNNEL_HOST=$(echo "$TUNNEL_URL" | sed 's|tcp://||' | cut -d: -f1)
TUNNEL_PORT=$(echo "$TUNNEL_URL" | sed 's|tcp://||' | cut -d: -f2)

# ── Print connection info ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║           CONNECTION DETAILS — SEND THESE TO MANUS          ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}SSH Command :${RESET}  ssh -p ${TUNNEL_PORT} ${TEMP_USER}@${TUNNEL_HOST}"
echo ""
echo -e "  ${BOLD}Host        :${RESET}  ${TUNNEL_HOST}"
echo -e "  ${BOLD}Port        :${RESET}  ${TUNNEL_PORT}"
echo -e "  ${BOLD}Username    :${RESET}  ${TEMP_USER}"
echo -e "  ${BOLD}Password    :${RESET}  ${TEMP_PASS}"
echo ""
echo -e "${YELLOW}  Tunnel is active — press Ctrl+C to close and clean up.${RESET}"
echo ""

# ── Cleanup on exit ───────────────────────────────────────────────────────────
cleanup() {
    echo ""
    info "Closing tunnel and cleaning up..."
    kill "$NGROK_PID" 2>/dev/null || true
    pkill -f "ngrok tcp" 2>/dev/null || true
    userdel -r "$TEMP_USER" 2>/dev/null || true
    rm -f "/etc/sudoers.d/${TEMP_USER}"
    rm -f /tmp/ngrok_fp.log
    ok "Done. Temp user removed, tunnel closed."
    echo ""
}
trap cleanup EXIT INT TERM

# Keep alive
while kill -0 "$NGROK_PID" 2>/dev/null; do
    sleep 5
done
