#!/usr/bin/env python3
"""
Test script for localhost support in the Linux Management Dashboard.
This verifies that localhost detection and handling works correctly.
"""

import sys
import os

# Add parent directory to path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from constants import is_localhost

def test_is_localhost():
    """Test the is_localhost function"""
    print("Testing is_localhost function...")
    
    # Test cases that should return True
    localhost_values = ['localhost', 'LOCALHOST', 'Localhost', '127.0.0.1', '::1', '0.0.0.0']
    for value in localhost_values:
        result = is_localhost(value)
        status = "✓" if result else "✗"
        print(f"  {status} is_localhost('{value}') = {result} (expected True)")
        if not result:
            print(f"    ERROR: Expected True but got False")
            return False
    
    # Test cases that should return False
    remote_values = ['192.168.1.1', 'example.com', 'remote-server', '10.0.0.1']
    for value in remote_values:
        result = is_localhost(value)
        status = "✓" if not result else "✗"
        print(f"  {status} is_localhost('{value}') = {result} (expected False)")
        if result:
            print(f"    ERROR: Expected False but got True")
            return False
    
    print("✓ All is_localhost tests passed!\n")
    return True

def test_imports():
    """Test that all necessary imports work"""
    print("Testing imports...")
    try:
        import updater
        import app
        print("✓ All imports successful!\n")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}\n")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing localhost support for Linux Management Dashboard")
    print("=" * 60 + "\n")
    
    all_passed = True
    
    # Test imports
    if not test_imports():
        all_passed = False
    
    # Test localhost detection
    if not test_is_localhost():
        all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("✓ All tests passed!")
        print("=" * 60)
        return 0
    else:
        print("✗ Some tests failed!")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
