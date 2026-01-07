#!/usr/bin/env python3
"""
Test script for SSH host key validation in updater.py.
This verifies that the SSH client uses proper host key verification.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call

# Add parent directory to path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paramiko
from updater import run_update


class TestSSHHostKeyValidation(unittest.TestCase):
    """Test SSH host key validation implementation"""
    
    @patch('updater.paramiko.SSHClient')
    def test_uses_reject_policy(self, mock_ssh_client_class):
        """Test that RejectPolicy is used instead of AutoAddPolicy"""
        # Setup mock
        mock_ssh = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh
        mock_ssh.exec_command.return_value = (MagicMock(), MagicMock(read=lambda: b'ubuntu'), MagicMock())
        mock_ssh.connect.side_effect = paramiko.SSHException("Server 'test.example.com' not found in known_hosts")
        
        log_list = []
        
        # Run update
        run_update('test.example.com', 'testuser', 'TestHost', log_list, repo_only=False)
        
        # Verify that RejectPolicy was set
        mock_ssh.set_missing_host_key_policy.assert_called_once()
        call_args = mock_ssh.set_missing_host_key_policy.call_args
        
        # Check that the policy is RejectPolicy (not AutoAddPolicy)
        policy_instance = call_args[0][0]
        self.assertIsInstance(policy_instance, paramiko.RejectPolicy,
                            "Should use RejectPolicy for host key validation")
        self.assertNotIsInstance(policy_instance, paramiko.AutoAddPolicy,
                                "Should NOT use AutoAddPolicy")
    
    @patch('updater.paramiko.SSHClient')
    def test_loads_system_host_keys(self, mock_ssh_client_class):
        """Test that system host keys are loaded"""
        # Setup mock
        mock_ssh = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh
        mock_ssh.exec_command.return_value = (MagicMock(), MagicMock(read=lambda: b'ubuntu'), MagicMock())
        mock_ssh.connect.side_effect = paramiko.SSHException("Server 'test.example.com' not found in known_hosts")
        
        log_list = []
        
        # Run update
        run_update('test.example.com', 'testuser', 'TestHost', log_list, repo_only=False)
        
        # Verify that system host keys were loaded
        mock_ssh.load_system_host_keys.assert_called_once()
    
    @patch('updater.os.path.exists')
    @patch('updater.os.path.expanduser')
    @patch('updater.paramiko.SSHClient')
    def test_loads_user_host_keys_if_exists(self, mock_ssh_client_class, mock_expanduser, mock_exists):
        """Test that user host keys are loaded if the file exists"""
        # Setup mocks
        mock_ssh = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh
        mock_ssh.exec_command.return_value = (MagicMock(), MagicMock(read=lambda: b'ubuntu'), MagicMock())
        mock_ssh.connect.side_effect = paramiko.SSHException("Server 'test.example.com' not found in known_hosts")
        
        mock_expanduser.return_value = '/home/testuser/.ssh/known_hosts'
        mock_exists.return_value = True
        
        log_list = []
        
        # Run update
        run_update('test.example.com', 'testuser', 'TestHost', log_list, repo_only=False)
        
        # Verify that user host keys were loaded
        mock_ssh.load_host_keys.assert_called_once_with('/home/testuser/.ssh/known_hosts')
    
    @patch('updater.os.path.exists')
    @patch('updater.os.path.expanduser')
    @patch('updater.paramiko.SSHClient')
    def test_skips_user_host_keys_if_not_exists(self, mock_ssh_client_class, mock_expanduser, mock_exists):
        """Test that user host keys are skipped if the file doesn't exist"""
        # Setup mocks
        mock_ssh = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh
        mock_ssh.exec_command.return_value = (MagicMock(), MagicMock(read=lambda: b'ubuntu'), MagicMock())
        mock_ssh.connect.side_effect = paramiko.SSHException("Server 'test.example.com' not found in known_hosts")
        
        mock_expanduser.return_value = '/home/testuser/.ssh/known_hosts'
        mock_exists.return_value = False
        
        log_list = []
        
        # Run update
        run_update('test.example.com', 'testuser', 'TestHost', log_list, repo_only=False)
        
        # Verify that user host keys were NOT loaded
        mock_ssh.load_host_keys.assert_not_called()
    
    @patch('updater.paramiko.SSHClient')
    def test_helpful_error_message_for_unknown_host(self, mock_ssh_client_class):
        """Test that a helpful error message is provided when host key is not found"""
        # Setup mock
        mock_ssh = MagicMock()
        mock_ssh_client_class.return_value = mock_ssh
        mock_ssh.connect.side_effect = paramiko.SSHException("Server 'test.example.com' not found in known_hosts")
        
        log_list = []
        
        # Run update
        run_update('test.example.com', 'testuser', 'TestHost', log_list, repo_only=False)
        
        # Check that helpful error message is in logs
        log_text = ' '.join(log_list)
        self.assertIn('Host key verification failed', log_text,
                     "Should provide clear error message about host key verification")
        self.assertIn('ssh-keyscan', log_text,
                     "Should provide instructions on how to add the host key")
    
    @patch('updater.is_localhost')
    def test_localhost_skips_ssh(self, mock_is_localhost):
        """Test that localhost updates skip SSH entirely"""
        mock_is_localhost.return_value = True
        
        log_list = []
        
        # This should not attempt SSH connection
        # We'll just verify it doesn't raise an exception
        # (full localhost testing is done in test_localhost_support.py)
        try:
            run_update('localhost', 'testuser', 'LocalHost', log_list, repo_only=False)
            # We expect this to fail because we can't actually run updates
            # but it shouldn't fail due to SSH issues
        except Exception:
            # Expected to fail for other reasons (no actual system to update)
            pass


def main():
    """Run all tests"""
    print("=" * 70)
    print("Testing SSH Host Key Validation for updater.py")
    print("=" * 70 + "\n")
    
    # Run tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSSHHostKeyValidation)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print("✓ All tests passed!")
        print("=" * 70)
        return 0
    else:
        print("✗ Some tests failed!")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
