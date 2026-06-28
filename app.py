from flask import Flask, render_template, redirect, session, request, flash, jsonify, send_file, url_for
from markupsafe import escape as html_escape
import re, time as _time
from collections import defaultdict
from i18n import get_translator, SUPPORTED_LANGUAGES
import json, threading, paramiko, os, secrets
from updater import run_update
import scheduler
import disktool_core
from addon_loader import AddonManager
from functools import wraps
import user_management
import version_manager
import email_config
import email_notifier
from constants import is_localhost, LOCALHOST_IDENTIFIERS
import arp_tracker
import vm_controller
import storage_controller
import smart_manager
import system_monitor
import corsair_commander
import backup_controller as _bc
# Load environment variables from .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional

# ── Persistent Data Directory ───────────────────────────────────────────────────
# All mutable data files (hosts.json, history.json, etc.) are stored in DATA_DIR.
# This directory is preserved across git-pull updates.
# Override via environment variable FLEETPILOT_DATA_DIR.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('FLEETPILOT_DATA_DIR', os.path.join(_APP_DIR, 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
# Security: Use environment variables for credentials, generate secure secret key
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# ── Flask-Compress: Gzip response compression ───────────────────────────────────────
try:
    from flask_compress import Compress as _Compress
    _compress = _Compress()
    _compress.init_app(app)
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'text/javascript',
        'application/javascript', 'application/json', 'text/plain'
    ]
    app.config['COMPRESS_LEVEL'] = 6
    app.config['COMPRESS_MIN_SIZE'] = 500
except ImportError:
    pass

# ── Brute-Force Rate Limiting (in-process, no Redis required) ─────────────────
_login_attempts = defaultdict(list)   # ip -> [timestamp, ...]
_LOGIN_MAX       = 10                  # max failed attempts per window
_LOGIN_WINDOW    = 60                  # window in seconds

def _check_rate_limit(ip):
    """Returns True if IP is allowed, False if rate-limited."""
    now = _time.time()
    attempts = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) < _LOGIN_MAX

def _record_failed_login(ip):
    _login_attempts[ip].append(_time.time())

def _clear_login_attempts(ip):
    _login_attempts.pop(ip, None)

# ── CSRF Protection ────────────────────────────────────────────────────────────
try:
    from flask_wtf.csrf import CSRFProtect as _CSRFProtect, generate_csrf as _gen_csrf, CSRFError
    _csrf = _CSRFProtect(app)
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600

    # Exempt pure JSON/API and SSE-stream endpoints from CSRF
    _CSRF_EXEMPT_PREFIXES = ('/api/', '/progress/', '/disks/stream', '/smart/stream',
                              '/set_language', '/set_theme')
    _CSRF_EXEMPT_SUFFIXES = ('/set_fan', '/test', '/refresh')

    @_csrf.exempt
    def _csrf_exempt_check():
        pass

    @app.before_request
    def _maybe_exempt_csrf():
        """Exempt API, streaming and UI-helper routes from CSRF validation."""
        if any(request.path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES) or any(request.path.endswith(s) for s in _CSRF_EXEMPT_SUFFIXES):
            # Disable CSRF check for this request by setting the flag Flask-WTF reads
            app.config['WTF_CSRF_ENABLED'] = False

    @app.after_request
    def _re_enable_csrf(response):
        """Re-enable CSRF after each request so only exempt routes skip it."""
        app.config['WTF_CSRF_ENABLED'] = True
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        # Count CSRF failures on login endpoint as failed login attempts
        if request.path == '/' and request.method == 'POST':
            ip = request.remote_addr or '0.0.0.0'
            _record_failed_login(ip)
            if not _check_rate_limit(ip):
                flash('Too many failed login attempts. Please wait 60 seconds.')
                return render_template('login.html', next=request.args.get('next', '/index'), rate_limited=True), 429
            flash('Security token expired or missing. Please try again.')
            return redirect(url_for('login'))
        return jsonify({'error': 'CSRF token missing or invalid', 'detail': str(e)}), 400

    @app.context_processor
    def _inject_csrf():
        return dict(csrf_token=_gen_csrf)
except ImportError:
    _csrf = None
    @app.context_processor
    def _inject_csrf():
        return dict(csrf_token=lambda: '')

# ── Input sanitisation helpers ───────────────────────────────────────────────────
_DANGEROUS_PROTO = re.compile(r'^\s*(javascript|vbscript|data):', re.IGNORECASE)

def sanitize_input(value, max_len=256):
    """Strip dangerous protocols and limit length."""
    if not isinstance(value, str):
        return ''
    value = value.strip()[:max_len]
    if _DANGEROUS_PROTO.match(value):
        return ''
    return value

import ipaddress as _ipaddress
import re as _re_host

# Allowed hostname pattern: RFC-1123 labels, optional port suffix stripped before check
_HOSTNAME_RE = _re_host.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*'
    r'[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$'
)


def validate_host_address(value: str) -> str:
    """Validate and normalise a host address (IPv4, IPv6, or hostname).

    Returns the sanitised value if valid, or raises ``ValueError`` with a
    human-readable message so the caller can surface it to the user.
    """
    value = value.strip()
    if not value:
        return value  # empty is allowed (host field optional in some flows)
    # Try IPv4 / IPv6 first
    try:
        addr = _ipaddress.ip_address(value)
        return str(addr)
    except ValueError:
        pass
    # Accept plain hostnames (strip optional port)
    host_part = value.split(":")[0] if ":" in value and not value.startswith("[") else value
    if _HOSTNAME_RE.match(host_part) and len(host_part) <= 253:
        return value
    raise ValueError(
        f"'{value}' is not a valid IPv4 address, IPv6 address, or hostname."
    )


def sanitize_host_data(data):
    """Sanitize all string fields in a host data dict."""
    for field in ('host','user','mac','description','notes','group',
                  'location','environment','criticality','ssh_key'):
        if field in data and isinstance(data[field], str):
            data[field] = sanitize_input(data[field])
    return data

# ── In-memory cache for expensive reads ──────────────────────────────────────────
_cache = {}
_cache_ttl = {}
_CACHE_DEFAULT_TTL = 30  # seconds

def cache_get(key):
    if key in _cache and _time.time() < _cache_ttl.get(key, 0):
        return _cache[key]
    return None

def cache_set(key, value, ttl=_CACHE_DEFAULT_TTL):
    _cache[key] = value
    _cache_ttl[key] = _time.time() + ttl

def cache_invalidate(key):
    _cache.pop(key, None)
    _cache_ttl.pop(key, None)

USERNAME = os.environ.get('DASHBOARD_USERNAME', 'admin')
PASSWORD = os.environ.get('DASHBOARD_PASSWORD', 'password')

# Warn if using default credentials
if USERNAME == 'admin' and PASSWORD == 'password':
    print("WARNING: Using default credentials! Set DASHBOARD_USERNAME and DASHBOARD_PASSWORD environment variables.")

# Initialize Disk Tools addon system
addon_mgr = AddonManager(app, disktool_core)
app.addon_mgr = addon_mgr
addon_mgr.load_addons()

# ── Database initialisation ───────────────────────────────────────────────────
# Runs at module import time so both Gunicorn workers and direct python3
# invocations initialise the database before any request is handled.
with app.app_context():
    user_management.init_user_db()
    if user_management.migrate_env_user_to_db():
        print(f"INFO: Migrated env-var user '{USERNAME}' to database.")
    disktool_core.init_db()
    vm_controller.init_db()
    storage_controller.init_db()
    smart_manager.init_db()
    smart_manager.start_polling()
    system_monitor.init_db(DATA_DIR)
    system_monitor.start_polling()
    corsair_commander.init_db(DATA_DIR)
    corsair_commander.start_polling()
    _bc.init_db(DATA_DIR)
    _bc.start_all_polling()

# Template function for HTML extensions
@app.context_processor
def inject_hooks():
    return dict(
        hook=lambda name, *args, **kwargs: addon_mgr.render_hooks(name, *args, **kwargs),
        addon_mgr=addon_mgr,
    )

# Template function for user context
@app.context_processor
def inject_user_context():
    """Make user information available in all templates."""
    user_id = session.get("user_id")
    user_roles = []
    is_admin = False
    is_operator = False
    if user_id:
        user_roles = user_management.get_user_role_names(user_id)
        is_admin = 'admin' in user_roles
        is_operator = 'operator' in user_roles or is_admin
    return dict(
        current_user_id=user_id,
        current_user_roles=user_roles,
        is_admin=is_admin,
        is_operator=is_operator,
        localhost_identifiers=LOCALHOST_IDENTIFIERS
    )

# Template function for theme and language context
@app.context_processor
def inject_ui_context():
    """Inject current theme and language into all templates."""
    lang = session.get('lang', 'en')
    theme = session.get('theme', 'dark')
    translator = get_translator(lang)
    return dict(
        current_lang=lang,
        current_theme=theme,
        _=translator,
        supported_languages=SUPPORTED_LANGUAGES
    )

# Template function for version update notifications
@app.context_processor
def inject_version_notification():
    """Make version update notifications available in all templates."""
    notification = version_manager.get_update_notification()
    return dict(update_notification=notification)

logs = {}

def current_user_has_role(*roles):
    """Check if the current logged-in user has any of the specified roles."""
    user_id = session.get("user_id")
    if not user_id:
        return False
    user_roles = user_management.get_user_role_names(user_id)
    # Admin has access to everything
    if 'admin' in user_roles:
        return True
    return any(role in user_roles for role in roles)

def is_online(host, user):
    # Check if this is localhost
    if is_localhost(host):
        # For localhost, just return True (we're always online to ourselves)
        return True
    
    try:
        ssh = paramiko.SSHClient()
        # Security Note: AutoAddPolicy accepts any host key, making this vulnerable to MITM attacks.
        # For production, use WarningPolicy or maintain a known_hosts file.
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, username=user, timeout=3)
        ssh.close()
        return True
    except:
        return False

# Predefined tag palette for hosts
HOST_TAG_PRESETS = [
    "Server", "PC", "VM", "Container", "Laptop", "NAS",
    "Router", "Raspberry Pi", "Workstation", "IoT", "Database",
    "Web Server", "Mail Server", "Backup", "Monitoring"
]

HOST_ENVIRONMENTS = ["Production", "Staging", "Development", "Testing", "Lab"]
HOST_CRITICALITY  = ["Critical", "High", "Medium", "Low"]

def normalize_host(data):
    """Ensure all optional host fields have sensible defaults."""
    defaults = {
        "host": "",
        "user": "",
        "mac": "",
        "description": "",
        "notes": "",
        "group": "",
        "location": "",
        "environment": "Production",
        "criticality": "Medium",
        "tags": [],
        "port": 22,
        "ssh_key": "",
        "os_profiles": [],
        "last_update": None,
        "last_seen": None,
    }
    defaults.update(data)
    # Ensure tags is always a list
    if isinstance(defaults["tags"], str):
        defaults["tags"] = [t.strip() for t in defaults["tags"].split(",") if t.strip()]
    return defaults

def load_hosts():
    cached = cache_get('hosts')
    if cached is not None:
        return cached
    try:
        with open(os.path.join(DATA_DIR, "hosts.json"), "r") as f:
            raw = json.load(f)
        data = {name: normalize_host(d) for name, d in raw.items()}
    except Exception:
        data = {}
    cache_set('hosts', data, ttl=15)
    return data

def save_hosts(hosts):
    with open(os.path.join(DATA_DIR, "hosts.json"), "w") as f:
        json.dump(hosts, f, indent=2)
    cache_invalidate('hosts')

def get_local_public_key():
    """
    Return the local public key string. Generate a new keypair if needed.
    """
    ssh_dir = os.path.expanduser("~/.ssh")
    pub_path = os.path.join(ssh_dir, "id_rsa.pub")
    priv_path = os.path.join(ssh_dir, "id_rsa")

    try:
        if os.path.exists(pub_path):
            with open(pub_path, "r") as f:
                return f.read().strip()
        # generate new keypair
        os.makedirs(ssh_dir, exist_ok=True)
        key = paramiko.RSAKey.generate(2048)
        # write private key
        key.write_private_key_file(priv_path)
        with open(pub_path, "w") as f:
            f.write(f"{key.get_name()} {key.get_base64()}\n")
        os.chmod(priv_path, 0o600)
        os.chmod(pub_path, 0o644)
        with open(pub_path, "r") as f:
            return f.read().strip()
    except Exception as e:
        raise RuntimeError(f"Failed to obtain or generate local SSH key: {e}")

def login_required(f):
    """Decorator to require login - uses new user management system."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        # Check new user_id session first
        if session.get("user_id"):
            return f(*args, **kwargs)
        # Fallback to old login session for backward compatibility
        if session.get("login"):
            return f(*args, **kwargs)
        return redirect(url_for('login', next=request.path))
    return wrapped

@app.route("/", methods=["GET", "POST"])
def login():
    next_url = request.args.get('next') or url_for('index')
    if request.method == "POST":
        ip = request.remote_addr or '0.0.0.0'
        # ── Brute-Force check ─────────────────────────────────────────────────────────
        if not _check_rate_limit(ip):
            flash('Too many failed login attempts. Please wait 60 seconds.')
            return render_template("login.html", next=next_url, rate_limited=True), 429

        username = sanitize_input(request.form.get("user", ""), max_len=128)
        password = request.form.get("pass", "")
        
        # Try database authentication first
        user_id = user_management.verify_password(username, password)
        if user_id:
            _clear_login_attempts(ip)
            session["user_id"] = user_id
            session["username"] = username
            session["login"] = True
            flash('Logged in successfully')
            return redirect(next_url)
        
        # Fallback to environment variable authentication for backward compatibility
        if username == USERNAME and password == PASSWORD:
            _clear_login_attempts(ip)
            session["login"] = True
            session["username"] = username
            flash('Logged in successfully (legacy mode)')
            return redirect(next_url)
        
        _record_failed_login(ip)
        flash('Invalid username or password')
    return render_template("login.html", next=next_url)

@app.route("/logout")
def logout():
    session.pop("login", None)
    session.pop("user_id", None)
    session.pop("username", None)
    flash('Logged out')
    return redirect(url_for('login'))

@app.route("/index")
@login_required
def index():
    """Main menu/landing page showing both tools"""
    hosts = load_hosts()
    # Compute quick stats for the home page
    try:
        history = json.load(open(os.path.join(DATA_DIR, "history.json")))
    except Exception:
        history = []
    try:
        disk_count = len(disktool_core.list_disks())
    except Exception:
        disk_count = 0
    user_id = session.get("user_id")
    try:
        all_users = user_management.get_all_users()
        active_users = len([u for u in all_users if u.get("active", True)])
    except Exception:
        active_users = 0
    # Tag/environment summary
    all_tags = []
    env_counts = {}
    for h in hosts.values():
        all_tags.extend(h.get("tags", []))
        env = h.get("environment", "Production")
        env_counts[env] = env_counts.get(env, 0) + 1
    tag_counts = {}
    for t in all_tags:
        tag_counts[t] = tag_counts.get(t, 0) + 1

    # VM / Storage / SMART summary for dashboard widgets
    try:
        vm_endpoints = vm_controller.list_endpoints()
    except Exception:
        vm_endpoints = []
    try:
        storage_endpoints = storage_controller.list_endpoints()
    except Exception:
        storage_endpoints = []
    try:
        smart_summary = smart_manager.get_health_summary()
    except Exception:
        smart_summary = {}

    # Per-user dashboard layout
    layout = user_management.get_dashboard_layout(user_id) if user_id else user_management.DEFAULT_DASHBOARD_LAYOUT

    # Recent update history (last 5)
    recent_history = history[-5:][::-1] if history else []

    return render_template(
        "index.html",
        host_count=len(hosts),
        disk_count=disk_count,
        update_count=len(history),
        active_users=active_users,
        tag_counts=tag_counts,
        env_counts=env_counts,
        hosts=hosts,
        vm_endpoints=vm_endpoints,
        storage_endpoints=storage_endpoints,
        smart_summary=smart_summary,
        dashboard_layout=layout,
        recent_history=recent_history,
    )


# ── Dashboard Layout API ──────────────────────────────────────────────────────

@app.route("/api/dashboard/layout", methods=["GET"])
@login_required
def api_dashboard_layout_get():
    """Return the current user's dashboard layout as JSON."""
    user_id = session.get("user_id")
    layout = user_management.get_dashboard_layout(user_id)
    return jsonify(layout)


