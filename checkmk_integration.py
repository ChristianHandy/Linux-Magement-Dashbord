"""
checkmk_integration.py — FleetPilot ↔ CheckMK Integration
===========================================================

Provides:
  1. /api/checkmk/agent          — Full agent-style output (<<<local>>> section)
                                   Drop this URL as a "datasource program" in CheckMK.
  2. /api/checkmk/host/<name>    — Per-host local-check output for piggyback data.
  3. /checkmk/local_check        — Downloadable shell script for CheckMK agents.
  4. /checkmk/status             — Human-readable JSON summary for CheckMK REST API.

CheckMK local-check output format (one line per service):
  <state> "<Service Name>" <perfdata|-> <summary text>

  state:  0=OK  1=WARN  2=CRIT  3=UNKNOWN
  perfdata: metricname=value;warn;crit;min;max  (or - if none)

Author: FleetPilot
"""

from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── helpers ──────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(ok: bool, warn: bool = False, crit: bool = False) -> int:
    if crit:
        return 2
    if warn:
        return 1
    if ok:
        return 0
    return 3


def _fmt_line(state: int, name: str, perfdata: str, summary: str) -> str:
    """Format one CheckMK local-check output line."""
    # Escape double-quotes inside name
    safe_name = name.replace('"', "'")
    # Ensure perfdata is non-empty
    perf = perfdata.strip() if perfdata and perfdata.strip() else "-"
    # Remove newlines from summary
    safe_summary = summary.replace("\n", " ").replace("\r", "")
    return f'{state} "{safe_name}" {perf} {safe_summary}'


# ─── individual check generators ──────────────────────────────────────────────

def check_pending_updates(hosts: dict) -> list[str]:
    """Generate CheckMK lines for pending OS updates on each host."""
    lines = []
    for name, hdata in hosts.items():
        updates = hdata.get("pending_updates", [])
        security = hdata.get("security_updates", [])
        total = len(updates)
        sec_count = len(security)

        if sec_count > 0:
            state = 2  # CRIT — security updates pending
        elif total > 10:
            state = 1  # WARN — many updates pending
        elif total > 0:
            state = 1  # WARN
        else:
            state = 0  # OK

        perf = f"pending_updates={total};1;1;0 security_updates={sec_count};1;1;0"
        if state == 0:
            summary = f"No pending updates"
        elif sec_count > 0:
            summary = f"{total} updates pending, {sec_count} SECURITY updates!"
        else:
            summary = f"{total} updates pending"

        lines.append(_fmt_line(state, f"FleetPilot Updates {name}", perf, summary))
    return lines


def check_host_connectivity(hosts: dict) -> list[str]:
    """Generate CheckMK lines for SSH host reachability."""
    lines = []
    for name, hdata in hosts.items():
        status = hdata.get("status", "unknown")
        last_seen = hdata.get("last_seen", "")
        ip = hdata.get("host", "?")

        if status == "online":
            state = 0
            summary = f"Host {ip} is reachable"
        elif status == "offline":
            state = 2
            summary = f"Host {ip} is UNREACHABLE"
        else:
            state = 3
            summary = f"Host {ip} status unknown"

        perf = f"reachable={'1' if status == 'online' else '0'};1;1;0;1"
        lines.append(_fmt_line(state, f"FleetPilot Host {name}", perf, summary))
    return lines


