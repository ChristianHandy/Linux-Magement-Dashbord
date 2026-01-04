from flask import Flask, render_template, redirect, session, request
import json, threading, paramiko
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
