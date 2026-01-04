from flask import Flask, render_template, redirect, session, request
import json, threading, paramiko, os
from updater import run_update
import scheduler

app = Flask(__name__, template_folder="templates")
app.secret_key = "change_me"

USERNAME = "admin"
PASSWORD = "password"

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

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["user"] == USERNAME and request.form["pass"] == PASSWORD:
            session["login"] = True
            return redirect("/dashboard")
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if not session.get("login"):
        return redirect("/")
    hosts = load_hosts()
    history = json.load(open("history.json"))
    status = {n: is_online(h["host"], h["user"]) for n, h in hosts.items()}
    return render_template("dashboard.html", hosts=hosts, status=status, history=history)

@app.route("/update/<name>")
def update(name):
    hosts = load_hosts()
    logs[name] = []
    threading.Thread(
        target=run_update,
        args=(hosts[name]["host"], hosts[name]["user"], name, logs[name])
    ).start()
    return redirect(f"/progress/{name}")

@app.route("/progress/<name>")
def progress(name):
    return render_template("progress.html", log=logs.get(name, []))

# New: Manage hosts (list + add)
@app.route("/hosts", methods=["GET", "POST"])
def manage_hosts():
    if not session.get("login"):
        return redirect("/")
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

# New: Edit host
@app.route("/hosts/edit/<orig_name>", methods=["GET", "POST"])
def edit_host(orig_name):
    if not session.get("login"):
        return redirect("/")
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

# New: Delete host
@app.route("/hosts/delete/<name>", methods=["POST"])
def delete_host(name):
    if not session.get("login"):
        return redirect("/")
    hosts = load_hosts()
    if name in hosts:
        hosts.pop(name)
        save_hosts(hosts)
    return redirect("/hosts")

# NEW: Install SSH public key on remote host using password auth
@app.route("/hosts/install_key/<name>", methods=["GET", "POST"])
def install_key(name):
    if not session.get("login"):
        return redirect("/")
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
