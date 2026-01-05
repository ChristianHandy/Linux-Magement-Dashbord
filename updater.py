import paramiko, json, time

def ssh_connect(host, user, timeout=5):
    ssh = paramiko.SSHClient()
    # Security Note: AutoAddPolicy accepts any host key, making this vulnerable to MITM attacks.
    # For production, use WarningPolicy or maintain a known_hosts file.
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, timeout=timeout)
    return ssh

def detect_distro(ssh):
    _, stdout, _ = ssh.exec_command("cat /etc/os-release")
    return stdout.read().decode()

def update_command(distro):
    if "Ubuntu" in distro or "Debian" in distro:
        return "sudo apt update && sudo apt upgrade -y"
    if "Fedora" in distro:
        return "sudo dnf upgrade -y"
    if "Arch" in distro:
        return "sudo pacman -Syu --noconfirm"
    return None

def run_update(host, user, name, log):
    try:
        ssh = ssh_connect(host, user)
        distro = detect_distro(ssh)
        cmd = update_command(distro)

        if not cmd:
            log.append("Unsupported distro")
            return

        _, stdout, _ = ssh.exec_command(cmd, get_pty=True)
        for line in iter(stdout.readline, ""):
            log.append(line)

        ssh.close()

        history = json.load(open("history.json"))
        history.append({
            "host": name,
            "time": time.ctime(),
            "status": "Success"
        })
        json.dump(history, open("history.json", "w"), indent=2)

    except Exception as e:
        log.append(str(e))

