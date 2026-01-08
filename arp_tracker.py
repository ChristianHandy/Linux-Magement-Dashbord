"""
ARP Tracker Module - Track IP address changes using ARP tables and MAC addresses.

This module provides functionality to:
- Read ARP tables from the system
- Track MAC-to-IP mappings
- Detect IP address changes for known MAC addresses
- Automatically update host configurations when IPs change
"""

import subprocess
import re
import json
import logging
import platform
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


def get_arp_table() -> Dict[str, str]:
    """
    Retrieve the system ARP table and return MAC-to-IP mappings.
    
    Returns:
        dict: Dictionary mapping MAC addresses to IP addresses
              Example: {'00:11:22:33:44:55': '192.168.1.10'}
    """
    arp_mappings = {}
    system_platform = platform.system().lower()
    
    try:
        if system_platform == 'windows':
            # Windows: Use 'arp -a' command
            result = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=10)
            output = result.stdout
            
            # Parse Windows ARP output
            # Format: Internet Address    Physical Address      Type
            #         192.168.1.10        00-11-22-33-44-55     dynamic
            for line in output.split('\n'):
                # Match IP and MAC address patterns
                match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s+([\da-fA-F]{2}[-:][\da-fA-F]{2}[-:][\da-fA-F]{2}[-:][\da-fA-F]{2}[-:][\da-fA-F]{2}[-:][\da-fA-F]{2})', line)
                if match:
                    ip = match.group(1)
                    mac = match.group(2).replace('-', ':').upper()
                    arp_mappings[mac] = ip
        else:
            # Linux/Unix: Use 'arp -n' or 'ip neigh' command
            try:
                # Try 'ip neigh' first (more modern)
                result = subprocess.run(['ip', 'neigh'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                
                # Parse 'ip neigh' output
                # Format: 192.168.1.10 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE
                for line in output.split('\n'):
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s+.*\s+lladdr\s+([\da-fA-F]{2}:[\da-fA-F]{2}:[\da-fA-F]{2}:[\da-fA-F]{2}:[\da-fA-F]{2}:[\da-fA-F]{2})', line)
                    if match:
                        ip = match.group(1)
                        mac = match.group(2).upper()
                        arp_mappings[mac] = ip
            except (FileNotFoundError, subprocess.SubprocessError):
                # Fallback to 'arp -n' if 'ip neigh' is not available
                result = subprocess.run(['arp', '-n'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                
                # Parse 'arp -n' output
                # Format: Address    HWtype  HWaddress           Flags Mask   Iface
                #         192.168.1.10 ether   00:11:22:33:44:55   C            eth0
                for line in output.split('\n'):
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s+\S+\s+([\da-fA-F]{2}:[\da-fA-F]{2}:[\da-fA-F]{2}:[\da-fA-F]{2}:[\da-fA-F]{2}:[\da-fA-F]{2})', line)
                    if match:
                        ip = match.group(1)
                        mac = match.group(2).upper()
                        arp_mappings[mac] = ip
    
    except subprocess.TimeoutExpired:
        logger.error("Timeout while retrieving ARP table")
    except Exception as e:
        logger.error(f"Error retrieving ARP table: {e}")
    
    return arp_mappings


def normalize_mac_address(mac: str) -> str:
    """
    Normalize a MAC address to a consistent format (uppercase, colon-separated).
    
    Args:
        mac: MAC address in various formats (e.g., '00-11-22-33-44-55', '00:11:22:33:44:55')
    
    Returns:
        str: Normalized MAC address (e.g., '00:11:22:33:44:55')
    """
    # Remove any separators and convert to uppercase
    mac_clean = re.sub(r'[:-]', '', mac).upper()
    
    # Validate MAC address format (should be 12 hex characters)
    if not re.match(r'^[0-9A-F]{12}$', mac_clean):
        raise ValueError(f"Invalid MAC address format: {mac}")
    
    # Format as colon-separated pairs
    return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])


def detect_ip_changes(hosts: Dict[str, Dict], arp_mappings: Dict[str, str]) -> List[Tuple[str, str, str]]:
    """
    Detect IP address changes for hosts with known MAC addresses.
    
    Args:
        hosts: Dictionary of host configurations from hosts.json
               Format: {'hostname': {'host': 'IP', 'user': 'username', 'mac': 'MAC'}}
        arp_mappings: Dictionary of MAC-to-IP mappings from ARP table
    
    Returns:
        list: List of tuples (hostname, old_ip, new_ip) for hosts with changed IPs
    """
    changes = []
    
    for hostname, host_config in hosts.items():
        # Skip hosts without MAC addresses
        if 'mac' not in host_config or not host_config['mac']:
            continue
        
        try:
            # Normalize the MAC address
            mac = normalize_mac_address(host_config['mac'])
            
            # Check if this MAC address is in the ARP table
            if mac in arp_mappings:
                current_ip = arp_mappings[mac]
                configured_ip = host_config['host']
                
                # Check if the IP has changed
                if current_ip != configured_ip:
                    changes.append((hostname, configured_ip, current_ip))
                    logger.info(f"IP change detected for {hostname}: {configured_ip} -> {current_ip}")
        
        except ValueError as e:
            logger.warning(f"Invalid MAC address for host {hostname}: {e}")
            continue
    
    return changes


def update_host_ips(hosts: Dict[str, Dict], changes: List[Tuple[str, str, str]]) -> Dict[str, Dict]:
    """
    Update host IP addresses based on detected changes.
    
    Args:
        hosts: Dictionary of host configurations
        changes: List of tuples (hostname, old_ip, new_ip)
    
    Returns:
        dict: Updated hosts dictionary
    """
    updated_hosts = hosts.copy()
    
    for hostname, old_ip, new_ip in changes:
        if hostname in updated_hosts:
            updated_hosts[hostname]['host'] = new_ip
            logger.info(f"Updated IP for {hostname}: {old_ip} -> {new_ip}")
    
    return updated_hosts


def get_mac_address_for_ip(ip: str) -> Optional[str]:
    """
    Get the MAC address for a given IP address from the ARP table.
    
    Args:
        ip: IP address to lookup
    
    Returns:
        str: MAC address if found, None otherwise
    """
    arp_mappings = get_arp_table()
    
    # Reverse lookup: find MAC for the given IP
    for mac, mapped_ip in arp_mappings.items():
        if mapped_ip == ip:
            return mac
    
    return None


def ping_host(ip: str) -> bool:
    """
    Ping a host to populate the ARP table.
    
    Args:
        ip: IP address to ping
    
    Returns:
        bool: True if ping successful, False otherwise
    """
    system_platform = platform.system().lower()
    
    try:
        if system_platform == 'windows':
            # Windows: ping -n 1
            result = subprocess.run(['ping', '-n', '1', '-w', '1000', ip], 
                                    capture_output=True, timeout=5)
        else:
            # Linux/Unix: ping -c 1
            result = subprocess.run(['ping', '-c', '1', '-W', '1', ip], 
                                    capture_output=True, timeout=5)
        
        return result.returncode == 0
    
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"Ping failed for {ip}: {e}")
        return False


def scan_network_for_mac(mac: str, network_prefix: str = "192.168.1") -> Optional[str]:
    """
    Scan a network range to find a host with a specific MAC address.
    
    Args:
        mac: MAC address to search for (normalized format)
        network_prefix: Network prefix to scan (e.g., "192.168.1")
    
    Returns:
        str: IP address if found, None otherwise
    """
    logger.info(f"Scanning network {network_prefix}.0/24 for MAC {mac}")
    
    # Ping all hosts in the range to populate ARP table
    for i in range(1, 255):
        ip = f"{network_prefix}.{i}"
        ping_host(ip)
    
    # Check ARP table for the MAC address
    arp_mappings = get_arp_table()
    
    try:
        normalized_mac = normalize_mac_address(mac)
        if normalized_mac in arp_mappings:
            return arp_mappings[normalized_mac]
    except ValueError:
        pass
    
    return None
