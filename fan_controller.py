"""
fan_controller.py — FleetPilot Universal Fan Controller Integration

Supports the following controller types (all via SSH to remote hosts):

  TYPE          TOOL            USE CASE
  ──────────────────────────────────────────────────────────────────
  lm_sensors    lm-sensors      Linux PCs / servers (PWM via sysfs)
  ipmi          ipmitool        Servers with IPMI/BMC (Dell iDRAC,
                                HP iLO, Supermicro IPMI, etc.)
  nbfc          nbfc-linux      Laptops (NoteBook FanControl)
  liquidctl     liquidctl       NZXT, Aquacomputer, Corsair (non-Pro),
                                Kraken, Smart Device, etc.
  pwm_sysfs     (built-in)      Direct /sys/class/hwmon PWM control
                                (advanced, no extra tool needed)

Architecture:
  FleetPilot (Unraid) ──SSH──▶ Remote host ──▶ Fan controller

Database: DATA_DIR/fan_controller.db

Package installation:
  Each controller type knows which packages it needs.
  install_packages(dev_id) installs them via SSH (apt / pip).
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Encryption helpers ────────────────────────────────────────────────────────
try:
    from cryptography.fernet import Fernet
    _SECRET = os.environ.get("SECRET_KEY", "").encode()
    if len(_SECRET) >= 32:
        import base64
        _FKEY = Fernet(base64.urlsafe_b64encode(_SECRET[:32]))
        def _encrypt(s: str) -> str:
            return _FKEY.encrypt(s.encode()).decode()
        def _decrypt(s: str) -> str:
            return _FKEY.decrypt(s.encode()).decode()
    else:
        raise ValueError("key too short")
except Exception:
    def _encrypt(s: str) -> str: return s
    def _decrypt(s: str) -> str: return s

# ── Controller type registry ──────────────────────────────────────────────────

CONTROLLER_TYPES = {
    "lm_sensors": {
        "label": "lm-sensors (Linux PWM)",
        "description": "Linux PCs and servers — reads temperatures via lm-sensors, controls fans via PWM sysfs nodes (/sys/class/hwmon).",
        "icon": "🌡",
        "packages_apt": ["lm-sensors", "fancontrol"],
        "packages_pip": [],
        "check_cmd": "sensors --version 2>&1 | head -1",
        "detect_cmd": "sensors -j 2>/dev/null | head -5",
    },
    "ipmi": {
        "label": "IPMI / ipmitool (Server BMC)",
        "description": "Servers with IPMI/BMC: Dell iDRAC, HP iLO, Supermicro, generic IPMI. Controls fans via raw IPMI commands.",
        "icon": "🖥",
        "packages_apt": ["ipmitool"],
        "packages_pip": [],
        "check_cmd": "ipmitool -V 2>&1 | head -1",
        "detect_cmd": "ipmitool sdr type Fan 2>&1 | head -10",
    },
    "nbfc": {
        "label": "nbfc-linux (Laptop Fan Control)",
        "description": "Laptops running Linux — uses NoteBook FanControl (nbfc-linux) to read and set fan speeds.",
        "icon": "💻",
        "packages_apt": [],
        "packages_pip": [],
        "check_cmd": "nbfc status --version 2>&1 | head -1 || nbfc --version 2>&1 | head -1",
        "detect_cmd": "nbfc status -a 2>&1 | head -20",
        "install_note": "nbfc-linux must be installed manually: https://github.com/nbfc-linux/nbfc-linux",
    },
    "liquidctl": {
        "label": "liquidctl (NZXT / Aquacomputer / Kraken)",
        "description": "NZXT Smart Device, Kraken AIO, Aquacomputer Quadro/Octo, HUE 2, and other USB fan/pump controllers.",
        "icon": "💧",
        "packages_apt": ["liquidctl"],
        "packages_pip": ["liquidctl"],
        "check_cmd": "liquidctl --version 2>&1 | head -1",
        "detect_cmd": "liquidctl list --json 2>/dev/null || liquidctl list 2>&1 | head -20",
    },
    "pwm_sysfs": {
        "label": "PWM sysfs (Direct kernel control)",
        "description": "Direct control of PWM fan outputs via Linux kernel sysfs (/sys/class/hwmon/hwmonX/pwmY). No extra tool needed.",
        "icon": "⚙",
        "packages_apt": ["lm-sensors"],
        "packages_pip": [],
        "check_cmd": "ls /sys/class/hwmon/ 2>&1",
        "detect_cmd": "for h in /sys/class/hwmon/hwmon*; do echo \"=== $h ===\"; cat $h/name 2>/dev/null; ls $h/pwm* 2>/dev/null; done",
    },
}

# ── Module state ──────────────────────────────────────────────────────────────
_DB_FILE: Optional[Path] = None
_poll_thread: Optional[threading.Thread] = None
_poll_running = False
_POLL_INTERVAL = 30
_RETENTION_DAYS = 30

# ── Database ──────────────────────────────────────────────────────────────────

def _get_db():
    conn = sqlite3.connect(str(_DB_FILE), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(data_dir: str):
    global _DB_FILE
    _DB_FILE = Path(data_dir) / "fan_controller.db"
    with _get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS fc_devices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL UNIQUE,
            controller_type TEXT NOT NULL DEFAULT 'lm_sensors',
            host            TEXT NOT NULL,
            port            INTEGER DEFAULT 22,
            username        TEXT NOT NULL DEFAULT 'root',
            password        TEXT NOT NULL DEFAULT '',
            ssh_key         TEXT NOT NULL DEFAULT '',
            extra_config    TEXT NOT NULL DEFAULT '{}',
            enabled         INTEGER DEFAULT 1,
            notes           TEXT DEFAULT '',
            added_ts        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS fc_samples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id   INTEGER NOT NULL,
            ts          INTEGER NOT NULL,
            status_json TEXT NOT NULL,
            FOREIGN KEY(device_id) REFERENCES fc_devices(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fc_samples_ts ON fc_samples(device_id, ts);
        """)
    logger.info("fan_controller DB initialised at %s", _DB_FILE)


# ── Device CRUD ───────────────────────────────────────────────────────────────

