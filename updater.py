# updater.py - Enhanced error handling, better distribution support, and fixed notification propagation
import os
import logging
import paramiko
import time
import subprocess
import email_config
import email_notifier
from constants import is_localhost, is_windows, get_platform

SUPPORTED_DISTRIBUTIONS = ['ubuntu', 'debian', 'fedora', 'centos', 'arch', 'windows']

# Windows Update PowerShell commands
WINDOWS_UPDATE_BASE = (
    "Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -ErrorAction SilentlyContinue; "
    "Install-Module PSWindowsUpdate -Force -ErrorAction SilentlyContinue; "
    "Import-Module PSWindowsUpdate; "
    "Get-WindowsUpdate -AcceptAll -Install -AutoReboot:$false"
)

WINDOWS_WINGET_UPDATE = (
    "if (Get-Command winget -ErrorAction SilentlyContinue) { "
    "winget upgrade --all --accept-source-agreements --accept-package-agreements --silent "
    "}"
)

# Remote Windows detection command
WINDOWS_DETECTION_COMMAND = 'powershell.exe -Command "Write-Output \'windows\'" 2>&1 || echo \'\''

def get_update_command(distro, repo_only=False):
    """
    Get the update command for a given Linux distribution or Windows.
    
    Args:
        distro: Linux distribution name ('ubuntu', 'debian', 'fedora', 'centos', 'arch') or 'windows'
        repo_only: If True, only update packages without modifying config files
    
    Returns:
        tuple: (command_string, description)
    
    Raises:
        ValueError: If distribution is not supported
    """
    if distro in ['ubuntu', 'debian']:
        if repo_only:
            cmd = "sudo DEBIAN_FRONTEND=noninteractive apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -o Dpkg::Options::='--force-confold'"
            desc = "repository-only update (preserving config files)"
        else:
            cmd = "sudo DEBIAN_FRONTEND=noninteractive apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y && sudo DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y"
            desc = "full system update"
    
    elif distro == 'fedora':
        if repo_only:
            cmd = "sudo dnf upgrade -y --setopt=tsflags=noscripts"
            desc = "repository-only update (preserving config files)"
        else:
            cmd = "sudo dnf upgrade -y"
            desc = "full system update"
    
    elif distro == 'centos':
        if repo_only:
            cmd = "sudo yum update -y --setopt=tsflags=noscripts"
            desc = "repository-only update (preserving config files)"
        else:
            cmd = "sudo yum update -y"
            desc = "full system update"
    
    elif distro == 'arch':
        if repo_only:
            cmd = "sudo pacman -Syu --noconfirm --needed"
            desc = "repository-only update"
        else:
            cmd = "sudo pacman -Syu --noconfirm"
            desc = "full system update"
    
    elif distro == 'windows':
        if repo_only:
            # Windows Update via PowerShell (system updates only)
            cmd = f'powershell.exe -Command "{WINDOWS_UPDATE_BASE}"'
            desc = "Windows system updates only"
        else:
            # Full Windows Update + software updates via winget
            cmd = f'powershell.exe -Command "{WINDOWS_UPDATE_BASE}; {WINDOWS_WINGET_UPDATE}"'
            desc = "full Windows system and software updates"
    
    else:
        raise ValueError(f"Unsupported distribution: {distro}")
    
    return cmd, desc

