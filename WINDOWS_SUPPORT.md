# Windows Support for FleetPilot

## Overview

The FleetPilot now supports managing Windows systems for both system updates (Windows Update) and software updates (winget). This document provides detailed information about Windows support implementation and usage.

## Features

### Windows System Updates
- Automatic Windows Update installation via PowerShell
- Uses PSWindowsUpdate module for comprehensive update management
- Automatically installs required modules if not present
- No-reboot option to prevent automatic restarts
- Repository-only mode for system updates without software packages

### Windows Software Updates
- Software package updates via Windows Package Manager (winget)
- Updates all installed applications in one command
- Automatic acceptance of source and package agreements
- Silent installation for unattended operations
- Full update mode combines both system and software updates

## Prerequisites

### For Local Windows Management
1. **Operating System**: Windows 10 (1809+) or Windows 11, Windows Server 2016+
2. **PowerShell**: Version 5.0 or later (included by default)
3. **Administrator Privileges**: Required for installing updates
4. **Execution Policy**: Set to allow script execution
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```
5. **Python**: Python 3.8+ installed and in PATH
6. **Winget** (Optional but recommended): Included in Windows 11, available for Windows 10

### For Remote Windows Management
1. All prerequisites for local management, plus:
2. **OpenSSH Server**: Configured and running on the Windows host
3. **SSH Key Authentication**: Set up between dashboard and Windows host
4. **Network Connectivity**: SSH port (22) accessible from dashboard host

## Installation on Windows

### Step 1: Install Python
Download and install Python from https://www.python.org/downloads/
- Check "Add Python to PATH" during installation

### Step 2: Clone the Repository
```powershell
git clone https://github.com/ChristianHandy/fleetpilot.git
cd fleetpilot
```

### Step 3: Create Virtual Environment
```powershell
python -m venv venv
venv\Scripts\activate
```

### Step 4: Install Dependencies
```powershell
pip install -r requirements.txt
```

### Step 5: Configure Environment
```powershell
# Copy example environment file
copy .env.example .env

# Generate a secure secret key
python -c "import secrets; print(secrets.token_hex(32))"

# Edit .env with your favorite editor
notepad .env
```

Set the following variables:
- `SECRET_KEY`: Use the generated secure key
- `DASHBOARD_USERNAME`: Your admin username
- `DASHBOARD_PASSWORD`: A secure password

### Step 6: Run the Dashboard
```powershell
# Run as Administrator for Windows Update support
python app.py
```

Open your browser to `http://localhost:5000` and log in.

## Usage

### Managing Local Windows System

1. **Add Localhost as a Host**:
   - Navigate to `/hosts` in the dashboard
   - Click "Add Host"
   - Fill in:
     - Display name: "Local Windows Server"
     - Host: `localhost` or `127.0.0.1`
     - User: (any value, ignored for localhost)
   - Click Save

2. **Run Updates**:
   - From the dashboard, click on your host
   - Choose update type:
     - **Repo Update** (Purple button): Windows system updates only
     - **Full Update** (Blue button): System updates + software updates via winget

3. **Monitor Progress**:
   - Updates run in the background
   - View real-time logs on the progress page
   - Email notifications available (if configured)

### Managing Remote Windows Systems

#### Step 1: Install OpenSSH Server on Windows
```powershell
# Check if OpenSSH Server is installed
Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'

# Install if not present
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# Start the service
Start-Service sshd

# Set service to start automatically
Set-Service -Name sshd -StartupType 'Automatic'

# Configure firewall
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

#### Step 2: Add Remote Windows Host to Dashboard
1. Navigate to `/hosts`
2. Click "Add Host"
3. Fill in:
   - Display name: "Remote Windows Server"
   - Host: IP address or hostname
   - User: Windows administrator username
4. Click Save

#### Step 3: Install SSH Key
1. Click "Install SSH key" next to the host
2. Enter the Windows administrator password
3. Wait for key installation to complete

#### Step 4: Run Updates
- Same as local management - use Repo Update or Full Update buttons

## Update Types

### Repository-Only Update (Repo Update)
**What it does**:
- Installs Windows system updates only
- Uses PSWindowsUpdate PowerShell module
- No software package updates

**Command executed**:
```powershell
Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -ErrorAction SilentlyContinue
Install-Module PSWindowsUpdate -Force -ErrorAction SilentlyContinue
Import-Module PSWindowsUpdate
Get-WindowsUpdate -AcceptAll -Install -AutoReboot:$false
```

**Use cases**:
- Regular security patching
- Critical updates only
- Systems where software updates are managed separately

### Full System Update (Full Update)
**What it does**:
- Installs Windows system updates
- Updates all installed software via winget
- Comprehensive system maintenance

**Command executed**:
```powershell
# Windows Update
Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -ErrorAction SilentlyContinue
Install-Module PSWindowsUpdate -Force -ErrorAction SilentlyContinue
Import-Module PSWindowsUpdate
Get-WindowsUpdate -AcceptAll -Install -AutoReboot:$false

