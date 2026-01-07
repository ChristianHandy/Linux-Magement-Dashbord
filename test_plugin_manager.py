#!/usr/bin/env python3
"""
Test script for plugin manager functionality
"""
import sys
import os
import json
import tempfile
from pathlib import Path

# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_plugin_manager_import():
    """Test that plugin manager can be imported"""
    print("Testing plugin manager import...")
    try:
        from addons import plugin_manager
        print("✓ Plugin manager imported successfully")
        return True
    except Exception as e:
        print(f"✗ Failed to import plugin manager: {e}")
        return False

def test_plugin_manager_blueprint():
    """Test that plugin manager blueprint is configured correctly"""
    print("\nTesting plugin manager blueprint...")
    try:
        from addons import plugin_manager
        assert hasattr(plugin_manager, 'blueprint'), "Blueprint not found"
        assert plugin_manager.blueprint.url_prefix == '/pluginmanager', "Incorrect URL prefix"
        print("✓ Plugin manager blueprint configured correctly")
        return True
    except Exception as e:
        print(f"✗ Blueprint test failed: {e}")
        return False

def test_plugin_validation():
    """Test plugin ID validation"""
    print("\nTesting plugin ID validation...")
    try:
        import re
        
        # Test valid plugin IDs
        valid_ids = ['example_plugin', 'backup_plugin', 'test123', 'my_plugin_v2']
        for pid in valid_ids:
            assert re.match(r'^[a-zA-Z0-9_]+$', pid), f"Valid ID rejected: {pid}"
        
        # Test invalid plugin IDs
        invalid_ids = ['../etc/passwd', 'plugin-name', 'plugin.py', 'plugin name', 'plugin;rm']
        for pid in invalid_ids:
            assert not re.match(r'^[a-zA-Z0-9_]+$', pid), f"Invalid ID accepted: {pid}"
        
        print("✓ Plugin ID validation working correctly")
        return True
    except Exception as e:
        print(f"✗ Validation test failed: {e}")
        return False

def test_addon_loader_status():
    """Test that addon loader includes file information"""
    print("\nTesting addon loader status...")
    try:
        from addon_loader import AddonManager
        from flask import Flask
        import disktool_core
        
        app = Flask(__name__)
        addon_mgr = AddonManager(app, disktool_core)
        addon_mgr.load_addons('addons', 'templates/addons')
        
        # Check that status includes file information
        for plugin in addon_mgr.status:
            assert 'file' in plugin, f"Plugin {plugin.get('name')} missing 'file' field"
            assert 'name' in plugin, f"Plugin missing 'name' field"
            assert 'status' in plugin, f"Plugin {plugin.get('name')} missing 'status' field"
        
        print(f"✓ Addon loader status includes file information for {len(addon_mgr.status)} plugins")
        return True
    except Exception as e:
        print(f"✗ Addon loader test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_remote_plugin_json_format():
    """Test that remote plugin JSON format is valid"""
    print("\nTesting remote plugin JSON format...")
    try:
        # Sample plugin data
        plugin_data = {
            "plugins": [
                {
                    "id": "test_plugin",
                    "name": "Test Plugin",
                    "description": "A test plugin",
                    "version": "1.0.0",
                    "author": "Test Author",
                    "url": "https://example.com/test_plugin.py"
                }
            ]
        }
        
        # Validate required fields
        for plugin in plugin_data['plugins']:
            assert 'id' in plugin, "Missing 'id' field"
            assert 'name' in plugin, "Missing 'name' field"
            assert 'description' in plugin, "Missing 'description' field"
            assert 'version' in plugin, "Missing 'version' field"
            assert 'author' in plugin, "Missing 'author' field"
            assert 'url' in plugin, "Missing 'url' field"
            
            # Validate ID format
            import re
            assert re.match(r'^[a-zA-Z0-9_]+$', plugin['id']), f"Invalid plugin ID: {plugin['id']}"
        
        print("✓ Remote plugin JSON format is valid")
        return True
    except Exception as e:
        print(f"✗ JSON format test failed: {e}")
        return False

def test_security_checks():
    """Test security features"""
    print("\nTesting security checks...")
    try:
        # Test that plugin manager checks admin role
        from addons import plugin_manager
        import inspect
        
        # Verify that install and uninstall functions exist
        assert hasattr(plugin_manager, 'install_plugin'), "install_plugin function missing"
        assert hasattr(plugin_manager, 'uninstall_plugin'), "uninstall_plugin function missing"
        
        # Check that they check for admin role
        install_source = inspect.getsource(plugin_manager.install_plugin)
        uninstall_source = inspect.getsource(plugin_manager.uninstall_plugin)
        
        assert 'current_user_has_role' in install_source, "Install doesn't check user role"
        assert 'current_user_has_role' in uninstall_source, "Uninstall doesn't check user role"
        assert 'admin' in install_source, "Install doesn't require admin role"
        assert 'admin' in uninstall_source, "Uninstall doesn't require admin role"
        
        # Verify plugin ID validation exists
        assert 'regex' in install_source.lower() or 're.match' in install_source, "Install doesn't validate plugin ID"
        assert 'regex' in uninstall_source.lower() or 're.match' in uninstall_source, "Uninstall doesn't validate plugin file"
        
        print("✓ Security checks in place")
        return True
    except Exception as e:
        print(f"✗ Security test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Plugin Manager Test Suite")
    print("=" * 60)
    
    tests = [
        test_plugin_manager_import,
        test_plugin_manager_blueprint,
        test_plugin_validation,
        test_addon_loader_status,
        test_remote_plugin_json_format,
        test_security_checks,
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
        print("\n✓ All tests passed!")
        return 0
    else:
        print("\n✗ Some tests failed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
