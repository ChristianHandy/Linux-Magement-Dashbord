"""
FleetPilot — Gunicorn Production Configuration
Optimised for a typical home-lab / small-enterprise server.
"""
import multiprocessing, os

# ── Binding ───────────────────────────────────────────────────────────────────
# Respect the SERVER_IP env var set in /opt/fleetpilot/.env, fallback to 0.0.0.0
_server_ip = os.environ.get("SERVER_IP", "0.0.0.0")
_app_port  = os.environ.get("APP_PORT", "5000")
bind        = os.environ.get("GUNICORN_BIND", f"{_server_ip}:{_app_port}")
backlog     = 2048

# ── Workers ───────────────────────────────────────────────────────────────────
# Formula: (2 × CPU cores) + 1  — good for I/O-bound Flask apps
workers     = int(os.environ.get("GUNICORN_WORKERS",
                  min(multiprocessing.cpu_count() * 2 + 1, 9)))
worker_class = "sync"          # sync is fine; use "gthread" for heavy concurrency
threads     = 2                # 2 threads per worker for light parallelism
worker_connections = 1000

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout         = 120          # SSH commands can take a while
keepalive       = 5            # seconds to keep idle connections open
graceful_timeout = 30

# ── Logging ───────────────────────────────────────────────────────────────────
# Use "-" to log to stdout/stderr (captured by systemd journal)
accesslog   = "-"
errorlog    = "-"
loglevel    = "warning"        # reduce log noise in production
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── Process naming ────────────────────────────────────────────────────────────
proc_name   = "fleetpilot"
default_proc_name = "fleetpilot"

# ── Performance tweaks ────────────────────────────────────────────────────────
preload_app  = True            # load app once before forking → lower RAM per worker
max_requests = 1000            # recycle workers to prevent memory leaks
max_requests_jitter = 100      # randomise recycling to avoid thundering herd
sendfile     = True            # use OS sendfile() for static files
