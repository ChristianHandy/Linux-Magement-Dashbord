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
- **Automatic update scheduling** with configurable frequency (daily, weekly, monthly)
- **Email notifications** - Scheduled reports and error alerts via SMTP
- **Repository-only updates** - Update packages while preserving host configuration files
- **Full system updates** - Complete updates including configuration files
- Mobile-friendly UI
- Update history tracking with update type information
- Online/offline host detection
- Update status notifications
- SSH key management

### Disk Management Tools
- Format disks (ext4, XFS, FAT32)
- SMART health monitoring (short/long tests)
- Block validation and error detection
- Disk history and operations tracking
- Remote disk management
- Automatic disk detection and processing
- **Plugin/addon system** for extensibility with remote plugin installation
- CSV export/import of SMART data

### Plugin System
- **Plugin Manager** - Web interface to manage plugins
- **Remote Plugin Repository** - Install plugins directly from the web
- **Easy Installation** - One-click plugin installation (admin only)
- **Plugin Uninstallation** - Remove plugins when no longer needed
- Extensible architecture for custom disk tools and features

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

## Plugin Management

The dashboard includes a powerful plugin system that allows you to extend disk management functionality with custom plugins.

### Accessing the Plugin Manager

1. Navigate to **Disk Management Tools** (`/disks`)
2. Click the **🔌 Plugin Manager** button
3. Or directly access `/disks/pluginmanager/`

**Note:** Only administrators can install or uninstall plugins. All users can view installed plugins.

### Addon Paths

Addon pages are accessible at `/disks/addons/<plugin_name>/<device>`. For backward compatibility, the old path `/addons/<plugin_name>/<device>` will automatically redirect to the correct location.

**Examples:**
- Correct path: `/disks/addons/example_plugin/sda`
- Legacy path (redirects): `/addons/example_plugin/sda`

### Plugin Manager Features

**Installed Plugins Section:**
- View all currently installed plugins
- See plugin status (OK or Error)
- View error messages for failed plugins
- Uninstall plugins (admin only)

**Available Remote Plugins Section:**
- Browse plugins from the remote repository
- View plugin details (name, description, version, author)
- Install plugins with one click (admin only)
- Automatic detection of already-installed plugins

### Installing a Plugin

1. Navigate to the Plugin Manager (`/disks/pluginmanager/`)
2. Scroll to the **Available Remote Plugins** section
3. Find the plugin you want to install
4. Click the **Install** button
5. Wait for the installation to complete
6. **Restart the application** to activate the plugin

**Important:** Application restart is required for plugins to take effect!

### Uninstalling a Plugin

1. Navigate to the Plugin Manager
2. Find the plugin in the **Installed Plugins** section
3. Click the **Uninstall** button
4. Confirm the action
5. **Restart the application** to complete removal

**Note:** You cannot uninstall the Plugin Manager itself.

### Security

The plugin system includes several security features:

- **Admin-only access** - Only administrators can install or uninstall plugins
- **Plugin validation** - Plugin IDs are validated (alphanumeric and underscores only)
- **HTTPS-only downloads** - Remote plugins must be served over HTTPS
- **Filename validation** - Prevents path traversal attacks
- **Automatic restart required** - Plugins are not dynamically loaded, preventing runtime injection

### Creating Your Own Plugins

Plugins follow a simple Python structure. See `PLUGIN_REPOSITORY.md` for detailed documentation on:
- Plugin file structure
- Remote repository setup
- Security best practices
- Testing plugins locally

**Example Plugin Structure:**
```python
addon_meta = {
    "name": "My Plugin",
    "html": '''
    {% extends 'disks/base.html' %}
    {% block title %}My Plugin{% endblock %}
    {% block content %}
      <h1>My Plugin Content</h1>
    {% endblock %}
    '''
}

def register(app, core):
    """Called when the plugin is loaded"""
    print("[my_plugin] successfully registered.")
```

### Plugin Repository Configuration

The default remote repository URL can be changed in `addons/plugin_manager.py`:
```python
REMOTE_PLUGIN_REPO = "https://your-repo-url/plugins.json"
```

For information on hosting your own plugin repository, see `PLUGIN_REPOSITORY.md`.


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

## Automatic Update Configuration

The Linux Management Dashboard now includes comprehensive automatic update controls accessible via the Update Settings page (`/update_settings`).

### Accessing Update Settings
1. Log in to the dashboard
2. Navigate to the main menu (`/index`) or Update Dashboard (`/dashboard`)
3. Click the "Update Settings" button
4. Configure your automatic update preferences