@app.route("/api/dashboard/layout", methods=["POST"])
@login_required
def api_dashboard_layout_save():
    """Persist the current user's dashboard layout."""
    user_id = session.get("user_id")
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400
    try:
        user_management.save_dashboard_layout(user_id, data)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/dashboard/layout/reset", methods=["POST"])
@login_required
def api_dashboard_layout_reset():
    """Reset the current user's dashboard layout to defaults."""
    user_id = session.get("user_id")
    user_management.reset_dashboard_layout(user_id)
    return jsonify({"ok": True})

@app.route("/dashboard")
@login_required
def dashboard():
    """Linux Update Dashboard"""
    hosts = load_hosts()
    history = json.load(open(os.path.join(DATA_DIR, "history.json")))
    status = {n: is_online(h["host"], h["user"]) for n, h in hosts.items()}
    
    # Load update settings for display
    settings = scheduler.load_update_settings()
    
    return render_template(
        "update_dashboard.html", 
        hosts=hosts, 
        status=status, 
        history=history,
        auto_updates_enabled=settings.get("automatic_updates_enabled", False),
        update_frequency=settings.get("update_frequency", "daily"),
        last_auto_update=settings.get("last_auto_update")
    )

@app.route("/update/<name>")
@login_required
def update(name):
    # Require operator or admin role to perform updates
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to perform system updates.')
        return redirect(url_for('dashboard'))
    
    hosts = load_hosts()
    logs[name] = []
    threading.Thread(
        target=run_update,
        args=(hosts[name]["host"], hosts[name]["user"], name, logs[name])
    ).start()
    return redirect(f"/progress/{name}")

@app.route("/progress/<name>")
@login_required
def progress(name):
    return render_template("progress.html", log=logs.get(name, []))

# Update settings routes
@app.route("/update_settings", methods=["GET", "POST"])
@login_required
def update_settings():
    """Manage automatic update settings"""
    # Require operator or admin role to modify settings
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to modify update settings.')
        return redirect(url_for('dashboard'))
    
    if request.method == "POST":
        settings = scheduler.load_update_settings()
        
        # Update settings from form
        settings["automatic_updates_enabled"] = bool(request.form.get("automatic_updates_enabled"))
        settings["update_frequency"] = request.form.get("update_frequency", "daily")
        settings["notification_enabled"] = bool(request.form.get("notification_enabled"))
        settings["dashboard_update_notifications"] = bool(request.form.get("dashboard_update_notifications"))
        
        # Validate frequency
        if settings["update_frequency"] not in ["daily", "weekly", "monthly"]:
            settings["update_frequency"] = "daily"
        
        # Save settings
        scheduler.save_update_settings(settings)
        
        # Reconfigure scheduler
        scheduler.configure_scheduler()
        
        flash('Update settings saved successfully')
        return redirect(url_for('update_settings'))
    
    # GET request - display current settings
    settings = scheduler.load_update_settings()
    return render_template("update_settings.html", settings=settings)

# Email settings routes
@app.route("/email_settings", methods=["GET", "POST"])
@login_required
def email_settings():
    """Manage email notification settings"""
    # Require operator or admin role to modify settings
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to modify email settings.')
        return redirect(url_for('index'))
    
    if request.method == "POST":
        # Check if this is a test email request
        if request.form.get("test_email"):
            success, error = email_notifier.test_email_configuration()
            if success:
                flash('Test email sent successfully! Check your inbox.')
            else:
                flash(f'Failed to send test email: {error}')
            return redirect(url_for('email_settings'))
        
        # Regular settings update
        settings = email_config.load_email_settings()
        
        # Update settings from form
        settings["email_enabled"] = bool(request.form.get("email_enabled"))
        settings["smtp_server"] = request.form.get("smtp_server", "").strip()
        settings["smtp_port"] = int(request.form.get("smtp_port", 587))
        settings["smtp_use_tls"] = bool(request.form.get("smtp_use_tls"))
        settings["smtp_username"] = request.form.get("smtp_username", "").strip()
        settings["smtp_password"] = request.form.get("smtp_password", "").strip()
        settings["sender_email"] = request.form.get("sender_email", "").strip()
        
        # Parse recipient emails (one per line)
        recipient_text = request.form.get("recipient_emails", "").strip()
        settings["recipient_emails"] = [email.strip() for email in recipient_text.split('\n') if email.strip()]
        
        settings["report_enabled"] = bool(request.form.get("report_enabled"))
        settings["report_interval"] = request.form.get("report_interval", "weekly")
        settings["error_notifications_enabled"] = bool(request.form.get("error_notifications_enabled"))
        
        # Validate report interval
        if settings["report_interval"] not in ["daily", "weekly", "monthly"]:
            settings["report_interval"] = "weekly"
        
        # Save settings
        email_config.save_email_settings(settings)
        
        # Reconfigure scheduler to apply report changes
        scheduler.configure_scheduler()
        
        flash('Email settings saved successfully')
        return redirect(url_for('email_settings'))
    
    # GET request - display current settings
    settings = email_config.load_email_settings()
    return render_template("email_settings.html", settings=settings)


# Dashboard version update routes
@app.route("/dashboard_version/check")
@login_required
def check_dashboard_version():
    """Check for dashboard updates"""
    # Require operator or admin role to check for updates
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to check for updates.')
        return redirect(url_for('index'))
    
    version_data = version_manager.check_for_updates()
    
    if version_data.get("update_available"):
        flash(f'Dashboard update available: {version_data.get("update_description")}')
    else:
        flash('Dashboard is up to date!')
    
    return redirect(url_for('index'))

@app.route("/dashboard_version/dismiss")
@login_required
def dismiss_dashboard_notification():
    """Dismiss the current update notification"""
    version_manager.dismiss_notification()
    return redirect(request.referrer or url_for('index'))

@app.route("/dashboard_version/update", methods=["GET", "POST"])
@login_required
def update_dashboard():
    """Update the dashboard to the latest version"""
    # Require admin role to update dashboard
    if session.get("user_id") and not current_user_has_role('admin'):
        flash('Only administrators can update the dashboard.')
        return redirect(url_for('index'))
    
    if request.method == "POST":
        preserve_configs = request.form.get("preserve_configs", "yes") == "yes"
        success, message = version_manager.perform_self_update(preserve_configs)
        
        if success:
            flash(message, 'success')
        else:
            flash(message, 'error')
        
        return redirect(url_for('index'))
    
    # GET request - show confirmation page
    version_data = version_manager.load_version_data()
    return render_template("dashboard_update.html", version_data=version_data)

@app.route("/update_repo/<name>")
@login_required
def update_repo(name):
    """Update from repository only, skip host configuration updates"""
    # Require operator or admin role to perform updates
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to perform system updates.')
        return redirect(url_for('dashboard'))
    
    hosts = load_hosts()
    if name not in hosts:
        flash(f'Host {name} not found')
        return redirect(url_for('dashboard'))
    
    logs[name] = []
    threading.Thread(
        target=run_update,
        args=(hosts[name]["host"], hosts[name]["user"], name, logs[name], True)
    ).start()
    return redirect(f"/progress/{name}")

# Host management routes
@app.route("/hosts", methods=["GET", "POST"])
@login_required
def manage_hosts():
    hosts = load_hosts()
    if request.method == "POST":
        # Require operator or admin role to modify hosts
        if session.get("user_id") and not current_user_has_role('operator', 'admin'):
            flash('You need operator or admin role to manage hosts.')
            return redirect(url_for('manage_hosts'))
        
        # Add or update host via the add form
        name = sanitize_input(request.form.get("name", ""), max_len=64)
        raw_host = sanitize_input(request.form.get("host", ""), max_len=253)
        try:
            host = validate_host_address(raw_host)
        except ValueError as _ve:
            flash(f'Invalid host address: {_ve}', 'error')
            return redirect(url_for('manage_hosts'))
        user = sanitize_input(request.form.get("user", ""), max_len=64)
        mac  = sanitize_input(request.form.get("mac", ""), max_len=17)
        if name:
            host_data = {
                "host": host,
                "user": user,
                "mac": mac,
                "description": sanitize_input(request.form.get("description", ""), max_len=512),
                "notes":       sanitize_input(request.form.get("notes", ""), max_len=2048),
                "group":       sanitize_input(request.form.get("group", ""), max_len=64),
                "location":    sanitize_input(request.form.get("location", ""), max_len=128),
                "environment": sanitize_input(request.form.get("environment", "Production"), max_len=32),
                "criticality": sanitize_input(request.form.get("criticality", "Medium"), max_len=32),
                "port":        max(1, min(65535, int(request.form.get("port", 22) or 22))),
                "ssh_key":     sanitize_input(request.form.get("ssh_key", ""), max_len=512),
                "tags":        [sanitize_input(t, max_len=32) for t in request.form.get("tags", "").split(",") if t.strip()][:20],
            }
            # Multiboot: parse OS profiles from form (issue #36)
            os_names    = request.form.getlist("os_name")
            os_types    = request.form.getlist("os_type")
            os_defaults = request.form.getlist("os_default")
            os_profiles = []
            for i, oname in enumerate(os_names):
                oname = sanitize_input(oname, max_len=64)
                if not oname:
                    continue
                otype = sanitize_input(os_types[i] if i < len(os_types) else "linux", max_len=32)
                is_default = str(i) in os_defaults or oname in os_defaults
                os_profiles.append({"name": oname, "type": otype, "default": is_default})
            if os_profiles:
                if not any(p["default"] for p in os_profiles):
                    os_profiles[0]["default"] = True
            host_data["os_profiles"] = os_profiles
            hosts[name] = host_data
            save_hosts(hosts)
            cache_invalidate('hosts')
        return redirect("/hosts")
    return render_template(
        "hosts.html",
        hosts=hosts,
        tag_presets=HOST_TAG_PRESETS,
        environments=HOST_ENVIRONMENTS,
        criticalities=HOST_CRITICALITY,
    )

# Edit host
@app.route("/hosts/edit/<orig_name>", methods=["GET", "POST"])
@login_required
def edit_host(orig_name):
    hosts = load_hosts()
    if orig_name not in hosts:
        return redirect("/hosts")
    if request.method == "POST":
        # Require operator or admin role to modify hosts
        if session.get("user_id") and not current_user_has_role('operator', 'admin'):
            flash('You need operator or admin role to manage hosts.')
            return redirect(url_for('manage_hosts'))
        
        new_name = sanitize_input(request.form.get("name", ""), max_len=64)
        raw_host = sanitize_input(request.form.get("host", ""), max_len=253)
        try:
            host = validate_host_address(raw_host)
        except ValueError as _ve:
            flash(f'Invalid host address: {_ve}', 'error')
            return redirect(url_for('edit_host', orig_name=orig_name))
        user = sanitize_input(request.form.get("user", ""), max_len=64)
        mac  = sanitize_input(request.form.get("mac", ""), max_len=17)
        if new_name:
            if new_name != orig_name:
                hosts.pop(orig_name, None)
            host_data = {
                "host": host,
                "user": user,
                "mac": mac,
                "description": sanitize_input(request.form.get("description", ""), max_len=512),
                "notes":       sanitize_input(request.form.get("notes", ""), max_len=2048),
                "group":       sanitize_input(request.form.get("group", ""), max_len=64),
                "location":    sanitize_input(request.form.get("location", ""), max_len=128),
                "environment": sanitize_input(request.form.get("environment", "Production"), max_len=32),
                "criticality": sanitize_input(request.form.get("criticality", "Medium"), max_len=32),
                "port":        max(1, min(65535, int(request.form.get("port", 22) or 22))),
                "ssh_key":     sanitize_input(request.form.get("ssh_key", ""), max_len=512),
                "tags":        [sanitize_input(t, max_len=32) for t in request.form.get("tags", "").split(",") if t.strip()][:20],
                # Preserve timestamps
                "last_update": hosts.get(orig_name, {}).get("last_update"),
                "last_seen":   hosts.get(orig_name, {}).get("last_seen"),
            }
            # Multiboot: parse OS profiles from form (issue #36)
            os_names    = request.form.getlist("os_name")
            os_types    = request.form.getlist("os_type")
            os_defaults = request.form.getlist("os_default")
            os_profiles = []
            for i, oname in enumerate(os_names):
                oname = oname.strip()
                if not oname:
                    continue
                otype = os_types[i].strip() if i < len(os_types) else "linux"
                is_default = str(i) in os_defaults or oname in os_defaults
                os_profiles.append({"name": oname, "type": otype, "default": is_default})
            if os_profiles:
                if not any(p["default"] for p in os_profiles):
                    os_profiles[0]["default"] = True
            host_data["os_profiles"] = os_profiles
            hosts[new_name] = host_data
            save_hosts(hosts)
            cache_invalidate('hosts')
        return redirect("/hosts")
    # GET
    return render_template(
        "edit_host.html",
        name=orig_name,
        data=hosts[orig_name],
        tag_presets=HOST_TAG_PRESETS,
        environments=HOST_ENVIRONMENTS,
        criticalities=HOST_CRITICALITY,
    )

