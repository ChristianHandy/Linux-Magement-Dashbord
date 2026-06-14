"""
FleetPilot Example Plugin: Host Ping Button
============================================
Adds a "Ping" action button to every host card on the Hosts page.
Clicking the button pings the host's IP and shows the round-trip time.

Hooks used: host_card_action
Routes added: GET /plugins/ping?ip=<ip>

Install: Place this file in the addons/ directory and restart FleetPilot.
"""

import socket
import time
import logging

logger = logging.getLogger("fleetpilot.host_ping")


def _ping_button(host: dict) -> str:
    """Return an HTML button that triggers a client-side ping request."""
    ip = host.get("ip", "")
    if not ip:
        return ""
    return f"""
<button
  class="btn btn-sm btn-secondary"
  style="font-size:0.75rem; padding:0.25rem 0.6rem"
  onclick="fpPing(this, '{ip}')"
  title="Ping {ip}">
  <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"
       viewBox="0 0 24 24" style="margin-right:4px; vertical-align:-1px">
    <circle cx="12" cy="12" r="10"/>
    <polyline points="12 8 12 12 14 14"/>
  </svg>
  Ping
</button>
<script>
/* Injected once per page by example_host_ping plugin */
if (!window._fpPingLoaded) {{
  window._fpPingLoaded = true;
  window.fpPing = function(btn, ip) {{
    btn.disabled = true;
    btn.textContent = '…';
    fetch('/plugins/ping?ip=' + encodeURIComponent(ip))
      .then(r => r.json())
      .then(d => {{
        btn.textContent = d.ok ? d.ms + ' ms' : 'Timeout';
        btn.style.color = d.ok ? '#10b981' : '#ef4444';
        setTimeout(() => {{
          btn.disabled = false;
          btn.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="margin-right:4px;vertical-align:-1px"><circle cx="12" cy="12" r="10"/><polyline points="12 8 12 12 14 14"/></svg>Ping';
          btn.style.color = '';
        }}, 3000);
      }})
      .catch(() => {{
        btn.textContent = 'Error';
        btn.style.color = '#ef4444';
        btn.disabled = false;
      }});
  }};
}}
</script>
"""


addon_meta = {
    "name":        "Host Ping Button",
    "version":     "1.0.0",
    "author":      "FleetPilot Team",
    "description": "Adds a Ping button to every host card. Shows round-trip time via a lightweight TCP probe.",
    "scope":       "hosts",

    "host_card_action": _ping_button,
}


def register(app, core):
    """Add the /plugins/ping API endpoint."""
    from flask import Blueprint, jsonify, request, session
    from functools import wraps

    bp = Blueprint("host_ping_plugin", __name__)

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("user_id"):
                from flask import redirect, url_for
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    @bp.route("/plugins/ping")
    @login_required
    def ping():
        ip = request.args.get("ip", "").strip()
        if not ip:
            return jsonify({"ok": False, "error": "no ip"}), 400
        # Lightweight TCP probe on port 80 (falls back to ICMP-style timing)
        start = time.monotonic()
        ok = False
        try:
            with socket.create_connection((ip, 80), timeout=2):
                ok = True
        except OSError:
            # Port 80 closed — try port 22 (SSH)
            try:
                with socket.create_connection((ip, 22), timeout=2):
                    ok = True
            except OSError:
                pass
        ms = round((time.monotonic() - start) * 1000)
        return jsonify({"ok": ok, "ms": ms, "ip": ip})

    app.register_blueprint(bp)
    logger.info("[host_ping] /plugins/ping route registered")