def check_disk_smart(smart_manager) -> list[str]:
    """Generate CheckMK lines for SMART disk health."""
    lines = []
    try:
        raw = smart_manager.get_all_disks()
    except Exception:
        return [_fmt_line(3, "FleetPilot SMART", "-", "SMART manager unavailable")]

    # get_all_disks() may return a list or a dict depending on version
    if isinstance(raw, dict):
        disks = raw  # {disk_id: disk_data}
    elif isinstance(raw, list):
        # Convert list to dict keyed by device path or index
        disks = {d.get("device", str(i)): d for i, d in enumerate(raw)}
    else:
        disks = {}

    for disk_id, disk in disks.items():
        device = disk.get("device", disk_id)
        source = disk.get("source", "local")
        health = disk.get("health", "UNKNOWN")
        temp = disk.get("temperature")
        reallocated = disk.get("reallocated_sectors", 0) or 0
        pending = disk.get("pending_sectors", 0) or 0
        model = disk.get("model", "")

        # Build state
        if health == "FAILED":
            state = 2
        elif health == "CRITICAL":
            state = 2
        elif health == "WARNING":
            state = 1
        elif health == "GOOD":
            state = 0
        else:
            state = 3

        # Build perfdata
        perf_parts = []
        if temp is not None:
            perf_parts.append(f"temperature={temp};45;55;0;70")
        perf_parts.append(f"reallocated_sectors={reallocated};1;5;0")
        perf_parts.append(f"pending_sectors={pending};1;5;0")
        perf = "|".join(perf_parts) if perf_parts else "-"

        # Build summary
        parts = [f"Health: {health}"]
        if model:
            parts.append(model)
        if temp is not None:
            parts.append(f"{temp}°C")
        if reallocated > 0:
            parts.append(f"Reallocated: {reallocated}")
        if pending > 0:
            parts.append(f"Pending: {pending}")
        summary = " | ".join(parts)

        # Service name: device + source
        svc_name = f"FleetPilot Disk {device} ({source})"
        lines.append(_fmt_line(state, svc_name, perf, summary))

    if not lines:
        lines.append(_fmt_line(0, "FleetPilot Disks", "disk_count=0", "No disks registered"))

    return lines


def check_vm_status(vm_controller) -> list[str]:
    """Generate CheckMK lines for VM endpoint connectivity."""
    lines = []
    try:
        endpoints = vm_controller.list_endpoints()
    except Exception:
        return [_fmt_line(3, "FleetPilot VM Controller", "-", "VM controller unavailable")]

    for ep in endpoints:
        ep_id = ep.get("id", "?")
        name = ep.get("name", ep_id)
        platform = ep.get("platform", "?")
        connected = ep.get("connected", False)

        state = 0 if connected else 2
        perf = f"connected={'1' if connected else '0'};1;1;0;1"
        summary = f"{platform.upper()} endpoint {'reachable' if connected else 'UNREACHABLE'}"
        lines.append(_fmt_line(state, f"FleetPilot VM {name}", perf, summary))

        # Per-VM running count if connected
        if connected and platform == "proxmox":
            try:
                vms = vm_controller.get_proxmox_vms(ep_id)
                running = sum(1 for v in vms if v.get("status") == "running")
                stopped = sum(1 for v in vms if v.get("status") == "stopped")
                total = len(vms)
                perf2 = f"vms_running={running};0;0;0 vms_stopped={stopped};0;0;0 vms_total={total}"
                summary2 = f"{running}/{total} VMs running, {stopped} stopped"
                lines.append(_fmt_line(0, f"FleetPilot VMs {name}", perf2, summary2))
            except Exception:
                pass

    if not lines:
        lines.append(_fmt_line(0, "FleetPilot VM Controller", "endpoints=0", "No VM endpoints configured"))

    return lines


def check_storage_status(storage_controller) -> list[str]:
    """Generate CheckMK lines for storage endpoint health."""
    lines = []
    try:
        endpoints = storage_controller.list_endpoints()
    except Exception:
        return [_fmt_line(3, "FleetPilot Storage", "-", "Storage controller unavailable")]

    for ep in endpoints:
        ep_id = ep.get("id", "?")
        name = ep.get("name", ep_id)
        platform = ep.get("platform", "?")
        connected = ep.get("connected", False)

        state = 0 if connected else 2
        perf = f"connected={'1' if connected else '0'};1;1;0;1"
        summary = f"{platform.upper()} storage {'reachable' if connected else 'UNREACHABLE'}"
        lines.append(_fmt_line(state, f"FleetPilot Storage {name}", perf, summary))

        # Pool health if connected
        if connected:
            try:
                pools = storage_controller.get_pools(ep_id)
                degraded = [p for p in pools if p.get("status", "").upper() not in ("ONLINE", "HEALTHY", "OK")]
                perf2 = f"pools_total={len(pools)};0;0;0 pools_degraded={len(degraded)};1;1;0"
                state2 = 2 if len(degraded) > 0 else 0
                summary2 = f"{len(pools)} pools, {len(degraded)} degraded" if degraded else f"{len(pools)} pools all healthy"
                lines.append(_fmt_line(state2, f"FleetPilot Pools {name}", perf2, summary2))
            except Exception:
                pass

    if not lines:
        lines.append(_fmt_line(0, "FleetPilot Storage", "endpoints=0", "No storage endpoints configured"))

    return lines