# Delete host
@app.route("/hosts/delete/<name>", methods=["POST"])
@login_required
def delete_host(name):
    # Require operator or admin role to delete hosts
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to delete hosts.')
        return redirect(url_for('manage_hosts'))
    
    hosts = load_hosts()
    if name in hosts:
        hosts.pop(name)
        save_hosts(hosts)
        cache_invalidate('hosts')
    return redirect("/hosts")

# Install SSH public key on remote host using password auth
@app.route("/hosts/install_key/<name>", methods=["GET", "POST"])
@app.route("/install_key", methods=["GET", "POST"], defaults={"name": None})
@login_required
def install_key(name):
    # Require operator or admin role to install keys
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to install SSH keys.')
        return redirect(url_for('manage_hosts'))
    
    hosts = load_hosts()
    if name is None:
        # Show host selection page when accessed without a specific host
        return render_template("install_key.html", name=None, hosts=hosts, error=None, success=False)
    if name not in hosts:
        return redirect("/hosts")
    
    target = hosts[name]
    
    # Check if this is localhost - no SSH key needed
    if is_localhost(target["host"]):
        flash('SSH key installation is not needed for localhost. Updates will run directly on the local system.')
        return redirect("/hosts")
    
    error = None
    success = False
    if request.method == "POST":
        password = request.form.get("password", "")
        try:
            pubkey = get_local_public_key()
        except Exception as e:
            error = str(e)
            return render_template("install_key.html", name=name, error=error, success=False)

        target = hosts[name]
        try:
            ssh = paramiko.SSHClient()
            # Security Note: AutoAddPolicy accepts any host key, making this vulnerable to MITM attacks.
            # For production, use WarningPolicy or maintain a known_hosts file.
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(target["host"], username=target["user"], password=password, timeout=10)
            
            # Security: Use SFTP to safely write the key file instead of shell commands
            try:
                sftp = ssh.open_sftp()
                # Create .ssh directory
                try:
                    sftp.stat('.ssh')
                except IOError:
                    sftp.mkdir('.ssh')
                    sftp.chmod('.ssh', 0o700)
                
                # Read existing authorized_keys if present
                auth_keys_path = '.ssh/authorized_keys'
                try:
                    with sftp.file(auth_keys_path, 'r') as f:
                        existing_keys = f.read().decode('utf-8')
                except IOError:
                    existing_keys = ''
                
                # Append new key if not already present
                if pubkey not in existing_keys:
                    with sftp.file(auth_keys_path, 'a') as f:
                        f.write(f'\n{pubkey}\n')
                    sftp.chmod(auth_keys_path, 0o600)
                    success = True
                else:
                    success = True  # Key already installed
                    
                sftp.close()
            except Exception as e:
                error = f"SFTP error: {e}"
            finally:
                ssh.close()
        except Exception as e:
            error = f"Connection error: {e}"
    return render_template("install_key.html", name=name, error=error, success=success)

# ARP-based IP change detection routes
@app.route("/hosts/detect_mac/<name>")
@login_required
def detect_mac(name):
    """Detect MAC address for a host by pinging it and checking ARP table"""
    # Require operator or admin role
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to detect MAC addresses.')
        return redirect(url_for('manage_hosts'))
    
    hosts = load_hosts()
    if name not in hosts:
        flash(f'Host {name} not found')
        return redirect(url_for('manage_hosts'))
    
    host_config = hosts[name]
    ip = host_config['host']
    
    # Check if this is localhost
    if is_localhost(ip):
        flash('MAC address detection is not applicable for localhost.')
        return redirect(url_for('manage_hosts'))
    
    # Ping the host to populate ARP table
    if arp_tracker.ping_host(ip):
        # Get MAC address from ARP table
        mac = arp_tracker.get_mac_address_for_ip(ip)
        if mac:
            # Update host configuration with MAC address
            host_config['mac'] = mac
            hosts[name] = host_config
            save_hosts(hosts)
            flash(f'MAC address detected and saved for {name}: {mac}')
        else:
            flash(f'Host {name} is reachable but MAC address could not be detected from ARP table.')
    else:
        flash(f'Could not ping host {name} at {ip}. Make sure the host is online and reachable.')
    
    return redirect(url_for('manage_hosts'))

@app.route("/hosts/scan_ip_changes")
@login_required
def scan_ip_changes():
    """Scan for IP changes using ARP table"""
    # Require operator or admin role
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to scan for IP changes.')
        return redirect(url_for('manage_hosts'))
    
    hosts = load_hosts()
    
    # Get current ARP table
    arp_mappings = arp_tracker.get_arp_table()
    
    # Detect IP changes
    changes = arp_tracker.detect_ip_changes(hosts, arp_mappings)
    
    if changes:
        # Update host IPs
        updated_hosts = arp_tracker.update_host_ips(hosts, changes)
        save_hosts(updated_hosts)
        
        # Create flash message with changes
        change_messages = []
        for hostname, old_ip, new_ip in changes:
            change_messages.append(f'{hostname}: {old_ip} → {new_ip}')
        
        flash(f"IP changes detected and updated: {', '.join(change_messages)}")
    else:
        flash('No IP changes detected.')
    
    return redirect(url_for('manage_hosts'))

@app.route("/hosts/arp_table")
@app.route("/arp_table")   # alias without /hosts prefix
@login_required
def view_arp_table():
    """View current ARP table"""
    arp_mappings = arp_tracker.get_arp_table()
    return render_template("arp_table.html", arp_mappings=arp_mappings)

# ============================================================================
# DISK TOOLS ROUTES (from Disk_Tools repository)
# ============================================================================

@app.route("/disks")
@login_required
def disks_index():
    """Disk management main page"""
    disktool_core.sync_disks()
    q = request.args.get('q','')
    disks = disktool_core.get_disk_list(q)
    return render_template('disks/index.html', disks=disks, auto=disktool_core.auto_enabled)

@app.route("/disks/toggle_auto")
@login_required
def toggle_auto():
    # Require operator or admin role to toggle automatic mode
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to toggle automatic mode.')
        return redirect(url_for('disks_index'))
    
    disktool_core.auto_enabled = not disktool_core.auto_enabled
    flash(f"Automatic mode {'ON' if disktool_core.auto_enabled else 'OFF'}")
    return redirect(url_for('disks_index'))

@app.route("/disks/format/<device>", methods=['GET','POST'])
@login_required
def format_route(device):
    try:
        device = disktool_core.sanitize_device_name(device)
    except ValueError as e:
        flash(f'Invalid device name: {e}')
        return redirect(url_for('disks_index'))
    if request.method == 'POST':
        # Require operator or admin role to format disks
        if session.get("user_id") and not current_user_has_role('operator', 'admin'):
            flash('You need operator or admin role to format disks.')
            return redirect(url_for('disks_index'))
        
        fs = request.form.get('fs','ext4')
        if fs not in {'ext4', 'xfs', 'fat32'}:
            flash('Invalid filesystem type')
            return redirect(url_for('disks_index'))
        op_id = disktool_core.start_format(device, fs)
        flash(f'Format task {op_id} started for {device}')
        return redirect(url_for('task_status', op_id=op_id))
    return render_template('disks/format.html', device=device)

@app.route("/disks/smart/start/<device>/<mode>")
@login_required
def smart_start_route(device, mode):
    # Require operator or admin role to start SMART tests
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to start SMART tests.')
        return redirect(url_for('disks_index'))
    
    try:
        device = disktool_core.sanitize_device_name(device)
    except ValueError as e:
        flash(f'Invalid device name: {e}')
        return redirect(url_for('disks_index'))
    if mode not in {'short','long'}:
        flash('Invalid SMART type')
        return redirect(url_for('disks_index'))
    disktool_core.start_smart(device, mode)
    flash(f'SMART {mode} started for {device}')
    return redirect(url_for('disks_index'))

@app.route("/disks/smart/view/<device>")
@login_required
def smart_view_route(device):
    try:
        device = disktool_core.sanitize_device_name(device)
    except ValueError as e:
        flash(f'Invalid device name: {e}')
        return redirect(url_for('disks_index'))
    report = disktool_core.view_smart(device)
    return render_template('disks/smart_view.html', device=device, report=report)

@app.route("/disks/validate/<device>")
@login_required
def validate_route(device):
    try:
        device = disktool_core.sanitize_device_name(device)
    except ValueError as e:
        flash(f'Invalid device name: {e}')
        return redirect(url_for('disks_index'))
    blocks, bad = disktool_core.validate_blocks(device)
    return render_template('disks/validate.html', device=device, blocks=blocks, bad_blocks=bad)

@app.route("/disks/history")
@login_required
def disk_history():
    ops, smart = disktool_core.fetch_history_data()
    return render_template('disks/history.html', ops=ops, smart=smart)

@app.route("/disks/clear_history")
@login_required
def clear_disk_history():
    # Require operator or admin role to clear history
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to clear history.')
        return redirect(url_for('disk_history'))
    
    disktool_core.clear_history()
    flash('History cleared')
    return redirect(url_for('disk_history'))

@app.route("/disks/dashboard")
@login_required
def disk_dashboard():
    stats = disktool_core.get_dashboard_data()
    return render_template('disks/dashboard.html', **stats)

@app.route("/disks/export-smart")
@login_required
def export_smart():
    csv_path = disktool_core.export_smart_data()
    return send_file(csv_path, as_attachment=True)

@app.route("/disks/import-smart", methods=['GET','POST'])
@login_required
def import_smart():
    if request.method == 'POST':
        # Require operator or admin role to import data
        if session.get("user_id") and not current_user_has_role('operator', 'admin'):
            flash('You need operator or admin role to import SMART data.')
            return redirect(url_for('disk_history'))
        
        f = request.files['file']
        device = request.form.get('device', 'UNKNOWN')
        disktool_core.import_smart_data(f, device)
        flash('SMART data imported')
        return redirect(url_for('disk_history'))
    return render_template('disks/import.html')

@app.route("/disks/task/status/api/<int:op_id>")
@login_required
def task_status_api(op_id):
    status, progress = disktool_core.get_task_status(op_id)
    return jsonify(status=status, progress=progress)

@app.route("/disks/task/status/<int:op_id>")
@login_required
def task_status(op_id):
    action = disktool_core.get_task_action(op_id)
    return render_template('disks/task_status.html', op_id=op_id, action=action)

@app.route("/disks/task/stop/<int:op_id>")
@login_required
def stop_task(op_id):
    # Require operator or admin role to stop tasks
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to stop tasks.')
        return redirect(url_for('disk_history'))
    
    disktool_core.stop_task(op_id)
    flash(f'Task {op_id} stopped')
    return redirect(url_for('disk_history'))

@app.route("/disks/addons/<plugin>/<device>")
@login_required
def render_plugin_page(plugin, device):
    # Validate plugin name to prevent template injection
    # Only allow alphanumeric characters and underscores
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', plugin):
        flash('Invalid plugin name')
        return redirect(url_for('disks_index'))
    
    # Validate device name
    try:
        device = disktool_core.sanitize_device_name(device)
    except ValueError as e:
        flash(f'Invalid device name: {e}')
        return redirect(url_for('disks_index'))
    
    # Check if the plugin template exists
    from pathlib import Path
    template_path = Path(app.template_folder) / 'addons' / f'{plugin}.html'
    if not template_path.exists():
        flash(f'Plugin {plugin} not found')
        return redirect(url_for('disks_index'))
    
    # Special handling for remote_disk_plugin to pass remotes data
    if plugin == 'remote_disk_plugin':
        remotes = disktool_core.list_remotes()
        return render_template(f'addons/{plugin}.html', device=device, remotes=remotes)
    
    return render_template(f'addons/{plugin}.html', device=device)

@app.route("/addons/<plugin>/<device>")
@login_required
def redirect_addon_page(plugin, device):
    """Redirect old /addons/ paths to /disks/addons/ for backward compatibility"""
    return redirect(url_for('render_plugin_page', plugin=plugin, device=device))

@app.route("/disks/remotes", methods=['GET', 'POST'])
@login_required
def remotes():
    if request.method == 'POST':
        # Require operator or admin role to add remotes
        if session.get("user_id") and not current_user_has_role('operator', 'admin'):
            flash('You need operator or admin role to add remotes.')
            return redirect(url_for('remotes'))
        
        name = request.form.get('name')
        host = request.form.get('host')
        port = int(request.form.get('port', 22))
        disktool_core.add_remote(name, host, port)
        flash('Remote added')
        return redirect(url_for('remotes'))
    rems = disktool_core.list_remotes()
    return render_template('disks/remotes.html', remotes=rems)

@app.route("/disks/remotes/delete/<int:rid>")
@login_required
def remotes_delete(rid):
    # Require operator or admin role to delete remotes
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to delete remotes.')
        return redirect(url_for('remotes'))
    
    disktool_core.remove_remote(rid)
    flash('Remote removed')
    return redirect(url_for('remotes'))

# ============================================================================
# USER MANAGEMENT ROUTES
# ============================================================================

@app.route("/users")
@login_required
def users_list():
    """List all users - only accessible to admins."""
    user_id = session.get("user_id")
    if not user_id:
        flash('User management requires database authentication.')
        return redirect(url_for('index'))
    
    # Check if user is admin
    if not user_management.user_has_role(user_id, 'admin'):
        flash('Only administrators can manage users.')
        return redirect(url_for('index'))
    
    users = user_management.list_users()
    roles_by_user = {}
    for user in users:
        roles_by_user[user['id']] = user_management.get_user_role_names(user['id'])
    
    return render_template('users/list.html', users=users, roles_by_user=roles_by_user)

@app.route("/users/add", methods=["GET", "POST"])
@login_required
def users_add():
    """Add a new user - only accessible to admins."""
    user_id = session.get("user_id")
    if not user_id:
        flash('User management requires database authentication.')
        return redirect(url_for('index'))
    
    if not user_management.user_has_role(user_id, 'admin'):
        flash('Only administrators can manage users.')
        return redirect(url_for('index'))
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip() or None
        roles = request.form.getlist("roles")
        
        if not username or not password:
            flash('Username and password are required.')
            return redirect(url_for('users_add'))
        
        new_user_id = user_management.create_user(username, password, email, roles)
        if new_user_id:
            flash(f'User {username} created successfully.')
            return redirect(url_for('users_list'))
        else:
            flash(f'Username {username} already exists.')
    
    all_roles = user_management.list_roles()
    return render_template('users/add.html', all_roles=all_roles)

