# -----------------------------------------
# 🌐 Remote Disk Management Plugin
# -----------------------------------------
# This plugin enables disk management on remote PCs and servers via SSH.
# Features:
#  - List disks on remote systems
#  - Format remote disks
#  - Run SMART tests on remote disks
#  - View SMART data from remote systems

import paramiko
import json
import re
import disktool_core
from flask import request, flash, redirect, url_for

addon_meta = {
    "name": "Remote Disk Manager",
    
    # Embedded HTML template
    "html": """
    {% extends 'disks/base.html' %}
    {% block title %}Remote Disk Manager – {{ device }}{% endblock %}
    {% block content %}
    <div class='container mt-4'>
      <h1>Remote Disk Manager</h1>
      <p>Manage disks on remote systems via SSH</p>
      <p>Local device context: <strong>{{ device }}</strong></p>
      
      <div class="card mb-4">
        <div class="card-header">
          <h5>Available Remote Systems</h5>
        </div>
        <div class="card-body">
          {% if remotes %}
            <div class="list-group">
              {% for remote in remotes %}
              <div class="list-group-item">
                <div class="d-flex w-100 justify-content-between">
                  <h6 class="mb-1">{{ remote.name }}</h6>
                  <small>{{ remote.host }}:{{ remote.port }}</small>
                </div>
                <div class="mt-2">
                  <a href="{{ url_for('remote_disk_list', remote_id=remote.id) }}" class="btn btn-sm btn-primary">
                    View Disks
                  </a>
                  <a href="{{ url_for('remote_disk_sync', remote_id=remote.id) }}" class="btn btn-sm btn-success">
                    Sync Disks
                  </a>
                </div>
              </div>
              {% endfor %}
            </div>
          {% else %}
            <p class="text-muted">No remote systems configured. Add remotes in <a href="{{ url_for('remotes') }}">Remote Management</a>.</p>
          {% endif %}
        </div>
      </div>
      
      <a href='{{ url_for('disks_index') }}' class='btn btn-secondary'>Back to Disk Overview</a>
    </div>
    {% endblock %}
    """
}


def execute_remote_command(host, port, username, command):
    """
    Execute a command on a remote host via SSH.
    Returns the output as a string or None if failed.
    
    Security Note: Uses AutoAddPolicy which accepts any host key, making this 
    vulnerable to MITM attacks. This is consistent with the existing implementation
    in app.py. For production use, consider using WarningPolicy and maintaining 
    a known_hosts file.
    """
    try:
        ssh = paramiko.SSHClient()
        # Security Note: AutoAddPolicy accepts any host key, making this vulnerable to MITM attacks.
        # For production, use WarningPolicy or maintain a known_hosts file.
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, timeout=10)
        
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        ssh.close()
        
        if error:
            return None, error
        return output, None
    except Exception as e:
        return None, str(e)


def list_remote_disks(host, port, username):
    """
    List all physical disks on a remote system using lsblk.
    Returns a list of disk dictionaries or None if failed.
    """
    command = "lsblk -J -d -o NAME,SIZE,MODEL,TYPE"
    output, error = execute_remote_command(host, port, username, command)
    
    if error:
        return None, error
    
    try:
        data = json.loads(output)
        # Filter only 'disk' type devices
        disks = [d for d in data.get('blockdevices', []) if d.get('type') == 'disk']
        return disks, None
    except Exception as e:
        return None, str(e)


def get_remote_smart(host, port, username, device):
    """
    Get SMART data from a remote disk.
    Returns the smartctl output or None if failed.
    """
    try:
        device = disktool_core.sanitize_device_name(device)
    except ValueError as e:
        return None, str(e)
    
    command = f"sudo smartctl -a /dev/{device}"
    output, error = execute_remote_command(host, port, username, command)
    
    if error:
        return None, error
    
    return output, None


def format_remote_disk(host, port, username, device, fs_type):
    """
    Format a remote disk with the specified filesystem.
    Returns success status and message.
    """
    try:
        device = disktool_core.sanitize_device_name(device)
    except ValueError as e:
        return False, str(e)
    
    # Validate filesystem type
    if fs_type not in ['ext4', 'xfs', 'fat32']:
        return False, "Invalid filesystem type"
    
    # Construct format command
    fs_commands = {
        'ext4': f"sudo wipefs -a /dev/{device} && sudo mkfs.ext4 -F /dev/{device}",
        'xfs': f"sudo wipefs -a /dev/{device} && sudo mkfs.xfs -f /dev/{device}",
        'fat32': f"sudo wipefs -a /dev/{device} && sudo mkfs.vfat -F 32 /dev/{device}"
    }
    
    command = fs_commands.get(fs_type)
    if not command:
        return False, "Filesystem not supported"
    
    output, error = execute_remote_command(host, port, username, command)
    
    if error:
        return False, error
    
    return True, "Format completed successfully"


def start_remote_smart_test(host, port, username, device, mode):
    """
    Start a SMART test on a remote disk.
    Returns success status and message.
    """
    try:
        device = disktool_core.sanitize_device_name(device)
    except ValueError as e:
        return False, str(e)
    
    # Validate mode
    if mode not in ['short', 'long']:
        return False, "Invalid SMART test mode"
    
    command = f"sudo smartctl -t {mode} /dev/{device}"
    output, error = execute_remote_command(host, port, username, command)
    
    if error:
        return False, error
    
    return True, f"SMART {mode} test started successfully"


