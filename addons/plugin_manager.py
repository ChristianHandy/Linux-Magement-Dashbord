from flask import Blueprint, render_template, jsonify, current_app, request, flash, redirect, url_for, session
import requests
import os
import re
from pathlib import Path

blueprint = Blueprint('plugin_manager', __name__, url_prefix='/pluginmanager')

addon_meta = {
    "name": "Plugin Manager",
    "html_hooks": {}
}

# Default plugin repository (GitHub repo or API endpoint)
REMOTE_PLUGIN_REPO = "https://raw.githubusercontent.com/ChristianHandy/Linux-Management-Dashboard-Plugins/main/plugins.json"

def current_user_has_role(*roles):
    """Check if the current logged-in user has any of the specified roles."""
    from user_management import get_user_role_names
    user_id = session.get("user_id")
    if not user_id:
        return False
    user_roles = get_user_role_names(user_id)
    # Admin has access to everything
    if 'admin' in user_roles:
        return True
    return any(role in user_roles for role in roles)

def register(app, core):
    app.register_blueprint(blueprint)

@blueprint.route('/')
def plugin_manager_index():
    mgr = getattr(current_app, 'addon_mgr', None)
    installed_plugins = mgr.status if mgr else []
    
    # Fetch available remote plugins
    remote_plugins = []
    try:
        response = requests.get(REMOTE_PLUGIN_REPO, timeout=5)
        if response.status_code == 200:
            remote_plugins = response.json().get('plugins', [])
    except Exception as e:
        # Log but don't crash if remote fetch fails
        print(f"Failed to fetch remote plugins: {e}")
    
    # Mark which remote plugins are already installed
    installed_names = {p['file'].replace('.py', '') for p in installed_plugins}
    for plugin in remote_plugins:
        plugin['installed'] = plugin.get('id', '') in installed_names
    
    return render_template('disks/plugin_manager.html', 
                         plugins=installed_plugins, 
                         remote_plugins=remote_plugins)

@blueprint.route('/status.json')
def plugin_manager_json():
    mgr = getattr(current_app, 'addon_mgr', None)
    return jsonify(mgr.status if mgr else [])

@blueprint.route('/install/<plugin_id>', methods=['POST'])
def install_plugin(plugin_id):
    """Install a plugin from the remote repository"""
    # Require admin role to install plugins
    if session.get("user_id") and not current_user_has_role('admin'):
        flash('Only administrators can install plugins.')
        return redirect(url_for('plugin_manager.plugin_manager_index'))
    
    # Validate plugin_id (alphanumeric and underscores only)
    if not re.match(r'^[a-zA-Z0-9_]+$', plugin_id):
        flash('Invalid plugin ID.')
        return redirect(url_for('plugin_manager.plugin_manager_index'))
    
    try:
        # Fetch available plugins
        response = requests.get(REMOTE_PLUGIN_REPO, timeout=10)
        if response.status_code != 200:
            flash('Failed to fetch plugin repository.')
            return redirect(url_for('plugin_manager.plugin_manager_index'))
        
        plugins_data = response.json().get('plugins', [])
        plugin_info = next((p for p in plugins_data if p.get('id') == plugin_id), None)
        
        if not plugin_info:
            flash(f'Plugin {plugin_id} not found in repository.')
            return redirect(url_for('plugin_manager.plugin_manager_index'))
        
        # Download plugin file
        plugin_url = plugin_info.get('url')
        if not plugin_url:
            flash('Plugin URL not found.')
            return redirect(url_for('plugin_manager.plugin_manager_index'))
        
        plugin_response = requests.get(plugin_url, timeout=10)
        if plugin_response.status_code != 200:
            flash(f'Failed to download plugin from {plugin_url}')
            return redirect(url_for('plugin_manager.plugin_manager_index'))
        
        # Save plugin to addons directory
        plugin_filename = f"{plugin_id}.py"
        plugin_path = Path('addons') / plugin_filename
        
        # Check if plugin already exists
        if plugin_path.exists():
            flash(f'Plugin {plugin_id} is already installed.')
            return redirect(url_for('plugin_manager.plugin_manager_index'))
        
        # Write plugin file
        with open(plugin_path, 'w', encoding='utf-8') as f:
            f.write(plugin_response.text)
        
        flash(f'Plugin {plugin_id} installed successfully! Please restart the application to activate.')
        
    except Exception as e:
        flash(f'Error installing plugin: {str(e)}')
    
    return redirect(url_for('plugin_manager.plugin_manager_index'))

@blueprint.route('/uninstall/<plugin_file>', methods=['POST'])
def uninstall_plugin(plugin_file):
    """Uninstall (delete) a plugin"""
    # Require admin role to uninstall plugins
    if session.get("user_id") and not current_user_has_role('admin'):
        flash('Only administrators can uninstall plugins.')
        return redirect(url_for('plugin_manager.plugin_manager_index'))
    
    # Validate filename (must end with .py and contain only safe characters)
    if not re.match(r'^[a-zA-Z0-9_]+\.py$', plugin_file):
        flash('Invalid plugin filename.')
        return redirect(url_for('plugin_manager.plugin_manager_index'))
    
    # Don't allow uninstalling the plugin manager itself
    if plugin_file == 'plugin_manager.py':
        flash('Cannot uninstall the Plugin Manager.')
        return redirect(url_for('plugin_manager.plugin_manager_index'))
    
    try:
        plugin_path = Path('addons') / plugin_file
        
        if not plugin_path.exists():
            flash(f'Plugin {plugin_file} not found.')
            return redirect(url_for('plugin_manager.plugin_manager_index'))
        
        # Delete the plugin file
        os.remove(plugin_path)
        
        # Delete template if exists
        template_name = plugin_file.replace('.py', '.html')
        template_path = Path('templates/addons') / template_name
        if template_path.exists():
            os.remove(template_path)
        
        flash(f'Plugin {plugin_file} uninstalled successfully! Please restart the application.')
        
    except Exception as e:
        flash(f'Error uninstalling plugin: {str(e)}')
    
    return redirect(url_for('plugin_manager.plugin_manager_index'))