# Software Updates
if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget upgrade --all --accept-source-agreements --accept-package-agreements --silent
}
```

**Use cases**:
- Complete system maintenance
- Monthly update cycles
- Keeping all software up to date

## Technical Details

### Platform Detection
The dashboard automatically detects Windows systems:
- **Local detection**: Uses `platform.system()` to identify Windows
- **Remote detection**: Attempts PowerShell command execution to identify Windows
- **Fallback**: Falls back to Linux detection if Windows detection fails

### Update Execution
- **Local**: Uses `subprocess.Popen()` with PowerShell commands
- **Remote**: Uses SSH with PowerShell command execution
- **Real-time logging**: Output streamed to dashboard in real-time
- **Error handling**: Comprehensive error detection and notification

### Security Considerations
1. **Administrator Privileges**: Required for Windows Update installation
2. **Execution Policy**: Must allow PowerShell script execution
3. **Automatic Module Installation**: PSWindowsUpdate installed automatically if needed
4. **No Automatic Reboot**: Updates installed without automatic restart
5. **SSH Security**: Uses standard SSH authentication for remote systems

## Troubleshooting

### Issue: "Execution policy does not allow running scripts"
**Solution**:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue: "PSWindowsUpdate module not found"
**Solution**: The dashboard automatically installs it, but you can install manually:
```powershell
Install-Module -Name PSWindowsUpdate -Force
```

### Issue: "winget not found"
**Solution**: 
- Windows 11: Winget is pre-installed, update Microsoft Store if needed
- Windows 10: Install App Installer from Microsoft Store
- Alternative: Download from https://github.com/microsoft/winget-cli/releases

### Issue: "Access denied" errors during update
**Solution**: Ensure the dashboard is running with Administrator privileges:
```powershell
# Right-click PowerShell and select "Run as Administrator"
python app.py
```

### Issue: Remote Windows host connection fails
**Solution**:
1. Verify OpenSSH Server is running: `Get-Service sshd`
2. Check firewall allows port 22: `Test-NetConnection -ComputerName localhost -Port 22`
3. Verify SSH key authentication works: `ssh username@hostname`

### Issue: Updates appear to hang
**Solution**: Windows Update can take significant time. Check progress in:
- Dashboard logs (real-time updates)
- Windows Update history (`Get-WindowsUpdateLog` or Settings > Update & Security)

## Limitations

1. **Disk Management**: Disk tools are Linux-only and not supported on Windows
2. **Sudo Commands**: Linux-specific sudo commands not applicable to Windows
3. **Distribution Detection**: Windows hosts show as "windows" distribution
4. **Reboot Handling**: Automatic reboots are disabled; manual reboot may be needed
5. **Local Execution**: Running the dashboard on Windows is supported but primarily designed for Linux

## Supported Windows Versions

- ✅ Windows 11 (all editions)
- ✅ Windows 10 version 1809 and later
- ✅ Windows Server 2019 and later
- ✅ Windows Server 2016 (with latest updates)
- ⚠️ Windows 10 earlier than 1809 (limited support)
- ❌ Windows 7, 8, 8.1 (not supported)

## FAQ

**Q: Can I run the dashboard on Windows to manage Linux systems?**
A: Yes! The dashboard runs on Windows and can manage both Linux and Windows hosts.

**Q: Do I need winget for Windows updates?**
A: No, winget is only for software package updates. System updates use PSWindowsUpdate which is automatically installed.

**Q: Will updates reboot my system automatically?**
A: No, the `-AutoReboot:$false` flag prevents automatic reboots. You can reboot manually when convenient.

**Q: Can I schedule automatic Windows updates?**
A: Yes, use the Update Settings page to configure automatic updates on a schedule (daily, weekly, monthly).

**Q: How do I update only specific software packages?**
A: Currently, the dashboard updates all packages. For selective updates, use winget directly on the Windows system.

**Q: Is there a dry-run mode to preview updates?**
A: Not currently. Consider testing on a non-production system first.

## Contributing

Windows support is new! If you encounter issues or have suggestions:
1. Check existing issues: https://github.com/ChristianHandy/fleetpilot/issues
2. Open a new issue with:
   - Windows version
   - Error messages
   - Steps to reproduce
   - Expected vs actual behavior

## See Also

- [README.md](README.md) - Main documentation
- [LOCALHOST_EXAMPLE.md](LOCALHOST_EXAMPLE.md) - Managing local servers
- [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) - Technical implementation details
- [SECURITY.md](SECURITY.md) - Security considerations

## Version History

- **v1.0** (2026-01-07): Initial Windows support implementation
  - Windows Update via PSWindowsUpdate
  - Software updates via winget
  - Local and remote Windows host support
  - Cross-platform compatibility maintained
