#!/usr/bin/env bash
# =============================================================================
#  FleetPilot — Remote Access Helper
#  Installs ngrok, opens a secure SSH tunnel and prints the connection data.
#  Run as root: sudo bash remote-access.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

# ── Root check ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Run as root: sudo bash remote-access.sh"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║         FleetPilot — Remote Access Helper            ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
warn "This script opens a temporary SSH tunnel so a remote helper can"
warn "connect to this server. The tunnel closes when you press Ctrl+C."
echo ""
read -rp "  Continue? [Y/n] " CONFIRM
[[ "${CONFIRM,,}" == "n" ]] && { info "Cancelled."; exit 0; }

# ── Step 1: Install ngrok if missing ─────────────────────────────────────────
if ! command -v ngrok &>/dev/null; then
    info "Installing ngrok..."
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  NGROK_ARCH="amd64" ;;
        aarch64) NGROK_ARCH="arm64" ;;
        armv7l)  NGROK_ARCH="arm"   ;;
        *)       error "Unsupported architecture: $ARCH" ;;
    esac

    # Try apt first (cleaner), fall back to direct binary download
    if apt-get install -y ngrok 2>/dev/null; then
        success "ngrok installed via apt"
    else
        info "Downloading ngrok binary..."
        NGROK_URL="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${NGROK_ARCH}.tgz"
        TMP_DIR=$(mktemp -d)
        curl -sSL "$NGROK_URL" -o "${TMP_DIR}/ngrok.tgz"
        tar -xzf "${TMP_DIR}/ngrok.tgz" -C "${TMP_DIR}"
        mv "${TMP_DIR}/ngrok" /usr/local/bin/ngrok
        chmod +x /usr/local/bin/ngrok
        rm -rf "$TMP_DIR"
        success "ngrok installed to /usr/local/bin/ngrok"
    fi
else
    success "ngrok already installed: $(ngrok version 2>/dev/null | head -1)"
fi

# ── Step 2: Auth token ────────────────────────────────────────────────────────
echo ""
info "You need a FREE ngrok account to use this."
info "Sign up at: https://ngrok.com  (takes 30 seconds)"
info "Then go to: https://dashboard.ngrok.com/get-started/your-authtoken"
echo ""

# Check if already configured
NGROK_CONFIG="${HOME}/.config/ngrok/ngrok.yml"
NGROK_CONFIG_OLD="${HOME}/.ngrok2/ngrok.yml"
ALREADY_CONFIGURED=false

if [[ -f "$NGROK_CONFIG" ]] && grep -q "authtoken" "$NGROK_CONFIG" 2>/dev/null; then
    ALREADY_CONFIGURED=true
elif [[ -f "$NGROK_CONFIG_OLD" ]] && grep -q "authtoken" "$NGROK_CONFIG_OLD" 2>/dev/null; then
    ALREADY_CONFIGURED=true
fi

if [[ "$ALREADY_CONFIGURED" == "true" ]]; then
    success "ngrok auth token already configured"
else
    read -rp "  Paste your ngrok auth token: " NGROK_TOKEN
    [[ -z "$NGROK_TOKEN" ]] && error "Auth token cannot be empty"
    ngrok config add-authtoken "$NGROK_TOKEN"
    success "Auth token saved"
fi

# ── Step 3: Ensure SSH is running ─────────────────────────────────────────────
echo ""
info "Checking SSH service..."
if systemctl is-active --quiet ssh 2>/dev/null || systemctl is-active --quiet sshd 2>/dev/null; then
    success "SSH service is running"
else
    info "Starting SSH service..."
    systemctl start ssh 2>/dev/null || systemctl start sshd 2>/dev/null || \
        error "Could not start SSH. Install with: apt install openssh-server"
    success "SSH service started"
fi

# ── Step 4: Create a temporary access user ────────────────────────────────────
echo ""
info "Creating temporary access user..."

TEMP_USER="fleetpilot-support"
TEMP_PASS=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)

# Create user if it doesn't exist
if id "$TEMP_USER" &>/dev/null; then
    info "User '${TEMP_USER}' already exists — resetting password"
