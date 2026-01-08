# Multi-boot / Dual-boot Support

## Overview

The Linux Management Dashboard now supports managing PCs with multiple operating systems (multi-boot or dual-boot configurations). This feature automatically detects which OS is currently running on each host and applies the correct update commands accordingly.

## Use Cases

- **Dual-boot Windows/Linux**: Manage a PC that can boot into either Windows or Linux (e.g., Windows 11 and Ubuntu 22.04)
- **Triple-boot systems**: Support for systems with three or more operating systems
- **Development machines**: Manage development workstations with multiple OS installations for testing
- **Server environments**: Track which OS is active on multi-boot servers

## How It Works

### OS Detection

The dashboard automatically detects the currently running operating system when:
1. A host is added and comes online
2. You click the "Detect OS" button on the Manage Hosts page
3. The dashboard page is loaded for online hosts

The detection process:
- For **local hosts** (localhost): Reads `/etc/os-release` on Linux or uses platform detection on Windows
- For **remote hosts**: Connects via SSH and runs detection commands to identify the OS
- Supports detection of: Ubuntu, Debian, Fedora, CentOS, Arch Linux, and Windows

### OS Information Caching

Once detected, the OS information is cached in the host configuration (`hosts.json`). This means:
- The dashboard remembers which OS each host is running
- Updates use the correct commands for the detected OS
- Detection doesn't run on every page load (only when needed)

### Multi-boot Workflow

For a PC with multiple operating systems:

1. **Initial Setup**: Add the PC as a host with its IP address or hostname
2. **Boot into OS #1**: Boot the PC into the first OS (e.g., Windows)
3. **Detect OS**: Click "Detect OS" in the dashboard - it will detect Windows
4. **Update**: Run updates - Windows Update commands are used
5. **Reboot into OS #2**: Reboot the PC into the second OS (e.g., Ubuntu)
6. **Re-detect OS**: Click "Detect OS" again - it will now detect Ubuntu
7. **Update**: Run updates - Ubuntu apt-get commands are used

## Features

### Visual OS Indicators

The dashboard displays OS information with visual indicators:
- **🪟 Windows badge**: Blue badge for Windows systems
- **🐧 Linux badge**: Green badge for Linux distributions
- **OS name and version**: Displayed prominently (e.g., "Ubuntu 22.04", "Windows 10")

### Automatic Command Selection

The dashboard automatically selects the correct update commands based on the detected OS:
- **Windows**: Uses PowerShell with PSWindowsUpdate module and winget
- **Ubuntu/Debian**: Uses apt-get with appropriate flags
- **Fedora**: Uses dnf package manager
- **CentOS**: Uses yum package manager
- **Arch Linux**: Uses pacman package manager

### OS Detection Button

A convenient "Detect OS" button is available on the Manage Hosts page:
- Click to detect or refresh OS information for any host
- Useful after rebooting into a different OS on multi-boot systems
- Shows a confirmation message with the detected OS

## Setup Instructions

### Adding a Multi-boot Host

1. **Add the Host**:
   - Navigate to `/hosts` in the dashboard
   - Click "Add Host"
   - Fill in:
     - **Display name**: A descriptive name (e.g., "Dev Workstation")
     - **Host**: IP address or hostname (e.g., "192.168.1.50")
     - **User**: SSH username for the host
   - Click Save

2. **Install SSH Key** (for remote hosts):
   - Click "Install SSH key" next to the host
   - Enter the SSH password
   - This enables password-less SSH access

3. **Detect the OS**:
   - Click "Detect OS" next to the host
   - The dashboard will detect which OS is currently running
   - OS information is displayed (e.g., "Ubuntu 22.04 🐧")

4. **Run Updates**:
   - Go to the Update Dashboard (`/dashboard`)
   - Choose "Full Update" or "Repo Update"
   - Updates use the correct commands for the detected OS

### Switching Between OSes

When you reboot your multi-boot PC into a different OS:

1. **Reboot** the PC into the desired OS
2. **Wait** for the PC to come online
3. **Detect OS** again by clicking the "Detect OS" button
4. **Verify** the OS information has been updated
5. **Run updates** - the correct commands will now be used

## Example Scenarios

### Scenario 1: Windows/Ubuntu Dual-boot Desktop

**Setup**:
- PC: Desktop with Windows 11 and Ubuntu 22.04
- IP: 192.168.1.100
- User: john

**Workflow**:
```
1. Boot into Windows 11
2. Add host: "My Desktop", 192.168.1.100, john
3. Click "Detect OS" → Shows "Windows 10" 🪟
4. Run "Full Update" → Uses PowerShell and winget
5. Reboot into Ubuntu 22.04
6. Click "Detect OS" → Shows "Ubuntu 22.04" 🐧
7. Run "Full Update" → Uses apt-get
```

### Scenario 2: Development Server with Multiple Distros

**Setup**:
- Server: Test server with Fedora, Ubuntu, and Arch Linux
- IP: 192.168.1.200
- User: admin

