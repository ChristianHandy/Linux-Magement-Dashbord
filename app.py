from flask import Flask, render_template, redirect, session, request, flash, jsonify, send_file, url_for
import json, threading, paramiko, os
from updater import run_update
import scheduler
import disktool_core
from addon_loader import AddonManager
from functools import wraps

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "change_me"

USERNAME = "admin"
PASSWORD = "password"

# Initialize Disk Tools addon system
addon_mgr = AddonManager(app, disktool_core)
app.addon_mgr = addon_mgr
addon_mgr.load_addons()

# Template function for HTML extensions
@app.context_processor
def inject_hooks():
    return dict(hook=lambda name, *args, **kwargs: addon_mgr.render_hooks(name, *args, **kwargs))

logs = {}

def is_online(host, user):
    try:
        ssh = paramiko.SSHClient()
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
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("login"):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapped

@app.route("/", methods=["GET", "POST"])
def login():
    next_url = request.args.get('next') or url_for('index')
    if request.method == "POST":
        if request.form.get("user") == USERNAME and request.form.get("pass") == PASSWORD:
            session["login"] = True
            flash('Logged in successfully')
            return redirect(next_url)
    return render_template("login.html", next=next_url)

@app.route("/logout")
def logout():
    session.pop("login", None)
    flash('Logged out')
    return redirect(url_for('login'))

@app.route("/index")
def index():
    """Main menu/landing page showing both tools"""
    if not session.get("login"):
        return redirect("/")
    return render_template("index.html")

@app.route("/dashboard")
@login_required
def dashboard():
    """Linux Update Dashboard"""
    hosts = load_hosts()
    history = json.load(open("history.json"))
    status = {n: is_online(h["host"], h["user"]) for n, h in hosts.items()}
    return render_template("update_dashboard.html", hosts=hosts, status=status, history=history)

@app.route("/update/<name>")
@login_required
def update(name):
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

# Host management routes
@app.route("/hosts", methods=["GET", "POST"])
@login_required
def manage_hosts():
    hosts = load_hosts()
    if request.method == "POST":
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
    hosts = load_hosts()
    if name in hosts:
        hosts.pop(name)
        save_hosts(hosts)
    return redirect("/hosts")

# Install SSH public key on remote host using password auth
@app.route("/hosts/install_key/<name>", methods=["GET", "POST"])
@login_required
def install_key(name):
    hosts = load_hosts()
    if name not in hosts:
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
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(target["host"], username=target["user"], password=password, timeout=10)
            safe_key = pubkey.replace('\"', '\\\"')
            cmd = (
                'mkdir -p ~/.ssh && chmod 700 ~/.ssh && '
                f'echo "{safe_key}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
            )
            stdin, stdout, stderr = ssh.exec_command(cmd)
            err = stderr.read().decode().strip()
            ssh.close()
            if err:
                error = f"Remote error: {err}"
            else:
                success = True
        except Exception as e:
            error = f"Connection error: {e}"
    return render_template("install_key.html", name=name, error=error, success=success)

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
    disktool_core.auto_enabled = not disktool_core.auto_enabled
    flash(f"Automatic mode {'ON' if disktool_core.auto_enabled else 'OFF'}")
    return redirect(url_for('disks_index'))

@app.route("/disks/format/<device>", methods=['GET','POST'])
@login_required
def format_route(device):
    if request.method == 'POST':
        fs = request.form.get('fs','ext4')
        op_id = disktool_core.start_format(device, fs)
        flash(f'Format task {op_id} started for {device}')
        return redirect(url_for('task_status', op_id=op_id))
    return render_template('disks/format.html', device=device)

@app.route("/disks/smart/start/<device>/<mode>")
@login_required
def smart_start_route(device, mode):
    if mode not in {'short','long'}:
        flash('Invalid SMART type')
        return redirect(url_for('disks_index'))
    disktool_core.start_smart(device, mode)
    flash(f'SMART {mode} started for {device}')
    return redirect(url_for('disks_index'))

@app.route("/disks/smart/view/<device>")
@login_required
def smart_view_route(device):
    report = disktool_core.view_smart(device)
    return render_template('disks/smart_view.html', device=device, report=report)

@app.route("/disks/validate/<device>")
@login_required
def validate_route(device):
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
    
    # Check if the plugin template exists
    from pathlib import Path
    template_path = Path(app.template_folder) / 'addons' / f'{plugin}.html'
    if not template_path.exists():
        flash(f'Plugin {plugin} not found')
        return redirect(url_for('disks_index'))
    
    return render_template(f'addons/{plugin}.html', device=device)

@app.route("/disks/remotes", methods=['GET', 'POST'])
@login_required
def remotes():
    if request.method == 'POST':
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
    disktool_core.remove_remote(rid)
    flash('Remote removed')
    return redirect(url_for('remotes'))

if __name__ == "__main__":
    # Initialize Disk Tools database
    disktool_core.init_db()
    # Start Disk Tools auto-mode worker
    threading.Thread(target=disktool_core.auto_mode_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
