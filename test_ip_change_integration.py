"""
Integration test for IP change detection features
Tests the web routes and end-to-end functionality
"""

import unittest
import json
import os
import tempfile
from unittest.mock import patch, MagicMock
import sys

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app
import arp_tracker


class TestIpChangeDetectionIntegration(unittest.TestCase):
    """Integration tests for IP change detection features"""
    
    def setUp(self):
        """Set up test client and temporary files"""
        app.app.config['TESTING'] = True
        app.app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.app.test_client()
        
        # Create a temporary hosts.json file
        self.temp_hosts_fd, self.temp_hosts_path = tempfile.mkstemp(suffix='.json')
        
        # Store the original load_hosts and save_hosts functions
        self.original_load_hosts = app.load_hosts
        self.original_save_hosts = app.save_hosts
        
        # Replace with test versions
        def test_load_hosts():
            try:
                with open(self.temp_hosts_path, 'r') as f:
                    return json.load(f)
            except:
                return {}
        
        def test_save_hosts(hosts):
            with open(self.temp_hosts_path, 'w') as f:
                json.dump(hosts, f)
        
        app.load_hosts = test_load_hosts
        app.save_hosts = test_save_hosts
        
        # Initialize with empty hosts
        test_save_hosts({})
        
        # Log in for tests
        with self.client.session_transaction() as sess:
            sess['login'] = True
            sess['username'] = 'test'
    
    def tearDown(self):
        """Clean up temporary files"""
        os.close(self.temp_hosts_fd)
        os.unlink(self.temp_hosts_path)
        
        # Restore original functions
        app.load_hosts = self.original_load_hosts
        app.save_hosts = self.original_save_hosts
    
    def test_hosts_page_loads(self):
        """Test that hosts page loads successfully"""
        response = self.client.get('/hosts')
        self.assertEqual(response.status_code, 200)
    
    def test_add_host_with_mac(self):
        """Test adding a host with MAC address"""
        response = self.client.post('/hosts', data={
            'name': 'test-host',
            'host': '192.168.1.10',
            'user': 'admin',
            'mac': '00:11:22:33:44:55'
        }, follow_redirects=False)
        
        # Should redirect to /hosts
        self.assertEqual(response.status_code, 302)
        
        # Check that host was added
        hosts = app.load_hosts()
        self.assertIn('test-host', hosts)
        self.assertEqual(hosts['test-host']['host'], '192.168.1.10')
        self.assertEqual(hosts['test-host']['mac'], '00:11:22:33:44:55')
    
    def test_edit_host_with_mac(self):
        """Test editing a host to add MAC address"""
        # First, add a host without MAC
        app.save_hosts({
            'test-host': {
                'host': '192.168.1.10',
                'user': 'admin'
            }
        })
        
        # Edit to add MAC
        response = self.client.post('/hosts/edit/test-host', data={
            'name': 'test-host',
            'host': '192.168.1.10',
            'user': 'admin',
            'mac': '00:11:22:33:44:55'
        }, follow_redirects=False)
        
        # Check that MAC was added
        hosts = app.load_hosts()
        self.assertEqual(hosts['test-host']['mac'], '00:11:22:33:44:55')
    
    @patch('arp_tracker.get_arp_table')
    def test_scan_ip_changes_route(self, mock_get_arp_table):
        """Test the scan IP changes route"""
        # Set up test data
        app.save_hosts({
            'host1': {
                'host': '192.168.1.10',
                'user': 'admin',
                'mac': '00:11:22:33:44:55'
            }
        })
        
        # Mock ARP table with changed IP
        mock_get_arp_table.return_value = {
            '00:11:22:33:44:55': '192.168.1.20'
        }
        
        # Scan for changes
        response = self.client.get('/hosts/scan_ip_changes', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        
        # Check that IP was updated
        hosts = app.load_hosts()
        self.assertEqual(hosts['host1']['host'], '192.168.1.20')
    
    @patch('arp_tracker.ping_host')
    @patch('arp_tracker.get_mac_address_for_ip')
    def test_detect_mac_route(self, mock_get_mac, mock_ping):
        """Test the detect MAC address route"""
        # Set up test data
        app.save_hosts({
            'test-host': {
                'host': '192.168.1.10',
                'user': 'admin'
            }
        })
        
        # Mock successful ping and MAC detection
        mock_ping.return_value = True
        mock_get_mac.return_value = '00:11:22:33:44:55'
        
        # Detect MAC
        response = self.client.get('/hosts/detect_mac/test-host', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        
        # Check that MAC was added
        hosts = app.load_hosts()
        self.assertEqual(hosts['test-host']['mac'], '00:11:22:33:44:55')
    
    @patch('arp_tracker.get_arp_table')
    def test_arp_table_route(self, mock_get_arp_table):
        """Test the ARP table viewing route"""
        mock_get_arp_table.return_value = {
            '00:11:22:33:44:55': '192.168.1.10',
            'AA:BB:CC:DD:EE:FF': '192.168.1.20'
        }
        
        response = self.client.get('/hosts/arp_table')
        self.assertEqual(response.status_code, 200)
        
        # Check that ARP data is in response
        self.assertIn(b'00:11:22:33:44:55', response.data)
        self.assertIn(b'192.168.1.10', response.data)


if __name__ == '__main__':
    unittest.main()
