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

def update_command(distro, repo_only=False):
    """
    Generate update command for a given distro.
    If repo_only=True, skip host configuration updates.
    """
    if "Ubuntu" in distro or "Debian" in distro:
        if repo_only:
            # Update repos only, exclude config files
            return "sudo apt update && sudo apt upgrade -y -o Dpkg::Options::='--force-confold'"
        return "sudo apt update && sudo apt upgrade -y"
    if "Fedora" in distro:
        if repo_only:
            # Update packages but keep config files
            return "sudo dnf upgrade -y --setopt=tsflags=noscripts"
        return "sudo dnf upgrade -y"
    if "Arch" in distro:
        if repo_only:
            # Update without replacing config files
            return "sudo pacman -Syu --noconfirm --needed"
        return "sudo pacman -Syu --noconfirm"
    return None

def run_update(host, user, name, log, repo_only=False):
    """
    Run system update on a remote host.
    If repo_only=True, skip host configuration file updates.
    """
    try:
        ssh = ssh_connect(host, user)
        distro = detect_distro(ssh)
        cmd = update_command(distro, repo_only=repo_only)

        if not cmd:
            log.append("Unsupported distro")
            return

        _, stdout, _ = ssh.exec_command(cmd, get_pty=True)
        for line in iter(stdout.readline, ""):
            log.append(line)

        ssh.close()

        history = json.load(open("history.json"))
        update_type = "Repository-only update" if repo_only else "Full update"
        history.append({
            "host": name,
            "time": time.ctime(),
            "status": "Success",
            "type": update_type
        })
        json.dump(history, open("history.json", "w"), indent=2)

    except Exception as e:
        log.append(str(e))

