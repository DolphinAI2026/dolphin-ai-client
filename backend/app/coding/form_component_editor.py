"""Compatibility exports for the form-component editor implementation.

The implementation is a root-level module so the desktop sidecar can freeze it
without walking the configuration-sensitive ``app`` package during packaging.
"""

from form_component_editor_impl import *  # noqa: F403
