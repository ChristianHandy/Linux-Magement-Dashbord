"""
Test suite for ARP tracker functionality
Tests MAC address detection, IP change detection, and ARP table parsing
"""

import unittest
from unittest.mock import patch, MagicMock
import arp_tracker


class TestArpTracker(unittest.TestCase):
    """Test cases for arp_tracker module"""
    
    def test_normalize_mac_address(self):
        """Test MAC address normalization"""
        # Test with colons
        self.assertEqual(
            arp_tracker.normalize_mac_address('00:11:22:33:44:55'),
            '00:11:22:33:44:55'
        )
        
        # Test with hyphens
        self.assertEqual(
            arp_tracker.normalize_mac_address('00-11-22-33-44-55'),
            '00:11:22:33:44:55'
        )
        
        # Test with lowercase
        self.assertEqual(
            arp_tracker.normalize_mac_address('aa:bb:cc:dd:ee:ff'),
            'AA:BB:CC:DD:EE:FF'
        )
        
        # Test with mixed separators
        self.assertEqual(
            arp_tracker.normalize_mac_address('aa-BB:cc-DD:ee-FF'),
            'AA:BB:CC:DD:EE:FF'
        )
        
        # Test invalid MAC address
        with self.assertRaises(ValueError):
            arp_tracker.normalize_mac_address('invalid')
        
        with self.assertRaises(ValueError):
            arp_tracker.normalize_mac_address('00:11:22:33:44')  # Too short
    
    def test_detect_ip_changes_no_mac(self):
        """Test IP change detection with hosts without MAC addresses"""
        hosts = {
            'host1': {'host': '192.168.1.10', 'user': 'admin'}
        }
        arp_mappings = {
            '00:11:22:33:44:55': '192.168.1.10'
        }
        
        changes = arp_tracker.detect_ip_changes(hosts, arp_mappings)
        self.assertEqual(len(changes), 0)
    
    def test_detect_ip_changes_with_change(self):
        """Test IP change detection when IP has changed"""
        hosts = {
            'host1': {
                'host': '192.168.1.10',
                'user': 'admin',
                'mac': '00:11:22:33:44:55'
            }
        }
        arp_mappings = {
            '00:11:22:33:44:55': '192.168.1.20'  # Changed IP
        }
        
        changes = arp_tracker.detect_ip_changes(hosts, arp_mappings)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0], ('host1', '192.168.1.10', '192.168.1.20'))
    
    def test_detect_ip_changes_no_change(self):
        """Test IP change detection when IP has not changed"""
        hosts = {
            'host1': {
                'host': '192.168.1.10',
                'user': 'admin',
                'mac': '00:11:22:33:44:55'
            }
        }
        arp_mappings = {
            '00:11:22:33:44:55': '192.168.1.10'  # Same IP
        }
        
        changes = arp_tracker.detect_ip_changes(hosts, arp_mappings)
        self.assertEqual(len(changes), 0)
    
    def test_detect_ip_changes_mac_not_in_arp(self):
        """Test IP change detection when MAC is not in ARP table"""
        hosts = {
            'host1': {
                'host': '192.168.1.10',
                'user': 'admin',
                'mac': '00:11:22:33:44:55'
            }
        }
        arp_mappings = {
            'AA:BB:CC:DD:EE:FF': '192.168.1.20'  # Different MAC
        }
        
        changes = arp_tracker.detect_ip_changes(hosts, arp_mappings)
        self.assertEqual(len(changes), 0)
    
    def test_detect_ip_changes_multiple_hosts(self):
        """Test IP change detection with multiple hosts"""
        hosts = {
            'host1': {
                'host': '192.168.1.10',
                'user': 'admin',
                'mac': '00:11:22:33:44:55'
            },
            'host2': {
                'host': '192.168.1.20',
                'user': 'admin',
                'mac': 'AA:BB:CC:DD:EE:FF'
            },
            'host3': {
                'host': '192.168.1.30',
                'user': 'admin',
                'mac': '11:22:33:44:55:66'
            }
        }
        arp_mappings = {
            '00:11:22:33:44:55': '192.168.1.15',  # Changed
            'AA:BB:CC:DD:EE:FF': '192.168.1.20',  # Same
            '11:22:33:44:55:66': '192.168.1.35'   # Changed
        }
        
        changes = arp_tracker.detect_ip_changes(hosts, arp_mappings)
        self.assertEqual(len(changes), 2)
        
        # Check that both changes were detected
        change_dict = {hostname: (old_ip, new_ip) for hostname, old_ip, new_ip in changes}
        self.assertIn('host1', change_dict)
        self.assertIn('host3', change_dict)
        self.assertEqual(change_dict['host1'], ('192.168.1.10', '192.168.1.15'))
        self.assertEqual(change_dict['host3'], ('192.168.1.30', '192.168.1.35'))
    
    def test_update_host_ips(self):
        """Test updating host IPs"""
        hosts = {
            'host1': {
                'host': '192.168.1.10',
                'user': 'admin',
                'mac': '00:11:22:33:44:55'
            },
            'host2': {
                'host': '192.168.1.20',
                'user': 'admin',
                'mac': 'AA:BB:CC:DD:EE:FF'
            }
        }
        
        changes = [
            ('host1', '192.168.1.10', '192.168.1.15'),
            ('host2', '192.168.1.20', '192.168.1.25')
        ]
        
        updated_hosts = arp_tracker.update_host_ips(hosts, changes)
        
        self.assertEqual(updated_hosts['host1']['host'], '192.168.1.15')
        self.assertEqual(updated_hosts['host2']['host'], '192.168.1.25')
        
        # Ensure original data is preserved
        self.assertEqual(updated_hosts['host1']['user'], 'admin')
        self.assertEqual(updated_hosts['host1']['mac'], '00:11:22:33:44:55')
    
    @patch('subprocess.run')
    def test_ping_host_success(self, mock_run):
        """Test successful ping"""
        mock_run.return_value = MagicMock(returncode=0)
        
        result = arp_tracker.ping_host('192.168.1.10')
        self.assertTrue(result)
        
        # Verify subprocess.run was called
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_ping_host_failure(self, mock_run):
        """Test failed ping"""
        mock_run.return_value = MagicMock(returncode=1)
        
        result = arp_tracker.ping_host('192.168.1.10')
        self.assertFalse(result)
    
    @patch('subprocess.run')
    def test_get_arp_table_linux(self, mock_run):
        """Test ARP table retrieval on Linux"""
        # Mock 'ip neigh' output
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='192.168.1.10 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE\n'
                   '192.168.1.20 dev eth0 lladdr aa:bb:cc:dd:ee:ff STALE\n'
        )
        
        with patch('platform.system', return_value='Linux'):
            arp_table = arp_tracker.get_arp_table()
        
        self.assertEqual(len(arp_table), 2)
        self.assertEqual(arp_table['00:11:22:33:44:55'], '192.168.1.10')
        self.assertEqual(arp_table['AA:BB:CC:DD:EE:FF'], '192.168.1.20')
    
    def test_get_mac_address_for_ip(self):
        """Test MAC address lookup by IP"""
        with patch('arp_tracker.get_arp_table') as mock_get_arp:
            mock_get_arp.return_value = {
                '00:11:22:33:44:55': '192.168.1.10',
                'AA:BB:CC:DD:EE:FF': '192.168.1.20'
            }
            
            mac = arp_tracker.get_mac_address_for_ip('192.168.1.10')
            self.assertEqual(mac, '00:11:22:33:44:55')
            
            mac = arp_tracker.get_mac_address_for_ip('192.168.1.20')
            self.assertEqual(mac, 'AA:BB:CC:DD:EE:FF')
            
            mac = arp_tracker.get_mac_address_for_ip('192.168.1.30')
            self.assertIsNone(mac)


if __name__ == '__main__':
    unittest.main()
