"""
User Management Module
Provides user authentication, role-based access control, and user CRUD operations.
"""
import sqlite3
import os
from pathlib import Path
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask import session, redirect, url_for, flash, request

# Database file for user management
USER_DB_FILE = Path(__file__).parent / 'users.db'

def get_user_db():
    """Get database connection for user management."""
    conn = sqlite3.connect(USER_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_user_db():
    """Initialize the user management database with required tables."""
    with get_user_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          email TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          active INTEGER DEFAULT 1
        );
        
        CREATE TABLE IF NOT EXISTS roles(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE NOT NULL,
          description TEXT
        );
        
        CREATE TABLE IF NOT EXISTS user_roles(
          user_id INTEGER,
          role_id INTEGER,
          PRIMARY KEY (user_id, role_id),
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
        );
        
        CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id);
        """)
        
        # Create default roles if they don't exist
        roles = [
            ('admin', 'Full system access including user management'),
            ('operator', 'Can perform system operations (updates, disk management)'),
            ('viewer', 'Read-only access to system information')
        ]
        
        for role_name, description in roles:
            db.execute(
                'INSERT OR IGNORE INTO roles(name, description) VALUES (?, ?)',
                (role_name, description)
            )
        db.commit()

def migrate_env_user_to_db():
    """
    Migrate environment variable user to database if it doesn't exist.
    This ensures backward compatibility.
    """
    username = os.environ.get('DASHBOARD_USERNAME', 'admin')
    password = os.environ.get('DASHBOARD_PASSWORD', 'password')
    
    with get_user_db() as db:
        # Check if user exists
        user = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if not user:
            # Create user from environment variables
            password_hash = generate_password_hash(password)
            cursor = db.execute(
                'INSERT INTO users(username, password_hash, active) VALUES (?, ?, 1)',
                (username, password_hash)
            )
            user_id = cursor.lastrowid
            
            # Assign admin role
            admin_role = db.execute('SELECT id FROM roles WHERE name = ?', ('admin',)).fetchone()
            if admin_role:
                db.execute(
                    'INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)',
                    (user_id, admin_role['id'])
                )
            db.commit()
            return True
    return False

# User CRUD operations
def create_user(username, password, email=None, roles=None):
    """
    Create a new user.
    
    Args:
        username: Unique username
        password: Plain text password (will be hashed)
        email: Optional email address
        roles: List of role names to assign (default: ['viewer'])
    
    Returns:
        user_id if successful, None if username already exists
    """
    if roles is None:
        roles = ['viewer']
    
    try:
        with get_user_db() as db:
            password_hash = generate_password_hash(password)
            cursor = db.execute(
                'INSERT INTO users(username, password_hash, email, active) VALUES (?, ?, ?, 1)',
                (username, password_hash, email)
            )
            user_id = cursor.lastrowid
            
            # Assign roles
            for role_name in roles:
                role = db.execute('SELECT id FROM roles WHERE name = ?', (role_name,)).fetchone()
                if role:
                    db.execute(
                        'INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)',
                        (user_id, role['id'])
                    )
            db.commit()
            return user_id
    except sqlite3.IntegrityError:
        return None

def get_user(username):
    """Get user by username."""
    with get_user_db() as db:
        return db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

def get_user_by_id(user_id):
    """Get user by ID."""
    with get_user_db() as db:
        return db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

def list_users():
    """Get all users."""
    with get_user_db() as db:
        return db.execute('SELECT * FROM users ORDER BY username').fetchall()

def update_user(user_id, username=None, email=None, active=None, password=None):
    """
    Update user information.
    
    Args:
        user_id: User ID to update
        username: New username (optional)
        email: New email (optional)
        active: New active status (optional)
        password: New password in plain text (optional, will be hashed)
    
    Returns:
        True if successful, False otherwise
    """
    # Whitelist of allowed columns to prevent SQL injection
    ALLOWED_COLUMNS = {'username', 'email', 'active', 'password_hash'}
    
    updates = []
    params = []
    
    if username is not None:
        updates.append('username = ?')
        params.append(username)
    if email is not None:
        updates.append('email = ?')
        params.append(email)
    if active is not None:
        updates.append('active = ?')
        params.append(active)
    if password is not None:
        updates.append('password_hash = ?')
        params.append(generate_password_hash(password))
    
    if not updates:
        return True
    
    params.append(user_id)
    
    try:
        with get_user_db() as db:
            # Safe: updates contains only whitelisted column names with parameterized values
            db.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
                params
            )
            db.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def delete_user(user_id):
    """Delete a user."""
    with get_user_db() as db:
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()

def verify_password(username, password):
    """
    Verify username and password.
    
    Returns:
        user_id if valid, None otherwise
    """
    user = get_user(username)
    if user and user['active'] and check_password_hash(user['password_hash'], password):
        return user['id']
    return None

# Role management
def get_user_roles(user_id):
    """Get all roles for a user."""
    with get_user_db() as db:
        return db.execute('''
            SELECT r.* FROM roles r
            JOIN user_roles ur ON r.id = ur.role_id
            WHERE ur.user_id = ?
        ''', (user_id,)).fetchall()

def get_user_role_names(user_id):
    """Get role names for a user as a list."""
    roles = get_user_roles(user_id)
    return [role['name'] for role in roles]

def user_has_role(user_id, role_name):
    """Check if user has a specific role."""
    role_names = get_user_role_names(user_id)
    return role_name in role_names

def assign_role(user_id, role_name):
    """Assign a role to a user."""
    with get_user_db() as db:
        role = db.execute('SELECT id FROM roles WHERE name = ?', (role_name,)).fetchone()
        if role:
            db.execute(
                'INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?, ?)',
                (user_id, role['id'])
            )
            db.commit()
            return True
    return False

def remove_role(user_id, role_name):
    """Remove a role from a user."""
    with get_user_db() as db:
        role = db.execute('SELECT id FROM roles WHERE name = ?', (role_name,)).fetchone()
        if role:
            db.execute(
                'DELETE FROM user_roles WHERE user_id = ? AND role_id = ?',
                (user_id, role['id'])
            )
            db.commit()
            return True
    return False

def set_user_roles(user_id, role_names):
    """Set user roles (replaces existing roles)."""
    with get_user_db() as db:
        # Remove all existing roles
        db.execute('DELETE FROM user_roles WHERE user_id = ?', (user_id,))
        
        # Add new roles
        for role_name in role_names:
            role = db.execute('SELECT id FROM roles WHERE name = ?', (role_name,)).fetchone()
            if role:
                db.execute(
                    'INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)',
                    (user_id, role['id'])
                )
        db.commit()

def list_roles():
    """Get all roles."""
    with get_user_db() as db:
        return db.execute('SELECT * FROM roles ORDER BY name').fetchall()

# Authorization decorators
def login_required(f):
    """Decorator to require login."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapped

def role_required(*required_roles):
    """
    Decorator to require specific roles.
    Usage: @role_required('admin', 'operator')
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                return redirect(url_for('login', next=request.path))
            
            user_roles = get_user_role_names(user_id)
            
            # Admin has access to everything
            if 'admin' in user_roles:
                return f(*args, **kwargs)
            
            # Check if user has any of the required roles
            if any(role in user_roles for role in required_roles):
                return f(*args, **kwargs)
            
            flash('You do not have permission to access this page.')
            return redirect(url_for('index'))
        return wrapped
    return decorator

def admin_required(f):
    """Decorator to require admin role."""
    return role_required('admin')(f)