def check_fleetpilot_service() -> list[str]:
    """Self-check: FleetPilot service health."""
    lines = []

    # Check if the process is running (we are running, so always OK here)
    lines.append(_fmt_line(0, "FleetPilot Service", "running=1;1;1;0;1", "FleetPilot is running"))

    # Check data directory
    data_dir = Path("/opt/fleetpilot")
    if not data_dir.exists():
        data_dir = Path(os.path.dirname(os.path.abspath(__file__)))

    hosts_file = data_dir / "hosts.json"
    if hosts_file.exists():
        age_s = int(time.time() - hosts_file.stat().st_mtime)
        state = 0 if age_s < 86400 else 1
        lines.append(_fmt_line(state, "FleetPilot Config", f"config_age_s={age_s};86400;604800;0",
                               f"Config last modified {age_s}s ago"))
    else:
        lines.append(_fmt_line(1, "FleetPilot Config", "-", "hosts.json not found"))

    return lines


# ─── main agent output builder ─────────────────────────────────────────────────

def build_agent_output(hosts: dict, smart_manager=None,
                       vm_controller=None, storage_controller=None) -> str:
    """
    Build the full CheckMK agent output with a <<<local>>> section.
    This can be used as a datasource program or piped into check_mk_agent.
    """
    lines = ["<<<local>>>"]

    # 1. FleetPilot self-check
    lines.extend(check_fleetpilot_service())

    # 2. Host connectivity
    lines.extend(check_host_connectivity(hosts))

    # 3. Pending updates
    lines.extend(check_pending_updates(hosts))

    # 4. SMART disk health
    if smart_manager:
        lines.extend(check_disk_smart(smart_manager))

    # 5. VM status
    if vm_controller:
        lines.extend(check_vm_status(vm_controller))

    # 6. Storage status
    if storage_controller:
        lines.extend(check_storage_status(storage_controller))

    return "\n".join(lines) + "\n"


