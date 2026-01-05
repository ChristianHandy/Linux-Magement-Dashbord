#!/usr/bin/env python3
"""
Test script for user management functionality
"""
import sys
import user_management

def test_user_creation():
    """Test creating users with different roles"""
    print("Testing user creation...")
    
    # Clean up test users if they exist
    existing = user_management.get_user('testadmin')
    if existing:
        user_management.delete_user(existing['id'])
    
    existing = user_management.get_user('testoperator')
    if existing:
        user_management.delete_user(existing['id'])
    
    existing = user_management.get_user('testviewer')
    if existing:
        user_management.delete_user(existing['id'])
    
    # Create test users
    admin_id = user_management.create_user('testadmin', 'pass123', 'admin@test.com', ['admin'])
    operator_id = user_management.create_user('testoperator', 'pass123', 'operator@test.com', ['operator'])
    viewer_id = user_management.create_user('testviewer', 'pass123', 'viewer@test.com', ['viewer'])
    
    assert admin_id is not None, "Failed to create admin user"
    assert operator_id is not None, "Failed to create operator user"
    assert viewer_id is not None, "Failed to create viewer user"
    
    print(f"  ✓ Created testadmin (ID: {admin_id})")
    print(f"  ✓ Created testoperator (ID: {operator_id})")
    print(f"  ✓ Created testviewer (ID: {viewer_id})")
    
    return admin_id, operator_id, viewer_id

def test_password_verification():
    """Test password verification"""
    print("\nTesting password verification...")
    
    # Test correct password
    user_id = user_management.verify_password('testadmin', 'pass123')
    assert user_id is not None, "Failed to verify correct password"
    print("  ✓ Correct password verification works")
    
    # Test incorrect password
    user_id = user_management.verify_password('testadmin', 'wrongpass')
    assert user_id is None, "Incorrect password was accepted"
    print("  ✓ Incorrect password is rejected")
    
    # Test non-existent user
    user_id = user_management.verify_password('nonexistent', 'pass123')
    assert user_id is None, "Non-existent user was accepted"
    print("  ✓ Non-existent user is rejected")

def test_role_management(admin_id, operator_id, viewer_id):
    """Test role assignment and checking"""
    print("\nTesting role management...")
    
    # Check admin roles
    admin_roles = user_management.get_user_role_names(admin_id)
    assert 'admin' in admin_roles, "Admin role not found for admin user"
    print(f"  ✓ Admin user has roles: {admin_roles}")
    
    # Check operator roles
    operator_roles = user_management.get_user_role_names(operator_id)
    assert 'operator' in operator_roles, "Operator role not found for operator user"
    print(f"  ✓ Operator user has roles: {operator_roles}")
    
    # Check viewer roles
    viewer_roles = user_management.get_user_role_names(viewer_id)
    assert 'viewer' in viewer_roles, "Viewer role not found for viewer user"
    print(f"  ✓ Viewer user has roles: {viewer_roles}")
    
    # Test adding a role
    user_management.assign_role(viewer_id, 'operator')
    viewer_roles = user_management.get_user_role_names(viewer_id)
    assert 'operator' in viewer_roles, "Failed to add operator role to viewer"
    print(f"  ✓ Successfully added operator role to viewer: {viewer_roles}")
    
    # Test removing a role
    user_management.remove_role(viewer_id, 'operator')
    viewer_roles = user_management.get_user_role_names(viewer_id)
    assert 'operator' not in viewer_roles, "Failed to remove operator role from viewer"
    print(f"  ✓ Successfully removed operator role from viewer: {viewer_roles}")

def test_user_update(admin_id):
    """Test updating user information"""
    print("\nTesting user updates...")
    
    # Update email
    success = user_management.update_user(admin_id, email='newemail@test.com')
    assert success, "Failed to update user email"
    user = user_management.get_user_by_id(admin_id)
    assert user['email'] == 'newemail@test.com', "Email was not updated"
    print("  ✓ Email update works")
    
    # Update password
    success = user_management.update_user(admin_id, password='newpass456')
    assert success, "Failed to update user password"
    user_id = user_management.verify_password('testadmin', 'newpass456')
    assert user_id == admin_id, "Password was not updated"
    print("  ✓ Password update works")
    
    # Change password back
    user_management.update_user(admin_id, password='pass123')

def test_user_deactivation(viewer_id):
    """Test user activation/deactivation"""
    print("\nTesting user deactivation...")
    
    # Deactivate user
    success = user_management.update_user(viewer_id, active=0)
    assert success, "Failed to deactivate user"
    
    # Try to login with deactivated user
    user_id = user_management.verify_password('testviewer', 'pass123')
    assert user_id is None, "Deactivated user was able to login"
    print("  ✓ Deactivated user cannot login")
    
    # Reactivate user
    success = user_management.update_user(viewer_id, active=1)
    assert success, "Failed to reactivate user"
    
    # Try to login with reactivated user
    user_id = user_management.verify_password('testviewer', 'pass123')
    assert user_id == viewer_id, "Reactivated user cannot login"
    print("  ✓ Reactivated user can login")

def test_list_users():
    """Test listing all users"""
    print("\nTesting user listing...")
    
    users = user_management.list_users()
    usernames = [u['username'] for u in users]
    
    assert 'admin' in usernames, "Admin user not in list"
    assert 'testadmin' in usernames, "Test admin user not in list"
    assert 'testoperator' in usernames, "Test operator user not in list"
    assert 'testviewer' in usernames, "Test viewer user not in list"
    
    print(f"  ✓ Found {len(users)} users: {usernames}")

def cleanup():
    """Clean up test users"""
    print("\nCleaning up test users...")
    
    for username in ['testadmin', 'testoperator', 'testviewer']:
        user = user_management.get_user(username)
        if user:
            user_management.delete_user(user['id'])
            print(f"  ✓ Deleted {username}")

def main():
    try:
        print("=" * 60)
        print("User Management System Test Suite")
        print("=" * 60)
        
        # Initialize database
        user_management.init_user_db()
        
        # Run tests
        admin_id, operator_id, viewer_id = test_user_creation()
        test_password_verification()
        test_role_management(admin_id, operator_id, viewer_id)
        test_user_update(admin_id)
        test_user_deactivation(viewer_id)
        test_list_users()
        
        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        
        # Cleanup
        cleanup()
        
        return 0
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
