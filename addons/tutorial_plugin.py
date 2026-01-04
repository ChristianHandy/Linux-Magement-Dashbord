# -----------------------------------------
# 📦 Tutorial Plugin für das DiskTool System
# -----------------------------------------
# Dieses Plugin demonstriert, wie ein vollständiges Addon aufgebaut ist.
# Es enthält:
#  - addon_meta mit eingebettetem HTML
#  - automatische Template-Generierung
#  - einen Button für jede Festplatte, der auf eine eigene Ansicht verweist
#  - Nutzung von base.html und Übergabe von "device" ins Template

addon_meta = {
    "name": "tutorial_plugin",

    # 🔽 Embedded HTML template – automatically extracted
    "html": """
    {% extends 'disks/base.html' %}
    {% block title %}Tutorial Plugin – {{ device }}{% endblock %}
    {% block content %}
    <div class='container mt-4'>
      <h1>Tutorial Plugin</h1>
      <p>This is an example page created with the <code>tutorial_plugin</code>.</p>
      <p>Current device: <strong>{{ device }}</strong></p>
      <hr>
      <h5>🔧 Notes:</h5>
      <ul>
        <li>This HTML comes from the Python code in <code>tutorial_plugin.py</code>.</li>
        <li>Automatically extracted and saved under <code>templates/addons/tutorial_plugin.html</code>.</li>
        <li>A button appears automatically behind each disk.</li>
        <li>The page uses <code>disks/base.html</code> as foundation.</li>
      </ul>
      <a href='{{ url_for('disks_index') }}' class='btn btn-secondary mt-3'>Back</a>
    </div>
    {% endblock %}
    """
}

# This function is called when the plugin is loaded
def register(app, core):
    print("[tutorial_plugin] successfully loaded.")