def build_host_piggyback(host_name: str, host_data: dict,
                         smart_manager=None) -> str:
    """
    Build piggyback output for a specific host.
    Format: <<<piggyback>>> section with host-specific checks.
    """
    ip = host_data.get("host", host_name)
    lines = [
        f"<<<<{host_name}>>>>",
        "<<<local>>>",
    ]

    # Host status
    status = host_data.get("status", "unknown")
    state = 0 if status == "online" else (2 if status == "offline" else 3)
    lines.append(_fmt_line(state, "FleetPilot Host Status",
                           f"reachable={'1' if status=='online' else '0'};1;1;0;1",
                           f"Host {ip} is {status}"))

    # Pending updates for this host
    updates = host_data.get("pending_updates", [])
    security = host_data.get("security_updates", [])
    total = len(updates)
    sec_count = len(security)
    if sec_count > 0:
        upd_state = 2
    elif total > 0:
        upd_state = 1
    else:
        upd_state = 0
    lines.append(_fmt_line(upd_state, "FleetPilot Pending Updates",
                           f"pending={total};1;1;0 security={sec_count};1;1;0",
                           f"{total} updates ({sec_count} security)" if total else "Up to date"))

    # SMART disks for this host
    if smart_manager:
        try:
            raw_disks = smart_manager.get_all_disks()
            if isinstance(raw_disks, dict):
                all_disks = raw_disks
            elif isinstance(raw_disks, list):
                all_disks = {d.get("device", str(i)): d for i, d in enumerate(raw_disks)}
            else:
                all_disks = {}
            host_disks = {k: v for k, v in all_disks.items()
                          if v.get("source_host") == host_name or v.get("source") == host_name}
            for disk_id, disk in host_disks.items():
                device = disk.get("device", disk_id)
                health = disk.get("health", "UNKNOWN")
                temp = disk.get("temperature")
                reallocated = disk.get("reallocated_sectors", 0) or 0
                pending = disk.get("pending_sectors", 0) or 0

                if health in ("FAILED", "CRITICAL"):
                    ds = 2
                elif health == "WARNING":
                    ds = 1
                elif health == "GOOD":
                    ds = 0
                else:
                    ds = 3

                perf_parts = []
                if temp is not None:
                    perf_parts.append(f"temperature={temp};45;55;0;70")
                perf_parts.append(f"reallocated={reallocated};1;5;0")
                perf_parts.append(f"pending={pending};1;5;0")
                perf = "|".join(perf_parts) if perf_parts else "-"

                summary_parts = [f"Health: {health}"]
                if temp:
                    summary_parts.append(f"{temp}°C")
                if reallocated:
                    summary_parts.append(f"Reallocated: {reallocated}")
                lines.append(_fmt_line(ds, f"FleetPilot Disk {device}",
                                       perf, " | ".join(summary_parts)))
        except Exception:
            pass

    lines.append("<<<<>>>>")  # End of piggyback section
    return "\n".join(lines) + "\n"


def build_status_json(hosts: dict, smart_manager=None,
                      vm_controller=None, storage_controller=None) -> dict:
    """
    Build a structured JSON status summary for CheckMK REST API or Grafana.
    """
    now = _ts()

    # Host summary
    host_summary = []
    for name, hdata in hosts.items():
        updates = hdata.get("pending_updates", [])
        security = hdata.get("security_updates", [])
        host_summary.append({
            "name": name,
            "ip": hdata.get("host", ""),
            "status": hdata.get("status", "unknown"),
            "os": hdata.get("os", ""),
            "pending_updates": len(updates),
            "security_updates": len(security),
            "last_seen": hdata.get("last_seen", ""),
        })

    # Disk summary
    disk_summary = []
    failed_disks = []
    if smart_manager:
        try:
            raw_disks = smart_manager.get_all_disks()
            if isinstance(raw_disks, dict):
                all_disks = raw_disks
            elif isinstance(raw_disks, list):
                all_disks = {d.get("device", str(i)): d for i, d in enumerate(raw_disks)}
            else:
                all_disks = {}
            health_counts = {"GOOD": 0, "WARNING": 0, "CRITICAL": 0, "FAILED": 0, "UNKNOWN": 0}
            for disk_id, disk in all_disks.items():
                health = disk.get("health", "UNKNOWN")
                health_counts[health] = health_counts.get(health, 0) + 1
                entry = {
                    "device": disk.get("device", disk_id),
                    "source": disk.get("source", "local"),
                    "source_host": disk.get("source_host", ""),
                    "model": disk.get("model", ""),
                    "health": health,
                    "temperature": disk.get("temperature"),
                    "reallocated_sectors": disk.get("reallocated_sectors", 0),
                    "pending_sectors": disk.get("pending_sectors", 0),
                    "last_checked": disk.get("last_polled", ""),
                }
                disk_summary.append(entry)
                if health in ("FAILED", "CRITICAL"):
                    failed_disks.append(entry)
        except Exception as e:
            disk_summary = [{"error": str(e)}]

    # VM summary
    vm_summary = []
    if vm_controller:
        try:
            endpoints = vm_controller.list_endpoints()
            for ep in endpoints:
                vm_summary.append({
                    "name": ep.get("name", ""),
                    "platform": ep.get("platform", ""),
                    "host": ep.get("host", ""),
                    "connected": ep.get("connected", False),
                })
        except Exception:
            pass

    # Storage summary
    storage_summary = []
    if storage_controller:
        try:
            endpoints = storage_controller.list_endpoints()
            for ep in endpoints:
                storage_summary.append({
                    "name": ep.get("name", ""),
                    "platform": ep.get("platform", ""),
                    "host": ep.get("host", ""),
                    "connected": ep.get("connected", False),
                })
        except Exception:
            pass

    # Overall health
    total_hosts = len(hosts)
    online_hosts = sum(1 for h in hosts.values() if h.get("status") == "online")
    hosts_with_updates = sum(1 for h in hosts.values() if h.get("pending_updates"))
    hosts_with_security = sum(1 for h in hosts.values() if h.get("security_updates"))

    overall_state = "OK"
    if failed_disks or hosts_with_security > 0:
        overall_state = "CRITICAL"
    elif hosts_with_updates > 0 or (total_hosts > 0 and online_hosts < total_hosts):
        overall_state = "WARNING"

    return {
        "generated_at": now,
        "fleetpilot_version": "2.0",
        "overall_state": overall_state,
        "summary": {
            "hosts_total": total_hosts,
            "hosts_online": online_hosts,
            "hosts_offline": total_hosts - online_hosts,
            "hosts_with_pending_updates": hosts_with_updates,
            "hosts_with_security_updates": hosts_with_security,
            "disks_total": len(disk_summary),
            "disks_failed": len(failed_disks),
            "vm_endpoints": len(vm_summary),
            "storage_endpoints": len(storage_summary),
        },
        "hosts": host_summary,
        "disks": disk_summary,
        "failed_disks": failed_disks,
        "vm_endpoints": vm_summary,
        "storage_endpoints": storage_summary,
    }