@app.route("/users/edit/<int:uid>", methods=["GET", "POST"])
@login_required
def users_edit(uid):
    """Edit a user - only accessible to admins."""
    user_id = session.get("user_id")
    if not user_id:
        flash('User management requires database authentication.')
        return redirect(url_for('index'))
    
    if not user_management.user_has_role(user_id, 'admin'):
        flash('Only administrators can manage users.')
        return redirect(url_for('index'))
    
    user = user_management.get_user_by_id(uid)
    if not user:
        from flask import abort
        abort(404)
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        active = 1 if request.form.get("active") else 0
        roles = request.form.getlist("roles")
        
        if not username:
            flash('Username is required.')
            return redirect(url_for('users_edit', uid=uid))
        
        # Update user
        success = user_management.update_user(
            uid, 
            username=username, 
            email=email, 
            active=active,
            password=password if password else None
        )
        
        if success:
            # Update roles
            user_management.set_user_roles(uid, roles)
            flash(f'User {username} updated successfully.')
            return redirect(url_for('users_list'))
        else:
            flash(f'Failed to update user. Username may already exist.')
    
    all_roles = user_management.list_roles()
    user_roles = user_management.get_user_role_names(uid)
    return render_template('users/edit.html', user=user, all_roles=all_roles, user_roles=user_roles)

@app.route("/users/delete/<int:uid>", methods=["POST"])
@login_required
def users_delete(uid):
    """Delete a user - only accessible to admins."""
    user_id = session.get("user_id")
    if not user_id:
        flash('User management requires database authentication.')
        return redirect(url_for('index'))
    
    if not user_management.user_has_role(user_id, 'admin'):
        flash('Only administrators can manage users.')
        return redirect(url_for('index'))
    
    # Prevent deleting yourself
    if uid == user_id:
        flash('You cannot delete your own account.')
        return redirect(url_for('users_list'))
    
    user = user_management.get_user_by_id(uid)
    if user:
        user_management.delete_user(uid)
        flash(f'User {user["username"]} deleted.')
    
    return redirect(url_for('users_list'))

@app.route("/users/profile", methods=["GET", "POST"])
@login_required
def users_profile():
    """View and edit own profile."""
    user_id = session.get("user_id")
    if not user_id:
        flash('Profile management requires database authentication.')
        return redirect(url_for('index'))
    
    user = user_management.get_user_by_id(user_id)
    if not user:
        flash('User not found.')
        return redirect(url_for('index'))
    
    if request.method == "POST":
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        
        # Update user
        user_management.update_user(
            user_id,
            email=email,
            password=password if password else None
        )
        flash('Profile updated successfully.')
        return redirect(url_for('users_profile'))
    
    user_roles = user_management.get_user_role_names(user_id)
    return render_template('users/profile.html', user=user, user_roles=user_roles)

# Security: Add security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    # Content-Security-Policy: allow inline styles/scripts for existing UI
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com https://fonts.gstatic.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self';"
    )
    # Cache-Control for static assets
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=86400, immutable'
    elif request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    else:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    # Only set HSTS header for HTTPS connections
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# ---- Network Scanner Routes ----

import socket, subprocess, concurrent.futures

def _detect_hostname(ip):
    """Try reverse DNS lookup for a discovered IP."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ''

def _check_ssh_port(ip, port=22, timeout=1.5):
    """Check if SSH port is open on an IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except Exception:
        return False

def _ping_ip(ip, timeout=1):
    """Check if a host is reachable.
    Uses TCP socket probes on common ports (no ping binary required).
    Falls back to ICMP ping via subprocess if available.
    """
    # TCP probe on common ports — works without ping binary and even through some firewalls
    probe_ports = [22, 80, 443, 445, 8080, 3389, 8443, 5900]
    for p in probe_ports:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            if s.connect_ex((ip, p)) == 0:
                s.close()
                return True
            s.close()
        except Exception:
            pass
    # Fallback: ICMP ping via subprocess (may not be available in all environments)
    try:
        import platform
        flag = '-n' if platform.system().lower() == 'windows' else '-c'
        for ping_bin in ['ping', '/bin/ping', '/usr/bin/ping', '/usr/sbin/ping']:
            try:
                result = subprocess.run(
                    [ping_bin, flag, '1', '-W', str(timeout), ip],
                    capture_output=True, timeout=timeout + 2
                )
                return result.returncode == 0
            except FileNotFoundError:
                continue
    except Exception:
        pass
    return False

@app.route('/scanner')
@login_required
def scanner():
    """Network scanner page."""
    hosts = load_hosts()
    # Collect all managed IPs for duplicate detection
    managed_ips = [h.get('host', '') for h in hosts.values()]
    # Guess default subnet from local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
        default_prefix = '.'.join(local_ip.split('.')[:3])
    except Exception:
        default_prefix = '192.168.1'
    return render_template(
        'scanner.html',
        managed_host_ips=managed_ips,
        default_prefix=default_prefix,
        tag_presets=HOST_TAG_PRESETS,
    )

@app.route('/api/scan_host')
@login_required
def api_scan_host():
    """Probe a single IP: ping + SSH port check + MAC + hostname."""
    from flask import jsonify
    ip   = request.args.get('ip', '').strip()
    port = int(request.args.get('port', 22) or 22)
    if not arp_tracker.validate_ip_address(ip):
        return jsonify({'ip': ip, 'online': False, 'ssh': False, 'mac': '', 'hostname': ''})
    online = _ping_ip(ip)
    ssh    = False
    mac    = ''
    hostname = ''
    if online:
        ssh = _check_ssh_port(ip, port)
        # Try to get MAC from ARP table (populate via ping first)
        try:
            arp = arp_tracker.get_arp_table()
            # arp is mac->ip, invert to ip->mac
            ip_to_mac = {v: k for k, v in arp.items()}
            mac = ip_to_mac.get(ip, '')
        except Exception:
            pass
        hostname = _detect_hostname(ip)
    return jsonify({'ip': ip, 'online': online, 'ssh': ssh, 'mac': mac, 'hostname': hostname})

@app.route('/hosts/quick_add', methods=['POST'])
@login_required
def quick_add_host():
    """Quick-add a host discovered by the scanner."""
    if session.get('user_id') and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to manage hosts.')
        return redirect(url_for('scanner'))
    hosts = load_hosts()
    name = request.form.get('name', '').strip()
    if not name:
        flash('Host name is required.', 'error')
        return redirect(url_for('scanner'))
    host_data = {
        'host':        request.form.get('host', '').strip(),
        'user':        request.form.get('user', 'admin').strip(),
        'mac':         request.form.get('mac', '').strip(),
        'description': request.form.get('description', '').strip(),
        'environment': request.form.get('environment', 'Production'),
        'criticality': request.form.get('criticality', 'Medium'),
        'port':        int(request.form.get('port', 22) or 22),
        'tags':        [t.strip() for t in request.form.get('tags', '').split(',') if t.strip()],
        'notes':       f'Discovered by Network Scanner on {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}',
    }
    hosts[name] = normalize_host(host_data)
    save_hosts(hosts)
    flash(f'Host "{name}" added successfully from scanner!', 'success')
    return redirect(url_for('manage_hosts'))

# ---- Update Notification API ----

@app.route('/api/update_notification')
@login_required
def api_update_notification():
    """JSON API for in-app update notification polling."""
    from flask import jsonify
    notification = version_manager.get_update_notification()
    is_admin = False
    if session.get('user_id'):
        is_admin = current_user_has_role('admin')
    elif session.get('login'):
        is_admin = True  # legacy mode
    if notification:
        return jsonify({
            'available': True,
            'type':        notification.get('type'),
            'version':     notification.get('version'),
            'description': notification.get('description'),
            'url':         notification.get('url'),
            'is_admin':    is_admin,
        })
    return jsonify({'available': False})

@app.route('/api/update_notification/dismiss', methods=['POST'])
@login_required
def api_dismiss_notification():
    """Dismiss the update notification via AJAX."""
    from flask import jsonify
    version_manager.dismiss_notification()
    return jsonify({'ok': True})

# ── /update landing page (backward-compat alias) ─────────────────────────────
@app.route("/update")
@login_required
def update_landing():
    """Redirect bare /update to the host list so old links / test scripts don't 404."""
    hosts = load_hosts()
    if hosts:
        # Redirect to the first host's update page as a sensible default
        first = next(iter(hosts))
        return redirect(url_for('update_repo', name=first))
    flash('No hosts configured. Please add a host first.', 'warning')
    return redirect(url_for('manage_hosts'))


# ---- Server Self-Update Tool ----

_server_update_log = []   # in-memory log for the running update
_server_update_lock = threading.Lock()
_server_update_running = False

def _run_server_update_bg(sudo_password: str):
    """Background thread: apt update + apt upgrade on the FleetPilot host."""
    global _server_update_running, _server_update_log
    import subprocess, shlex, datetime

    def log(msg, level='info'):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        _server_update_log.append({'ts': ts, 'msg': msg, 'level': level})

    _server_update_running = True
    _server_update_log = []
    log('Starting server package update…')

    env = os.environ.copy()
    env['DEBIAN_FRONTEND'] = 'noninteractive'
    env['SUDO_ASKPASS'] = '/bin/false'

    def run_cmd(cmd_list, label):
        log(f'▶ {label}')
        try:
            if sudo_password:
                # pipe password into sudo -S
                proc = subprocess.Popen(
                    ['sudo', '-S'] + cmd_list,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env
                )
                stdout, _ = proc.communicate(input=(sudo_password + '\n').encode(), timeout=300)
            else:
                proc = subprocess.Popen(
                    cmd_list,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env
                )
                stdout, _ = proc.communicate(timeout=300)
            for line in stdout.decode(errors='replace').splitlines():
                line = line.strip()
                if line and '[sudo]' not in line and 'password for' not in line:
                    log(line)
            if proc.returncode == 0:
                log(f'✔ {label} completed successfully.', 'success')
            else:
                log(f'✘ {label} exited with code {proc.returncode}', 'error')
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            log(f'✘ {label} timed out after 5 minutes', 'error')
            return False
        except Exception as e:
            log(f'✘ {label} failed: {e}', 'error')
            return False

    # Step 1: apt update
    ok = run_cmd(['apt-get', 'update', '-qq'], 'apt-get update')
    if not ok:
        log('apt-get update failed — aborting.', 'error')
        _server_update_running = False
        return

    # Step 2: list upgradable packages
    try:
        proc = subprocess.run(
            ['apt-get', '--simulate', 'upgrade', '-y'],
            capture_output=True, timeout=60, env=env
        )
        upgradable = [l for l in proc.stdout.decode(errors='replace').splitlines()
                      if l.startswith('Inst ')]
        if upgradable:
            log(f'Found {len(upgradable)} package(s) to upgrade:')
            for pkg in upgradable[:20]:
                log('  ' + pkg.replace('Inst ', '').split(' ')[0])
            if len(upgradable) > 20:
                log(f'  … and {len(upgradable)-20} more')
        else:
            log('All packages are already up to date.', 'success')
            _server_update_running = False
            return
    except Exception as e:
        log(f'Could not list upgradable packages: {e}', 'warn')

    # Step 3: apt upgrade
    ok = run_cmd(
        ['apt-get', 'upgrade', '-y', '-o', 'Dpkg::Options::=--force-confold'],
        'apt-get upgrade'
    )

    # Step 4: apt autoremove
    run_cmd(['apt-get', 'autoremove', '-y'], 'apt-get autoremove')

    if ok:
        log('🎉 Server update completed successfully!', 'success')
    else:
        log('Server update finished with errors. Check the log above.', 'error')

    _server_update_running = False


