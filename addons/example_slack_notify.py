"""
FleetPilot Example Plugin: Slack Notification
===============================================
Sends a Slack webhook message after every successful update run.
Hooks used: update_post, notification

Configuration:
  Set the environment variable SLACK_WEBHOOK_URL before starting FleetPilot:
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"

Install: Place this file in the addons/ directory and restart FleetPilot.
"""

import os
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("fleetpilot.slack_notify")

# ── Helpers ──────────────────────────────────────────────────────────────────

def _send_slack(text: str) -> bool:
    """Send a plain-text message to the configured Slack webhook."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.debug("[slack_notify] SLACK_WEBHOOK_URL not set — skipping")
        return False
    try:
        payload = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = resp.status == 200
            if not ok:
                logger.warning("[slack_notify] Slack returned HTTP %s", resp.status)
            return ok
    except urllib.error.URLError as exc:
        logger.error("[slack_notify] Failed to send Slack message: %s", exc)
        return False


def _on_update_post(host: dict, result: dict) -> None:
    """Called after each host update run."""
    host_name = host.get("name", "unknown")
    success   = result.get("success", False)
    packages  = result.get("packages_updated", 0)
    status    = "✅ succeeded" if success else "❌ failed"
    msg = (
        f"*FleetPilot Update* — `{host_name}` {status}\n"
        f"Packages updated: *{packages}*"
    )
    _send_slack(msg)


def _on_notification(event: str, data: dict) -> None:
    """Called for generic system events (e.g. new_version_available)."""
    if event == "new_version_available":
        version = data.get("version", "?")
        _send_slack(f"🆕 *FleetPilot* — new version *{version}* is available!")


# ── Plugin metadata ───────────────────────────────────────────────────────────

addon_meta = {
    "name":        "Slack Notification",
    "version":     "1.0.0",
    "author":      "FleetPilot Team",
    "description": (
        "Sends a Slack webhook message after every update run and when a new "
        "FleetPilot version is available. Requires SLACK_WEBHOOK_URL env var."
    ),
    "scope":       "global",

    # Hook registrations
    "update_post":    _on_update_post,
    "notification":   _on_notification,
}