def add_device(name: str, controller_type: str, host: str, port: int = 22,
               username: str = "root", password: str = "", ssh_key: str = "",
               extra_config: dict = None, notes: str = "") -> int:
    extra = json.dumps(extra_config or {})
    with _get_db() as db:
        cur = db.execute(
            "INSERT INTO fc_devices(name,controller_type,host,port,username,"
            "password,ssh_key,extra_config,notes) VALUES (?,?,?,?,?,?,?,?,?)",
            (name, controller_type, host, port, username,
             _encrypt(password), ssh_key, extra, notes)
        )
        return cur.lastrowid


def list_devices() -> List[Dict]:
    with _get_db() as db:
        rows = db.execute(
            "SELECT * FROM fc_devices ORDER BY added_ts DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("password", None)
        try:
            d["extra_config"] = json.loads(d.get("extra_config") or "{}")
        except Exception:
            d["extra_config"] = {}
        d["type_info"] = CONTROLLER_TYPES.get(d["controller_type"], {})
        result.append(d)
    return result


def get_device(dev_id: int) -> Optional[Dict]:
    with _get_db() as db:
        row = db.execute(
            "SELECT * FROM fc_devices WHERE id=?", (dev_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["password_plain"] = _decrypt(d["password"])
    except Exception:
        d["password_plain"] = ""
    try:
        d["extra_config"] = json.loads(d.get("extra_config") or "{}")
    except Exception:
        d["extra_config"] = {}
    d["type_info"] = CONTROLLER_TYPES.get(d["controller_type"], {})
    return d


def update_device(dev_id: int, **kwargs) -> bool:
    allowed = {"name", "controller_type", "host", "port", "username",
               "password", "ssh_key", "extra_config", "enabled", "notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if "password" in fields:
        fields["password"] = _encrypt(fields["password"])
    if "extra_config" in fields and isinstance(fields["extra_config"], dict):
        fields["extra_config"] = json.dumps(fields["extra_config"])
    if not fields:
        return False
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with _get_db() as db:
        db.execute(
            f"UPDATE fc_devices SET {set_clause} WHERE id=?",
            list(fields.values()) + [dev_id]
        )
    return True


def delete_device(dev_id: int):
    with _get_db() as db:
        db.execute("DELETE FROM fc_devices WHERE id=?", (dev_id,))


# ── SSH helpers ───────────────────────────────────────────────────────────────

def _ssh_connect(dev: Dict):
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(
        hostname=dev["host"],
        port=dev.get("port", 22),
        username=dev.get("username", "root"),
        timeout=15,
    )
    pw = dev.get("password_plain") or dev.get("password", "")
    key_path = dev.get("ssh_key", "")
    if key_path and Path(key_path).exists():
        kwargs["key_filename"] = key_path
    elif pw:
        kwargs["password"] = pw
        kwargs["look_for_keys"] = False
        kwargs["allow_agent"] = False
    ssh.connect(**kwargs)
    return ssh


def _run_remote(ssh, cmd: str, timeout: int = 60) -> Tuple[str, str, int]:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return out, err, code


# ── Package installation ──────────────────────────────────────────────────────

def install_packages(dev_id: int, progress_key: str = None) -> Dict:
    """
    Install required packages for the controller type on the remote host.
    Uses apt-get (Debian/Ubuntu/Proxmox) or pip3 as fallback.
    Streams output to progress log if progress_key is given.
    """
    dev = get_device(dev_id)
    if not dev:
        return {"ok": False, "message": "Device not found"}

    ctype = dev.get("controller_type", "lm_sensors")
    type_info = CONTROLLER_TYPES.get(ctype, {})
    apt_pkgs = type_info.get("packages_apt", [])
    pip_pkgs = type_info.get("packages_pip", [])
    install_note = type_info.get("install_note", "")

    lines = []

    def _log(msg: str):
        lines.append(msg)
        logger.info("[fan_controller] install: %s", msg)
        if progress_key:
            try:
                from app import _progress_logs
                _progress_logs.setdefault(progress_key, []).append(msg)
            except Exception:
                pass

    ssh = None
    try:
        _log(f"Connecting to {dev['host']}:{dev.get('port', 22)} as {dev.get('username', 'root')}...")
        ssh = _ssh_connect(dev)
        _log("Connected.")

        # Detect OS / package manager
        out, _, _ = _run_remote(ssh, "cat /etc/os-release 2>/dev/null | grep -E '^ID=|^ID_LIKE=' | head -3", timeout=10)
        is_debian = any(x in out.lower() for x in ["debian", "ubuntu", "proxmox", "raspbian"])
        is_arch = "arch" in out.lower()
        is_fedora = any(x in out.lower() for x in ["fedora", "rhel", "centos"])

        # Detect if running as root
        whoami_out, _, _ = _run_remote(ssh, "whoami", timeout=5)
        is_root = whoami_out.strip() == "root"
        sudo_prefix = "" if is_root else "sudo "

        if apt_pkgs and is_debian:
            _log(f"Updating apt cache...")
            out, err, code = _run_remote(
                ssh,
                f"DEBIAN_FRONTEND=noninteractive {sudo_prefix}apt-get update -qq 2>&1",
                timeout=120
            )
            _log(out or err or "apt update done")

            pkgs_str = " ".join(apt_pkgs)
            _log(f"Installing: {pkgs_str}")
            out, err, code = _run_remote(
                ssh,
                f"DEBIAN_FRONTEND=noninteractive {sudo_prefix}apt-get install -y {pkgs_str} 2>&1",
                timeout=300
            )
            for line in (out or err or "").splitlines():
                _log(line)
            if code == 0:
                _log(f"✔ apt packages installed successfully.")
            else:
                _log(f"✘ apt install failed (exit {code})")

        elif apt_pkgs and is_arch:
            pkgs_str = " ".join(apt_pkgs)
            _log(f"Installing via pacman: {pkgs_str}")
            out, err, code = _run_remote(
                ssh,
                f"{sudo_prefix}pacman -Sy --noconfirm {pkgs_str} 2>&1",
                timeout=300
            )
            for line in (out or err or "").splitlines():
                _log(line)

        elif apt_pkgs and is_fedora:
            pkgs_str = " ".join(apt_pkgs)
            _log(f"Installing via dnf: {pkgs_str}")
            out, err, code = _run_remote(
                ssh,
                f"{sudo_prefix}dnf install -y {pkgs_str} 2>&1",
                timeout=300
            )
            for line in (out or err or "").splitlines():
                _log(line)

        elif apt_pkgs:
            _log("⚠ Unknown OS — trying apt-get anyway...")
            pkgs_str = " ".join(apt_pkgs)
            out, err, code = _run_remote(
                ssh,
                f"DEBIAN_FRONTEND=noninteractive {sudo_prefix}apt-get install -y {pkgs_str} 2>&1",
                timeout=300
            )
            for line in (out or err or "").splitlines():
                _log(line)

        # pip fallback for liquidctl
        if pip_pkgs:
            for pkg in pip_pkgs:
                _log(f"Installing via pip3: {pkg}")
                out, err, code = _run_remote(
                    ssh,
                    f"{sudo_prefix}pip3 install --upgrade {pkg} 2>&1",
                    timeout=120
                )
                for line in (out or err or "").splitlines():
                    _log(line)

        if install_note:
            _log(f"ℹ Note: {install_note}")

        # Verify installation
        check_cmd = type_info.get("check_cmd", "echo 'no check'")
        _log(f"Verifying: {check_cmd}")
        out, err, code = _run_remote(ssh, check_cmd, timeout=15)
        _log(out or err or "(no output)")
        if code == 0:
            _log("✔ Installation verified successfully.")
            return {"ok": True, "message": "\n".join(lines)}
        else:
            _log("⚠ Verification returned non-zero — check manually.")
            return {"ok": True, "message": "\n".join(lines)}

    except Exception as exc:
        _log(f"✘ Error: {exc}")
        return {"ok": False, "message": "\n".join(lines)}
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


# ── Status fetching ───────────────────────────────────────────────────────────

def fetch_status(dev: Dict) -> Dict:
    """Dispatch to the correct fetch function based on controller_type."""
    ctype = dev.get("controller_type", "lm_sensors")
    fetchers = {
        "lm_sensors": _fetch_lm_sensors,
        "ipmi":       _fetch_ipmi,
        "nbfc":       _fetch_nbfc,
        "liquidctl":  _fetch_liquidctl,
        "pwm_sysfs":  _fetch_pwm_sysfs,
    }
    fn = fetchers.get(ctype, _fetch_lm_sensors)
    return fn(dev)


def _base_result(dev: Dict) -> Dict:
    return {
        "ok": False,
        "error": None,
        "device": dev.get("name", ""),
        "controller_type": dev.get("controller_type", ""),
        "temperatures": [],
        "fans": [],
        "voltages": [],
        "raw": "",
        "ts": int(time.time()),
    }


# ── lm-sensors ────────────────────────────────────────────────────────────────

def _fetch_lm_sensors(dev: Dict) -> Dict:
    result = _base_result(dev)
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        out, err, code = _run_remote(ssh, "sensors -j 2>/dev/null || sensors 2>&1", timeout=20)
        result["raw"] = out or err

        # Try JSON first
        try:
            data = json.loads(out)
            for chip_name, chip_data in data.items():
                if not isinstance(chip_data, dict):
                    continue
                for feature_name, feature_data in chip_data.items():
                    if not isinstance(feature_data, dict):
                        continue
                    for key, val in feature_data.items():
                        if not isinstance(val, (int, float)):
                            continue
                        if "temp" in key.lower() or "input" in key.lower() and "temp" in feature_name.lower():
                            result["temperatures"].append({
                                "label": f"{chip_name} / {feature_name}",
                                "value": round(float(val), 1),
                                "unit": "°C",
                            })
                        elif "fan" in feature_name.lower() and "input" in key.lower():
                            result["fans"].append({
                                "label": f"{chip_name} / {feature_name}",
                                "rpm": int(val),
                            })
                        elif "in" in feature_name.lower() and "input" in key.lower():
                            result["voltages"].append({
                                "label": f"{chip_name} / {feature_name}",
                                "value": round(float(val), 3),
                                "unit": "V",
                            })
        except (json.JSONDecodeError, AttributeError):
            # Fallback: parse text output
            for line in (out or err or "").splitlines():
                m = re.match(r"(.+?):\s+([\d.]+)\s*°C", line)
                if m:
                    result["temperatures"].append({
                        "label": m.group(1).strip(),
                        "value": float(m.group(2)),
                        "unit": "°C",
                    })
                m2 = re.match(r"(.+?):\s+([\d]+)\s*RPM", line, re.IGNORECASE)
                if m2:
                    result["fans"].append({
                        "label": m2.group(1).strip(),
                        "rpm": int(m2.group(2)),
                    })

        # Also read PWM values
        pwm_out, _, _ = _run_remote(
            ssh,
            "for f in /sys/class/hwmon/hwmon*/pwm[0-9]; do "
            "[ -f \"$f\" ] && echo \"$f:$(cat $f)\"; done 2>/dev/null",
            timeout=10
        )
        if pwm_out:
            result["pwm_nodes"] = []
            for line in pwm_out.splitlines():
                if ":" in line:
                    path, val = line.split(":", 1)
                    try:
                        result["pwm_nodes"].append({
                            "path": path.strip(),
                            "value": int(val.strip()),
                            "percent": round(int(val.strip()) / 255 * 100),
                        })
                    except ValueError:
                        pass

        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("[fan_controller] lm_sensors fetch error for %s: %s", dev.get("name"), exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


# ── IPMI ──────────────────────────────────────────────────────────────────────

def _fetch_ipmi(dev: Dict) -> Dict:
    result = _base_result(dev)
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        extra = dev.get("extra_config", {})
        ipmi_host = extra.get("ipmi_host", "localhost")
        ipmi_user = extra.get("ipmi_user", "ADMIN")
        ipmi_pass = extra.get("ipmi_pass", "ADMIN")

        if ipmi_host == "localhost":
            # Local IPMI via /dev/ipmi0
            fan_cmd = "ipmitool sdr type Fan 2>&1"
            temp_cmd = "ipmitool sdr type Temperature 2>&1"
        else:
            # Remote IPMI
            base = f"ipmitool -I lanplus -H {ipmi_host} -U {ipmi_user} -P {ipmi_pass}"
            fan_cmd = f"{base} sdr type Fan 2>&1"
            temp_cmd = f"{base} sdr type Temperature 2>&1"

        # Fans
        out, _, _ = _run_remote(ssh, fan_cmd, timeout=30)
        result["raw"] = out
        for line in out.splitlines():
            # Format: "Fan1             | 2400       | RPM        | ok"
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and "rpm" in parts[2].lower():
                try:
                    result["fans"].append({
                        "label": parts[0],
                        "rpm": int(parts[1]),
                        "status": parts[3] if len(parts) > 3 else "unknown",
                    })
                except (ValueError, IndexError):
                    pass

        # Temperatures
        out2, _, _ = _run_remote(ssh, temp_cmd, timeout=30)
        result["raw"] += "\n" + out2
        for line in out2.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and "degrees" in parts[2].lower():
                try:
                    result["temperatures"].append({
                        "label": parts[0],
                        "value": float(parts[1]),
                        "unit": "°C",
                        "status": parts[3] if len(parts) > 3 else "unknown",
                    })
                except (ValueError, IndexError):
                    pass

        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("[fan_controller] ipmi fetch error for %s: %s", dev.get("name"), exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


# ── nbfc (Laptop) ─────────────────────────────────────────────────────────────

def _fetch_nbfc(dev: Dict) -> Dict:
    result = _base_result(dev)
    ssh = None
    try:
        ssh = _ssh_connect(dev)

        # Try nbfc status -a (all fans)
        out, err, code = _run_remote(ssh, "nbfc status -a 2>&1", timeout=15)
        if code != 0 or not out:
            out, err, code = _run_remote(ssh, "nbfc status 2>&1", timeout=15)
        result["raw"] = out or err

        # Parse nbfc status output
        # Example:
        #   Fan #0
        #     Fan display name  : CPU Fan
        #     Auto control      : True
        #     Critical mode     : False
        #     Current fan speed : 45.0%
        #     Target fan speed  : 45.0%
        #     Fan speed steps   : 100
        current_fan = None
        for line in (out or "").splitlines():
            line = line.strip()
            m_fan = re.match(r"Fan #(\d+)", line)
            if m_fan:
                current_fan = {"label": f"Fan #{m_fan.group(1)}", "rpm": 0, "percent": 0}
                result["fans"].append(current_fan)
                continue
            if current_fan:
                m_name = re.match(r"Fan display name\s*:\s*(.+)", line)
                if m_name:
                    current_fan["label"] = m_name.group(1).strip()
                m_speed = re.match(r"Current fan speed\s*:\s*([\d.]+)%", line)
                if m_speed:
                    current_fan["percent"] = float(m_speed.group(1))
                m_target = re.match(r"Target fan speed\s*:\s*([\d.]+)%", line)
                if m_target:
                    current_fan["target_percent"] = float(m_target.group(1))
                m_auto = re.match(r"Auto control\s*:\s*(\w+)", line)
                if m_auto:
                    current_fan["auto"] = m_auto.group(1).lower() == "true"

        # Also get temperatures via sensors if available
        temp_out, _, temp_code = _run_remote(ssh, "sensors 2>/dev/null | grep -E '°C' | head -10", timeout=10)
        if temp_code == 0 and temp_out:
            for line in temp_out.splitlines():
                m = re.match(r"(.+?):\s+([\d.]+)\s*°C", line)
                if m:
                    result["temperatures"].append({
                        "label": m.group(1).strip(),
                        "value": float(m.group(2)),
                        "unit": "°C",
                    })

        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("[fan_controller] nbfc fetch error for %s: %s", dev.get("name"), exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


# ── liquidctl (NZXT, Aquacomputer, etc.) ──────────────────────────────────────

def _fetch_liquidctl(dev: Dict) -> Dict:
    result = _base_result(dev)
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        extra = dev.get("extra_config", {})
        match_str = extra.get("match_str", "")
        use_direct = extra.get("use_direct", False)

        match_arg = f"--match '{match_str}'" if match_str else ""
        direct_arg = "--direct-access" if use_direct else ""

        # Initialize
        _run_remote(ssh, f"liquidctl {match_arg} {direct_arg} initialize --json 2>/dev/null".strip(), timeout=20)

        # Status
        out, err, code = _run_remote(
            ssh,
            f"liquidctl {match_arg} {direct_arg} status --json 2>/dev/null".strip(),
            timeout=20
        )
        result["raw"] = out or err

        try:
            devices = json.loads(out) if out else []
            if isinstance(devices, dict):
                devices = [devices]
            for device_data in devices:
                for item in device_data.get("status", []):
                    key = item.get("key", "")
                    value = item.get("value")
                    unit = item.get("unit", "")
                    if "temperature" in key.lower() or unit == "°C":
                        try:
                            result["temperatures"].append({"label": key, "value": float(value), "unit": "°C"})
                        except (TypeError, ValueError):
                            pass
                    elif "speed" in key.lower() or unit == "rpm":
                        try:
                            result["fans"].append({"label": key, "rpm": int(float(value))})
                        except (TypeError, ValueError):
                            pass
                    elif unit == "V":
                        try:
                            result["voltages"].append({"label": key, "value": float(value), "unit": "V"})
                        except (TypeError, ValueError):
                            pass
        except (json.JSONDecodeError, TypeError):
            # Text fallback
            for line in (out or err or "").splitlines():
                m = re.match(r"(.+?)\s{2,}([\d.]+)\s+(°C|rpm|V)", line)
                if m:
                    label, val_str, unit = m.group(1).strip(), m.group(2), m.group(3)
                    try:
                        val = float(val_str)
                        if unit == "°C":
                            result["temperatures"].append({"label": label, "value": val, "unit": "°C"})
                        elif unit == "rpm":
                            result["fans"].append({"label": label, "rpm": int(val)})
                        elif unit == "V":
                            result["voltages"].append({"label": label, "value": val, "unit": "V"})
                    except ValueError:
                        pass

        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("[fan_controller] liquidctl fetch error for %s: %s", dev.get("name"), exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


# ── PWM sysfs ─────────────────────────────────────────────────────────────────

def _fetch_pwm_sysfs(dev: Dict) -> Dict:
    result = _base_result(dev)
    ssh = None
    try:
        ssh = _ssh_connect(dev)

        # Read all hwmon chips
        out, _, _ = _run_remote(
            ssh,
            """
for h in /sys/class/hwmon/hwmon*; do
  name=$(cat "$h/name" 2>/dev/null || echo "unknown")
  for f in "$h"/temp*_input; do
    [ -f "$f" ] || continue
    val=$(cat "$f" 2>/dev/null)
    label_file="${f%_input}_label"
    label=$(cat "$label_file" 2>/dev/null || basename "$f")
    echo "TEMP|$name|$label|$val"
  done
  for f in "$h"/fan*_input; do
    [ -f "$f" ] || continue
    val=$(cat "$f" 2>/dev/null)
    echo "FAN|$name|$(basename $f)|$val"
  done
  for f in "$h"/pwm[0-9]; do
    [ -f "$f" ] || continue
    val=$(cat "$f" 2>/dev/null)
    enable_file="${f}_enable"
    enable=$(cat "$enable_file" 2>/dev/null || echo "?")
    echo "PWM|$name|$(basename $f)|$val|$enable"
  done
  for f in "$h"/in*_input; do
    [ -f "$f" ] || continue
    val=$(cat "$f" 2>/dev/null)
    echo "VOLT|$name|$(basename $f)|$val"
  done
done
""",
            timeout=15
        )
        result["raw"] = out
        result["pwm_nodes"] = []

        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) < 4:
                continue
            kind = parts[0]
            chip = parts[1]
            label = parts[2]
            try:
                raw_val = int(parts[3])
            except ValueError:
                continue

            if kind == "TEMP":
                result["temperatures"].append({
                    "label": f"{chip} / {label}",
                    "value": round(raw_val / 1000, 1),
                    "unit": "°C",
                })
            elif kind == "FAN":
                result["fans"].append({
                    "label": f"{chip} / {label}",
                    "rpm": raw_val,
                })
            elif kind == "PWM":
                enable = parts[4] if len(parts) > 4 else "?"
                result["pwm_nodes"].append({
                    "path": f"/sys/class/hwmon/{chip}/{label}",
                    "chip": chip,
                    "label": label,
                    "value": raw_val,
                    "percent": round(raw_val / 255 * 100),
                    "enable_mode": enable,
                })
            elif kind == "VOLT":
                result["voltages"].append({
                    "label": f"{chip} / {label}",
                    "value": round(raw_val / 1000, 3),
                    "unit": "V",
                })

        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("[fan_controller] pwm_sysfs fetch error for %s: %s", dev.get("name"), exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


# ── Fan speed control ─────────────────────────────────────────────────────────

def set_fan_speed(dev: Dict, channel: str, speed, extra: dict = None) -> Dict:
    """
    Set fan speed. Dispatches to the correct method based on controller_type.
    speed: int (percent 0-100 or PWM 0-255) or list of (temp,rpm) pairs
    channel: fan identifier (type-specific)
    """
    ctype = dev.get("controller_type", "lm_sensors")
    setters = {
        "lm_sensors": _set_fan_lm_sensors,
        "ipmi":       _set_fan_ipmi,
        "nbfc":       _set_fan_nbfc,
        "liquidctl":  _set_fan_liquidctl,
        "pwm_sysfs":  _set_fan_pwm_sysfs,
    }
    fn = setters.get(ctype, _set_fan_lm_sensors)
    return fn(dev, channel, speed, extra or {})


def _set_fan_lm_sensors(dev: Dict, channel: str, speed, extra: dict) -> Dict:
    """Set fan via fancontrol / pwmconfig."""
    result = {"ok": False, "message": ""}
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        # channel = PWM sysfs path like "pwm1" or full path
        if channel.startswith("/"):
            pwm_path = channel
        else:
            # Find the pwm node by name
            find_out, _, _ = _run_remote(
                ssh,
                f"find /sys/class/hwmon -name '{channel}' 2>/dev/null | head -1",
                timeout=10
            )
            pwm_path = find_out.strip() or f"/sys/class/hwmon/hwmon0/{channel}"

        # Set PWM enable to manual (1)
        enable_path = pwm_path + "_enable"
        is_root = dev.get("username", "root") == "root"
        sudo = "" if is_root else "sudo "

        out1, err1, c1 = _run_remote(
            ssh,
            f"echo 1 | {sudo}tee {enable_path} 2>&1",
            timeout=10
        )
        # Convert percent to PWM value (0-255)
        if isinstance(speed, (int, float)):
            pwm_val = max(0, min(255, int(speed * 255 / 100)))
        else:
            pwm_val = 128  # default 50%
        out2, err2, c2 = _run_remote(
            ssh,
            f"echo {pwm_val} | {sudo}tee {pwm_path} 2>&1",
            timeout=10
        )
        result["ok"] = (c2 == 0)
        result["message"] = f"Set {pwm_path} to {pwm_val}/255 ({speed}%). {out2 or err2}"
    except Exception as exc:
        result["message"] = str(exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


def _set_fan_ipmi(dev: Dict, channel: str, speed, extra: dict) -> Dict:
    """Set fan speed via IPMI raw commands."""
    result = {"ok": False, "message": ""}
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        cfg = dev.get("extra_config", {})
        ipmi_host = cfg.get("ipmi_host", "localhost")
        ipmi_user = cfg.get("ipmi_user", "ADMIN")
        ipmi_pass = cfg.get("ipmi_pass", "ADMIN")
        vendor = cfg.get("vendor", "generic").lower()

        if isinstance(speed, (int, float)):
            pct = max(0, min(100, int(speed)))
        else:
            pct = 50

        if ipmi_host == "localhost":
            base = "ipmitool"
        else:
            base = f"ipmitool -I lanplus -H {ipmi_host} -U {ipmi_user} -P {ipmi_pass}"

        if "dell" in vendor or "idrac" in vendor:
            # Dell iDRAC: disable auto fan control, set manual speed
            hex_pct = hex(pct)
            cmds = [
                f"{base} raw 0x30 0x30 0x01 0x00",  # disable auto
                f"{base} raw 0x30 0x30 0x02 0xff {hex_pct}",  # set speed
            ]
        elif "hp" in vendor or "ilo" in vendor:
            # HP iLO: fan control via raw
            cmds = [f"{base} raw 0x04 0x30 0x{pct:02x}"]
        elif "supermicro" in vendor:
            # Supermicro: zone-based fan control
            zone = extra.get("zone", "0x00")
            hex_pct = hex(pct)
            cmds = [
                f"{base} raw 0x30 0x45 0x01 0x01",  # full speed mode off
                f"{base} raw 0x30 0x70 0x66 0x01 {zone} {hex_pct}",
            ]
        else:
            # Generic: try standard fan speed set
            cmds = [f"{base} dcmi power set_limit action {pct} 2>&1"]

        output_lines = []
        for cmd in cmds:
            out, err, code = _run_remote(ssh, cmd, timeout=15)
            output_lines.append(f"$ {cmd}\n{out or err}")

        result["ok"] = True
        result["message"] = "\n".join(output_lines)
    except Exception as exc:
        result["message"] = str(exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


def _set_fan_nbfc(dev: Dict, channel: str, speed, extra: dict) -> Dict:
    """Set fan speed via nbfc-linux."""
    result = {"ok": False, "message": ""}
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        # channel = fan index (0, 1, ...)
        fan_idx = int(channel) if str(channel).isdigit() else 0

        if isinstance(speed, (int, float)):
            pct = max(0, min(100, float(speed)))
            # nbfc set -a (auto) or -s <speed>
            cmd = f"nbfc set -f {fan_idx} -s {pct} 2>&1"
        else:
            # Auto mode
            cmd = f"nbfc set -f {fan_idx} -a 2>&1"

        out, err, code = _run_remote(ssh, cmd, timeout=15)
        result["ok"] = (code == 0)
        result["message"] = out or err or ("OK" if code == 0 else "Error")
    except Exception as exc:
        result["message"] = str(exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


def _set_fan_liquidctl(dev: Dict, channel: str, speed, extra: dict) -> Dict:
    """Set fan speed via liquidctl (NZXT, Aquacomputer, etc.)."""
    result = {"ok": False, "message": ""}
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        cfg = dev.get("extra_config", {})
        match_str = cfg.get("match_str", "")
        use_direct = cfg.get("use_direct", False)

        match_arg = f"--match '{match_str}'" if match_str else ""
        direct_arg = "--direct-access" if use_direct else ""

        if isinstance(speed, (int, float)):
            cmd = f"liquidctl {match_arg} {direct_arg} set {channel} speed {int(speed)} --json 2>&1".strip()
        elif isinstance(speed, list):
            pairs = " ".join(f"{t} {r}" for t, r in speed)
            cmd = f"liquidctl {match_arg} {direct_arg} set {channel} speed {pairs} --json 2>&1".strip()
        else:
            result["message"] = "Invalid speed format"
            return result

        out, err, code = _run_remote(ssh, cmd, timeout=30)
        result["ok"] = (code == 0)
        result["message"] = out or err or ("OK" if code == 0 else "Error")
    except Exception as exc:
        result["message"] = str(exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


def _set_fan_pwm_sysfs(dev: Dict, channel: str, speed, extra: dict) -> Dict:
    """Set fan via direct PWM sysfs write."""
    result = {"ok": False, "message": ""}
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        is_root = dev.get("username", "root") == "root"
        sudo = "" if is_root else "sudo "

        # channel = full sysfs path or "hwmon0/pwm1"
        if channel.startswith("/"):
            pwm_path = channel
        else:
            pwm_path = f"/sys/class/hwmon/{channel}"

        enable_path = pwm_path + "_enable"

        if isinstance(speed, (int, float)):
            # Accept both 0-100 (percent) and 0-255 (raw PWM)
            if speed <= 100:
                pwm_val = max(0, min(255, int(speed * 255 / 100)))
            else:
                pwm_val = max(0, min(255, int(speed)))
        else:
            pwm_val = 128

        # Set to manual mode
        _run_remote(ssh, f"echo 1 | {sudo}tee {enable_path} 2>&1", timeout=10)
        # Set PWM value
        out, err, code = _run_remote(
            ssh,
            f"echo {pwm_val} | {sudo}tee {pwm_path} 2>&1",
            timeout=10
        )
        result["ok"] = (code == 0)
        result["message"] = f"Set {pwm_path} → {pwm_val}/255 ({round(pwm_val/255*100)}%). {out or err}"
    except Exception as exc:
        result["message"] = str(exc)
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass
    return result


# ── Connection test ───────────────────────────────────────────────────────────

def test_connection(dev_id: int) -> Dict:
    """Test SSH connectivity and tool availability."""
    dev = get_device(dev_id)
    if not dev:
        return {"ok": False, "message": "Device not found"}

    ctype = dev.get("controller_type", "lm_sensors")
    type_info = CONTROLLER_TYPES.get(ctype, {})
    check_cmd = type_info.get("check_cmd", "echo 'no check'")
    detect_cmd = type_info.get("detect_cmd", "")

    ssh = None
    try:
        ssh = _ssh_connect(dev)
        # Check tool
        out, err, code = _run_remote(ssh, check_cmd, timeout=15)
        tool_ok = (code == 0)
        tool_msg = out or err or "(no output)"

        # Detect devices
        detect_out = ""
        if detect_cmd:
            d_out, d_err, _ = _run_remote(ssh, detect_cmd, timeout=15)
            detect_out = d_out or d_err

        if tool_ok:
            return {
                "ok": True,
                "message": f"✔ Connected. Tool: {tool_msg}\n\nDetected:\n{detect_out[:500]}"
            }
        else:
            pkgs = type_info.get("packages_apt", [])
            note = type_info.get("install_note", "")
            install_hint = f"Install with: apt install {' '.join(pkgs)}" if pkgs else note
            return {
                "ok": False,
                "message": f"✘ Tool not found on remote host.\n{tool_msg}\n\n{install_hint}"
            }
    except Exception as exc:
        return {"ok": False, "message": f"SSH connection failed: {exc}"}
    finally:
        if ssh:
            try: ssh.close()
            except Exception: pass


# ── Polling ───────────────────────────────────────────────────────────────────

def _store_sample(dev_id: int, status: Dict):
    try:
        with _get_db() as db:
            db.execute(
                "INSERT INTO fc_samples(device_id, ts, status_json) VALUES (?,?,?)",
                (dev_id, status["ts"], json.dumps(status))
            )
            # Purge old samples
            cutoff = int(time.time()) - _RETENTION_DAYS * 86400
            db.execute(
                "DELETE FROM fc_samples WHERE device_id=? AND ts<?",
                (dev_id, cutoff)
            )
    except Exception as exc:
        logger.warning("[fan_controller] store_sample error: %s", exc)


def get_latest(dev_id: int) -> Optional[Dict]:
    try:
        with _get_db() as db:
            row = db.execute(
                "SELECT status_json FROM fc_samples WHERE device_id=? ORDER BY ts DESC LIMIT 1",
                (dev_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def get_history(dev_id: int, hours: int = 24) -> List[Dict]:
    try:
        cutoff = int(time.time()) - hours * 3600
        with _get_db() as db:
            rows = db.execute(
                "SELECT status_json FROM fc_samples WHERE device_id=? AND ts>? ORDER BY ts ASC",
                (dev_id, cutoff)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]
    except Exception:
        return []


def _poll_all():
    global _poll_running
    while _poll_running:
        try:
            devices = list_devices()
            for d in devices:
                if not d.get("enabled"):
                    continue
                full_dev = get_device(d["id"])
                if not full_dev:
                    continue
                status = fetch_status(full_dev)
                _store_sample(d["id"], status)
        except Exception as exc:
            logger.warning("[fan_controller] poll_all error: %s", exc)
        time.sleep(_POLL_INTERVAL)


def start_polling():
    global _poll_thread, _poll_running
    if _poll_thread and _poll_thread.is_alive():
        return
    _poll_running = True
    _poll_thread = threading.Thread(target=_poll_all, daemon=True, name="fc_poll")
    _poll_thread.start()
    logger.info("[fan_controller] polling started (interval=%ds)", _POLL_INTERVAL)


def stop_polling():
    global _poll_running
    _poll_running = False


# ── Auto-Detect ───────────────────────────────────────────────────────────────

def detect_controllers(host: str, port: int = 22, username: str = "root",
                       password: str = "", ssh_key: str = "") -> Dict:
    """
    Connect to a remote host via SSH and detect which fan controller tools
    are available. Returns a ranked list of suggestions with detected devices.

    Returns:
        {
          "ok": bool,
          "error": str | None,
          "host": str,
          "os": str,
          "hostname": str,
          "is_laptop": bool,
          "suggestions": [
              {
                "controller_type": str,
                "label": str,
                "icon": str,
                "confidence": "high"|"medium"|"low",
                "reason": str,
                "detected_devices": str,
                "extra_config": dict,
              },
              ...
          ]
        }
    """
    dev = {
        "host": host,
        "port": port,
        "username": username,
        "password_plain": password,
        "ssh_key": ssh_key,
    }

    result = {
        "ok": False,
        "error": None,
        "host": host,
        "os": "",
        "hostname": "",
        "is_laptop": False,
        "suggestions": [],
    }

    ssh = None
    try:
        ssh = _ssh_connect(dev)

        def _r(cmd, timeout=10):
            out, err, code = _run_remote(ssh, cmd, timeout=timeout)
            return (out or "").strip(), (err or "").strip(), code

        # ── Gather system info ────────────────────────────────────────────────
        hostname_out, _, _ = _r("hostname 2>/dev/null")
        result["hostname"] = hostname_out

        os_out, _, _ = _r("cat /etc/os-release 2>/dev/null | grep -E '^PRETTY_NAME=' | head -1")
        result["os"] = os_out.replace('PRETTY_NAME=', '').strip('"\'') or "Linux"

        # Detect if laptop (battery present)
        bat_out, _, bat_code = _r("ls /sys/class/power_supply/ 2>/dev/null | grep -iE 'BAT|battery'")
        result["is_laptop"] = (bat_code == 0 and bool(bat_out))

        # Detect chassis type via DMI
        chassis_out, _, _ = _r("cat /sys/class/dmi/id/chassis_type 2>/dev/null")
        chassis_type = chassis_out.strip()
        # Chassis types 8-11 are laptops/notebooks
        if chassis_type in ("8", "9", "10", "11", "14"):
            result["is_laptop"] = True

        # ── Check each tool ───────────────────────────────────────────────────
        suggestions = []

        # 1. liquidctl
        lc_ver, _, lc_code = _r("liquidctl --version 2>&1 | head -1")
        if lc_code == 0 and lc_ver:
            lc_list, _, _ = _r("liquidctl list --json 2>/dev/null || liquidctl list 2>&1 | head -20", timeout=15)
            # Parse device names from JSON or text
            devices_found = []
            try:
                devs = json.loads(lc_list)
                if isinstance(devs, list):
                    devices_found = [d.get("description", d.get("device", "")) for d in devs]
            except (json.JSONDecodeError, TypeError):
                for line in lc_list.splitlines():
                    if "Device" in line or "#" in line:
                        devices_found.append(line.strip())

            if devices_found:
                # Determine best match string
                match_str = ""
                for d in devices_found:
                    for keyword in ["Commander", "Smart Device", "Kraken", "Quadro", "Octo", "HUE"]:
                        if keyword.lower() in d.lower():
                            match_str = keyword
                            break
                    if match_str:
                        break

                suggestions.append({
                    "controller_type": "liquidctl",
                    "label": CONTROLLER_TYPES["liquidctl"]["label"],
                    "icon": CONTROLLER_TYPES["liquidctl"]["icon"],
                    "confidence": "high",
                    "reason": f"liquidctl {lc_ver} found with {len(devices_found)} device(s)",
                    "detected_devices": "\n".join(devices_found[:5]),
                    "extra_config": {"match_str": match_str, "use_direct": False},
                })
            else:
                suggestions.append({
                    "controller_type": "liquidctl",
                    "label": CONTROLLER_TYPES["liquidctl"]["label"],
                    "icon": CONTROLLER_TYPES["liquidctl"]["icon"],
                    "confidence": "medium",
                    "reason": f"liquidctl {lc_ver} installed but no devices listed (may need --direct-access or udev rules)",
                    "detected_devices": lc_list[:300],
                    "extra_config": {"match_str": "", "use_direct": True},
                })

        # 2. lm-sensors
        sensors_ver, _, sensors_code = _r("sensors --version 2>&1 | head -1")
        if sensors_code == 0:
            sensors_out, _, _ = _r("sensors 2>/dev/null | head -30")
            fan_count = len(re.findall(r"RPM", sensors_out, re.IGNORECASE))
            temp_count = len(re.findall(r"°C", sensors_out))
            pwm_out, _, _ = _r("ls /sys/class/hwmon/hwmon*/pwm[0-9] 2>/dev/null | wc -l")
            pwm_count = int(pwm_out.strip() or "0")

            suggestions.append({
                "controller_type": "lm_sensors",
                "label": CONTROLLER_TYPES["lm_sensors"]["label"],
                "icon": CONTROLLER_TYPES["lm_sensors"]["icon"],
                "confidence": "high" if (fan_count > 0 or pwm_count > 0) else "medium",
                "reason": f"lm-sensors installed: {temp_count} temp sensor(s), {fan_count} fan(s), {pwm_count} PWM channel(s)",
                "detected_devices": sensors_out[:400],
                "extra_config": {},
            })

        # 3. PWM sysfs (always check)
        pwm_nodes_out, _, _ = _r(
            "for h in /sys/class/hwmon/hwmon*; do "
            "name=$(cat $h/name 2>/dev/null); "
            "pwms=$(ls $h/pwm[0-9] 2>/dev/null | wc -l); "
            "[ \"$pwms\" -gt 0 ] && echo \"$name: $pwms PWM channel(s)\"; "
            "done 2>/dev/null"
        )
        if pwm_nodes_out:
            suggestions.append({
                "controller_type": "pwm_sysfs",
                "label": CONTROLLER_TYPES["pwm_sysfs"]["label"],
                "icon": CONTROLLER_TYPES["pwm_sysfs"]["icon"],
                "confidence": "high",
                "reason": "Direct PWM sysfs nodes found (no extra tool needed)",
                "detected_devices": pwm_nodes_out[:300],
                "extra_config": {},
            })

        # 4. IPMI
        ipmi_ver, _, ipmi_code = _r("ipmitool -V 2>&1 | head -1")
        if ipmi_code == 0:
            ipmi_fans, _, _ = _r("ipmitool sdr type Fan 2>&1 | head -10", timeout=20)
            fan_count_ipmi = len([l for l in ipmi_fans.splitlines() if "|" in l])
            # Detect vendor
            dmi_vendor, _, _ = _r("cat /sys/class/dmi/id/sys_vendor 2>/dev/null")
            vendor = "generic"
            if "dell" in dmi_vendor.lower():
                vendor = "dell"
            elif "hp" in dmi_vendor.lower() or "hewlett" in dmi_vendor.lower():
                vendor = "hp"
            elif "supermicro" in dmi_vendor.lower():
                vendor = "supermicro"

            suggestions.append({
                "controller_type": "ipmi",
                "label": CONTROLLER_TYPES["ipmi"]["label"],
                "icon": CONTROLLER_TYPES["ipmi"]["icon"],
                "confidence": "high" if fan_count_ipmi > 0 else "medium",
                "reason": f"ipmitool found ({vendor} vendor), {fan_count_ipmi} fan sensor(s) via IPMI",
                "detected_devices": ipmi_fans[:300],
                "extra_config": {"ipmi_host": "localhost", "ipmi_user": "ADMIN", "ipmi_pass": "", "vendor": vendor},
            })

        # 5. nbfc (laptops)
        nbfc_ver, _, nbfc_code = _r("nbfc status --version 2>&1 | head -1 || nbfc --version 2>&1 | head -1")
        if nbfc_code == 0 or result["is_laptop"]:
            nbfc_status, _, _ = _r("nbfc status -a 2>&1 | head -20")
            confidence = "high" if nbfc_code == 0 else "low"
            reason = (
                f"nbfc-linux installed, {len([l for l in nbfc_status.splitlines() if 'Fan' in l])} fan(s) detected"
                if nbfc_code == 0
                else "Laptop detected but nbfc-linux not installed — install from https://github.com/nbfc-linux/nbfc-linux"
            )
            suggestions.append({
                "controller_type": "nbfc",
                "label": CONTROLLER_TYPES["nbfc"]["label"],
                "icon": CONTROLLER_TYPES["nbfc"]["icon"],
                "confidence": confidence,
                "reason": reason,
                "detected_devices": nbfc_status[:300] if nbfc_code == 0 else "",
                "extra_config": {},
            })

        # ── If nothing found, suggest based on OS/hardware ────────────────────
        if not suggestions:
            # Always suggest lm_sensors for Linux
            suggestions.append({
                "controller_type": "lm_sensors",
                "label": CONTROLLER_TYPES["lm_sensors"]["label"],
                "icon": CONTROLLER_TYPES["lm_sensors"]["icon"],
                "confidence": "low",
                "reason": "No fan control tools detected. Install lm-sensors for basic fan monitoring.",
                "detected_devices": "",
                "extra_config": {},
            })

        # ── Sort: high > medium > low, then liquidctl first if present ────────
        order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda s: order.get(s["confidence"], 3))

        result["suggestions"] = suggestions
        result["ok"] = True

    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("[fan_controller] detect_controllers error for %s: %s", host, exc)
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass

    return result
