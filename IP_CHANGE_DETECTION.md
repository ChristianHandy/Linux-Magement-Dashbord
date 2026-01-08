# IP Change Detection Feature

## Overview

The Linux Management Dashboard now includes automatic IP address change detection for hosts in DHCP environments. This feature uses ARP (Address Resolution Protocol) tables and MAC addresses to track and automatically update host IP addresses when they change.

## Features

### 1. MAC Address Storage
- Hosts can now have an optional MAC address field
- MAC addresses are used to track devices even when their IP address changes
- Supports standard MAC address formats (colon or hyphen separated)

### 2. Automatic MAC Address Detection
- Click "Detect MAC" button next to any host to automatically discover its MAC address
- The system pings the host and extracts the MAC address from the ARP table
- Detected MAC addresses are automatically saved to the host configuration

### 3. IP Change Scanning
- Click "Scan for IP Changes" to check all hosts with MAC addresses
- The system queries the ARP table and compares current IPs with stored IPs
- When changes are detected, host IPs are automatically updated
- Flash messages show which hosts had IP changes

### 4. ARP Table Viewer
- View the current system ARP table via "View ARP Table" button
- Shows all MAC-to-IP mappings currently known to the system
- Useful for troubleshooting network connectivity and IP detection issues

## Usage

### Adding a Host with MAC Address

1. Navigate to **Manage Hosts** (`/hosts`)
2. Fill in the host form:
   - **Display name**: A friendly name for the host
   - **Host**: The current IP address
   - **User**: SSH username
   - **MAC Address**: The hardware MAC address (optional)
3. Click **Save**

### Detecting MAC Address Automatically

1. Add or edit a host with its current IP address
2. Click the **"🔍 Detect MAC"** button next to the host
3. The system will:
   - Ping the host to populate the ARP table
   - Extract the MAC address from the ARP table
   - Automatically save it to the host configuration

### Scanning for IP Changes

1. Navigate to **Manage Hosts** (`/hosts`)
2. Click **"🔍 Scan for IP Changes"** button
3. The system will:
   - Query the current ARP table
   - Compare MAC addresses with stored host configurations
   - Detect any IP changes for known MAC addresses
   - Automatically update host IPs when changes are found
   - Display a summary of changes

### Viewing the ARP Table

1. Navigate to **Manage Hosts** (`/hosts`)
2. Click **"View ARP Table"** button
3. View all MAC-to-IP mappings currently in the system ARP cache

## Technical Details

### ARP Table Sources

The system uses different commands based on the operating system:

**Linux/Unix:**
- Primary: `ip neigh` (modern Linux)
- Fallback: `arp -n` (older systems)

**Windows:**
- `arp -a`

### MAC Address Format

MAC addresses are normalized to uppercase colon-separated format:
- Input: `00-11-22-33-44-55` or `00:11:22:33:44:55`
- Stored: `00:11:22:33:44:55`

### Host Configuration Schema

```json
{
  "hostname": {
    "host": "192.168.1.10",
    "user": "admin",
    "mac": "00:11:22:33:44:55"
  }
}
```

### API Routes

- `GET /hosts/detect_mac/<name>` - Detect MAC address for a host
- `GET /hosts/scan_ip_changes` - Scan all hosts for IP changes
- `GET /hosts/arp_table` - View current ARP table

## Use Cases

### DHCP Environments

In networks where hosts receive dynamic IP addresses via DHCP:
1. Add hosts with their current IP addresses
2. Detect or manually enter MAC addresses
3. Periodically scan for IP changes
4. Host configurations stay up-to-date automatically

### Mixed Static/Dynamic Networks

- Static hosts: Don't add MAC address (IP won't change)
- Dynamic hosts: Add MAC address for IP change detection
- The system handles both types seamlessly

### Network Troubleshooting

- Use the ARP table viewer to see which devices are currently reachable
- Verify that hosts are responding on the network
- Debug connectivity issues before running updates

## Security Considerations

- **Permissions**: Only operators and admins can detect MACs or scan for IP changes
- **Network Access**: The system must be on the same network segment to see ARP entries
- **ARP Spoofing**: MAC addresses can be spoofed; use in trusted networks only
- **Privacy**: ARP tables reveal network topology; restrict access appropriately

## Limitations

- **Same Network Segment**: ARP only works for devices on the same local network
- **ARP Cache Timeout**: Entries expire after inactivity (typically 2-5 minutes)
- **Router Boundaries**: Cannot detect IPs across routers/subnets
- **Windows Limitations**: Windows systems may have stricter ARP cache policies

## Troubleshooting

### "Could not detect MAC address"

**Causes:**
- Host is offline or unreachable
- Host is on a different subnet
- Firewall blocks ICMP (ping) packets
- ARP cache timeout

**Solutions:**
1. Verify the host is online and reachable
2. Ensure the host is on the same network segment
3. Check firewall rules allow ICMP
4. Try pinging the host manually first
5. Manually enter the MAC address if automatic detection fails

### "No IP changes detected"

**Causes:**
- No hosts have MAC addresses configured
- Hosts are offline
- IP addresses haven't actually changed
- ARP cache doesn't contain the hosts

**Solutions:**
1. Add MAC addresses to hosts
2. Ensure hosts are online
3. Ping hosts to populate the ARP cache
4. Wait for network activity to update ARP table

### MAC Address Formats

The system accepts these formats:
- ✅ `00:11:22:33:44:55` (preferred)
- ✅ `00-11-22-33-44-55`
- ✅ `aa:bb:cc:dd:ee:ff` (lowercase)
- ❌ `00112233445` (no separators)
- ❌ `0:1:2:3:4:5` (single digits)

## Examples

### Example 1: Home Lab with DHCP

```json
{
  "server1": {
    "host": "192.168.1.100",
    "user": "admin",
    "mac": "52:54:00:12:34:56"
  },
  "workstation": {
    "host": "192.168.1.101",
    "user": "user",
    "mac": "52:54:00:AB:CD:EF"
  }
}
```

1. Server1 gets new IP `192.168.1.105` from DHCP
2. Click "Scan for IP Changes"
3. System detects change: `192.168.1.100 → 192.168.1.105`
4. Host configuration automatically updated

### Example 2: Mixed Environment

```json
{
  "static-server": {
    "host": "10.0.0.10",
    "user": "root"
  },
  "dhcp-laptop": {
    "host": "10.0.0.50",
    "user": "admin",
    "mac": "00:11:22:33:44:55"
  }
}
```

- Static server: No MAC address, IP never changes
- DHCP laptop: Has MAC address, IP change detection enabled

## Future Enhancements

Potential improvements for future versions:

- **Automatic Scanning**: Background task to periodically scan for IP changes
- **Notification System**: Email alerts when IP changes are detected
- **History Tracking**: Log of all IP changes with timestamps
- **Network Discovery**: Scan entire subnet to discover new devices
- **DHCP Integration**: Direct integration with DHCP server logs
- **Multi-Subnet Support**: Track hosts across multiple network segments
