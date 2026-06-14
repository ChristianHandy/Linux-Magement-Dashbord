"""
FleetPilot Example Plugin: Dashboard Widget
============================================
Adds a custom summary widget to the Home dashboard.
Hook used: dashboard_widget

Install: Place this file in the addons/ directory and restart FleetPilot.
"""

addon_meta = {
    "name":        "Example Dashboard Widget",
    "version":     "1.0.0",
    "author":      "FleetPilot Team",
    "description": "Adds a custom info widget to the Home dashboard. Demonstrates the dashboard_widget hook.",
    "scope":       "dashboard",

    # ── dashboard_widget hook ────────────────────────────────────────────────
    # Called by index.html to render extra widgets on the Home page.
    # Arguments: hosts (list of host dicts), stats (dict with fleet statistics)
    # Returns:   HTML string that is injected into the dashboard widget grid.
    "dashboard_widget": lambda hosts, stats: _render_widget(hosts, stats),
}


def _render_widget(hosts: list, stats: dict) -> str:
    """Build a simple fleet-health summary card."""
    total = len(hosts)
    online = sum(1 for h in hosts if h.get("status") == "online")
    offline = total - online
    pct = int(online / total * 100) if total else 0

    bar_color = "#10b981" if pct >= 80 else "#f59e0b" if pct >= 50 else "#ef4444"

    return f"""
<div class="card" style="border-left:4px solid {bar_color}">
  <div class="card-body" style="padding:1.25rem">
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.75rem">
      <h3 style="margin:0; font-size:0.95rem; font-weight:600; color:var(--text-primary)">
        Fleet Health <span style="font-size:0.7rem; background:rgba(99,102,241,0.15); color:#6366f1;
          padding:0.15rem 0.5rem; border-radius:4px; margin-left:0.5rem; font-family:monospace">
          example_dashboard_widget
        </span>
      </h3>
      <span style="font-size:1.5rem; font-weight:700; color:{bar_color}">{pct}%</span>
    </div>
    <div style="background:var(--bg-tertiary); border-radius:99px; height:8px; overflow:hidden; margin-bottom:0.75rem">
      <div style="background:{bar_color}; width:{pct}%; height:100%; border-radius:99px; transition:width 0.4s ease"></div>
    </div>
    <div style="display:flex; gap:1.5rem; font-size:0.85rem; color:var(--text-secondary)">
      <span>🟢 Online: <strong style="color:var(--text-primary)">{online}</strong></span>
      <span>🔴 Offline: <strong style="color:var(--text-primary)">{offline}</strong></span>
      <span>📦 Total: <strong style="color:var(--text-primary)">{total}</strong></span>
    </div>
  </div>
</div>
"""