**Note:** Modifying update settings requires operator or admin role.

### Configuration Options

#### Enable/Disable Automatic Updates
Toggle automatic updates on or off with a simple checkbox. When enabled, the system will automatically update all configured hosts at the specified frequency without manual intervention.

#### Update Frequency
Choose how often automatic updates should run:
- **Daily** - Updates run every 24 hours (recommended for security-critical systems)
- **Weekly** - Updates run every 7 days (balanced approach)
- **Monthly** - Updates run every 30 days (suitable for stable production environments)

#### Update Notifications
Enable or disable update status notifications displayed on the dashboard.

#### Dashboard Update Notifications
Enable or disable notifications for new versions of the Linux Management Dashboard itself. When enabled:
- The system checks for new dashboard versions every 24 hours
- Notifications appear for both official releases and new commits
- Users can update the dashboard directly from the UI while preserving configurations
- Only administrators can perform dashboard updates

### Update Types

The dashboard now supports two types of updates:

#### Repository-Only Updates
Click the **"Repo Update"** button (purple) on the dashboard to update packages from repositories while keeping host configuration files unchanged. This is ideal for:
- Production systems where configuration stability is critical
- Systems with custom configurations that should be preserved
- Regular package updates without configuration changes

**Technical details:**
- Debian/Ubuntu: Uses `--force-confold` to keep existing config files
- Fedora: Uses `--setopt=tsflags=noscripts` to preserve configurations
- Arch Linux: Uses `--needed` flag to avoid reinstalling packages

#### Full System Updates
Click the **"Full Update"** button (blue) on the dashboard to perform complete system updates including configuration files. This performs:
- Package updates from repositories
- Configuration file updates (may overwrite local changes)
- Complete system upgrade

### Routes
- Update settings page: `/update_settings`
- Repository-only update: `/update_repo/<host_name>`
- Full system update: `/update/<host_name>`
- Update progress: `/progress/<host_name>`

### Configuration Storage
Update settings are stored in `update_settings.json` with the following structure:
```json
{
  "automatic_updates_enabled": false,
  "update_frequency": "daily",
  "last_auto_update": null,
  "notification_enabled": true,
  "dashboard_update_notifications": true
}
```

### Dashboard Status Display
The Update Dashboard displays the current automatic update status:
- **Disabled**: Shows a neutral card indicating automatic updates are off
- **Enabled**: Shows a green card with the configured frequency and last update time

## Dashboard Self-Update Feature

The Linux Management Dashboard includes a self-update feature that automatically notifies users when a new version of the dashboard itself is available.

### Features

- **Automatic Version Checking**: Checks for new dashboard versions every 24 hours
- **Update Notifications**: Displays prominent notification banners when updates are available
- **Support for Releases and Commits**: Detects both official GitHub releases and new commits
- **Configuration Preservation**: Updates the dashboard while keeping all settings intact
- **Admin-Only Updates**: Only administrators can perform dashboard updates for security

### How It Works

1. **Background Checking**: A background worker automatically checks the GitHub repository for new versions every 24 hours
2. **Notification Display**: When an update is available, a blue notification banner appears on the main menu and dashboard pages
3. **User Action**: Users can view the update details, check the GitHub release/commit, or update immediately
4. **Safe Updates**: The update process preserves configuration files (hosts.json, users.db, update_settings.json, etc.)

### Update Process

1. Navigate to the main menu or dashboard
2. If an update is available, you'll see a notification banner with:
   - Update description (release name or commit message)
   - Version identifier (tag or short SHA)
   - Action buttons: "Update Now", "Check Again", "View on GitHub", "Dismiss"
3. Click "Update Now" to proceed to the update page
4. Review the important warnings and update options
5. Choose to preserve or reset configuration files
6. Click "Update Dashboard Now" to start the update
7. Restart the application after the update completes

### Routes

- Check for updates: `/dashboard_version/check`
- Update page: `/dashboard_version/update`
- Dismiss notification: `/dashboard_version/dismiss`

### Configuration

Dashboard update notifications can be enabled/disabled in Update Settings:
- Navigate to `/update_settings`
- Toggle "Enable Dashboard Update Notifications"
- This controls whether the system checks for and displays dashboard updates

### Preserved Files

When updating with "Preserve Configuration Files" option (recommended), these files are automatically backed up and restored:
- `hosts.json` - Host configurations
- `history.json` - Update history
- `update_settings.json` - Update settings
- `version_check.json` - Version check data
- `users.db` - User database
- `disks.db` - Disk management database
- `.env` - Environment variables
- `operations.db` - Operation history
- `smart.db` - SMART data