**Workflow**:
```
1. Boot into Fedora
2. Add host: "Test Server", 192.168.1.200, admin
3. Click "Detect OS" → Shows "Fedora 38" 🐧
4. Run updates → Uses dnf
5. Switch to Ubuntu partition
6. Click "Detect OS" → Shows "Ubuntu 22.04" 🐧
7. Run updates → Uses apt-get
8. Switch to Arch partition
9. Click "Detect OS" → Shows "Arch unknown" 🐧
10. Run updates → Uses pacman
```

### Scenario 3: Local Multi-boot PC

**Setup**:
- Running dashboard on a dual-boot PC (Windows/Linux)
- Want to manage the local system

**Workflow**:
```
1. Boot into Windows
2. Add host: "Local PC", localhost, (any user)
3. OS automatically detected as "Windows" 🪟
4. Run updates → Uses Windows Update
5. Reboot into Linux
6. Start dashboard again
7. Click "Detect OS" → Shows "Ubuntu 22.04" 🐧
8. Run updates → Uses apt-get
```

## Technical Details

### OS Detection Implementation

The OS detection uses the following methods:

**For Linux systems**:
- Reads `/etc/os-release` file
- Parses `ID=` for distribution name
- Parses `VERSION_ID=` for version number

**For Windows systems**:
- Tries PowerShell command execution
- Checks for `powershell.exe` availability
- Gets Windows version from environment

**For remote systems**:
- Uses SSH to connect to the host
- Runs detection commands remotely
- Returns results to the dashboard

### Data Storage

OS information is stored in `hosts.json`:

```json
{
  "my-pc": {
    "host": "192.168.1.100",
    "user": "john",
    "os_name": "ubuntu",
    "os_version": "22.04"
  },
  "dev-server": {
    "host": "192.168.1.200",
    "user": "admin",
    "os_name": "windows",
    "os_version": "10"
  }
}
```

### Update Command Selection

The system uses the `get_update_command()` function which:
1. Takes the detected OS name as input
2. Returns the appropriate update command for that OS
3. Supports both "full update" and "repo-only update" modes

## Limitations

1. **Manual Re-detection Required**: After rebooting into a different OS, you must manually click "Detect OS" to update the information
2. **Single Host Entry**: Each physical machine requires only one host entry, even with multiple OSes
3. **OS Must Be Online**: OS detection requires the host to be online and accessible
4. **SSH Access Required**: Remote hosts need SSH access configured for detection

## Troubleshooting

### OS Not Detected

**Symptom**: "Could not detect OS" message after clicking "Detect OS"

**Solutions**:
- Verify the host is online and accessible
- Check SSH connection is working (for remote hosts)
- Ensure `/etc/os-release` exists on Linux systems
- Verify PowerShell is available on Windows systems

### Wrong OS Shown

**Symptom**: Dashboard shows the wrong OS after rebooting

**Solutions**:
- Click "Detect OS" button to refresh the detection
- Verify you're connecting to the correct IP address
- Check if the IP address changed after reboot

### Updates Use Wrong Commands

**Symptom**: Updates fail because wrong package manager is used

**Solutions**:
- Click "Detect OS" to update the OS information
- Verify the detected OS matches the currently running OS
- Check the logs for OS detection messages

## FAQ

**Q: Do I need separate host entries for each OS on a multi-boot PC?**
A: No! Use a single host entry. The dashboard detects which OS is currently running.

**Q: How do I switch between OSes for updates?**
A: Reboot into the desired OS, then click "Detect OS" in the dashboard to update the information.

**Q: Does the dashboard automatically detect when I reboot into a different OS?**
A: No, you need to manually click "Detect OS" after rebooting to update the cached information.

**Q: Can I manage a triple-boot system (three or more OSes)?**
A: Yes! The system supports any number of operating systems. Just use "Detect OS" after booting into each OS.

**Q: What happens if OS detection fails?**
A: The dashboard will show an error message. Updates may still work if you previously detected the OS and it's cached.

**Q: Can I force a specific OS without detection?**
A: Currently, no. The system relies on automatic detection. However, you can manually edit `hosts.json` if needed (not recommended).

**Q: Does this work with localhost?**
A: Yes! If you're running the dashboard on a multi-boot PC, use "localhost" as the host and detect the OS after each boot.

## Security Considerations

- OS detection requires SSH access to remote hosts
- Detection commands are read-only and don't modify the system
- Cached OS information is stored in `hosts.json` (not sensitive data)
- All detection uses the same SSH authentication as regular updates

## See Also

- [README.md](README.md) - Main documentation
- [WINDOWS_SUPPORT.md](WINDOWS_SUPPORT.md) - Windows-specific features
- [LOCALHOST_EXAMPLE.md](LOCALHOST_EXAMPLE.md) - Managing local servers
- [SECURITY.md](SECURITY.md) - Security considerations

## Version History

- **v1.0** (2026-01-08): Initial multi-boot support implementation
  - OS detection for Linux and Windows
  - Automatic update command selection
  - Visual OS indicators in UI
  - "Detect OS" button for manual refresh
