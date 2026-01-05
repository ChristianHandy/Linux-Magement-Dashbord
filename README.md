# Linux Management Dashboard

A comprehensive web dashboard combining system update management and disk tools for Linux computers.

> **Note:** This project merges functionality from two repositories:
> - [linux-update-dashboard](https://github.com/ChristianHandy/linux-update-dashboard) - Remote system update management
> - [Disk_Tools](https://github.com/ChristianHandy/Disk_Tools) - Disk formatting and SMART monitoring
>
> Both tools are now accessible from a unified interface after logging in.

## Features

### User Management & Security
- **Multi-user authentication** with secure password hashing
- **Role-based access control (RBAC)** with three built-in roles:
  - **Admin**: Full system access including user management
  - **Operator**: Can perform system operations (updates, disk management)
  - **Viewer**: Read-only access to system information
- User profile management
- Backward compatibility with environment variable authentication
- Secure session management

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
6. **Configure security settings:**
   ```bash
   # Copy the example environment file
   cp .env.example .env
   
   # Edit .env and set secure values:
   # - Generate a secure SECRET_KEY: python -c "import secrets; print(secrets.token_hex(32))"
   # - Set DASHBOARD_USERNAME and DASHBOARD_PASSWORD to secure credentials
   nano .env
   ```
7. Run: `python app.py` (requires sudo for disk management features)

## Quick Start

1. **Configure credentials (REQUIRED for security):**
   ```bash
   # Set environment variables with secure credentials
   export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
   export DASHBOARD_USERNAME=your_username
   export DASHBOARD_PASSWORD=your_secure_password
   ```

2. Start the application:
   ```bash
   # For system updates only (no sudo needed)
   python3 app.py
   
   # For full features including disk management (requires sudo)
   sudo -E python3 app.py  # -E preserves environment variables
   ```

3. Open your browser to `http://localhost:5000`

4. Login with your configured credentials
   - **Important:** Never use default credentials in production!

5. From the main menu, choose:
   - **System Update Manager** (`/dashboard`) - Manage remote Linux systems
   - **Disk Management Tools** (`/disks`) - Format and test disks (requires sudo)
   - **User Management** (`/users`) - Manage users and roles (admin only)
   - **My Profile** (`/users/profile`) - Update your own profile

## Usage

The dashboard provides multiple tools accessible from the main menu:

### System Update Manager (`/dashboard`)
Monitor and update remote Linux systems via SSH. See "Managing hosts" section below for details.

### Disk Management Tools (`/disks`)
Format, test, and monitor disk drives. Requires root/sudo privileges for disk operations.

### User Management (`/users`)
Administrators can manage user accounts and assign roles. See "User Management" section below for details.

## User Management

The dashboard includes a comprehensive user management system with role-based access control.

### Initial Setup

On first run, the application automatically creates an admin user from your environment variables:
- Username: Value of `DASHBOARD_USERNAME` (default: `admin`)
- Password: Value of `DASHBOARD_PASSWORD` (default: `password`)
- Role: Automatically assigned `admin` role

**Important:** Change the default credentials immediately!

### User Roles

The system includes three built-in roles with different permission levels:

1. **Admin** - Full system access
   - Manage users and roles
   - All operator permissions
   - Access user management interface

2. **Operator** - Can perform system operations
   - Trigger system updates
   - Manage hosts
   - Format disks and run SMART tests
   - Manage disk remotes
   - Import/export data
   - Cannot manage users

3. **Viewer** - Read-only access
   - View all system information
   - View disk information and SMART data
   - View host configurations
   - Cannot modify anything

### Managing Users (Admin Only)

**Accessing User Management:**
- Navigate to `/users` or click "User Management" from the main menu
- Only administrators can access this section

**Creating a New User:**
1. Click "Add New User"
2. Enter username, password, and email (optional)
3. Select one or more roles
4. Click "Create User"

**Editing a User:**
1. From the user list, click "Edit" next to the user
2. Modify username, email, password (optional), or active status
3. Change role assignments by checking/unchecking roles
4. Click "Update User"

**Deleting a User:**
1. From the user list, click "Delete" next to the user
2. Confirm the deletion
3. Note: You cannot delete your own account

### User Profile

All users can manage their own profile:
1. Click "My Profile" from the main menu or navigate to `/users/profile`
2. Update your email or change your password
3. View your assigned roles

### Routes

User Management Routes:
- User list: `/users` (admin only)
- Add user: `/users/add` (admin only)
- Edit user: `/users/edit/<id>` (admin only)
- Delete user: `/users/delete/<id>` (admin only, POST)
- User profile: `/users/profile` (all users)

### Authentication Flow

The system supports two authentication methods for backward compatibility:

1. **Database Authentication** (Recommended)
   - User accounts stored in SQLite database
   - Passwords hashed with werkzeug security
   - Supports multiple users with different roles

2. **Environment Variable Authentication** (Legacy)
   - Single user from `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`
   - Maintained for backward compatibility
   - Automatically migrated to database on first run

### Database

User information is stored in `users.db` (SQLite database) with the following tables:
- `users` - User accounts with hashed passwords
- `roles` - Available system roles
- `user_roles` - Many-to-many relationship between users and roles

The database is automatically created on first run and excluded from git (via `.gitignore`).

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

**Note:** Host management operations (add, edit, delete) require operator or admin role.

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

## Security

### Security Improvements
This project has been hardened with the following security improvements:

**Authentication & Credentials:**
- ✅ Credentials moved to environment variables (no hardcoded passwords)
- ✅ Secure session key generation using `secrets.token_hex(32)`
- ✅ Warning printed when using default credentials
- ✅ `.env.example` file provided for configuration

**Command Injection Prevention:**
- ✅ Device name sanitization to prevent command injection
- ✅ Input validation on all disk operations
- ✅ SFTP used instead of shell commands for SSH key installation
- ✅ Whitelist validation for filesystem types and SMART modes

**Security Headers:**
- ✅ X-Content-Type-Options: nosniff
- ✅ X-Frame-Options: DENY
- ✅ X-XSS-Protection enabled
- ✅ Strict-Transport-Security for HTTPS

**Other Improvements:**
- ✅ Debug mode disabled by default (controlled via FLASK_DEBUG environment variable)
- ✅ Plugin name validation to prevent template injection
- ✅ SQL parameterized queries (already implemented)

### Important Security Notes

**Before Production Deployment:**
1. **Set secure credentials** using environment variables:
   ```bash
   export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
   export DASHBOARD_USERNAME=your_secure_username
   export DASHBOARD_PASSWORD=your_secure_password
   ```

2. **Use HTTPS/TLS** - This is critical! Without TLS:
   - Passwords are transmitted in plain text
   - Session cookies can be intercepted
   - SSH passwords sent to the server are exposed

3. **SSH Host Key Verification** - The current implementation uses `AutoAddPolicy`, which accepts any host key. This is vulnerable to man-in-the-middle attacks. For production:
   - Manually verify host keys on first connection
   - Use `WarningPolicy` instead of `AutoAddPolicy`
   - Maintain a proper `known_hosts` file

4. **Network Security:**
   - Run behind a reverse proxy (nginx, Apache) with TLS
   - Restrict access to trusted networks/VPN only
   - Consider using firewall rules to limit access
   - Never expose directly to the internet without proper hardening

5. **Additional Hardening (Recommended):**
   - Add CSRF protection using Flask-WTF
   - Implement rate limiting for login attempts
   - Add two-factor authentication
   - Use a production WSGI server (gunicorn, uWSGI) instead of Flask's development server
   - Implement audit logging for all operations
   - Regular security updates for all dependencies

6. **Disk Operations Security:**
   - Requires root/sudo access (significant security risk)
   - Only run on isolated, trusted systems
   - Validate that only intended disks are being modified
   - Consider running disk operations in a separate, sandboxed process

### Environment Variables

Create a `.env` file or set these environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Recommended | Auto-generated | Flask session encryption key |
| `DASHBOARD_USERNAME` | Recommended | admin | Dashboard login username |
| `DASHBOARD_PASSWORD` | Recommended | password | Dashboard login password |
| `FLASK_DEBUG` | Optional | false | Enable Flask debug mode (never in production!) |

Security notes (legacy - see Security section above for updated guidance)
- Use HTTPS/TLS if the dashboard is reachable over an untrusted network, otherwise passwords and session cookies travel unencrypted.
- The "Install SSH key" flow requires you to enter the remote account password; that password is sent to the dashboard server and used transiently. Do not expose the dashboard without TLS and strong authentication.
- The dashboard may generate and store a private key under `~/.ssh` on the dashboard host. Protect that machine and its filesystem.
- Credentials and `app.secret_key` now use environment variables (see Security section).

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
# Export environment variables first
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export DASHBOARD_USERNAME=your_username
export DASHBOARD_PASSWORD=your_password

# Run with sudo, preserving environment variables
sudo -E python3 app.py
```

### Disk Tools Security Note
The application requires root access for disk operations. This poses significant security risks:
- **Only run on isolated, trusted systems** - Root access means any vulnerability can compromise the entire system
- **Never expose to the internet** without multiple layers of security
- Use HTTPS/TLS for all deployments (critical!)
- Set secure credentials via environment variables (see Security section)
- Consider using a reverse proxy with proper authentication
- Limit access to trusted users only
- Run in a VM or container for additional isolation
- Regularly audit disk operations and review logs
- See the **Security** section above for comprehensive security guidance