### GitHub Actions Integration

The repository includes a GitHub Actions workflow (`.github/workflows/notify-version.yml`) that:
- Triggers on pushes to main branch and published releases
- Creates a notification summary in GitHub Actions
- Provides update instructions for installed dashboards
- Helps track when new versions are available

### Manual Version Check

To manually check for updates:
1. Log in as an operator or administrator
2. Navigate to the main menu (`/index`)
3. If no notification is visible, go to `/dashboard_version/check`
4. The system will immediately check for updates and display results

### Security Notes

- Only administrators can perform dashboard updates
- The update process uses `git reset --hard` to ensure a clean update
- Configuration files are backed up to `/tmp` before updates
- The system validates the current branch and commit SHA
- Updates are fetched from the official GitHub repository only

## Email Reporting

The Linux Management Dashboard includes comprehensive email notification capabilities to keep administrators informed about system status and issues.

### Features

- **Scheduled Reports**: Receive periodic system status reports with host information and update history
- **Error Notifications**: Get immediate alerts when system updates fail
- **Flexible Configuration**: Support for any SMTP server (Gmail, Office 365, custom servers)
- **Multiple Recipients**: Send notifications to multiple email addresses
- **HTML Formatting**: Professional, easy-to-read email formats with both HTML and plain text

### Accessing Email Settings

1. Log in to the dashboard with operator or admin credentials
2. Navigate to the main menu (`/index`)
3. Click the "Email Configuration" button in the System Update Manager section
4. Configure your SMTP settings and preferences

### Configuration Options

#### SMTP Settings
- **SMTP Server**: Hostname of your email server (e.g., smtp.gmail.com)
- **SMTP Port**: Port number (587 for TLS, 465 for SSL, 25 for unencrypted)
- **Use TLS**: Enable TLS encryption (recommended)
- **SMTP Username**: Authentication username (usually your email address)
- **SMTP Password**: Authentication password (for Gmail, use an app-specific password)
- **Sender Email**: Email address that appears as the sender
- **Recipient Emails**: One or more email addresses to receive notifications

#### Report Settings
- **Enable Scheduled Reports**: Toggle periodic system status reports
- **Report Interval**: Choose how often to send reports (daily, weekly, or monthly)
- **Enable Error Notifications**: Toggle immediate alerts for update failures

### Email Provider Setup

#### Gmail
1. Enable 2-factor authentication in your Google Account
2. Generate an app-specific password:
   - Go to Google Account → Security → 2-Step Verification → App passwords
   - Generate a new app password for "Mail"
3. Use these settings:
   - SMTP Server: `smtp.gmail.com`
   - SMTP Port: `587`
   - Use TLS: ✓ (enabled)
   - Username: Your Gmail address
   - Password: The app-specific password (not your regular password)

#### Office 365
1. Use these settings:
   - SMTP Server: `smtp.office365.com`
   - SMTP Port: `587`
   - Use TLS: ✓ (enabled)
   - Username: Your full Office 365 email address
   - Password: Your Office 365 password
2. Ensure Modern Authentication is enabled if required by your organization

#### Custom SMTP Server
Configure the appropriate settings for your SMTP server. Contact your email provider or system administrator for specific details.

### Testing Email Configuration

Use the "Send Test Email" button on the email configuration page to verify your settings before enabling automatic reports. This sends a test message to all configured recipients.

### Email Types

#### Scheduled Reports
Scheduled reports include:
- Current status of all configured hosts (online/offline)
- Recent update history
- Summary of system operations
- Professional HTML formatting with color-coded status

Reports are sent according to your configured interval (daily, weekly, or monthly).

#### Error Notifications
Error notifications are sent immediately when:
- A system update fails
- SSH connection errors occur
- Unsupported distributions are detected
- Any other update-related errors happen

Error notifications include:
- Host name where the error occurred
- Timestamp of the error
- Detailed error message and diagnostics
- Red alert styling for immediate attention

### Security Notes

- Email settings including passwords are stored in `email_settings.json`
- The configuration file is excluded from version control via `.gitignore`
- For production deployments, consider using environment variables for sensitive data
- Use TLS/SSL encryption when possible to protect credentials in transit
- App-specific passwords are recommended for Gmail and other providers that support them
- Only operators and administrators can configure email settings

### Routes

- Email configuration page: `/email_settings`


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