def register(app, core):
    """
    Register the remote disk management plugin with the Flask app.
    This adds routes for remote disk operations.
    """
    print("[remote_disk_plugin] Registering routes...")
    
    # Import what we need from Flask
    from flask import render_template, session
    from functools import wraps
    
    # Helper to check login
    def login_required(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not session.get("user_id") and not session.get("login"):
                flash('Please log in to access this feature.')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return wrapped
    
    # Helper to check roles
    def current_user_has_role(*roles):
        user_id = session.get("user_id")
        if not user_id:
            return False
        try:
            import user_management
            user_roles = user_management.get_user_role_names(user_id)
            if 'admin' in user_roles:
                return True
            return any(role in user_roles for role in roles)
        except:
            return False
    
    # Helper to get username from session
    def get_username():
        """Get username from session, default to 'root'"""
        return session.get('username', 'root')
    
    # Helper to get remote by ID
    def get_remote_by_id(remote_id):
        """Get remote configuration by ID, returns None if not found"""
        remotes = core.list_remotes()
        for r in remotes:
            if r['id'] == remote_id:
                return r
        return None
    
    @app.route("/disks/remote/list/<int:remote_id>")
    @login_required
    def remote_disk_list(remote_id):
        """List disks on a remote system."""
        # Get remote details using helper
        remote = get_remote_by_id(remote_id)
        
        if not remote:
            flash('Remote system not found')
            return redirect(url_for('disks_index'))
        
        # Get username using helper
        username = get_username()
        
        # List disks on remote
        disks, error = list_remote_disks(remote['host'], remote['port'], username)
        
        if error:
            flash(f'Error listing remote disks: {error}')
            disks = []
        
        return render_template('disks/remote_list.html', 
                             remote=remote, 
                             disks=disks,
                             username=username)
    
    @app.route("/disks/remote/sync/<int:remote_id>")
    @login_required
    def remote_disk_sync(remote_id):
        """Sync/refresh disk list for a remote system."""
        # Require operator or admin role
        if session.get("user_id") and not current_user_has_role('operator', 'admin'):
            flash('You need operator or admin role to sync remote disks.')
            return redirect(url_for('disks_index'))
        
        flash('Remote disk sync initiated')
        return redirect(url_for('remote_disk_list', remote_id=remote_id))
    
    @app.route("/disks/remote/smart/<int:remote_id>/<device>")
    @login_required
    def remote_disk_smart(remote_id, device):
        """View SMART data for a remote disk."""
        # Get remote details using helper
        remote = get_remote_by_id(remote_id)
        
        if not remote:
            flash('Remote system not found')
            return redirect(url_for('disks_index'))
        
        username = get_username()
        
        # Get SMART data
        smart_data, error = get_remote_smart(remote['host'], remote['port'], username, device)
        
        if error:
            flash(f'Error reading SMART data: {error}')
            smart_data = None
        
        return render_template('disks/remote_smart.html',
                             remote=remote,
                             device=device,
                             smart_data=smart_data)
    
    @app.route("/disks/remote/format/<int:remote_id>/<device>", methods=['GET', 'POST'])
    @login_required
    def remote_disk_format(remote_id, device):
        """Format a disk on a remote system."""
        # Require operator or admin role
        if session.get("user_id") and not current_user_has_role('operator', 'admin'):
            flash('You need operator or admin role to format remote disks.')
            return redirect(url_for('disks_index'))
        
        # Get remote details using helper
        remote = get_remote_by_id(remote_id)
        
        if not remote:
            flash('Remote system not found')
            return redirect(url_for('disks_index'))
        
        if request.method == 'POST':
            fs_type = request.form.get('fs', 'ext4')
            username = get_username()
            
            success, message = format_remote_disk(remote['host'], remote['port'], 
                                                  username, device, fs_type)
            
            if success:
                flash(f'Remote disk format successful: {message}')
            else:
                flash(f'Remote disk format failed: {message}')
            
            return redirect(url_for('remote_disk_list', remote_id=remote_id))
        
        return render_template('disks/remote_format.html',
                             remote=remote,
                             device=device)
    
    @app.route("/disks/remote/smart_test/<int:remote_id>/<device>/<mode>")
    @login_required
    def remote_disk_smart_test(remote_id, device, mode):
        """Start a SMART test on a remote disk."""
        # Require operator or admin role
        if session.get("user_id") and not current_user_has_role('operator', 'admin'):
            flash('You need operator or admin role to run SMART tests on remote disks.')
            return redirect(url_for('disks_index'))
        
        # Get remote details using helper
        remote = get_remote_by_id(remote_id)
        
        if not remote:
            flash('Remote system not found')
            return redirect(url_for('disks_index'))
        
        username = get_username()
        
        success, message = start_remote_smart_test(remote['host'], remote['port'],
                                                   username, device, mode)
        
        if success:
            flash(f'Remote SMART test started: {message}')
        else:
            flash(f'Remote SMART test failed: {message}')
        
        return redirect(url_for('remote_disk_list', remote_id=remote_id))
    
    print("[remote_disk_plugin] Successfully registered remote disk management routes.")
