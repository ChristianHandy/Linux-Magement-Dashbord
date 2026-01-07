#!/usr/bin/env python3
"""
Test script to verify the /addons/ to /disks/addons/ redirect fix
Tests that addon paths without /disks prefix redirect correctly
"""
import sys
import os

# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_addon_redirect_unauthenticated():
    """Test that /addons/ paths redirect even without authentication"""
    print("Testing /addons/ redirect for unauthenticated users...")
    try:
        from app import app
        
        with app.test_client() as client:
            # Test redirect without authentication
            response = client.get('/addons/example_plugin/zd320', follow_redirects=False)
            print(f"  Status code: {response.status_code}")
            
            # Should be 302 (redirect to login)
            if response.status_code == 302:
                location = response.headers.get('Location', '')
                print(f"  Redirects to: {location}")
                # Should redirect to login with next parameter
                if 'login' in location.lower() or location.startswith('/?next='):
                    print("✓ Correctly redirects to login")
                    return True
                else:
                    print(f"✗ Unexpected redirect location: {location}")
                    return False
            else:
                print(f"✗ Expected 302 redirect, got {response.status_code}")
                return False
                
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_addon_redirect_authenticated():
    """Test that /addons/ paths redirect to /disks/addons/ when authenticated"""
    print("\nTesting /addons/ redirect for authenticated users...")
    try:
        from app import app
        import user_management
        
        # Initialize the database
        user_management.init_user_db()
        
        with app.test_client() as client:
            # Create a test admin user
            user_id = user_management.create_user('testredruser', 'testpass', None, ['admin'])
            if not user_id:
                # User might already exist, try to get it
                user_id = user_management.verify_password('testredruser', 'testpass')
            
            # Login
            with client.session_transaction() as sess:
                sess['user_id'] = user_id
                sess['username'] = 'testredruser'
                sess['login'] = True
            
            # Test redirect when authenticated
            response = client.get('/addons/example_plugin/zd320', follow_redirects=False)
            print(f"  Status code: {response.status_code}")
            
            if response.status_code == 302:
                location = response.headers.get('Location', '')
                print(f"  Redirects to: {location}")
                
                # Should redirect to /disks/addons/...
                if location == '/disks/addons/example_plugin/zd320':
                    print("✓ Correctly redirects to /disks/addons/ path")
                    
                    # Follow the redirect and verify we reach the page
                    response = client.get('/addons/example_plugin/zd320', follow_redirects=True)
                    if response.status_code == 200:
                        print("✓ Successfully reaches the plugin page after redirect")
                        return True
                    else:
                        print(f"✗ Expected 200 after redirect, got {response.status_code}")
                        return False
                else:
                    print(f"✗ Expected redirect to /disks/addons/..., got {location}")
                    return False
            else:
                print(f"✗ Expected 302 redirect, got {response.status_code}")
                return False
                
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_original_path_still_works():
    """Test that original /disks/addons/ path still works"""
    print("\nTesting that original /disks/addons/ path still works...")
    try:
        from app import app
        
        with app.test_client() as client:
            # Test original path
            response = client.get('/disks/addons/example_plugin/zd320', follow_redirects=False)
            print(f"  Status code: {response.status_code}")
            
            # Should be 302 (redirect to login) not 404
            if response.status_code == 302:
                location = response.headers.get('Location', '')
                print(f"  Redirects to: {location}")
                if 'login' in location.lower() or location.startswith('/?next='):
                    print("✓ Original path still works correctly")
                    return True
                else:
                    print(f"✗ Unexpected redirect: {location}")
                    return False
            elif response.status_code == 404:
                print("✗ Original path returns 404 - this is broken!")
                return False
            else:
                print(f"✗ Unexpected status code: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_no_404_for_addon_paths():
    """Test that we no longer get 404 for /addons/ paths"""
    print("\nTesting that /addons/ paths no longer return 404...")
    try:
        from app import app
        
        with app.test_client() as client:
            # Test that we don't get 404
            response = client.get('/addons/example_plugin/zd320', follow_redirects=False)
            print(f"  Status code: {response.status_code}")
            
            if response.status_code == 404:
                print("✗ Still getting 404 - fix didn't work!")
                return False
            elif response.status_code == 302:
                print("✓ No 404 error - redirect is working")
                return True
            else:
                print(f"✓ No 404 error - got {response.status_code}")
                return True
                
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("=" * 70)
    print("Addon Redirect Fix Verification Test Suite")
    print("=" * 70)
    
    tests = [
        test_addon_redirect_unauthenticated,
        test_addon_redirect_authenticated,
        test_original_path_still_works,
        test_no_404_for_addon_paths,
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
    
    print("\n" + "=" * 70)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 70)
    
    if all(results):
        print("\n✓ All tests passed! The addon redirect fix is working correctly.")
        return 0
    else:
        print("\n✗ Some tests failed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
