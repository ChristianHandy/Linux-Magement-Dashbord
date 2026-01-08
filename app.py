from flask import Flask, render_template, redirect, session, request, flash, jsonify, send_file, url_for
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

# Load environment variables from .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional

app = Flask(__name__, template_folder="templates", static_folder="static")

# Security: Use environment variables for credentials, generate secure secret key
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

USERNAME = os.environ.get('DASHBOARD_USERNAME', 'admin')
PASSWORD = os.environ.get('DASHBOARD_PASSWORD', 'password')

# Warn if using default credentials
if USERNAME == 'admin' and PASSWORD == 'password':
    print("WARNING: Using default credentials! Set DASHBOARD_USERNAME and DASHBOARD_PASSWORD environment variables.")

# Initialize Disk Tools addon system
addon_mgr = AddonManager(app, disktool_core)
app.addon_mgr = addon_mgr
addon_mgr.load_addons()

# Template function for HTML extensions
@app.context_processor
def inject_hooks():
    return dict(hook=lambda name, *args, **kwargs: addon_mgr.render_hooks(name, *args, **kwargs))

# Template function for user context
@app.context_processor
def inject_user_context():
    """Make user information available in all templates."""
    user_id = session.get("user_id")
    user_roles = []
    is_admin = False
    
    if user_id:
        user_roles = user_management.get_user_role_names(user_id)
        is_admin = 'admin' in user_roles
    
    return dict(
        current_user_id=user_id,
        current_user_roles=user_roles,
        is_admin=is_admin,
        localhost_identifiers=LOCALHOST_IDENTIFIERS
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

def load_hosts():
    try:
        with open("hosts.json", "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_hosts(hosts):
    with open("hosts.json", "w") as f:
        json.dump(hosts, f, indent=2)

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
        username = request.form.get("user")
        password = request.form.get("pass")
        
        # Try database authentication first
        user_id = user_management.verify_password(username, password)
        if user_id:
            session["user_id"] = user_id
            session["username"] = username
            # Keep old session key for backward compatibility
            session["login"] = True
            flash('Logged in successfully')
            return redirect(next_url)
        
        # Fallback to environment variable authentication for backward compatibility
        if username == USERNAME and password == PASSWORD:
            session["login"] = True
            session["username"] = username
            flash('Logged in successfully (legacy mode)')
            return redirect(next_url)
        
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
    return render_template("index.html")

@app.route("/dashboard")
@login_required
def dashboard():
    """Linux Update Dashboard"""
    from updater import detect_os_remote
    
    hosts = load_hosts()
    history = json.load(open("history.json"))
    status = {n: is_online(h["host"], h["user"]) for n, h in hosts.items()}
    
    # Detect OS for each online host (with caching)
    os_info = {}
    for name, h in hosts.items():
        if status[name]:  # Only detect for online hosts
            # Check if OS info is cached in host data
            if "os_name" in h and "os_version" in h:
                os_info[name] = {
                    "os_name": h["os_name"],
                    "os_version": h["os_version"]
                }
            else:
                # Detect OS and cache it
                os_name, os_version = detect_os_remote(h["host"], h["user"])
                if os_name:
                    os_info[name] = {
                        "os_name": os_name,
                        "os_version": os_version or "unknown"
                    }
                    # Cache the detection result
                    h["os_name"] = os_name
                    h["os_version"] = os_version or "unknown"
                    save_hosts(hosts)
        elif "os_name" in h:
            # Use cached OS info for offline hosts
            os_info[name] = {
                "os_name": h["os_name"],
                "os_version": h.get("os_version", "unknown")
            }
    
    # Load update settings for display
    settings = scheduler.load_update_settings()
    
    return render_template(
        "update_dashboard.html", 
        hosts=hosts, 
        status=status, 
        history=history,
        os_info=os_info,
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
        name = request.form.get("name", "").strip()
        host = request.form.get("host", "").strip()
        user = request.form.get("user", "").strip()
        if name:
            hosts[name] = {"host": host, "user": user}
            save_hosts(hosts)
        return redirect("/hosts")
    return render_template("hosts.html", hosts=hosts)

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
        
        new_name = request.form.get("name", "").strip()
        host = request.form.get("host", "").strip()
        user = request.form.get("user", "").strip()
        if new_name:
            # If the name changed, remove the old key
            if new_name != orig_name:
                hosts.pop(orig_name, None)
            hosts[new_name] = {"host": host, "user": user}
            save_hosts(hosts)
        return redirect("/hosts")
    # GET
    return render_template("edit_host.html", name=orig_name, data=hosts[orig_name])

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
    return redirect("/hosts")

# Install SSH public key on remote host using password auth
@app.route("/hosts/install_key/<name>", methods=["GET", "POST"])
@login_required
def install_key(name):
    # Require operator or admin role to install keys
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to install SSH keys.')
        return redirect(url_for('manage_hosts'))
    
    hosts = load_hosts()
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

# Detect/refresh OS on a host
@app.route("/hosts/detect_os/<name>")
@login_required
def detect_host_os(name):
    """Detect or refresh OS information for a host"""
    from updater import detect_os_remote
    
    # Require operator or admin role to detect OS
    if session.get("user_id") and not current_user_has_role('operator', 'admin'):
        flash('You need operator or admin role to detect OS.')
        return redirect(url_for('manage_hosts'))
    
    hosts = load_hosts()
    if name not in hosts:
        flash('Host not found.')
        return redirect(url_for('manage_hosts'))
    
    host_info = hosts[name]
    
    # Detect OS
    os_name, os_version = detect_os_remote(host_info["host"], host_info["user"])
    
    if os_name:
        # Update host with OS information
        host_info["os_name"] = os_name
        host_info["os_version"] = os_version or "unknown"
        save_hosts(hosts)
        flash(f'Detected OS: {os_name} {os_version or ""}')
    else:
        flash('Could not detect OS. Make sure the host is online and accessible.')
    
    return redirect(url_for('manage_hosts'))

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
        flash('User not found.')
        return redirect(url_for('users_list'))
    
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
    # Only set HSTS header for HTTPS connections
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

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
