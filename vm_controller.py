"""
FleetPilot — VM Controller
===========================
Manages virtual machines on Proxmox VE and Veeam Backup & Replication servers.

Supported platforms:
  - Proxmox VE 7/8  (REST API v2)
  - Veeam Backup & Replication 12  (REST API v1.2)

All connections are stored in the SQLite database (vm_endpoints table).
Credentials are stored encrypted with Fernet (symmetric key in SECRET_KEY env var).
"""

import os
import json
import sqlite3
import logging
import threading
import urllib.request
import urllib.error
import ssl
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

logger = logging.getLogger("fleetpilot.vm_controller")

DB_FILE = Path(__file__).parent / "vm_controller.db"

# ── Encryption helpers (simple base64 if cryptography not available) ──────────
try:
    from cryptography.fernet import Fernet
    _FERNET_KEY = os.environ.get("SECRET_KEY", "").encode()[:32].ljust(32, b"0")
    import base64
    _fernet = Fernet(base64.urlsafe_b64encode(_FERNET_KEY))
    def _encrypt(s: str) -> str:
        return _fernet.encrypt(s.encode()).decode()
    def _decrypt(s: str) -> str:
        return _fernet.decrypt(s.encode()).decode()
except Exception:
    import base64
    def _encrypt(s: str) -> str:
        return base64.b64encode(s.encode()).decode()
    def _decrypt(s: str) -> str:
        return base64.b64decode(s.encode()).decode()


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS vm_endpoints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            platform    TEXT NOT NULL,   -- proxmox | veeam
            host        TEXT NOT NULL,
            port        INTEGER DEFAULT 8006,
            username    TEXT NOT NULL,
            password    TEXT NOT NULL,   -- encrypted
            verify_ssl  INTEGER DEFAULT 0,
            enabled     INTEGER DEFAULT 1,
            notes       TEXT DEFAULT '',
            added_ts    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS vm_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id INTEGER,
            vm_id       TEXT,
            vm_name     TEXT,
            snap_name   TEXT,
            snap_desc   TEXT,
            created_ts  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS vm_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id INTEGER,
            vm_id       TEXT,
            vm_name     TEXT,
            action      TEXT,
            status      TEXT,
            message     TEXT,
            ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)


# ── Endpoint CRUD ─────────────────────────────────────────────────────────────

def add_endpoint(name: str, platform: str, host: str, port: int,
                 username: str, password: str, verify_ssl: bool = False,
                 notes: str = "") -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO vm_endpoints(name,platform,host,port,username,password,verify_ssl,notes) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (name, platform, host, port, username, _encrypt(password),
             1 if verify_ssl else 0, notes)
        )
        return cur.lastrowid