# ─── CheckMK local-check shell script generator ───────────────────────────────

LOCAL_CHECK_SCRIPT_TEMPLATE = """\
#!/bin/bash
# FleetPilot CheckMK Local Check Script
# Generated by FleetPilot — place in /usr/lib/check_mk_agent/local/
# Make executable: chmod +x /usr/lib/check_mk_agent/local/fleetpilot_check
#
# This script queries the FleetPilot REST API and outputs
# CheckMK-compatible local check lines.
#
# Configuration:
FLEETPILOT_URL="{base_url}"
FLEETPILOT_TOKEN="{api_token}"
TIMEOUT=10

# Fetch data from FleetPilot
RESPONSE=$(curl -sf --max-time "$TIMEOUT" \\
  -H "X-FleetPilot-Token: $FLEETPILOT_TOKEN" \\
  "$FLEETPILOT_URL/api/checkmk/agent" 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$RESPONSE" ]; then
  echo '2 "FleetPilot Agent" - FleetPilot API unreachable'
  exit 0
fi

# Output the agent data directly (already in <<<local>>> format)
echo "$RESPONSE"
"""

PIGGYBACK_SCRIPT_TEMPLATE = """\
#!/bin/bash
# FleetPilot CheckMK Piggyback Script
# Outputs per-host piggyback data for all configured FleetPilot hosts.
# Place in /usr/lib/check_mk_agent/local/fleetpilot_piggyback
#
FLEETPILOT_URL="{base_url}"
FLEETPILOT_TOKEN="{api_token}"
TIMEOUT=10

# Fetch all host names
HOSTS=$(curl -sf --max-time "$TIMEOUT" \\
  -H "X-FleetPilot-Token: $FLEETPILOT_TOKEN" \\
  "$FLEETPILOT_URL/api/checkmk/hosts" 2>/dev/null | python3 -c "
import sys,json
data=json.load(sys.stdin)
print(' '.join(h['name'] for h in data.get('hosts',[])))
" 2>/dev/null)

for HOST in $HOSTS; do
  curl -sf --max-time "$TIMEOUT" \\
    -H "X-FleetPilot-Token: $FLEETPILOT_TOKEN" \\
    "$FLEETPILOT_URL/api/checkmk/host/$HOST" 2>/dev/null
done
"""