@app.route('/server_update', methods=['GET', 'POST'])
@login_required
def server_update():
    """Server self-update page — runs apt update + apt upgrade on the FleetPilot host."""
    global _server_update_running, _server_update_log
    if session.get('user_id') and not current_user_has_role('admin'):
        flash('You need admin role to run server updates.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = request.form.get('action', 'start')
        if action == 'start':
            if _server_update_running:
                return jsonify({'error': 'Update already running'}), 409
            sudo_pw = request.form.get('sudo_password', '')
            with _server_update_lock:
                t = threading.Thread(
                    target=_run_server_update_bg,
                    args=(sudo_pw,),
                    daemon=True
                )
                t.start()
            return jsonify({'started': True})
        elif action == 'clear':
            if not _server_update_running:
                _server_update_log = []
            return jsonify({'ok': True})
        elif action == 'reboot':
            sudo_pw = request.form.get('sudo_password', '')
            if not sudo_pw:
                return jsonify({'error': 'Sudo password required for reboot'}), 400
            import subprocess, threading
            def _do_reboot():
                import time
                time.sleep(2)  # Give the HTTP response time to reach the browser
                try:
                    proc = subprocess.Popen(
                        ['sudo', '-S', 'reboot'],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT
                    )
                    proc.communicate(input=(sudo_pw + '\n').encode(), timeout=10)
                except Exception:
                    pass
            t = threading.Thread(target=_do_reboot, daemon=True)
            t.start()
            return jsonify({'rebooting': True})

    return render_template('server_update.html',
                           running=_server_update_running,
                           log=_server_update_log)


@app.route('/api/server_update_log')
@login_required
def api_server_update_log():
    """JSON polling endpoint for live server update log."""
    return jsonify({
        'running': _server_update_running,
        'log': _server_update_log,
        'count': len(_server_update_log)
    })


# ---- FleetPilot Self-Update (git pull + pip install + service restart) ----

_fp_update_running = False
_fp_update_log = []
_fp_update_lock = threading.Lock()
_fp_restart_pending = False

def _fp_log(msg, level='info'):
    import datetime
    _fp_update_log.append({'ts': datetime.datetime.now().strftime('%H:%M:%S'), 'msg': msg, 'level': level})

def _run_fp_update_bg(channel, do_restart):
    global _fp_update_running, _fp_update_log, _fp_restart_pending
    import subprocess, datetime
    _fp_update_log = []
    _fp_restart_pending = False

    app_dir = _APP_DIR

    def run(cmd, label):
        _fp_log(f'$ {" ".join(cmd)}')
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, cwd=app_dir
            )
            for line in (proc.stdout + proc.stderr).splitlines():
                if line.strip():
                    _fp_log(line)
            if proc.returncode != 0:
                _fp_log(f'{label} failed (exit {proc.returncode})', 'error')
                return False
            return True
        except subprocess.TimeoutExpired:
            _fp_log(f'{label} timed out', 'error')
            return False
        except Exception as e:
            _fp_log(f'{label} error: {e}', 'error')
            return False

    _fp_log('Starting FleetPilot update…')
    _fp_log(f'App directory: {app_dir}')

    # Step 1: git fetch + check
    run(['git', 'fetch', '--all'], 'git fetch')
    try:
        proc = subprocess.run(['git', 'log', 'HEAD..origin/' + channel, '--oneline'],
                              capture_output=True, text=True, timeout=30, cwd=app_dir)
        pending = [l for l in proc.stdout.splitlines() if l.strip()]
        if pending:
            _fp_log(f'Found {len(pending)} new commit(s):', 'info')
            for c in pending[:10]:
                _fp_log('  ' + c)
        else:
            _fp_log('Already up to date — no new commits on ' + channel, 'success')
            _fp_update_running = False
            return
    except Exception:
        pass

    # Step 2: discard any local modifications to tracked files so git pull always wins
    # (user data is safe in data/ which is .gitignored)
    run(['git', 'checkout', '--', '.'], 'git checkout -- .')

    # Step 2b: remove untracked files that would conflict with the incoming pull
    # These are files that exist locally but are not yet tracked by git,
    # yet are part of the incoming commit (e.g. manually deployed files).
    try:
        proc_dry = subprocess.run(
            ['git', 'pull', '--ff-only', '--dry-run', 'origin', channel],
            capture_output=True, text=True, timeout=30, cwd=app_dir
        )
        if 'would be overwritten' in proc_dry.stderr or 'untracked working tree' in proc_dry.stderr:
            _fp_log('Untracked files conflict detected — stashing before pull…', 'warn')
            subprocess.run(['git', 'add', '-A'], capture_output=True, cwd=app_dir)
            subprocess.run(['git', 'stash'], capture_output=True, cwd=app_dir)
            _fp_log('Stashed local untracked files.', 'info')
    except Exception as e:
        _fp_log(f'Pre-pull stash check error (non-fatal): {e}', 'warn')

    # Step 3: git pull
    ok = run(['git', 'pull', 'origin', channel], 'git pull')
    if not ok:
        _fp_log('git pull failed — aborting update.', 'error')
        _fp_update_running = False
        return

    # Step 3: pip install requirements
    req_file = os.path.join(app_dir, 'requirements.txt')
    if os.path.exists(req_file):
        venv_pip = os.path.join(app_dir, 'venv', 'bin', 'pip')
        pip_cmd = venv_pip if os.path.exists(venv_pip) else 'pip3'
        run([pip_cmd, 'install', '-r', req_file, '-q'], 'pip install')
    else:
        _fp_log('No requirements.txt found — skipping pip install', 'warn')

    _fp_log('✅ Code update complete!', 'success')

    # Step 4: restart service
    if do_restart:
        _fp_log('Restarting FleetPilot service…', 'warn')
        _fp_restart_pending = True
        _fp_update_running = False
        import time
        time.sleep(1)
        try:
            subprocess.Popen(['sudo', 'systemctl', 'restart', 'fleetpilot'])
        except Exception as e:
            _fp_log(f'Could not restart service: {e}', 'error')
        return
    else:
        _fp_log('Skipping service restart (manual restart required).', 'warn')

    _fp_update_running = False


@app.route('/fleetpilot_update', methods=['GET', 'POST'])
@login_required
def fleetpilot_update():
    """In-app FleetPilot self-update page (git pull + pip install + restart)."""
    global _fp_update_running, _fp_update_log, _fp_restart_pending
    if session.get('user_id') and not current_user_has_role('admin'):
        flash('You need admin role to update FleetPilot.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = request.form.get('action', 'start')
        if action == 'check':
            if _fp_update_running:
                return jsonify({'error': 'Update already running'}), 409
            channel = request.form.get('channel', 'main')
            with _fp_update_lock:
                _fp_update_running = True
                t = threading.Thread(
                    target=_run_fp_update_bg,
                    args=(channel, False),
                    daemon=True
                )
                t.start()
            return jsonify({'started': True})
        elif action == 'start':
            if _fp_update_running:
                return jsonify({'error': 'Update already running'}), 409
            channel = request.form.get('channel', 'main')
            do_restart = request.form.get('after_update', 'restart') == 'restart'
            with _fp_update_lock:
                _fp_update_running = True
                t = threading.Thread(
                    target=_run_fp_update_bg,
                    args=(channel, do_restart),
                    daemon=True
                )
                t.start()
            return jsonify({'started': True})
        elif action == 'clear':
            if not _fp_update_running:
                _fp_update_log = []
            return jsonify({'ok': True})

    # GET — render page
    import subprocess
    try:
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                                          cwd=_APP_DIR, text=True).strip()
    except Exception:
        branch = 'unknown'
    try:
        commit = subprocess.check_output(['git', 'log', '-1', '--format=%h %s'],
                                          cwd=_APP_DIR, text=True).strip()
    except Exception:
        commit = 'unknown'
    try:
        from version_manager import get_current_version
        cur_ver = get_current_version()
    except Exception:
        cur_ver = 'unknown'

    return render_template('fleetpilot_update.html',
                           running=_fp_update_running,
                           log=_fp_update_log,
                           current_version=cur_ver,
                           git_branch=branch,
                           last_commit=commit)


@app.route('/api/fleetpilot_update_log')
@login_required
def api_fleetpilot_update_log():
    """JSON polling endpoint for live FleetPilot update log."""
    return jsonify({
        'running': _fp_update_running,
        'log': _fp_update_log,
        'count': len(_fp_update_log),
        'restart_pending': _fp_restart_pending
    })


# ---- UI Preference Routes ----

@app.route("/set_theme", methods=["POST", "GET"])
def set_theme():
    """Persist the user's chosen theme (light/dark) in the session."""
    theme = request.args.get('theme') or request.form.get('theme', 'dark')
    if theme in ('light', 'dark'):
        session['theme'] = theme
    return ('', 204)

@app.route("/set_language", methods=["GET", "POST"])
def set_language():
    """Persist the user's chosen language in the session.
    Accepts both GET (?lang=de&next=/hosts) and POST for backwards compat.
    CSRF-exempt because changing UI language is not a security-sensitive action.
    """
    from i18n import SUPPORTED_LANGUAGES
    lang = request.args.get('lang') or request.form.get('lang', 'en')
    if lang not in SUPPORTED_LANGUAGES:
        lang = 'en'
    session['lang'] = lang
    session.modified = True          # force session save even if nothing else changed
    next_url = request.args.get('next') or request.form.get('next') or request.referrer or '/index'
    # Sanitise next_url: only allow relative paths
    if next_url and (next_url.startswith('http://') or next_url.startswith('https://')):
        next_url = '/index'
    return redirect(next_url)

# ─────────────────────────────────────────────────────────────────────────────
# Plugin Manager Routes
# ─────────────────────────────────────────────────────────────────────────────

import re
from pathlib import Path

REMOTE_PLUGIN_REPO = "https://raw.githubusercontent.com/ChristianHandy/FleetPilot-Plugins/main/plugins.json"

HOOK_NAMES_LIST = [
    "dashboard_widgets", "host_card_actions", "host_detail_tabs",
    "scanner_result_actions", "update_pre_hook", "update_post_hook",
    "notification_hook", "sidebar_links", "navbar_badges",
    "settings_panels", "device_buttons",
]

EXAMPLE_PLUGINS = [
    {"name": "Example Dashboard Widget", "file": "example_dashboard_widget.py",
     "description": "Adds a fleet-health summary widget to the Home dashboard. Demonstrates the dashboard_widget hook."},
    {"name": "Slack Notification", "file": "example_slack_notify.py",
     "description": "Sends a Slack webhook message after every update run. Requires SLACK_WEBHOOK_URL env var."},
    {"name": "Host Ping Button", "file": "example_host_ping.py",
     "description": "Adds a Ping button to every host card. Shows round-trip time via TCP probe."},
]


def _sanitize_addon_path(filename: str):
    """Return a safe absolute path inside addons/ or None if invalid."""
    base = Path("addons").resolve()
    target = (base / filename).resolve()
    try:
        target.relative_to(base)
        return target
    except ValueError:
        return None


@app.route("/plugins")
@login_required
def plugin_manager():
    """Plugin Manager overview page."""
    plugins = addon_mgr.status
    active_hooks = {}
    for h in HOOK_NAMES_LIST:
        count = len(addon_mgr.hooks.get(h, []))
        if count:
            active_hooks[h] = count
    installed_names = [p["file"] for p in plugins]
    hook_count = sum(len(v) for v in addon_mgr.hooks.values())
    return render_template(
        "plugin_manager.html",
        plugins=plugins,
        hook_names=HOOK_NAMES_LIST,
        active_hooks=active_hooks,
        installed_names=installed_names,
        hook_count=hook_count,
    )


@app.route("/plugins/upload", methods=["POST"])
@login_required
def plugin_upload():
    """Upload a .py plugin file into addons/."""
    if not current_user_has_role("admin"):
        flash("Only administrators can install plugins.", "error")
        return redirect("/plugins")
    f = request.files.get("plugin_file")
    if not f or not f.filename.endswith(".py"):
        flash("Please upload a valid .py file.", "error")
        return redirect("/plugins")
    fname = re.sub(r"[^a-zA-Z0-9_.\/]", "_", f.filename)
    if not re.match(r"^[a-zA-Z0-9_]+\.py$", fname):
        flash("Invalid filename.", "error")
        return redirect("/plugins")
    dest = _sanitize_addon_path(fname)
    if dest is None:
        flash("Invalid path.", "error")
        return redirect("/plugins")
    f.save(str(dest))
    flash(f"Plugin '{fname}' uploaded. Restart FleetPilot to activate it.", "success")
    return redirect("/plugins")


@app.route("/plugins/uninstall/<plugin_file>", methods=["POST"])
@login_required
def plugin_uninstall(plugin_file):
    """Delete a plugin file from addons/."""
    if not current_user_has_role("admin"):
        flash("Only administrators can uninstall plugins.", "error")
        return redirect("/plugins")
    if plugin_file == "plugin_manager.py":
        flash("Cannot uninstall the built-in Plugin Manager.", "warning")
        return redirect("/plugins")
    if not re.match(r"^[a-zA-Z0-9_]+\.py$", plugin_file):
        flash("Invalid filename.", "error")
        return redirect("/plugins")
    path = _sanitize_addon_path(plugin_file)
    if path is None or not path.exists():
        flash("Plugin not found.", "error")
        return redirect("/plugins")
    os.remove(path)
    # Remove associated template if present
    tpl = Path("templates/addons") / plugin_file.replace(".py", ".html")
    if tpl.exists():
        os.remove(tpl)
    flash(f"Plugin '{plugin_file}' removed. Restart FleetPilot to deactivate it.", "success")
    return redirect("/plugins")


@app.route("/plugins/view/<plugin_file>")
@login_required
def plugin_view_source(plugin_file):
    """Display the source code of an installed plugin."""
    if not re.match(r"^[a-zA-Z0-9_]+\.py$", plugin_file):
        flash("Invalid filename.", "error")
        return redirect("/plugins")
    path = _sanitize_addon_path(plugin_file)
    if path is None or not path.exists():
        flash("Plugin not found.", "error")
        return redirect("/plugins")
    source = path.read_text(encoding="utf-8")
    return render_template(
        "plugin_source.html",
        filename=plugin_file,
        source=source,
    )


@app.route("/plugins/docs")
@login_required
def plugin_docs():
    """Plugin developer documentation page."""
    return render_template("plugin_docs.html", examples=EXAMPLE_PLUGINS)


