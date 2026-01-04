# Linux Management Dashboard

A comprehensive web dashboard combining system update management and disk tools for Linux computers.

> **Note:** This project merges functionality from two repositories:
> - [linux-update-dashboard](https://github.com/ChristianHandy/linux-update-dashboard) - Remote system update management
> - [Disk_Tools](https://github.com/ChristianHandy/Disk_Tools) - Disk formatting and SMART monitoring
>
> Both tools are now accessible from a unified interface after logging in.

## Features

### System Update Manager
- Trigger updates remotely on multiple Linux computers via SSH
- Mobile-friendly UI
- Update history tracking
- Online/offline host detection
- Auto-scheduled updates
- SSH key management

### Disk Management Tools
- Format disks (ext4, XFS, FAT32)
- SMART health monitoring (short/long tests)
- Block validation and error detection
- Disk history and operations tracking
- Remote disk management
- Automatic disk detection and processing
- Plugin/addon system for extensibility
- CSV export/import of SMART data

## Installation
1. Clone repository: `git clone https://github.com/ChristianHandy/linux-update-dashboard.git`
2. Enter project: `cd linux-update-dashboard`
3. Create virtual env: `python3 -m venv venv`
4. Activate: `source venv/bin/activate`
5. Install requirements: `pip install -r requirements.txt`
6. Run: `python app.py` (requires sudo for disk management features)

## Quick Start

1. Start the application:
   ```bash
   # For system updates only (no sudo needed)
   python3 app.py
   
   # For full features including disk management (requires sudo)
   sudo python3 app.py
   ```

2. Open your browser to `http://localhost:5000`

3. Login with default credentials:
   - Username: `admin`
   - Password: `password`
   - **Important:** Change these credentials before exposing the dashboard publicly!

4. From the main menu, choose:
   - **System Update Manager** (`/dashboard`) - Manage remote Linux systems
   - **Disk Management Tools** (`/disks`) - Format and test disks (requires sudo)

## Usage

The dashboard provides two main tools accessible from the main menu:

### System Update Manager (`/dashboard`)
Monitor and update remote Linux systems via SSH. See "Managing hosts" section below for details.

### Disk Management Tools (`/disks`)
Format, test, and monitor disk drives. Requires root/sudo privileges for disk operations.

## Managing hosts (via web UI)

This project includes a small web UI to manage the list of hosts (PCs) the dashboard updates. You can add, edit, delete hosts and install an SSH public key on remote accounts using a password.

Important: The UI stores hosts in `hosts.json` (in the repository root). Make a backup before editing.

Routes
- Dashboard: `/dashboard`
- Manage hosts (list + add): `/hosts`
- Edit host: `/hosts/edit/<name>`
- Delete host (POST): `/hosts/delete/<name>`
- Install SSH public key (password auth): `/hosts/install_key/<name>`
- Update a host (starts update thread): `/update/<name>`
- Update progress: `/progress/<name>`

Default credentials (change before exposing publicly)
- Username: `admin`
- Password: `password`
- Secret (session): `app.secret_key = "change_me"` in `app.py`

Add a host (via web)
1. Log in to the dashboard (`/`) with the configured username/password.
2. Open `/hosts` (or click "Manage Hosts" on the dashboard).
3. Fill in:
   - Display name: a friendly name used by the dashboard (this becomes the key in `hosts.json`).
   - Host: IP address or hostname (used for SSH).
   - User: remote account username.
4. Click Save. The host will appear in the list and on the dashboard.

Edit a host
- Click "Edit" next to the host in `/hosts`, modify fields, then Save. If you change the Display name, the old entry will be removed and a new one created.

Delete a host
- Click the Delete button next to the host in `/hosts`. Deletion is performed with a POST request.

Install SSH public key on a remote host
- Click "Install SSH key" next to the host on `/hosts`.
- Enter the remote account password once and submit.
  - The server will:
    - Use your dashboard host's public key (`~/.ssh/id_rsa.pub`) if present, or
    - Generate an SSH keypair on the dashboard host (`~/.ssh/id_rsa` + `id_rsa.pub`) and use the public key.
    - Connect to the remote host over SSH with the provided password and append the public key to `~/.ssh/authorized_keys` (creating `~/.ssh` and setting permissions if necessary).
- On success, you will be able to SSH to the remote host from the dashboard host without a password (for that user).

hosts.json format
- The file is a simple JSON object mapping display name to host details:
```json
{
  "my-pc": { "host": "192.168.1.50", "user": "user" },
  "server-1": { "host": "server.example.local", "user": "admin" }
}
```
- You can edit `hosts.json` by hand, but the web UI will overwrite the file when hosts are added/edited/deleted. Back it up before manual edits.

Backup and restore hosts.json
- Backup:
  - cp hosts.json hosts.json.bak
- Restore:
  - mv hosts.json.bak hosts.json

Security notes (read before using publicly)
- Use HTTPS/TLS if the dashboard is reachable over an untrusted network, otherwise passwords and session cookies travel unencrypted.
- The "Install SSH key" flow requires you to enter the remote account password; that password is sent to the dashboard server and used transiently. Do not expose the dashboard without TLS and strong authentication.
- The dashboard may generate and store a private key under `~/.ssh` on the dashboard host. Protect that machine and its filesystem.
- Add CSRF protection (Flask-WTF) and stronger authentication before exposing publicly.
- Consider moving credentials and the `app.secret_key` into environment variables instead of hardcoding them.

Running & testing
1. Ensure dependencies are installed:
   - paramiko (see `requirements.txt`)
2. Start the app:
   - python3 app.py
3. Open a browser to the server's address (e.g. `http://localhost:5000`).
4. Log in and visit `/hosts` to manage hosts.

Troubleshooting
- Template errors: ensure `templates/` contains all required template files
- If `hosts.json` is malformed, the app will fall back to an empty hosts list. Check JSON syntax if hosts are missing.
- If SSH key installation fails, examine the error message shown on the `/hosts/install_key/<name>` page and check connectivity and credentials.

## Disk Management Tools

The Disk Tools section (`/disks`) provides comprehensive disk management capabilities.

### Prerequisites for Disk Tools
- Linux system with Python 3.8+
- Root/sudo privileges for disk operations
- System utilities: `lsblk`, `smartctl`, `wipefs`, `mkfs.ext4`, `mkfs.xfs`, `mkfs.vfat`, `dd`, `badblocks`

Install required tools:
```bash
sudo apt update
sudo apt install smartmontools parted e2fsprogs xfsprogs dosfstools
```

### Disk Tools Features

**Disk Overview** (`/disks`)
- Lists all connected disks with model, size, and serial information
- Search/filter disks by device name or model
- Real-time disk usage monitoring

**SMART Testing** (`/disks/smart/start/<device>/<mode>`)
- Run short or long SMART tests
- View detailed SMART reports with temperature and health status
- Track SMART history over time
- Export/import SMART data in CSV format

**Disk Formatting** (`/disks/format/<device>`)
- Format disks with ext4, XFS, or FAT32 filesystems
- Background task execution with progress tracking
- Safe wipefs operation before formatting

**Block Validation** (`/disks/validate/<device>`)
- Validates the first 256 blocks of a disk
- Visual display of good/bad blocks
- Identifies potential disk errors

**Automatic Mode** (`/disks/toggle_auto`)
- Automatically detect newly connected disks
- Auto-format and run SMART tests on new disks
- Configurable to skip system disks (e.g., mmcblk0, nvme*)

**History & Monitoring** (`/disks/history`)
- Complete log of all disk operations
- SMART test history with health trends
- Task management (view/stop running operations)

**Dashboard** (`/disks/dashboard`)
- Summary statistics: total disks, bad disks, running tasks
- Device runtime tracking

**Remote Disk Management** (`/disks/remotes`)
- Manage remote disk systems
- Add/remove remote connections

**Plugin System**
- Extensible addon architecture
- Create custom disk management tools
- See `addons/` directory for examples

### Running with Disk Tools
Since disk operations require root privileges, run the application with sudo:
```bash
sudo python3 app.py
```

### Security Note
The application requires root access for disk operations. This poses security risks:
- Only run on trusted networks
- Use HTTPS/TLS for production deployments
- Change default credentials before exposing publicly
- Consider using a reverse proxy with proper authentication
- Limit access to trusted users only
