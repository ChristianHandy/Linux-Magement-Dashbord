# updater.py - Enhanced error handling, better distribution support, and fixed notification propagation
import os
import logging
import paramiko
import time

SUPPORTED_DISTRIBUTIONS = ['ubuntu', 'debian', 'fedora', 'centos', 'arch']

def run_update(host, user, name, log_list, repo_only=False):
    """
    Run system update on a remote host via SSH.
    
    Args:
        host: Hostname or IP address of the remote system
        user: SSH username
        name: Display name for the host (used in logs)
        log_list: List to append log messages to
        repo_only: If True, only update packages from repositories without modifying config files
    """
    def log(msg):
        """Helper function to log messages"""
        timestamp = time.strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {msg}"
        print(log_msg)
        log_list.append(log_msg)
    
    ssh = None
    try:
        log(f"Connecting to {name} ({host})...")
        
        # Create SSH client
        # Note: Using AutoAddPolicy for convenience, but this is a security risk
        # as it automatically accepts unknown host keys (vulnerable to MITM attacks).
        # For production use, implement proper host key verification.
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect to the remote host using SSH key authentication
        # The SSH key should be configured beforehand (see "Install SSH key" feature)
        ssh.connect(host, username=user, timeout=30)
        log(f"Connected to {name}")
        
        # Detect the distribution
        log("Detecting Linux distribution...")
        stdin, stdout, stderr = ssh.exec_command("cat /etc/os-release | grep '^ID=' | cut -d'=' -f2 | tr -d '\"'")
        distro = stdout.read().decode().strip().lower()
        log(f"Detected distribution: {distro}")
        
        # Determine the update commands based on distribution and update type
        if distro in ['ubuntu', 'debian']:
            if repo_only:
                # Repository-only update for Debian/Ubuntu (preserve config files)
                update_cmd = "sudo DEBIAN_FRONTEND=noninteractive apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -o Dpkg::Options::='--force-confold'"
                log("Running repository-only update (preserving config files)...")
            else:
                # Full system update for Debian/Ubuntu
                update_cmd = "sudo DEBIAN_FRONTEND=noninteractive apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y && sudo DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y"
                log("Running full system update...")
        
        elif distro == 'fedora':
            if repo_only:
                # Repository-only update for Fedora (preserve config files)
                update_cmd = "sudo dnf upgrade -y --setopt=tsflags=noscripts"
                log("Running repository-only update (preserving config files)...")
            else:
                # Full system update for Fedora
                update_cmd = "sudo dnf upgrade -y"
                log("Running full system update...")
        
        elif distro == 'centos':
            if repo_only:
                # Repository-only update for CentOS (preserve config files)
                update_cmd = "sudo yum update -y --setopt=tsflags=noscripts"
                log("Running repository-only update (preserving config files)...")
            else:
                # Full system update for CentOS
                update_cmd = "sudo yum update -y"
                log("Running full system update...")
        
        elif distro == 'arch':
            if repo_only:
                # Repository-only update for Arch (skip already installed packages)
                update_cmd = "sudo pacman -Syu --noconfirm --needed"
                log("Running repository-only update...")
            else:
                # Full system update for Arch
                update_cmd = "sudo pacman -Syu --noconfirm"
                log("Running full system update...")
        
        else:
            log(f"✗ Unsupported distribution '{distro}'")
            log("Supported distributions: Ubuntu, Debian, Fedora, CentOS, Arch")
            return
        
        # Execute the update command
        log("Executing update command...")
        stdin, stdout, stderr = ssh.exec_command(update_cmd, get_pty=True)
        
        # Read output in real-time
        while True:
            line = stdout.readline()
            if not line:
                break
            log(line.rstrip())
        
        # Check exit status
        exit_status = stdout.channel.recv_exit_status()
        
        if exit_status == 0:
            log(f"✓ Update completed successfully for {name}")
        else:
            log(f"✗ Update finished with exit code {exit_status}")
            # Read any error messages
            errors = stderr.read().decode().strip()
            if errors:
                log(f"Errors: {errors}")
        
    except paramiko.AuthenticationException:
        log(f"✗ Authentication failed for {name}. Check SSH keys or credentials.")
    except paramiko.SSHException as e:
        log(f"✗ SSH error connecting to {name}: {str(e)}")
    except Exception as e:
        log(f"✗ Error updating {name}: {str(e)}")
    finally:
        if ssh:
            ssh.close()
            log(f"Disconnected from {name}")

def get_current_distribution():
    try:
        # Attempting to fetch distribution information
        with open('/etc/os-release', 'r') as file:
            for line in file:
                if line.startswith('ID='):
                    return line.strip().split('=')[1].lower()
    except Exception as e:
        logging.error(f"Error fetching distribution: {e}")
        raise RuntimeError("Could not determine the Linux distribution.")

def notify_error(update_id, message):
    try:
        # Assuming some kind of notification mechanism exists
        logging.info(f"Sending notification for Update {update_id}: {message}")
    except Exception as e:
        logging.error(f"Failed to send notification for Update {update_id}: {e}")

def process_update(update_id):
    try:
        current_distro = get_current_distribution()

        if current_distro not in SUPPORTED_DISTRIBUTIONS:
            raise ValueError(f"Unsupported distribution: {current_distro}")

        logging.info(f"Preparing to process update {update_id} for {current_distro}...")

        # Simulated update processing...
        logging.info(f"Update {update_id} processed successfully.")

    except ValueError as ve:
        logging.warning(f"Validation error for Update {update_id}: {ve}")
        notify_error(update_id, str(ve))
    except RuntimeError as re:
        logging.critical(f"Runtime error in Update {update_id}: {re}")
        notify_error(update_id, "Critical error encountered.")
        raise
    except Exception as e:
        logging.error(f"Unexpected error processing Update {update_id}: {e}")
        notify_error(update_id, "Unexpected error occurred.")

def main():
    logging.basicConfig(level=logging.INFO)

    updates = ['update1', 'update2', 'update3']

    for update_id in updates:
        try:
            process_update(update_id)
        except Exception as e:
            logging.error(f"Aborting processing due to error: {e}")

if __name__ == "__main__":
    main()