@app.route("/plugins/repository.json")
@login_required
def plugin_repository_json():
    """Proxy / cache the remote plugin repository JSON."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(REMOTE_PLUGIN_REPO, timeout=5) as resp:
            data = resp.read().decode("utf-8")
        return app.response_class(data, mimetype="application/json")
    except Exception:
        return jsonify({"plugins": []})


@app.route("/plugins/install/<plugin_id>", methods=["POST"])
@login_required
def plugin_install_remote(plugin_id):
    """Install a plugin from the remote repository."""
    if not current_user_has_role("admin"):
        flash("Only administrators can install plugins.", "error")
        return redirect("/plugins")
    if not re.match(r"^[a-zA-Z0-9_]+$", plugin_id):
        flash("Invalid plugin ID.", "error")
        return redirect("/plugins")
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(REMOTE_PLUGIN_REPO, timeout=10) as resp:
            repo = json.loads(resp.read().decode("utf-8"))
        plugin_info = next((p for p in repo.get("plugins", []) if p.get("id") == plugin_id), None)
        if not plugin_info:
            flash(f"Plugin '{plugin_id}' not found in repository.", "error")
            return redirect("/plugins")
        plugin_url = plugin_info.get("url", "")
        if not plugin_url:
            flash("Plugin URL missing.", "error")
            return redirect("/plugins")
        with urllib.request.urlopen(plugin_url, timeout=10) as resp:
            code = resp.read().decode("utf-8")
        fname = f"{plugin_id}.py"
        dest = _sanitize_addon_path(fname)
        if dest is None:
            flash("Invalid path.", "error")
            return redirect("/plugins")
        if dest.exists():
            flash(f"Plugin '{plugin_id}' is already installed.", "warning")
            return redirect("/plugins")
        dest.write_text(code, encoding="utf-8")
        flash(f"Plugin '{plugin_id}' installed. Restart FleetPilot to activate it.", "success")
    except Exception as exc:
        flash(f"Install failed: {exc}", "error")
    return redirect("/plugins")


# ══════════════════════════════════════════════════════════════════════════════
# VM CONTROLLER ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/vm")
@login_required
def vm_index():
    """VM Controller — overview of all endpoints."""
    endpoints = vm_controller.list_endpoints()
    events = vm_controller.get_events(limit=20)
    return render_template("vm/index.html", endpoints=endpoints, events=events)


@app.route("/vm/add", methods=["GET", "POST"])
@login_required
def vm_add():
    """Add a new VM endpoint (Proxmox or Veeam)."""
    if not current_user_has_role("admin"):
        flash("Only administrators can add VM endpoints.", "error")
        return redirect("/vm")
    if request.method == "POST":
        try:
            vm_controller.add_endpoint(
                name=request.form["name"],
                platform=request.form["platform"],
                host=request.form["host"],
                port=int(request.form.get("port", 8006)),
                username=request.form["username"],
                password=request.form["password"],
                verify_ssl=bool(request.form.get("verify_ssl")),
                notes=request.form.get("notes", ""),
            )
            flash("VM endpoint added successfully.", "success")
        except Exception as exc:
            flash(f"Error: {exc}", "error")
        return redirect("/vm")
    return render_template("vm/add.html")


@app.route("/vm/delete/<int:ep_id>", methods=["POST"])
@login_required
def vm_delete(ep_id):
    if not current_user_has_role("admin"):
        flash("Only administrators can delete VM endpoints.", "error")
        return redirect("/vm")
    vm_controller.delete_endpoint(ep_id)
    flash("Endpoint deleted.", "success")
    return redirect("/vm")


@app.route("/vm/test/<int:ep_id>")
@login_required
def vm_test(ep_id):
    result = vm_controller.test_connection(ep_id)
    return json.dumps(result), 200, {"Content-Type": "application/json"}


@app.route("/vm/<int:ep_id>/update")
@login_required
def vm_update(ep_id):
    """Trigger apt update + upgrade on a Proxmox endpoint via SSH using stored credentials."""
    if not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to perform system updates.', 'error')
        return redirect('/vm')
    ep = vm_controller.get_endpoint(ep_id)
    if not ep:
        flash('Endpoint not found.', 'error')
        return redirect('/vm')
    if ep.get('platform') != 'proxmox':
        flash('System updates are only supported for Proxmox endpoints.', 'error')
        return redirect('/vm')
    host = ep['host']
    user = ep['username']
    name = ep['name']
    password = ep.get('password_plain', '') or None
    log_key = f"vm_{ep_id}"
    logs[log_key] = []
    threading.Thread(
        target=run_update,
        args=(host, user, name, logs[log_key]),
        kwargs={'password': password},
        daemon=True
    ).start()
    return redirect(f"/progress/{log_key}")


@app.route("/vm/<int:ep_id>")
@login_required
def vm_detail(ep_id):
    """Show VMs / backup jobs for one endpoint."""
    ep = vm_controller.list_endpoints()
    ep = next((e for e in ep if e["id"] == ep_id), None)
    if not ep:
        flash("Endpoint not found.", "error")
        return redirect("/vm")
    vms = []
    jobs = []
    nodes = []
    error = None
    try:
        if ep["platform"] == "proxmox":
            client = vm_controller.connect(ep_id)
            nodes = client.get_nodes()
            vms = client.get_vms()
        elif ep["platform"] == "veeam":
            jobs = vm_controller.get_all_jobs(ep_id)
    except Exception as exc:
        error = str(exc)
    return render_template("vm/detail.html",
                           ep=ep, vms=vms, jobs=jobs, nodes=nodes, error=error)


@app.route("/vm/<int:ep_id>/action", methods=["POST"])
@login_required
def vm_action(ep_id):
    """Perform a power action on a Proxmox VM."""
    if not current_user_has_role("admin"):
        return json.dumps({"ok": False, "error": "Permission denied"}), 403, {"Content-Type": "application/json"}
    node   = request.form.get("node", "")
    vmid   = int(request.form.get("vmid", 0))
    action = request.form.get("action", "")
    rtype  = request.form.get("rtype", "qemu")
    if action not in ("start", "stop", "shutdown", "reboot", "suspend", "resume"):
        return json.dumps({"ok": False, "error": "Invalid action"}), 400, {"Content-Type": "application/json"}
    result = vm_controller.vm_power_action(ep_id, node, vmid, action, rtype)
    return json.dumps(result), 200, {"Content-Type": "application/json"}


@app.route("/vm/<int:ep_id>/veeam/job/<job_id>/start", methods=["POST"])
@login_required
def veeam_start_job(ep_id, job_id):
    if not current_user_has_role("admin"):
        return json.dumps({"ok": False, "error": "Permission denied"}), 403, {"Content-Type": "application/json"}
    try:
        client = vm_controller.connect(ep_id)
        result = client.start_job(job_id)
        vm_controller.log_event(ep_id, job_id, job_id, "START_JOB",
                                 "ok" if result.get("ok") else "error")
        return json.dumps(result), 200, {"Content-Type": "application/json"}
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}), 500, {"Content-Type": "application/json"}


@app.route("/vm/<int:ep_id>/disks")
@login_required
def vm_disks(ep_id):
    """Show physical disks on a Proxmox node."""
    node = request.args.get("node", "")
    disks = []
    error = None
    try:
        disks = vm_controller.get_proxmox_disks(ep_id, node)
        # Register disks in SMART manager
        for d in disks:
            dev = d.get("dev", d.get("devpath", "")).lstrip("/dev/")
            if dev:
                smart_manager.register_disk(
                    source="proxmox",
                    device=dev,
                    serial=d.get("serial"),
                    model=d.get("model"),
                    size_gb=round(d.get("size", 0) / 1e9, 1) if d.get("size") else None,
                    source_id=str(ep_id)
                )
    except Exception as exc:
        error = str(exc)
    return render_template("vm/disks.html", ep_id=ep_id, node=node, disks=disks, error=error)


# ══════════════════════════════════════════════════════════════════════════════
# STORAGE CONTROLLER ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/storage")
@login_required
def storage_index():
    """Storage Controller — overview of all NAS endpoints."""
    endpoints = storage_controller.list_endpoints()
    events = storage_controller.get_events(limit=20)
    return render_template("storage/index.html", endpoints=endpoints, events=events)


@app.route("/storage/add", methods=["GET", "POST"])
@login_required
def storage_add():
    if not current_user_has_role("admin"):
        flash("Only administrators can add storage endpoints.", "error")
        return redirect("/storage")
    if request.method == "POST":
        try:
            storage_controller.add_endpoint(
                name=request.form["name"],
                platform=request.form["platform"],
                host=request.form["host"],
                port=int(request.form.get("port", 443)),
                api_key=request.form["api_key"],
                verify_ssl=bool(request.form.get("verify_ssl")),
                notes=request.form.get("notes", ""),
            )
            flash("Storage endpoint added successfully.", "success")
        except Exception as exc:
            flash(f"Error: {exc}", "error")
        return redirect("/storage")
    return render_template("storage/add.html")


@app.route("/storage/delete/<int:ep_id>", methods=["POST"])
@login_required
def storage_delete(ep_id):
    if not current_user_has_role("admin"):
        flash("Only administrators can delete storage endpoints.", "error")
        return redirect("/storage")
    storage_controller.delete_endpoint(ep_id)
    flash("Endpoint deleted.", "success")
    return redirect("/storage")


@app.route("/storage/test/<int:ep_id>")
@login_required
def storage_test(ep_id):
    result = storage_controller.test_connection(ep_id)
    return json.dumps(result), 200, {"Content-Type": "application/json"}


@app.route("/storage/<int:ep_id>")
@login_required
def storage_detail(ep_id):
    """Show full overview for one storage endpoint."""
    overview = {}
    error = None
    try:
        overview = storage_controller.get_storage_overview(ep_id)
        # Register disks in SMART manager
        for d in overview.get("disks", []):
            smart_manager.register_disk(
                source=overview.get("platform", "storage"),
                device=d["name"],
                serial=d.get("serial"),
                model=d.get("model"),
                size_gb=d.get("size_gb"),
                source_id=str(ep_id)
            )
    except Exception as exc:
        error = str(exc)
        overview = {"error": error}
    return render_template("storage/detail.html", ep_id=ep_id, overview=overview, error=error)


@app.route("/storage/<int:ep_id>/poll", methods=["POST"])
@login_required
def storage_poll(ep_id):
    """Manually trigger a disk health poll for a storage endpoint."""
    if not current_user_has_role("admin"):
        return json.dumps({"ok": False, "error": "Permission denied"}), 403, {"Content-Type": "application/json"}
    try:
        storage_controller.poll_and_log_disks(ep_id)
        return json.dumps({"ok": True, "message": "Poll complete"}), 200, {"Content-Type": "application/json"}
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}), 500, {"Content-Type": "application/json"}


# ══════════════════════════════════════════════════════════════════════════════
# SMART MANAGER / DISK HEALTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/smart")
@app.route("/smart/dashboard")   # backward-compat alias (test scripts / old bookmarks)
@login_required
def smart_dashboard():
    """SMART Manager — unified disk health dashboard."""
    disks = smart_manager.get_all_disks()
    summary = smart_manager.get_health_summary()
    alerts = smart_manager.get_active_alerts()
    poll_cfg = smart_manager.get_poll_config()
    hosts = load_hosts()
    return render_template("smart/dashboard.html",
                           disks=disks, summary=summary,
                           alerts=alerts, poll_cfg=poll_cfg,
                           hosts=hosts)


@app.route("/smart/poll", methods=["POST"])
@app.route("/smart/poll_now", methods=["POST"])   # backward-compat alias
@login_required
def smart_poll_now():
    """Trigger an immediate SMART poll of ALL sources (local + SSH hosts + Proxmox + Storage)."""
    if not current_user_has_role("admin"):
        flash("Only administrators can trigger SMART polls.", "error")
        return redirect("/smart")
    total = 0
    errors = []
    try:
        # 1. Local disks
        local = smart_manager.collect_all_local_disks()
        total += len(local)
    except Exception as exc:
        errors.append(f"Local: {exc}")
    try:
        # 2. SSH-configured hosts
        ssh_disks = smart_manager.collect_all_ssh_hosts()
        total += len(ssh_disks)
    except Exception as exc:
        errors.append(f"SSH hosts: {exc}")
    try:
        # 3. Proxmox endpoints
        for ep in vm_controller.list_endpoints():
            if ep.get("platform") == "proxmox" and ep.get("enabled", 1):
                try:
                    client = vm_controller.connect(ep["id"])
                    for node in client.get_nodes():
                        smart_manager.collect_proxmox_disks(ep["id"], node["node"])
                except Exception as exc:
                    errors.append(f"Proxmox {ep['name']}: {exc}")
    except Exception as exc:
        errors.append(f"Proxmox: {exc}")
    try:
        # 4. Storage endpoints
        for ep in storage_controller.list_endpoints():
            if ep.get("enabled", 1):
                try:
                    smart_manager.collect_remote_storage_disks(ep["id"])
                except Exception as exc:
                    errors.append(f"Storage {ep['name']}: {exc}")
    except Exception as exc:
        errors.append(f"Storage: {exc}")

    all_disks = smart_manager.get_all_disks()
    msg = f"Full SMART import complete — {len(all_disks)} disk(s) in registry."
    if errors:
        msg += f" Warnings: {'; '.join(errors[:3])}"
    flash(msg, "success" if not errors else "warning")
    return redirect("/smart")


@app.route("/smart/import_host/<host_name>", methods=["POST"])
@login_required
def smart_import_host(host_name):
    """Import disks from a single SSH-configured host into the SMART registry."""
    if not current_user_has_role("admin"):
        return json.dumps({"ok": False, "error": "Permission denied"}), 403, {"Content-Type": "application/json"}
    hosts = load_hosts()
    if host_name not in hosts:
        return json.dumps({"ok": False, "error": "Host not found"}), 404, {"Content-Type": "application/json"}
    h = hosts[host_name]
    ip = h.get("host", "")
    user = h.get("user", "root")
    port = int(h.get("port", 22))
    key_path = h.get("ssh_key") or None
    if ip in ("localhost", "127.0.0.1", "::1", ""):
        # Localhost: use local collection
        results = smart_manager.collect_all_local_disks()
    else:
        results = smart_manager.collect_ssh_host_disks(
            host_name=host_name, host_ip=ip, user=user,
            port=port, key_path=key_path
        )
    return json.dumps({"ok": True, "imported": len(results),
                       "disks": [{"device": r["device"], "health": r["health"],
                                   "model": r.get("model"), "temp": r.get("temp")} for r in results]}), \
           200, {"Content-Type": "application/json"}


@app.route("/smart/config", methods=["POST"])
@login_required
def smart_config():
    """Update SMART polling configuration."""
    if not current_user_has_role("admin"):
        flash("Only administrators can change SMART config.", "error")
        return redirect("/smart")
    try:
        interval = int(request.form.get("interval_minutes", 60))
        enabled  = bool(request.form.get("enabled"))
        smart_manager.set_poll_config(interval, enabled)
        flash("SMART polling configuration updated.", "success")
    except Exception as exc:
        flash(f"Config error: {exc}", "error")
    return redirect("/smart")


@app.route("/smart/disk/<int:disk_id>")
@login_required
def smart_disk_detail(disk_id):
    """Detailed SMART history and attribute trends for one disk."""
    disk = smart_manager.get_disk_by_id(disk_id)
    if not disk:
        flash("Disk not found.", "error")
        return redirect("/smart")
    snapshots = smart_manager.get_disk_snapshots(disk_id, limit=30)
    attributes = smart_manager.get_disk_attributes(disk_id, limit=200)
    # Build attribute trend data for charts
    attr_trends = {}
    for a in attributes:
        aid = a["attr_id"]
        if aid not in attr_trends:
            attr_trends[aid] = {"name": a["attr_name"], "data": []}
        attr_trends[aid]["data"].append({"ts": a["ts"], "raw": a["raw_value"]})
    return render_template("smart/disk_detail.html",
                           disk=disk, snapshots=snapshots,
                           attr_trends=attr_trends)


@app.route("/smart/alert/<int:alert_id>/ack", methods=["POST"])
@login_required
def smart_ack_alert(alert_id):
    smart_manager.acknowledge_alert(alert_id)
    flash("Alert acknowledged.", "success")
    return redirect("/smart")


@app.route("/api/smart/summary")
@login_required
def api_smart_summary():
    """JSON API: disk health summary for widgets."""
    return json.dumps(smart_manager.get_health_summary()), 200, {"Content-Type": "application/json"}


@app.route("/api/smart/disks")
@login_required
def api_smart_disks():
    """JSON API: full disk list with latest health status."""
    disks = smart_manager.get_all_disks()
    return json.dumps(disks, default=str), 200, {"Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────────
# CheckMK Integration Routes
# ─────────────────────────────────────────────────────────────────────────────
import checkmk_integration as _cmk
import secrets as _secrets_mod

# API token for CheckMK (stored in a simple file, generated on first use)
_CMK_TOKEN_FILE = os.path.join(DATA_DIR, ".checkmk_token")

def _get_or_create_cmk_token() -> str:
    """Return the persistent CheckMK API token, creating it if necessary."""
    if os.path.exists(_CMK_TOKEN_FILE):
        with open(_CMK_TOKEN_FILE) as f:
            tok = f.read().strip()
            if tok:
                return tok
    tok = _secrets_mod.token_hex(32)
    with open(_CMK_TOKEN_FILE, "w") as f:
        f.write(tok)
    os.chmod(_CMK_TOKEN_FILE, 0o600)
    return tok


def _check_cmk_token():
    """Validate the X-FleetPilot-Token header or query param."""
    token = (request.headers.get("X-FleetPilot-Token")
             or request.args.get("token", ""))
    expected = _get_or_create_cmk_token()
    return token == expected


@app.route("/api/checkmk/token_info")
@login_required
def api_checkmk_token_info():
    """Return the current CheckMK API token for authenticated dashboard users.

    This allows scripts and integrations running inside the same browser
    session to discover the token without visiting /checkmk manually.
    """
    token = _get_or_create_cmk_token()
    base_url = request.host_url.rstrip("/")
    return jsonify({
        "token": token,
        "usage": {
            "header": "X-FleetPilot-Token: " + token,
            "query":  base_url + "/api/checkmk/status?token=" + token,
        }
    })


@app.route("/api/checkmk/agent")
def api_checkmk_agent():
    """CheckMK datasource program endpoint — returns <<<local>>> section."""
    if not _check_cmk_token():
        return "Unauthorized", 401
    hosts = load_hosts()
    output = _cmk.build_agent_output(
        hosts,
        smart_manager=smart_manager,
        vm_controller=vm_controller,
        storage_controller=storage_controller,
    )
    return output, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/checkmk/host/<host_name>")
def api_checkmk_host(host_name):
    """CheckMK piggyback data for a specific host."""
    if not _check_cmk_token():
        return "Unauthorized", 401
    hosts = load_hosts()
    if host_name not in hosts:
        return f"Host '{host_name}' not found", 404
    output = _cmk.build_host_piggyback(
        host_name, hosts[host_name], smart_manager=smart_manager
    )
    return output, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/checkmk/hosts")
def api_checkmk_hosts():
    """JSON list of all configured hosts (for piggyback script)."""
    if not _check_cmk_token():
        return jsonify({"error": "Unauthorized"}), 401
    hosts = load_hosts()
    return jsonify({"hosts": [{"name": n, "ip": h.get("host", "")} for n, h in hosts.items()]})


@app.route("/api/checkmk/status")
def api_checkmk_status():
    """Structured JSON status for CheckMK REST API or Grafana.

    Authentication: pass the FleetPilot API token via the
    ``X-FleetPilot-Token`` request header **or** the ``?token=<value>``
    query parameter.  Retrieve the token from the CheckMK integration
    page at ``/checkmk``.
    """
    if not _check_cmk_token():
        return jsonify({
            "error": "Unauthorized",
            "hint": (
                "Supply the API token via the 'X-FleetPilot-Token' header "
                "or '?token=<value>' query parameter. "
                "Find your token at /checkmk."
            )
        }), 401
    hosts = load_hosts()
    data = _cmk.build_status_json(
        hosts,
        smart_manager=smart_manager,
        vm_controller=vm_controller,
        storage_controller=storage_controller,
    )
    return jsonify(data)


@app.route("/checkmk")
@login_required
def checkmk_dashboard():
    """CheckMK Integration configuration page."""
    token = _get_or_create_cmk_token()
    base_url = request.host_url.rstrip("/")
    script_local = _cmk.LOCAL_CHECK_SCRIPT_TEMPLATE.format(
        base_url=base_url, api_token=token
    )
    script_piggyback = _cmk.PIGGYBACK_SCRIPT_TEMPLATE.format(
        base_url=base_url, api_token=token
    )
    hosts = load_hosts()
    status = _cmk.build_status_json(
        hosts,
        smart_manager=smart_manager,
        vm_controller=vm_controller,
        storage_controller=storage_controller,
    )
    return render_template(
        "checkmk/index.html",
        token=token,
        base_url=base_url,
        script_local=script_local,
        script_piggyback=script_piggyback,
        status=status,
    )


@app.route("/checkmk/regenerate_token", methods=["POST"])
@login_required
def checkmk_regenerate_token():
    """Regenerate the CheckMK API token."""
    if not current_user_has_role("admin"):
        flash("Admin role required.", "error")
        return redirect("/checkmk")
    tok = _secrets_mod.token_hex(32)
    with open(_CMK_TOKEN_FILE, "w") as f:
        f.write(tok)
    os.chmod(_CMK_TOKEN_FILE, 0o600)
    flash("CheckMK API token regenerated successfully.", "success")
    return redirect("/checkmk")


@app.route("/checkmk/download_script/<script_type>")
@login_required
def checkmk_download_script(script_type):
    """Download CheckMK local check shell script."""
    token = _get_or_create_cmk_token()
    base_url = request.host_url.rstrip("/")
    if script_type == "local":
        content = _cmk.LOCAL_CHECK_SCRIPT_TEMPLATE.format(
            base_url=base_url, api_token=token
        )
        filename = "fleetpilot_check"
    elif script_type == "piggyback":
        content = _cmk.PIGGYBACK_SCRIPT_TEMPLATE.format(
            base_url=base_url, api_token=token
        )
        filename = "fleetpilot_piggyback"
    else:
        return "Unknown script type", 404
    from flask import Response
    return Response(
        content,
        mimetype="text/x-shellscript",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    # Initialize User Management database
    user_management.init_user_db()
    # Migrate environment variable user to database
    if user_management.migrate_env_user_to_db():
        print(f"INFO: Migrated environment variable user '{USERNAME}' to database.")
    
    # Initialize Disk Tools database
    disktool_core.init_db()
    # Start Disk Tools auto-mode worker
    threading.Thread(target=disktool_core.auto_mode_worker, daemon=True).start()
    
    # Configure automatic update scheduler
    scheduler.configure_scheduler()
    
    # Background task to check for dashboard version updates
    def version_check_worker():
        """Background worker to periodically check for dashboard updates"""
        import time
        while True:
            try:
                settings = scheduler.load_update_settings()
                if settings.get("dashboard_update_notifications", True):
                    if version_manager.should_check_for_updates(check_interval_hours=24):
                        version_manager.check_for_updates()
            except Exception as e:
                print(f"Error checking for dashboard updates: {e}")
            # Sleep for 1 hour before checking again
            time.sleep(3600)
    
    threading.Thread(target=version_check_worker, daemon=True).start()
    
    # Security: Disable debug mode in production
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)


# ─────────────────────────────────────────────────────────────────────────────
# System Monitor Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/monitor')
@login_required
def monitor():
    """System resource & temperature monitor dashboard."""
    latest = system_monitor.get_latest()
    history = system_monitor.get_history(hours=24, limit=1440)
    log_data = system_monitor.get_log(page=1, per_page=50)
    return render_template(
        'monitor.html',
        latest=latest,
        history=history,
        log=log_data.get('items', []),
        log_meta=log_data,
    )


@app.route('/api/monitor/latest')
@login_required
def api_monitor_latest():
    """Return the most recent system metrics as JSON."""
    data = system_monitor.get_latest()
    return jsonify(data or {})


@app.route('/api/monitor/history')
@login_required
def api_monitor_history():
    """Return metric history for the last N hours."""
    hours = min(int(request.args.get('hours', 24)), 168)  # max 7 days
    limit = min(int(request.args.get('limit', 1440)), 10080)
    return jsonify(system_monitor.get_history(hours=hours, limit=limit))


@app.route('/api/monitor/log')
@login_required
def api_monitor_log():
    """Return paginated log entries."""
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(int(request.args.get('per_page', 100)), 500)
    return jsonify(system_monitor.get_log(page=page, per_page=per_page))


# ═══════════════════════════════════════════════════════════════════════════════
# Corsair Commander Pro Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/commander')
@login_required
def commander_index():
    """Corsair Commander Pro overview page."""
    devices = corsair_commander.list_devices()
    all_latest = corsair_commander.get_all_latest()
    return render_template('commander/index.html',
                           devices=devices,
                           all_latest=all_latest)


@app.route('/commander/add', methods=['GET', 'POST'])
@login_required
def commander_add():
    """Add a new Commander Pro device."""
    if request.method == 'POST':
        name       = sanitize_input(request.form.get('name', ''), max_len=64)
        host       = sanitize_input(request.form.get('host', ''), max_len=253)
        port       = int(request.form.get('port', 22) or 22)
        username   = sanitize_input(request.form.get('username', 'root'), max_len=64)
        password   = request.form.get('password', '')
        ssh_key    = request.form.get('ssh_key', '').strip()
        match_str  = sanitize_input(request.form.get('match_str', 'Commander Pro'), max_len=128)
        use_direct = bool(request.form.get('use_direct'))
        notes      = sanitize_input(request.form.get('notes', ''), max_len=512)

        if not name or not host:
            flash('Name and host are required.', 'error')
            try:
                from flask_wtf.csrf import generate_csrf as _gcf
                _tok = _gcf()
            except Exception:
                _tok = ''
            return render_template('commander/add.html', csrf_token_value=_tok)

        try:
            dev_id = corsair_commander.add_device(
                name=name, host=host, port=port, username=username,
                password=password, ssh_key=ssh_key, match_str=match_str,
                use_direct=use_direct, notes=notes
            )
            flash(f'Device "{name}" added successfully.', 'success')
            return redirect(url_for('commander_detail', dev_id=dev_id))
        except Exception as exc:
            flash(f'Error adding device: {exc}', 'error')

    try:
        from flask_wtf.csrf import generate_csrf as _gcf
        _tok = _gcf()
    except Exception:
        _tok = ''
    return render_template('commander/add.html', csrf_token_value=_tok)


@app.route('/commander/<int:dev_id>')
@login_required
def commander_detail(dev_id):
    """Commander Pro device detail page with live status and history."""
    dev = corsair_commander.get_device(dev_id)
    if not dev:
        flash('Device not found.', 'error')
        return redirect(url_for('commander_index'))
    latest = corsair_commander.get_latest(dev_id)
    history = corsair_commander.get_history(dev_id, hours=24, limit=1440)
    return render_template('commander/detail.html',
                           dev=dev,
                           latest=latest,
                           history=history)


@app.route('/commander/<int:dev_id>/edit', methods=['GET', 'POST'])
@login_required
def commander_edit(dev_id):
    """Edit Commander Pro device settings."""
    dev = corsair_commander.get_device(dev_id)
    if not dev:
        flash('Device not found.', 'error')
        return redirect(url_for('commander_index'))

    if request.method == 'POST':
        fields = {
            'name':       sanitize_input(request.form.get('name', ''), max_len=64),
            'host':       sanitize_input(request.form.get('host', ''), max_len=253),
            'port':       int(request.form.get('port', 22) or 22),
            'username':   sanitize_input(request.form.get('username', 'root'), max_len=64),
            'match_str':  sanitize_input(request.form.get('match_str', 'Commander Pro'), max_len=128),
            'use_direct': 1 if request.form.get('use_direct') else 0,
            'notes':      sanitize_input(request.form.get('notes', ''), max_len=512),
            'enabled':    1 if request.form.get('enabled') else 0,
        }
        pw = request.form.get('password', '')
        if pw:
            fields['password'] = pw
        ssh_key = request.form.get('ssh_key', '').strip()
        if ssh_key:
            fields['ssh_key'] = ssh_key

        corsair_commander.update_device(dev_id, **fields)
        flash('Device updated.', 'success')
        return redirect(url_for('commander_detail', dev_id=dev_id))

    return render_template('commander/edit.html', dev=dev)


@app.route('/commander/<int:dev_id>/delete', methods=['POST'])
@login_required
def commander_delete(dev_id):
    """Delete a Commander Pro device."""
    corsair_commander.delete_device(dev_id)
    flash('Device deleted.', 'success')
    return redirect(url_for('commander_index'))


@app.route('/commander/<int:dev_id>/refresh')
@_csrf.exempt
@login_required
def commander_refresh(dev_id):
    """Trigger an immediate status poll and redirect to detail page."""
    dev = corsair_commander.get_device(dev_id)
    if not dev:
        return jsonify({'ok': False, 'error': 'Device not found'}), 404
    status = corsair_commander.fetch_status(dev)
    if status.get('ok'):
        from corsair_commander import _save_sample
        _save_sample(dev_id, status)
    return redirect(url_for('commander_detail', dev_id=dev_id))


@app.route('/commander/<int:dev_id>/test')
@_csrf.exempt
@login_required
def commander_test(dev_id):
    """Test SSH + liquidctl connectivity."""
    result = corsair_commander.test_connection(dev_id)
    return jsonify(result)


@app.route('/commander/<int:dev_id>/set_fan', methods=['POST'])
@login_required
@_csrf.exempt
def commander_set_fan(dev_id):
    """Set fan speed on a Commander Pro device."""
    dev = corsair_commander.get_device(dev_id)
    if not dev:
        return jsonify({'ok': False, 'error': 'Device not found'}), 404

    channel = request.form.get('channel', 'fan1')
    mode    = request.form.get('mode', 'fixed')   # 'fixed' or 'profile'

    if mode == 'fixed':
        try:
            speed = int(request.form.get('duty', 50))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Invalid duty value'}), 400
    else:
        # Profile: pairs of temp,rpm from form
        try:
            pairs_raw = request.form.get('profile', '')
            pairs = []
            for pair in pairs_raw.split(';'):
                pair = pair.strip()
                if pair:
                    t, r = pair.split(',')
                    pairs.append((int(t.strip()), int(r.strip())))
            speed = pairs
        except Exception as exc:
            return jsonify({'ok': False, 'error': f'Invalid profile: {exc}'}), 400

    result = corsair_commander.set_fan_speed(dev, channel, speed)
    return jsonify(result)


# ── Corsair Commander Pro JSON API ────────────────────────────────────────────

@app.route('/api/commander/devices')
@login_required
def api_commander_devices():
    """List all Commander Pro devices."""
    return jsonify(corsair_commander.list_devices())


@app.route('/api/commander/<int:dev_id>/status')
@login_required
def api_commander_status(dev_id):
    """Return the latest cached status for a device."""
    latest = corsair_commander.get_latest(dev_id)
    return jsonify(latest or {})


@app.route('/api/commander/<int:dev_id>/history')
@login_required
def api_commander_history(dev_id):
    """Return status history for the last N hours."""
    hours = min(int(request.args.get('hours', 24)), 168)
    limit = min(int(request.args.get('limit', 1440)), 10080)
    return jsonify(corsair_commander.get_history(dev_id, hours=hours, limit=limit))


@app.route('/api/commander/all')
@login_required
def api_commander_all():
    """Return latest status for all enabled devices."""
    return jsonify(corsair_commander.get_all_latest())


# ═══════════════════════════════════════════════════════════════════════════════
# Fan Controller — universal fan management (lm-sensors, IPMI, nbfc, liquidctl)
# ═══════════════════════════════════════════════════════════════════════════════
import fan_controller as _fc

# Initialise DB and start polling (called once at startup via app context)
with app.app_context():
    try:
        _fc.init_db(DATA_DIR)
        _fc.start_polling()
    except Exception as _fc_init_err:
        import logging as _logging
        _logging.getLogger(__name__).warning("fan_controller init failed: %s", _fc_init_err)


@app.route('/fans')
@login_required
def fc_index():
    """Fan Controller overview page."""
    devices = _fc.list_devices()
    latest_map = {d['id']: _fc.get_latest(d['id']) for d in devices}
    return render_template('fans/index.html',
                           devices=devices,
                           latest_map=latest_map,
                           controller_types=_fc.CONTROLLER_TYPES)


@app.route('/fans/add', methods=['GET', 'POST'])
@login_required
def fc_add():
    """Add a new fan controller device."""
    from flask_wtf.csrf import generate_csrf
    csrf_token_value = generate_csrf()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ctype = request.form.get('controller_type', 'lm_sensors')
        host = request.form.get('host', '').strip()
        port = int(request.form.get('port', 22) or 22)
        username = request.form.get('username', 'root').strip()
        password = request.form.get('password', '').strip()
        ssh_key = request.form.get('ssh_key', '').strip()
        notes = request.form.get('notes', '').strip()

        extra = {}
        for key in ['match_str', 'ipmi_host', 'ipmi_user', 'ipmi_pass', 'vendor', 'zone']:
            val = request.form.get(key, '').strip()
            if val:
                extra[key] = val
        if request.form.get('use_direct') == '1':
            extra['use_direct'] = True

        if not name or not host:
            flash('Name and host are required.', 'danger')
            return render_template('fans/add.html',
                                   controller_types=_fc.CONTROLLER_TYPES,
                                   csrf_token_value=csrf_token_value)

        dev_id = _fc.add_device(name, ctype, host, port, username, password, ssh_key, extra, notes)
        flash(f'Device "{name}" added successfully.', 'success')
        return redirect(url_for('fc_detail', dev_id=dev_id))

    return render_template('fans/add.html',
                           controller_types=_fc.CONTROLLER_TYPES,
                           csrf_token_value=csrf_token_value)


@app.route('/fans/<int:dev_id>')
@login_required
def fc_detail(dev_id):
    """Fan Controller detail page with live data and controls."""
    dev = _fc.get_device(dev_id)
    if not dev:
        flash('Device not found.', 'danger')
        return redirect(url_for('fc_index'))
    from flask_wtf.csrf import generate_csrf
    latest = _fc.get_latest(dev_id)
    history = _fc.get_history(dev_id, hours=24)
    csrf_token_value = generate_csrf()
    return render_template('fans/detail.html',
                           dev=dev,
                           latest=latest,
                           history=history,
                           controller_types=_fc.CONTROLLER_TYPES,
                           csrf_token_value=csrf_token_value)


@app.route('/fans/<int:dev_id>/edit', methods=['GET', 'POST'])
@login_required
def fc_edit(dev_id):
    """Edit fan controller device settings."""
    dev = _fc.get_device(dev_id)
    if not dev:
        flash('Device not found.', 'danger')
        return redirect(url_for('fc_index'))
    from flask_wtf.csrf import generate_csrf
    csrf_token_value = generate_csrf()
    if request.method == 'POST':
        fields = {}
        for f in ['name', 'controller_type', 'host', 'port', 'username',
                  'password', 'ssh_key', 'notes', 'enabled']:
            val = request.form.get(f)
            if val is not None:
                fields[f] = val
        if 'port' in fields:
            fields['port'] = int(fields['port'] or 22)
        if 'enabled' in fields:
            fields['enabled'] = 1 if fields['enabled'] == '1' else 0

        extra = {}
        for key in ['match_str', 'ipmi_host', 'ipmi_user', 'ipmi_pass', 'vendor', 'zone']:
            val = request.form.get(key, '').strip()
            if val:
                extra[key] = val
        if request.form.get('use_direct') == '1':
            extra['use_direct'] = True
        fields['extra_config'] = extra

        _fc.update_device(dev_id, **fields)
        flash('Device updated.', 'success')
        return redirect(url_for('fc_detail', dev_id=dev_id))

    return render_template('fans/edit.html',
                           dev=dev,
                           controller_types=_fc.CONTROLLER_TYPES,
                           csrf_token_value=csrf_token_value)


@app.route('/fans/<int:dev_id>/delete', methods=['POST'])
@login_required
def fc_delete(dev_id):
    """Delete a fan controller device."""
    dev = _fc.get_device(dev_id)
    if dev:
        _fc.delete_device(dev_id)
        flash(f'Device "{dev["name"]}" deleted.', 'success')
    return redirect(url_for('fc_index'))


@app.route('/fans/<int:dev_id>/refresh')
@login_required
@_csrf.exempt
def fc_refresh(dev_id):
    """Force an immediate status poll."""
    dev = _fc.get_device(dev_id)
    if not dev:
        return jsonify({'ok': False, 'error': 'Device not found'}), 404
    status = _fc.fetch_status(dev)
    _fc._store_sample(dev_id, status)
    return jsonify(status)


@app.route('/fans/<int:dev_id>/test')
@login_required
@_csrf.exempt
def fc_test(dev_id):
    """Test SSH connectivity and tool availability."""
    result = _fc.test_connection(dev_id)
    return jsonify(result)


@app.route('/fans/<int:dev_id>/set_fan', methods=['POST'])
@login_required
@_csrf.exempt
def fc_set_fan(dev_id):
    """Set fan speed on a device."""
    dev = _fc.get_device(dev_id)
    if not dev:
        return jsonify({'ok': False, 'error': 'Device not found'}), 404

    channel = request.form.get('channel', '0')
    mode = request.form.get('mode', 'fixed')

    if mode == 'fixed':
        try:
            speed = float(request.form.get('speed', 50))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Invalid speed value'}), 400
    elif mode == 'auto':
        speed = -1
    else:
        try:
            pairs_raw = request.form.get('profile', '')
            speed = []
            for pair in pairs_raw.split(';'):
                pair = pair.strip()
                if pair:
                    t, r = pair.split(',')
                    speed.append((int(t.strip()), int(r.strip())))
        except Exception as exc:
            return jsonify({'ok': False, 'error': f'Invalid profile: {exc}'}), 400

    extra = {}
    for k in ['zone']:
        v = request.form.get(k)
        if v:
            extra[k] = v

    result = _fc.set_fan_speed(dev, channel, speed, extra)
    return jsonify(result)


@app.route('/fans/<int:dev_id>/install', methods=['POST'])
@login_required
@_csrf.exempt
def fc_install(dev_id):
    """Install required packages on the remote host."""
    dev = _fc.get_device(dev_id)
    if not dev:
        return jsonify({'ok': False, 'error': 'Device not found'}), 404

    import time as _t
    progress_key = f"fc_install_{dev_id}_{int(_t.time())}"
    logs[progress_key] = []

    def _run():
        result = _fc.install_packages(dev_id, progress_key=progress_key)
        logs[progress_key].append(
            '✔ Installation complete.' if result['ok'] else f'✘ Failed: {result["message"][-300:]}'
        )

    threading.Thread(target=_run, daemon=True).start()
    return redirect(f"/progress/{progress_key}")


# ── Fan Controller JSON API ───────────────────────────────────────────────────

@app.route('/api/fans/devices')
@login_required
def api_fc_devices():
    return jsonify(_fc.list_devices())


@app.route('/api/fans/<int:dev_id>/status')
@login_required
def api_fc_status(dev_id):
    return jsonify(_fc.get_latest(dev_id) or {})


@app.route('/api/fans/<int:dev_id>/history')
@login_required
def api_fc_history(dev_id):
    hours = min(int(request.args.get('hours', 24)), 168)
    return jsonify(_fc.get_history(dev_id, hours=hours))


@app.route('/api/fans/types')
@login_required
def api_fc_types():
    return jsonify(_fc.CONTROLLER_TYPES)


# ── Fan Controller Auto-Detect ────────────────────────────────────────────────

@app.route('/fans/detect')
@login_required
@_csrf.exempt
def fc_detect():
    """
    Auto-detect available fan controllers on a remote host via SSH.
    Query params: host, port, username, password, ssh_key
    Returns JSON with ranked suggestions.
    """
    host = request.args.get('host', '').strip()
    if not host:
        return jsonify({'ok': False, 'error': 'host parameter required'}), 400

    port = int(request.args.get('port', 22) or 22)
    username = request.args.get('username', 'root').strip()
    password = request.args.get('password', '').strip()
    ssh_key = request.args.get('ssh_key', '').strip()

    result = _fc.detect_controllers(
        host=host,
        port=port,
        username=username,
        password=password,
        ssh_key=ssh_key,
    )
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP CONTROLLER ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/backup")
@login_required
def backup_index():
    servers = _bc.list_servers()
    # Attach job summary to each server
    for srv in servers:
        jobs = _bc.get_jobs(srv["id"])
        srv["jobs_ok"] = sum(1 for j in jobs if j["status"] == "ok")
        srv["jobs_warn"] = sum(1 for j in jobs if j["status"] == "warning")
        srv["jobs_error"] = sum(1 for j in jobs if j["status"] == "error")
        srv["jobs_total"] = len(jobs)
    return render_template("backup/index.html",
                           servers=servers,
                           server_types=_bc.SERVER_TYPES)


@app.route("/backup/add", methods=["GET", "POST"])
@login_required
def backup_add():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        server_type = request.form.get("server_type", "pbs")
        host = request.form.get("host", "").strip()
        port = int(request.form.get("port") or _bc.SERVER_TYPES.get(server_type, {}).get("default_port", 80))
        protocol = request.form.get("protocol", "https")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        api_token = request.form.get("api_token", "").strip()
        ssh_key = request.form.get("ssh_key", "").strip()
        verify_ssl = bool(request.form.get("verify_ssl"))
        notes = request.form.get("notes", "").strip()
        if not name or not host:
            flash("Name and host are required.", "danger")
            return render_template("backup/add.html",
                                   server_types=_bc.SERVER_TYPES,
                                   csrf_token_value=_gen_csrf() if '_gen_csrf' in dir() else "")
        try:
            new_id = _bc.add_server(name, server_type, host, port, protocol,
                                    username, password, api_token, ssh_key,
                                    verify_ssl, notes)
            _bc.start_polling(new_id)
            flash(f"Backup server '{name}' added.", "success")
            return redirect(url_for("backup_detail", server_id=new_id))
        except Exception as e:
            flash(str(e), "danger")
    try:
        from flask_wtf.csrf import generate_csrf as _gcsrf
        csrf_val = _gcsrf()
    except Exception:
        csrf_val = ""
    return render_template("backup/add.html",
                           server_types=_bc.SERVER_TYPES,
                           csrf_token_value=csrf_val)


@app.route("/backup/<int:server_id>")
@login_required
def backup_detail(server_id):
    srv = _bc.get_server(server_id)
    if not srv:
        flash("Backup server not found.", "danger")
        return redirect(url_for("backup_index"))
    jobs = _bc.get_jobs(server_id)
    snapshots = _bc.get_snapshots(server_id, limit=30)
    history = _bc.get_history(server_id, hours=24)
    stype_info = _bc.SERVER_TYPES.get(srv["server_type"], {})
    return render_template("backup/detail.html",
                           srv=srv,
                           jobs=jobs,
                           snapshots=snapshots,
                           history=history,
                           stype_info=stype_info,
                           server_types=_bc.SERVER_TYPES,
                           format_bytes=_bc.format_bytes)


@app.route("/backup/<int:server_id>/edit", methods=["GET", "POST"])
@login_required
def backup_edit(server_id):
    srv = _bc.get_server(server_id)
    if not srv:
        flash("Backup server not found.", "danger")
        return redirect(url_for("backup_index"))
    if request.method == "POST":
        updates = {
            "name": request.form.get("name", "").strip(),
            "server_type": request.form.get("server_type", srv["server_type"]),
            "host": request.form.get("host", "").strip(),
            "port": int(request.form.get("port") or srv["port"]),
            "protocol": request.form.get("protocol", srv["protocol"]),
            "username": request.form.get("username", "").strip(),
            "notes": request.form.get("notes", "").strip(),
            "verify_ssl": int(bool(request.form.get("verify_ssl"))),
        }
        pw = request.form.get("password", "").strip()
        if pw:
            updates["password"] = pw
        tok = request.form.get("api_token", "").strip()
        if tok:
            updates["api_token"] = tok
        key = request.form.get("ssh_key", "").strip()
        if key:
            updates["ssh_key"] = key
        _bc.update_server(server_id, **updates)
        flash("Backup server updated.", "success")
        return redirect(url_for("backup_detail", server_id=server_id))
    try:
        from flask_wtf.csrf import generate_csrf as _gcsrf
        csrf_val = _gcsrf()
    except Exception:
        csrf_val = ""
    return render_template("backup/edit.html",
                           srv=srv,
                           server_types=_bc.SERVER_TYPES,
                           csrf_token_value=csrf_val)


@app.route("/backup/<int:server_id>/delete", methods=["POST"])
@login_required
def backup_delete(server_id):
    _bc.stop_polling(server_id)
    _bc.delete_server(server_id)
    flash("Backup server deleted.", "success")
    return redirect(url_for("backup_index"))


@app.route("/backup/<int:server_id>/refresh")
@login_required
@_csrf.exempt
def backup_refresh(server_id):
    result = _bc.poll_server(server_id)
    return jsonify(result)


@app.route("/backup/<int:server_id>/test")
@login_required
@_csrf.exempt
def backup_test(server_id):
    result = _bc.test_connection(server_id)
    return jsonify(result)


@app.route("/backup/<int:server_id>/trigger", methods=["POST"])
@login_required
@_csrf.exempt
def backup_trigger(server_id):
    job_id = request.json.get("job_id", "") if request.is_json else request.form.get("job_id", "")
    result = _bc.trigger_backup(server_id, job_id)
    return jsonify(result)


@app.route("/api/backup/servers")
@login_required
def api_backup_servers():
    return jsonify(_bc.list_servers())


@app.route("/api/backup/<int:server_id>/jobs")
@login_required
def api_backup_jobs(server_id):
    return jsonify(_bc.get_jobs(server_id))


@app.route("/api/backup/<int:server_id>/snapshots")
@login_required
def api_backup_snapshots(server_id):
    return jsonify(_bc.get_snapshots(server_id))


@app.route("/api/backup/<int:server_id>/history")
@login_required
def api_backup_history(server_id):
    hours = int(request.args.get("hours", 24))
    return jsonify(_bc.get_history(server_id, hours=hours))
