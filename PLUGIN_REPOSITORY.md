# Plugin Repository Format

This document describes the format for hosting remote plugins that can be installed through the Plugin Manager.

## Repository Structure

The plugin repository should be hosted as a JSON file accessible via HTTPS. The default repository URL is configured in `addons/plugin_manager.py`:

```python
REMOTE_PLUGIN_REPO = "https://raw.githubusercontent.com/ChristianHandy/Linux-Management-Dashboard-Plugins/main/plugins.json"
```

## plugins.json Format

```json
{
  "plugins": [
    {
      "id": "example_plugin",
      "name": "Example Plugin",
      "description": "An example plugin demonstrating the plugin system",
      "version": "1.0.0",
      "author": "Dashboard Team",
      "url": "https://raw.githubusercontent.com/ChristianHandy/Linux-Management-Dashboard-Plugins/main/plugins/example_plugin.py"
    },
    {
      "id": "backup_plugin",
      "name": "Disk Backup Plugin",
      "description": "Automated disk backup and restore functionality",
      "version": "1.0.0",
      "author": "Community Contributor",
      "url": "https://raw.githubusercontent.com/ChristianHandy/Linux-Management-Dashboard-Plugins/main/plugins/backup_plugin.py"
    }
  ]
}
```

## Field Descriptions

- **id** (required): Unique identifier for the plugin. Must match the filename without `.py` extension. Only alphanumeric characters and underscores allowed.
- **name** (required): Human-readable name of the plugin displayed in the UI.
- **description** (required): Brief description of what the plugin does.
- **version** (required): Version number of the plugin (semantic versioning recommended).
- **author** (required): Name of the plugin author or organization.
- **url** (required): Direct HTTPS URL to the plugin's Python source file.

## Plugin File Structure

Plugin files should follow the addon structure used in this dashboard:

```python
# Example plugin structure
addon_meta = {
    "name": "My Plugin Name",
    "html": '''
    {% extends 'disks/base.html' %}
    {% block title %}My Plugin – {{ device }}{% endblock %}
    {% block content %}
      <div class="container mt-4">
        <h1>My Plugin</h1>
        <p>Plugin content for device <strong>{{ device }}</strong>.</p>
        <a href="{{ url_for('disks_index') }}" class="btn btn-secondary">Back</a>
      </div>
    {% endblock %}
    '''
}

def register(app, core):
    """Called when the plugin is loaded"""
    print("[my_plugin] successfully registered.")
    # Add routes, hooks, or other functionality here
```

## Security Considerations

1. **HTTPS Only**: All plugin URLs must use HTTPS to prevent man-in-the-middle attacks.
2. **Code Review**: All plugins in the official repository should be reviewed for security vulnerabilities.
3. **Admin Only**: Only users with admin role can install or uninstall plugins.
4. **Validation**: Plugin IDs are validated to contain only alphanumeric characters and underscores.
5. **Restart Required**: Plugins are not dynamically loaded; application restart is required after installation.

## Setting Up Your Own Plugin Repository

1. Create a GitHub repository (or any web server with HTTPS)
2. Create a `plugins.json` file following the format above
3. Host your plugin `.py` files in the same repository
4. Update the `REMOTE_PLUGIN_REPO` constant in `addons/plugin_manager.py` to point to your `plugins.json` URL
5. Ensure all URLs use HTTPS

## Example Repository Structure

```
Linux-Management-Dashboard-Plugins/
├── plugins.json
└── plugins/
    ├── example_plugin.py
    ├── backup_plugin.py
    └── monitoring_plugin.py
```

## Testing Plugins Locally

Before publishing plugins to the remote repository:

1. Place the plugin file in the `addons/` directory
2. Restart the application
3. Check the Plugin Manager for any errors
4. Test the plugin functionality thoroughly
5. Review for security vulnerabilities before publishing
