#!/usr/bin/env python3
"""
Test script for Windows support in the Linux Management Dashboard.
This verifies that Windows detection and update command generation works correctly.
"""

import sys
import os

# Add parent directory to path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from constants import is_windows, get_platform
from updater import get_update_command, SUPPORTED_DISTRIBUTIONS

def test_platform_detection():
    """Test platform detection functions"""
    print("Testing platform detection...")
    
    platform = get_platform()
    print(f"  Current platform: {platform}")
    
    is_win = is_windows()
    print(f"  Is Windows: {is_win}")
    
    print("✓ Platform detection functions work!\n")
    return True

def test_supported_distributions():
    """Test that Windows is in supported distributions"""
    print("Testing supported distributions...")
    
    if 'windows' in SUPPORTED_DISTRIBUTIONS:
        print(f"  ✓ 'windows' is in SUPPORTED_DISTRIBUTIONS: {SUPPORTED_DISTRIBUTIONS}")
    else:
        print(f"  ✗ 'windows' is NOT in SUPPORTED_DISTRIBUTIONS: {SUPPORTED_DISTRIBUTIONS}")
        return False
    
    print("✓ Windows is supported!\n")
    return True

def test_windows_update_commands():
    """Test Windows update command generation"""
    print("Testing Windows update commands...")
    
    try:
        # Test repository-only update (Windows Update only)
        cmd, desc = get_update_command('windows', repo_only=True)
        print(f"  Repository-only update:")
        print(f"    Description: {desc}")
        print(f"    Command starts with: {cmd[:80]}...")
        
        if 'powershell' not in cmd.lower():
            print("  ✗ ERROR: Windows command should use PowerShell")
            return False
        if 'Get-WindowsUpdate' not in cmd:
            print("  ✗ ERROR: Windows command should use Get-WindowsUpdate")
            return False
        
        print("  ✓ Repository-only command is correct")
        
        # Test full update (Windows Update + winget)
        cmd, desc = get_update_command('windows', repo_only=False)
        print(f"  Full update:")
        print(f"    Description: {desc}")
        print(f"    Command starts with: {cmd[:80]}...")
        
        if 'powershell' not in cmd.lower():
            print("  ✗ ERROR: Windows command should use PowerShell")
            return False
        if 'winget upgrade' not in cmd:
            print("  ✗ ERROR: Full update should include winget upgrade")
            return False
        
        print("  ✓ Full update command is correct")
        
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        return False
    
    print("✓ Windows update commands work correctly!\n")
    return True

def test_linux_distributions_still_work():
    """Test that existing Linux distributions still work"""
    print("Testing Linux distributions still work...")
    
    linux_distros = ['ubuntu', 'debian', 'fedora', 'centos', 'arch']
    
    for distro in linux_distros:
        try:
            cmd, desc = get_update_command(distro, repo_only=False)
            print(f"  ✓ {distro}: {desc}")
        except Exception as e:
            print(f"  ✗ {distro}: ERROR - {e}")
            return False
    
    print("✓ All Linux distributions still work!\n")
    return True

def test_unsupported_distribution():
    """Test that unsupported distributions raise ValueError"""
    print("Testing unsupported distribution handling...")
    
    try:
        cmd, desc = get_update_command('unsupported_os', repo_only=False)
        print("  ✗ ERROR: Should have raised ValueError for unsupported OS")
        return False
    except ValueError as e:
        print(f"  ✓ Correctly raised ValueError: {e}")
    except Exception as e:
        print(f"  ✗ ERROR: Unexpected exception: {e}")
        return False
    
    print("✓ Unsupported distribution handling works!\n")
    return True

def test_imports():
    """Test that all necessary imports work"""
    print("Testing imports...")
    try:
        import updater
        import constants
        print("✓ All imports successful!\n")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}\n")
        return False

def main():
    """Run all tests"""
    print("=" * 70)
    print("Testing Windows support for Linux Management Dashboard")
    print("=" * 70 + "\n")
    
    all_passed = True
    
    # Test imports
    if not test_imports():
        all_passed = False
    
    # Test platform detection
    if not test_platform_detection():
        all_passed = False
    
    # Test supported distributions
    if not test_supported_distributions():
        all_passed = False
    
    # Test Windows update commands
    if not test_windows_update_commands():
        all_passed = False
    
    # Test that Linux distributions still work
    if not test_linux_distributions_still_work():
        all_passed = False
    
    # Test unsupported distribution handling
    if not test_unsupported_distribution():
        all_passed = False
    
    print("=" * 70)
    if all_passed:
        print("✓ All tests passed!")
        print("=" * 70)
        return 0
    else:
        print("✗ Some tests failed!")
        print("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