def list_endpoints() -> List[Dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM vm_endpoints ORDER BY added_ts DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("password", None)   # never expose encrypted password
        result.append(d)
    return result


def get_endpoint(ep_id: int) -> Optional[Dict]:
    with get_db() as db:
        row = db.execute("SELECT * FROM vm_endpoints WHERE id=?", (ep_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["password_plain"] = _decrypt(d["password"])
    except Exception:
        d["password_plain"] = ""
    return d


def delete_endpoint(ep_id: int):
    with get_db() as db:
        db.execute("DELETE FROM vm_endpoints WHERE id=?", (ep_id,))


def log_event(endpoint_id: int, vm_id: str, vm_name: str,
              action: str, status: str, message: str = ""):
    with get_db() as db:
        db.execute(
            "INSERT INTO vm_events(endpoint_id,vm_id,vm_name,action,status,message) "
            "VALUES (?,?,?,?,?,?)",
            (endpoint_id, vm_id, vm_name, action, status, message)
        )


def get_events(limit: int = 100) -> List[Dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT e.*, ep.name AS endpoint_name, ep.platform "
            "FROM vm_events e LEFT JOIN vm_endpoints ep ON e.endpoint_id=ep.id "
            "ORDER BY e.ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── HTTP helper ───────────────────────────────────────────────────────────────

import time as _time_mod

# Transient network errors that are safe to retry
_RETRYABLE_ERRORS = (TimeoutError, ConnectionResetError, ConnectionRefusedError)


def _http(method: str, url: str, headers: Dict = None,
          body: Any = None, verify_ssl: bool = False,
          timeout: int = 10, retries: int = 3, backoff: float = 1.0) -> Dict:
    """Minimal HTTP client using stdlib only.

    Automatically retries on transient network errors (timeout, connection
    reset, connection refused) with exponential back-off.  HTTP-level errors
    (4xx / 5xx) are *not* retried because they indicate a server-side problem.

    Args:
        retries:  Maximum number of *additional* attempts after the first
                  failure (default 3 → up to 4 total attempts).
        backoff:  Base delay in seconds between retries; doubles each attempt
                  (1 s → 2 s → 4 s by default).
    """
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    data = None
    if body is not None:
        if isinstance(body, dict):
            data = json.dumps(body).encode()
            headers = headers or {}
            headers["Content-Type"] = "application/json"
        else:
            data = body if isinstance(body, bytes) else str(body).encode()

    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)

    last_error: str = ""
    attempt = 0
    while attempt <= retries:
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    return {"ok": True, "status": resp.status, "data": json.loads(raw)}
                except json.JSONDecodeError:
                    return {"ok": True, "status": resp.status, "data": raw}
        except urllib.error.HTTPError as e:
            # HTTP errors are definitive — do not retry
            raw = e.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": e.code, "error": raw}
        except Exception as exc:
            last_error = str(exc)
            # Only retry on transient network/timeout errors
            is_transient = (
                isinstance(exc, _RETRYABLE_ERRORS)
                or "timed out" in last_error.lower()
                or "connection" in last_error.lower()
                or "reset" in last_error.lower()
            )
            if is_transient and attempt < retries:
                delay = backoff * (2 ** attempt)
                logger.warning(
                    "_http %s %s — transient error (attempt %d/%d): %s. "
                    "Retrying in %.1fs…",
                    method, url, attempt + 1, retries + 1, last_error, delay
                )
                _time_mod.sleep(delay)
                attempt += 1
                continue
            # Non-transient error or retries exhausted
            break

    return {"ok": False, "status": 0, "error": last_error}


# ══════════════════════════════════════════════════════════════════════════════
# Proxmox VE Client
# ══════════════════════════════════════════════════════════════════════════════

class ProxmoxClient:
    """Proxmox VE REST API v2 client."""

    def __init__(self, host: str, port: int, username: str, password: str,
                 verify_ssl: bool = False):
        self.base = f"https://{host}:{port}/api2/json"
        self.verify_ssl = verify_ssl
        self._ticket = None
        self._csrf = None
        self._login(username, password)

    def _login(self, username: str, password: str):
        resp = _http("POST", f"{self.base}/access/ticket",
                     body=f"username={urllib.parse.quote(username)}&password={urllib.parse.quote(password)}",
                     headers={"Content-Type": "application/x-www-form-urlencoded"},
                     verify_ssl=self.verify_ssl)
        if resp["ok"] and isinstance(resp["data"], dict):
            d = resp["data"].get("data", {})
            self._ticket = d.get("ticket")
            self._csrf = d.get("CSRFPreventionToken")
        else:
            raise ConnectionError(f"Proxmox login failed: {resp.get('error', resp)}")

    def _headers(self, write: bool = False) -> Dict:
        h = {"Cookie": f"PVEAuthCookie={self._ticket}"}
        if write:
            h["CSRFPreventionToken"] = self._csrf
        return h

    def _get(self, path: str) -> Dict:
        return _http("GET", f"{self.base}{path}", headers=self._headers(),
                     verify_ssl=self.verify_ssl)

    def _post(self, path: str, body: Any = None) -> Dict:
        return _http("POST", f"{self.base}{path}", headers=self._headers(write=True),
                     body=body, verify_ssl=self.verify_ssl)

    def get_nodes(self) -> List[Dict]:
        r = self._get("/nodes")
        if r["ok"]:
            return r["data"].get("data", [])
        return []

    def get_vms(self) -> List[Dict]:
        """Return all VMs and LXC containers across all nodes."""
        vms = []
        for node in self.get_nodes():
            n = node["node"]
            for rtype in ("qemu", "lxc"):
                r = self._get(f"/nodes/{n}/{rtype}")
                if r["ok"]:
                    for vm in r["data"].get("data", []):
                        vm["node"] = n
                        vm["type"] = rtype
                        vm["platform"] = "proxmox"
                        vms.append(vm)
        return vms

    def get_vm_status(self, node: str, vmid: int, rtype: str = "qemu") -> Dict:
        r = self._get(f"/nodes/{node}/{rtype}/{vmid}/status/current")
        return r["data"].get("data", {}) if r["ok"] else {}

    def vm_action(self, node: str, vmid: int, action: str,
                  rtype: str = "qemu") -> Dict:
        """action: start | stop | shutdown | reboot | suspend | resume"""
        return self._post(f"/nodes/{node}/{rtype}/{vmid}/status/{action}")

    def get_snapshots(self, node: str, vmid: int, rtype: str = "qemu") -> List[Dict]:
        r = self._get(f"/nodes/{node}/{rtype}/{vmid}/snapshot")
        return r["data"].get("data", []) if r["ok"] else []

    def create_snapshot(self, node: str, vmid: int, snap_name: str,
                        description: str = "", rtype: str = "qemu") -> Dict:
        return self._post(
            f"/nodes/{node}/{rtype}/{vmid}/snapshot",
            body={"snapname": snap_name, "description": description}
        )

    def get_storage(self, node: str) -> List[Dict]:
        r = self._get(f"/nodes/{node}/storage")
        return r["data"].get("data", []) if r["ok"] else []

    def get_disks(self, node: str) -> List[Dict]:
        r = self._get(f"/nodes/{node}/disks/list")
        return r["data"].get("data", []) if r["ok"] else []

    def get_disk_smart(self, node: str, disk: str) -> Dict:
        import urllib.parse
        r = self._get(f"/nodes/{node}/disks/smart?disk={urllib.parse.quote(disk)}")
        return r["data"].get("data", {}) if r["ok"] else {}

    def get_cluster_resources(self) -> List[Dict]:
        r = self._get("/cluster/resources")
        return r["data"].get("data", []) if r["ok"] else []


# ══════════════════════════════════════════════════════════════════════════════
# Veeam Backup & Replication Client
# ══════════════════════════════════════════════════════════════════════════════

class VeeamClient:
    """Veeam Backup & Replication REST API v1.2 client."""

    def __init__(self, host: str, port: int, username: str, password: str,
                 verify_ssl: bool = False):
        self.base = f"https://{host}:{port}/api/v1"
        self.verify_ssl = verify_ssl
        self._token = None
        self._login(username, password)

    def _login(self, username: str, password: str):
        import base64
        creds = base64.b64encode(f"{username}:{password}".encode()).decode()
        resp = _http("POST", f"{self.base}/token",
                     headers={"Authorization": f"Basic {creds}",
                               "Content-Type": "application/x-www-form-urlencoded",
                               "x-api-version": "1.2-rev0"},
                     body="grant_type=password",
                     verify_ssl=self.verify_ssl)
        if resp["ok"] and isinstance(resp["data"], dict):
            self._token = resp["data"].get("access_token")
        else:
            raise ConnectionError(f"Veeam login failed: {resp.get('error', resp)}")

    def _headers(self) -> Dict:
        return {"Authorization": f"Bearer {self._token}",
                "x-api-version": "1.2-rev0",
                "Accept": "application/json"}

    def _get(self, path: str, params: str = "") -> Dict:
        url = f"{self.base}{path}"
        if params:
            url += "?" + params
        return _http("GET", url, headers=self._headers(), verify_ssl=self.verify_ssl)

    def _post(self, path: str, body: Any = None) -> Dict:
        return _http("POST", f"{self.base}{path}", headers=self._headers(),
                     body=body, verify_ssl=self.verify_ssl)

    def get_jobs(self) -> List[Dict]:
        r = self._get("/jobs")
        if r["ok"] and isinstance(r["data"], dict):
            return r["data"].get("data", [])
        return []

    def get_job_states(self) -> List[Dict]:
        r = self._get("/jobStates")
        if r["ok"] and isinstance(r["data"], dict):
            return r["data"].get("data", [])
        return []

    def get_sessions(self, limit: int = 50) -> List[Dict]:
        r = self._get("/sessions", f"limit={limit}")
        if r["ok"] and isinstance(r["data"], dict):
            return r["data"].get("data", [])
        return []

    def start_job(self, job_id: str) -> Dict:
        return self._post(f"/jobs/{job_id}/start")

    def stop_job(self, job_id: str) -> Dict:
        return self._post(f"/jobs/{job_id}/stop")

    def get_managed_servers(self) -> List[Dict]:
        r = self._get("/backupInfrastructure/managedServers")
        if r["ok"] and isinstance(r["data"], dict):
            return r["data"].get("data", [])
        return []

    def get_repositories(self) -> List[Dict]:
        r = self._get("/backupInfrastructure/repositories")
        if r["ok"] and isinstance(r["data"], dict):
            return r["data"].get("data", [])
        return []


# ── urllib.parse shim (needed for ProxmoxClient._login) ──────────────────────
import urllib.parse


# ── High-level API used by Flask routes ──────────────────────────────────────

def connect(ep_id: int):
    """Return a connected client for the given endpoint, or raise."""
    ep = get_endpoint(ep_id)
    if not ep:
        raise ValueError(f"Endpoint {ep_id} not found")
    platform = ep["platform"]
    host = ep["host"]
    port = ep["port"]
    user = ep["username"]
    pwd  = ep["password_plain"]
    ssl_ = bool(ep.get("verify_ssl", 0))
    if platform == "proxmox":
        return ProxmoxClient(host, port, user, pwd, ssl_)
    elif platform == "veeam":
        return VeeamClient(host, port, user, pwd, ssl_)
    else:
        raise ValueError(f"Unknown platform: {platform}")


def test_connection(ep_id: int) -> Dict:
    """Try to connect and return a status dict."""
    try:
        client = connect(ep_id)
        if isinstance(client, ProxmoxClient):
            nodes = client.get_nodes()
            return {"ok": True, "message": f"Connected — {len(nodes)} node(s) found"}
        elif isinstance(client, VeeamClient):
            jobs = client.get_jobs()
            return {"ok": True, "message": f"Connected — {len(jobs)} backup job(s) found"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def get_all_vms(ep_id: int) -> List[Dict]:
    """Return all VMs/containers for a Proxmox endpoint."""
    client = connect(ep_id)
    if isinstance(client, ProxmoxClient):
        return client.get_vms()
    return []


def get_all_jobs(ep_id: int) -> List[Dict]:
    """Return all backup jobs for a Veeam endpoint."""
    client = connect(ep_id)
    if isinstance(client, VeeamClient):
        jobs = client.get_jobs()
        states = {s["id"]: s for s in client.get_job_states()}
        for j in jobs:
            j["state"] = states.get(j.get("id"), {})
        return jobs
    return []


def vm_power_action(ep_id: int, node: str, vmid: int, action: str,
                    rtype: str = "qemu") -> Dict:
    """Perform a power action on a Proxmox VM."""
    client = connect(ep_id)
    if not isinstance(client, ProxmoxClient):
        return {"ok": False, "error": "Not a Proxmox endpoint"}
    result = client.vm_action(node, vmid, action, rtype)
    status = "ok" if result.get("ok") else "error"
    log_event(ep_id, str(vmid), f"{node}/{vmid}", action.upper(), status,
              result.get("error", ""))
    return result


def get_proxmox_disks(ep_id: int, node: str) -> List[Dict]:
    """Return physical disks from a Proxmox node."""
    client = connect(ep_id)
    if isinstance(client, ProxmoxClient):
        return client.get_disks(node)
    return []


def get_proxmox_disk_smart(ep_id: int, node: str, disk: str) -> Dict:
    """Return SMART data for a disk on a Proxmox node."""
    client = connect(ep_id)
    if isinstance(client, ProxmoxClient):
        return client.get_disk_smart(node, disk)
    return {}
