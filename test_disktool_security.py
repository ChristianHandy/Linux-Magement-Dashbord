#!/usr/bin/env python3
"""
Test script for disktool_core security features
Tests the fix for command injection vulnerability at line 80
"""
import sys
import os

# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import disktool_core


def test_run_function_requires_list():
    """Test that run() function only accepts lists"""
    print("Testing run() requires list input...")
    
    # Test that string commands are rejected
    try:
        disktool_core.run("ls -la")
        assert False, "Should have raised ValueError for string command"
    except ValueError as e:
        assert "must be a list" in str(e)
        print("✓ String commands are rejected")
    
    # Test that valid list commands work
    try:
        result = disktool_core.run(['echo', 'test'])
        print("✓ List commands are accepted")
    except Exception as e:
        print(f"✗ Valid list command failed: {e}")
        return False
    
    return True


def test_run_function_validates_empty_list():
    """Test that run() rejects empty command lists"""
    print("\nTesting run() rejects empty lists...")
    
    try:
        disktool_core.run([])
        assert False, "Should have raised ValueError for empty list"
    except ValueError as e:
        assert "cannot be empty" in str(e)
        print("✓ Empty command lists are rejected")
        return True
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


def test_run_function_validates_argument_types():
    """Test that run() validates all arguments are strings"""
    print("\nTesting run() validates argument types...")
    
    # Test with non-string arguments
    try:
        disktool_core.run(['ls', 123])
        assert False, "Should have raised ValueError for non-string argument"
    except ValueError as e:
        assert "must be strings" in str(e)
        print("✓ Non-string arguments are rejected")
        return True
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


def test_run_function_validates_executable():
    """Test that run() validates the command executable"""
    print("\nTesting run() validates executable...")
    
    # Test with shell metacharacters
    dangerous_commands = [
        ['ls;rm -rf /'],
        ['ls|cat'],
        ['ls&whoami'],
        ['ls$(whoami)'],
        ['ls`whoami`'],
        ['../../../etc/passwd'],
        ['ls\x00'],  # null byte
    ]
    
    for cmd in dangerous_commands:
        try:
            disktool_core.run(cmd)
            print(f"✗ Dangerous command accepted: {cmd}")
            return False
        except ValueError as e:
            assert "Invalid command executable" in str(e)
    
    print("✓ Dangerous executables are rejected")
    return True


def test_sanitize_device_name():
    """Test that sanitize_device_name works correctly"""
    print("\nTesting sanitize_device_name()...")
    
    # Test valid device names
    valid_names = ['sda', 'sdb1', 'nvme0n1', 'mmcblk0', 'loop0']
    for name in valid_names:
        try:
            result = disktool_core.sanitize_device_name(name)
            assert result == name
        except Exception as e:
            print(f"✗ Valid device name rejected: {name} - {e}")
            return False
    
    print("✓ Valid device names accepted")
    
    # Test invalid device names
    invalid_names = [
        '../etc/passwd',
        'sda;rm -rf /',
        'sda|cat',
        'sda&whoami',
        'sda$(whoami)',
        'sda`whoami`',
        '/dev/sda',
        'sda\x00',
        '',
        None,
    ]
    
    for name in invalid_names:
        try:
            disktool_core.sanitize_device_name(name)
            print(f"✗ Invalid device name accepted: {name}")
            return False
        except (ValueError, Exception):
            pass
    
    print("✓ Invalid device names rejected")
    return True


def test_subprocess_shell_false():
    """Test that subprocess.run is called with shell=False"""
    print("\nTesting subprocess.run uses shell=False...")
    
    import inspect
    
    # Get the source code of the run function
    source = inspect.getsource(disktool_core.run)
    
    # Check that shell=False is explicitly set
    if 'shell=False' in source:
        print("✓ subprocess.run explicitly uses shell=False")
        return True
    else:
        print("✗ subprocess.run does not explicitly set shell=False")
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("Disktool Core Security Test Suite")
    print("=" * 60)
    
    tests = [
        test_run_function_requires_list,
        test_run_function_validates_empty_list,
        test_run_function_validates_argument_types,
        test_run_function_validates_executable,
        test_sanitize_device_name,
        test_subprocess_shell_false,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)
    
    if all(results):
        print("\n✓ All security tests passed!")
        return 0
    else:
        print("\n✗ Some security tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
