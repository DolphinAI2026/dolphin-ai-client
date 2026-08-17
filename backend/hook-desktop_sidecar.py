# PyInstaller hook: force-include form_component_editor_impl
# when freezing desktop_sidecar.py as the entry point.
# The spec hiddenimports list is not sufficient on Python 3.11 CI.
hiddenimports = ['form_component_editor_impl']