else
    useradd -m -s /bin/bash "$TEMP_USER"
    success "Created user: ${TEMP_USER}"
fi

echo "${TEMP_USER}:${TEMP_PASS}" | chpasswd
success "Temporary password set"

# Give sudo access (read-only commands + systemctl status)
cat > "/etc/sudoers.d/${TEMP_USER}" <<SUDOEOF
# Temporary remote support access — remove after session
${TEMP_USER} ALL=(ALL) NOPASSWD: /bin/journalctl, /usr/bin/journalctl, \
    /bin/systemctl status *, /usr/bin/systemctl status *, \
    /bin/cat /opt/fleetpilot/*, /usr/bin/cat /opt/fleetpilot/*, \
    /usr/bin/git -C /opt/fleetpilot *, /bin/git -C /opt/fleetpilot *, \
    /opt/fleetpilot/venv/bin/python3 *, /usr/bin/python3 *, \
    /bin/systemctl restart fleetpilot, /usr/bin/systemctl restart fleetpilot, \
    /bin/systemctl stop fleetpilot, /usr/bin/systemctl stop fleetpilot, \
    /bin/systemctl start fleetpilot, /usr/bin/systemctl start fleetpilot
SUDOEOF
chmod 440 "/etc/sudoers.d/${TEMP_USER}"
success "Sudo permissions configured (limited scope)"

# ── Step 5: Start ngrok tunnel ────────────────────────────────────────────────
echo ""
info "Starting ngrok SSH tunnel..."

# Start ngrok in background
ngrok tcp 22 --log=stdout --log-level=info > /tmp/ngrok_remote_access.log 2>&1 &
NGROK_PID=$!

# Wait for tunnel to be established
info "Waiting for tunnel to establish..."
for i in {1..20}; do
    sleep 1
    TUNNEL_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
        | python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print(t[0]['public_url'])" 2>/dev/null || true)
    if [[ -n "$TUNNEL_URL" ]]; then
        break
    fi
    echo -n "."
done
echo ""

if [[ -z "$TUNNEL_URL" ]]; then
    kill "$NGROK_PID" 2>/dev/null || true
    error "Tunnel failed to start. Check /tmp/ngrok_remote_access.log"
fi

# Parse host and port from tcp://X.tcp.ngrok.io:PORT
TUNNEL_HOST=$(echo "$TUNNEL_URL" | sed 's|tcp://||' | cut -d: -f1)
TUNNEL_PORT=$(echo "$TUNNEL_URL" | sed 's|tcp://||' | cut -d: -f2)

# ── Step 6: Print connection info ─────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║              CONNECTION DETAILS — SEND THESE                ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}SSH Command:${RESET}"
echo -e "  ${CYAN}ssh -p ${TUNNEL_PORT} ${TEMP_USER}@${TUNNEL_HOST}${RESET}"
echo ""
echo -e "  ${BOLD}Host     :${RESET}  ${TUNNEL_HOST}"
echo -e "  ${BOLD}Port     :${RESET}  ${TUNNEL_PORT}"
echo -e "  ${BOLD}Username :${RESET}  ${TEMP_USER}"
echo -e "  ${BOLD}Password :${RESET}  ${TEMP_PASS}"
echo ""
echo -e "${YELLOW}${BOLD}  ⚠  The tunnel is active as long as this script runs.${RESET}"
echo -e "${YELLOW}${BOLD}  ⚠  Press Ctrl+C to close the tunnel and remove the user.${RESET}"
echo ""

# ── Cleanup on exit ───────────────────────────────────────────────────────────
cleanup() {
    echo ""
    info "Closing tunnel and cleaning up..."
    kill "$NGROK_PID" 2>/dev/null || true
    userdel -r "$TEMP_USER" 2>/dev/null || true
    rm -f "/etc/sudoers.d/${TEMP_USER}"
    rm -f /tmp/ngrok_remote_access.log
    success "Tunnel closed. Temporary user removed."
    echo ""
}
trap cleanup EXIT INT TERM

# Keep running until Ctrl+C
while kill -0 "$NGROK_PID" 2>/dev/null; do
    sleep 5
done