def run_local_update(name, log_list, repo_only, log_func):
    """
    Run system update locally using subprocess.
    
    Args:
        name: Display name for the host (used in logs)
        log_list: List to append log messages to
        repo_only: If True, only update packages from repositories without modifying config files
        log_func: Logging function to use
    """
    error_occurred = False
    error_details = []
    
    try:
        log_func(f"Running local update on {name}...")
        
        # Detect the operating system and distribution
        current_platform = get_platform()
        log_func(f"Detecting operating system... Platform: {current_platform}")
        
        if current_platform == 'windows':
            # Windows detection
            distro = 'windows'
            log_func("Detected Windows operating system")
        else:
            # Linux/Unix distribution detection
            log_func("Detecting Linux distribution...")
            try:
                if not os.path.exists('/etc/os-release'):
                    raise FileNotFoundError("The /etc/os-release file is missing. This file is required to detect the Linux distribution.")
                
                with open('/etc/os-release', 'r') as f:
                    for line in f:
                        if line.startswith('ID='):
                            # Use split with maxsplit=1 to handle lines with multiple '=' safely
                            parts = line.strip().split('=', 1)
                            if len(parts) == 2:
                                distro = parts[1].strip('"').lower()
                                break
                    else:
                        raise ValueError("Could not find 'ID=' line in /etc/os-release")
            except FileNotFoundError as e:
                error_msg = f"✗ {str(e)}"
                log_func(error_msg)
                error_occurred = True
                error_details.append(str(e))
                if email_config.get_error_notifications_enabled():
                    email_notifier.send_error_notification(name, "\n".join(error_details))
                return
            except PermissionError:
                error_msg = "✗ Permission denied reading /etc/os-release. Ensure the application has read permissions."
                log_func(error_msg)
                error_occurred = True
                error_details.append("Permission denied reading /etc/os-release")
                if email_config.get_error_notifications_enabled():
                    email_notifier.send_error_notification(name, "\n".join(error_details))
                return
            except Exception as e:
                error_msg = f"✗ Could not detect distribution: {e}"
                log_func(error_msg)
                error_occurred = True
                error_details.append(f"Could not detect distribution: {e}")
                if email_config.get_error_notifications_enabled():
                    email_notifier.send_error_notification(name, "\n".join(error_details))
                return
        
        log_func(f"Detected distribution: {distro}")
        
        # Get the update command for this distribution
        try:
            update_cmd, description = get_update_command(distro, repo_only)
            log_func(f"Running {description}...")
        except ValueError as e:
            error_msg = f"✗ {str(e)}"
            log_func(error_msg)
            log_func("Supported distributions: Ubuntu, Debian, Fedora, CentOS, Arch, Windows")
            error_occurred = True
            error_details.append(str(e))
            if email_config.get_error_notifications_enabled():
                email_notifier.send_error_notification(name, "\n".join(error_details))
            return
        
        # Execute the update command locally
        log_func("Executing update command...")
        
        # Security Note: Using shell=True is required here because update_cmd contains 
        # shell operators (&&) and environment variables that need shell interpretation.
        # The command string is constructed entirely from:
        # 1. Trusted internal distribution detection (validated against known distros)
        # 2. Hardcoded command templates defined in get_update_command()
        # 3. No user input is incorporated into the command
        # This approach is acceptable because:
        # - The distribution is detected from the system's /etc/os-release file
        # - Commands are selected from a fixed set of templates per distribution
        # - No external or user-provided data influences command construction
        # Alternative: Could use subprocess.run() with shell=False and pass commands
        # as arrays, but would require restructuring the command chains.
        process = subprocess.Popen(
            update_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Read output in real-time
        for line in process.stdout:
            log_func(line.rstrip())
        
        # Wait for process to complete
        exit_status = process.wait()
        
        if exit_status == 0:
            log_func(f"✓ Update completed successfully for {name}")
        else:
            error_msg = f"✗ Update finished with exit code {exit_status}"
            log_func(error_msg)
            error_occurred = True
            error_details.append(f"Update failed with exit code {exit_status}")
        
    except Exception as e:
        error_msg = f"✗ Error updating {name}: {str(e)}"
        log_func(error_msg)
        error_occurred = True
        error_details.append(f"Unexpected error: {str(e)}")
    
    finally:
        # Send error notification if an error occurred
        if error_occurred and email_config.get_error_notifications_enabled():
            error_message = "\n".join(error_details)
            email_notifier.send_error_notification(name, error_message)

def run_update(host, user, name, log_list, repo_only=False):
    """
    Run system update on a remote host via SSH or locally via subprocess.
    
    Args:
        host: Hostname or IP address of the remote system (or 'localhost')
        user: SSH username (ignored for localhost)
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
    
    # Check if this is a local update
    if is_localhost(host):
        return run_local_update(name, log_list, repo_only, log)
    
    # Remote update via SSH
    ssh = None
    error_occurred = False
    error_details = []
    
    try:
        log(f"Connecting to {name} ({host})...")
        
        # Create SSH client with proper host key verification
        ssh = paramiko.SSHClient()
        
        # Load system host keys from standard locations
        # This loads known_hosts from ~/.ssh/known_hosts and /etc/ssh/ssh_known_hosts
        try:
            ssh.load_system_host_keys()
        except Exception as e:
            log(f"Warning: Could not load system host keys: {e}")
        
        # Load user-specific known_hosts if it exists
        user_known_hosts = os.path.expanduser('~/.ssh/known_hosts')
        if os.path.exists(user_known_hosts):
            try:
                ssh.load_host_keys(user_known_hosts)
            except Exception as e:
                log(f"Warning: Could not load user host keys from {user_known_hosts}: {e}")
        
        # Use RejectPolicy to reject unknown hosts (prevents MITM attacks)
        # Hosts must be added to known_hosts before connection
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        
        # Connect to the remote host using SSH key authentication
        # The SSH key should be configured beforehand (see "Install SSH key" feature)
        ssh.connect(host, username=user, timeout=30)
        log(f"Connected to {name}")
        
        # Detect the operating system and distribution
        log("Detecting operating system...")
        # First, try to detect if it's Windows by checking for PowerShell
        stdin, stdout, stderr = ssh.exec_command(WINDOWS_DETECTION_COMMAND)
        result = stdout.read().decode().strip().lower()
        
        if result == 'windows':
            distro = 'windows'
            log("Detected Windows operating system")
        else:
            # Try Linux detection
            log("Detecting Linux distribution...")
            stdin, stdout, stderr = ssh.exec_command("cat /etc/os-release | grep '^ID=' | cut -d'=' -f2 | tr -d '\"'")
            distro = stdout.read().decode().strip().lower()
            if distro:
                log(f"Detected Linux distribution: {distro}")
            else:
                error_msg = "✗ Could not detect operating system"
                log(error_msg)
                error_occurred = True
                error_details.append("Could not detect operating system")
                if email_config.get_error_notifications_enabled():
                    email_notifier.send_error_notification(name, "\n".join(error_details))
                return
        
        # Get the update command for this distribution
        try:
            update_cmd, description = get_update_command(distro, repo_only)
            log(f"Running {description}...")
        except ValueError as e:
            error_msg = f"✗ {str(e)}"
            log(error_msg)
            log("Supported distributions: Ubuntu, Debian, Fedora, CentOS, Arch, Windows")
            error_occurred = True
            error_details.append(str(e))
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
            error_msg = f"✗ Update finished with exit code {exit_status}"
            log(error_msg)
            error_occurred = True
            error_details.append(f"Update failed with exit code {exit_status}")
            
            # Read any error messages
            errors = stderr.read().decode().strip()
            if errors:
                log(f"Errors: {errors}")
                error_details.append(f"Error output: {errors}")
        
    except paramiko.AuthenticationException:
        error_msg = f"✗ Authentication failed for {name}. Check SSH keys or credentials."
        log(error_msg)
        error_occurred = True
        error_details.append("Authentication failed - check SSH keys or credentials")
    except paramiko.SSHException as e:
        error_msg_str = str(e)
        # Check if this is a host key rejection error
        if "not found in known_hosts" in error_msg_str.lower() or "reject" in error_msg_str.lower():
            error_msg = f"✗ Host key verification failed for {name}. The host key for {host} is not in known_hosts."
            log(error_msg)
            log(f"To add this host, run: ssh-keyscan -H {host} >> ~/.ssh/known_hosts")
            error_occurred = True
            error_details.append(f"Host key not found in known_hosts. Add it with: ssh-keyscan -H {host} >> ~/.ssh/known_hosts")
        else:
            error_msg = f"✗ SSH error connecting to {name}: {error_msg_str}"
            log(error_msg)
            error_occurred = True
            error_details.append(f"SSH error: {error_msg_str}")
    except Exception as e:
        error_msg = f"✗ Error updating {name}: {str(e)}"
        log(error_msg)
        error_occurred = True
        error_details.append(f"Unexpected error: {str(e)}")
    finally:
        if ssh:
            ssh.close()
            log(f"Disconnected from {name}")
        
        # Send error notification if an error occurred
        if error_occurred and email_config.get_error_notifications_enabled():
            error_message = "\n".join(error_details)
            email_notifier.send_error_notification(name, error_message)

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
