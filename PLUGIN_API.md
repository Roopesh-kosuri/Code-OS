# CODE OS Plugin API Specifications

CODE OS plugins enable developers to extend the IDE with custom logic, sidebar components, syntax linters, and themes.

## Extension Manifest Structure

Every extension must supply a `manifest.json` file in its root folder (located inside `~/.codeos/extensions/<id>`).

```json
{
  "id": "my_custom_plugin",
  "name": "My Custom Plugin",
  "version": "1.0.0",
  "description": "Expose custom formatting and refactoring tools.",
  "author": "Developer Name",
  "entry": "index.py",
  "permissions": [
    "workspace_access"
  ]
}
```

### Manifest Fields
- `id`: Unique alphanumeric identifier (snake_case/kebab-case).
- `name`: Human-readable name.
- `version`: SemVer-compatible version string.
- `description`: Brief description of what the extension provides.
- `entry`: Path to the entry file (typically `index.py` for Python extension scripts).
- `permissions`: Declared permissions required by the plugin.

---

## Lifecycle Hooks

Plugins must implement standard hook functions in their entry point:

```python
# index.py

def initialize(api_context):
    """
    Called when the plugin is loaded during application startup.
    Useful for registering custom commands or layout buttons.
    """
    api_context.log("Plugin successfully initialized")


def enable(api_context):
    """
    Called when the plugin is turned on in the Settings or Diagnostics view.
    """
    api_context.register_linter("my-format", format_handler)


def disable(api_context):
    """
    Called when the plugin is turned off. Use this to clean up resources or unregister hooks.
    """
    api_context.unregister_linter("my-format")
```
